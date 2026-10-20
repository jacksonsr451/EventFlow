"""Project triage configuration and immutable template versions (Issue #41).

This service is the one coordinator for project-owned triage customization. It
extends, and never replaces, the authoritative category criteria in
``services.triage_criteria``. Every mutation:

* authorizes through the caller's resolved ``AuthorizationContext``;
* validates a bounded declarative schema through ``services.triage_schema``;
* reserves an optional durable idempotency key in the same transaction;
* writes an append-only audit record;
* commits once.

Effective template resolution is deterministic:

1. the version pinned on the consultation (historical reads only);
2. the active project template for the category;
3. the baseline category contract.

Published versions are immutable. Activating a version only changes the
activation row; it never rewrites a consultation's pinned snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import (
    Project,
    ProjectTriageConfiguration,
    ProjectTriageTemplate,
    ProjectTriageTemplateActivation,
    ProjectTriageTemplateVersion,
)
from eventflow_work_management.models.enums import (
    TRIAGE_CATEGORY_VALUES,
    TRIAGE_TEMPLATE_STATUS_VALUES,
)
from eventflow_work_management.repositories.attachment_repository import (
    EvidenceRepository,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.triage_repository import (
    ProjectTriageConfigurationRepository,
    ProjectTriageTemplateActivationRepository,
    ProjectTriageTemplateRepository,
    ProjectTriageTemplateVersionRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.triage_schema import (
    CORE_CRITERIA_KEYS,
    apply_and_validate_field_values,
    evaluate_workflow,
    merge_workflow_rules,
    validate_field_definitions,
    validate_required_fields,
    validate_template_definition,
    validate_workflow_rules,
)

CONFIGURATION_UPDATE_OPERATION = "project_triage_configuration.update"
TEMPLATE_CREATE_OPERATION = "triage_template.create"
TEMPLATE_VERSION_CREATE_OPERATION = "triage_template.version.create"
TEMPLATE_VERSION_PUBLISH_OPERATION = "triage_template.version.publish"
TEMPLATE_ACTIVATE_OPERATION = "triage_template.activate"
TEMPLATE_ARCHIVE_OPERATION = "triage_template.archive"
TEMPLATE_DEPRECATE_OPERATION = "triage_template.deprecate"

MAX_TEMPLATE_DESCRIPTION = 2000
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404,
        code="TEMPLATE_NOT_FOUND",
        detail="The requested resource was not found.",
        title="Not found",
    )


def _version_not_found() -> ProblemError:
    return ProblemError(
        status_code=404,
        code="TEMPLATE_VERSION_NOT_FOUND",
        detail="The requested resource was not found.",
        title="Not found",
    )


def _conflict(
    detail: str, *, code: str = "TRIAGE_CONFIGURATION_CONFLICT"
) -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _unprocessable(
    detail: str, *, code: str = "TRIAGE_CONFIGURATION_CONFLICT"
) -> ProblemError:
    return ProblemError(
        status_code=422,
        code=code,
        detail=detail,
        title="Unprocessable entity",
    )


def project_configuration_etag(
    configuration: ProjectTriageConfiguration | None,
    workspace_id: UUID,
    project_id: UUID,
) -> str:
    if configuration is None:
        return (
            '"'
            + fingerprint(
                [
                    "project-triage-configuration",
                    str(workspace_id),
                    str(project_id),
                    0,
                ]
            )
            + '"'
        )
    return (
        '"'
        + fingerprint(
            [
                "project-triage-configuration",
                str(configuration.id),
                configuration.version,
                configuration.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def project_template_etag(template: ProjectTriageTemplate) -> str:
    return (
        '"'
        + fingerprint(
            [
                "project-triage-template",
                str(template.id),
                template.status,
                template.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def project_template_version_etag(version: ProjectTriageTemplateVersion) -> str:
    return (
        '"'
        + fingerprint(
            [
                "project-triage-template-version",
                str(version.id),
                version.version,
                version.status,
                version.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def project_template_activation_etag(
    activation: ProjectTriageTemplateActivation | None,
    workspace_id: UUID,
    project_id: UUID,
    category: str,
) -> str:
    if activation is None:
        return (
            '"'
            + fingerprint(
                [
                    "project-triage-activation",
                    str(workspace_id),
                    str(project_id),
                    category,
                ]
            )
            + '"'
        )
    return (
        '"'
        + fingerprint(
            [
                "project-triage-activation",
                str(activation.id),
                str(activation.template_version_id),
                activation.activated_at.isoformat(),
            ]
        )
        + '"'
    )


@dataclass(frozen=True, slots=True)
class TriageConfigurationOutcome:
    configuration: ProjectTriageConfiguration | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class TemplateOutcome:
    template: ProjectTriageTemplate
    version: ProjectTriageTemplateVersion | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class EffectiveTriageContext:
    """The exact validation context applied to one triage decision."""

    category: str
    custom_fields: dict
    template: ProjectTriageTemplate | None
    version: ProjectTriageTemplateVersion | None
    snapshot: dict


class TriageConfigurationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.configurations = ProjectTriageConfigurationRepository(session)
        self.templates = ProjectTriageTemplateRepository(session)
        self.versions = ProjectTriageTemplateVersionRepository(session)
        self.activations = ProjectTriageTemplateActivationRepository(session)
        self.projects = ProjectRepository(session)
        self.evidence = EvidenceRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    # -- configuration ----------------------------------------------------

    def get_configuration(
        self, context: AuthorizationContext, project_id: UUID
    ) -> ProjectTriageConfiguration | None:
        self._require_project(context.workspace_id, project_id)
        return self.configurations.get(
            workspace_id=context.workspace_id, project_id=project_id
        )

    def update_configuration(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        enabled: bool,
        required_fields: dict | None,
        custom_fields: list | None,
        workflow_rules: dict | None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TriageConfigurationOutcome:
        if not isinstance(enabled, bool):
            raise _validation("enabled must be a boolean.")
        normalized_required = validate_required_fields(required_fields)
        normalized_fields = validate_field_definitions(custom_fields)
        normalized_workflow = validate_workflow_rules(workflow_rules)
        self._validate_required_references(normalized_required, normalized_fields)
        self._require_project(context.workspace_id, project_id)

        request_fingerprint = fingerprint(
            {
                "operation": CONFIGURATION_UPDATE_OPERATION,
                "project_id": str(project_id),
                "enabled": enabled,
                "required_fields": normalized_required,
                "custom_fields": normalized_fields,
                "workflow_rules": normalized_workflow,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                CONFIGURATION_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                configuration = self.configurations.get(
                    workspace_id=context.workspace_id, project_id=project_id
                )
                return TriageConfigurationOutcome(
                    configuration=configuration, replayed=True
                )

        try:
            self._lock_project(context.workspace_id, project_id)
            configuration = self.configurations.get_for_update(
                workspace_id=context.workspace_id, project_id=project_id
            )
            if if_match is not None and if_match != project_configuration_etag(
                configuration, context.workspace_id, project_id
            ):
                raise _precondition_failed()
            record = self._reserve(
                context.workspace_id,
                CONFIGURATION_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if configuration is None:
                configuration = self.configurations.add(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    enabled=enabled,
                    required_fields=normalized_required,
                    custom_fields=normalized_fields,
                    workflow_rules=normalized_workflow,
                    actor_id=context.actor_id,
                )
                previous = None
            else:
                previous = {
                    "enabled": configuration.enabled,
                    "required_fields": configuration.required_fields,
                    "custom_fields": configuration.custom_fields,
                    "workflow_rules": configuration.workflow_rules,
                    "version": configuration.version,
                }
                configuration = self.configurations.update(
                    configuration,
                    enabled=enabled,
                    required_fields=normalized_required,
                    custom_fields=normalized_fields,
                    workflow_rules=normalized_workflow,
                    actor_id=context.actor_id,
                    updated_at=_now(),
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="project_triage_rules.updated",
                entity_type="project_triage_configuration",
                entity_id=configuration.id,
                actor_id=context.actor_id,
                snapshot={
                    "project_id": str(project_id),
                    "version": configuration.version,
                    "previous": previous,
                    "enabled": configuration.enabled,
                    "required_fields": configuration.required_fields,
                    "custom_field_keys": [
                        field["key"] for field in configuration.custom_fields
                    ],
                    "workflow_rules": configuration.workflow_rules,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=200,
                response_body={
                    "project_id": str(project_id),
                    "configuration_version": configuration.version,
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    CONFIGURATION_UPDATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    configuration = self.configurations.get(
                        workspace_id=context.workspace_id, project_id=project_id
                    )
                    return TriageConfigurationOutcome(
                        configuration=configuration, replayed=True
                    )
            raise _conflict("The project triage configuration changed concurrently.")
        except ProblemError:
            self._session.rollback()
            raise
        return TriageConfigurationOutcome(configuration=configuration)

    # -- templates --------------------------------------------------------

    def create_template(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        category: str,
        key: str,
        name: str,
        description: str | None,
        definition: dict,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        self._validate_category(category)
        self._validate_template_metadata(key, name, description)
        normalized = validate_template_definition(definition, category=category)
        self._require_project(context.workspace_id, project_id)

        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_CREATE_OPERATION,
                "project_id": str(project_id),
                "category": category,
                "key": key,
                "name": name,
                "description": description,
                "definition": normalized,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                template = self.templates.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=UUID(str(replay["template_id"])),
                )
                if template is None:
                    raise _not_found()
                version = self.versions.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template.id,
                    version_id=UUID(str(replay["template_version_id"])),
                )
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )

        try:
            self._lock_project(context.workspace_id, project_id)
            if self.templates.find_by_key(
                workspace_id=context.workspace_id, project_id=project_id, key=key
            ) is not None:
                raise _conflict(
                    "A template with this key already exists in the project.",
                    code="TRIAGE_CONFIGURATION_CONFLICT",
                )
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            template = self.templates.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                category=category,
                key=key,
                name=name,
                description=description,
                actor_id=context.actor_id,
            )
            version = self.versions.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template.id,
                version=1,
                definition=normalized,
                actor_id=context.actor_id,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.created",
                entity_type="project_triage_template",
                entity_id=template.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template.id),
                    "project_id": str(project_id),
                    "category": category,
                    "key": key,
                    "template_version_id": str(version.id),
                    "version": version.version,
                },
                correlation_id=correlation_id,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.version_created",
                entity_type="project_triage_template_version",
                entity_id=version.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template.id),
                    "template_version_id": str(version.id),
                    "version": version.version,
                    "status": version.status,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=201,
                response_body={
                    "template_id": str(template.id),
                    "template_version_id": str(version.id),
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    TEMPLATE_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    template = self.templates.get(
                        workspace_id=context.workspace_id,
                        project_id=project_id,
                        template_id=UUID(str(replay["template_id"])),
                    )
                    if template is not None:
                        version = self.versions.get(
                            workspace_id=context.workspace_id,
                            project_id=project_id,
                            template_id=template.id,
                            version_id=UUID(str(replay["template_version_id"])),
                        )
                        return TemplateOutcome(
                            template=template, version=version, replayed=True
                        )
            raise _conflict(
                "A template with this key already exists in the project.",
                code="TRIAGE_CONFIGURATION_CONFLICT",
            )
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=template, version=version)

    def create_version(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
        *,
        definition: dict,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        template = self.templates.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )
        if template is None:
            raise _not_found()
        normalized = validate_template_definition(
            definition, category=template.category
        )
        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_VERSION_CREATE_OPERATION,
                "template_id": str(template_id),
                "definition": normalized,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_VERSION_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                version = self.versions.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                    version_id=UUID(str(replay["template_version_id"])),
                )
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )
        try:
            locked = self.templates.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            if locked is None:
                raise _not_found()
            if locked.status == "archived":
                raise _conflict(
                    "An archived template cannot receive new versions.",
                    code="TEMPLATE_VERSION_IMMUTABLE",
                )
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_VERSION_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            version_number = self.versions.next_version_number(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            version = self.versions.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
                version=version_number,
                definition=normalized,
                actor_id=context.actor_id,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.version_created",
                entity_type="project_triage_template_version",
                entity_id=version.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template_id),
                    "template_version_id": str(version.id),
                    "version": version.version,
                    "status": version.status,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=201,
                response_body={
                    "template_id": str(template_id),
                    "template_version_id": str(version.id),
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    TEMPLATE_VERSION_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    version = self.versions.get(
                        workspace_id=context.workspace_id,
                        project_id=project_id,
                        template_id=template_id,
                        version_id=UUID(str(replay["template_version_id"])),
                    )
                    return TemplateOutcome(
                        template=template, version=version, replayed=True
                    )
            raise _conflict(
                "A template version was created concurrently; retry the operation.",
                code="TEMPLATE_VERSION_CONFLICT",
            )
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=locked, version=version)

    def publish_version(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
        version_id: UUID,
        *,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_VERSION_PUBLISH_OPERATION,
                "template_id": str(template_id),
                "template_version_id": str(version_id),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_VERSION_PUBLISH_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                template = self.templates.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                )
                version = self.versions.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                    version_id=version_id,
                )
                if template is None or version is None:
                    raise _version_not_found()
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )
        try:
            template = self.templates.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            if template is None:
                raise _not_found()
            version = self.versions.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
                version_id=version_id,
            )
            if version is None:
                raise _version_not_found()
            if version.status == "published":
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )
            if version.status != "draft":
                raise _conflict(
                    "Only a draft version can be published.",
                    code="TEMPLATE_VERSION_IMMUTABLE",
                )
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_VERSION_PUBLISH_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            version.status = "published"
            version.published_at = _now()
            version.published_by = context.actor_id
            version.updated_at = version.published_at
            self._session.flush()
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.version_published",
                entity_type="project_triage_template_version",
                entity_id=version.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template_id),
                    "template_version_id": str(version.id),
                    "version": version.version,
                    "schema_version": version.schema_version,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=200,
                response_body={
                    "template_id": str(template_id),
                    "template_version_id": str(version.id),
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise _conflict(
                "The template version changed concurrently.",
                code="TEMPLATE_VERSION_CONFLICT",
            )
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=template, version=version)

    def activate_version(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
        version_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_ACTIVATE_OPERATION,
                "template_id": str(template_id),
                "template_version_id": str(version_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_ACTIVATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                template = self.templates.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                )
                version = self.versions.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                    version_id=version_id,
                )
                if template is None or version is None:
                    raise _version_not_found()
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )
        scoped = self.templates.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )
        if scoped is None:
            raise _not_found()
        # ``category`` is immutable, so locking on it before taking the row lock
        # is safe and never lets a caller from another tenant influence the
        # advisory lock namespace.
        category = scoped.category
        try:
            self._lock_project(context.workspace_id, project_id)
            self._lock_activation(context.workspace_id, project_id, category)
            template = self.templates.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            if template is None:
                raise _not_found()
            if template.status == "archived":
                raise _conflict(
                    "An archived template cannot be activated.",
                    code="TEMPLATE_NOT_PUBLISHED",
                )
            version = self.versions.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
                version_id=version_id,
            )
            if version is None:
                raise _version_not_found()
            if version.status != "published":
                raise _conflict(
                    "Only a published version can be activated.",
                    code="TEMPLATE_NOT_PUBLISHED",
                )
            if version.schema_version != 1:
                raise _conflict(
                    "The template version uses an unsupported schema version.",
                    code="TEMPLATE_VERSION_CONFLICT",
                )
            activation = self.activations.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                category=template.category,
            )
            if if_match is not None and if_match != project_template_activation_etag(
                activation, context.workspace_id, project_id, template.category
            ):
                raise _precondition_failed()
            if (
                activation is not None
                and activation.template_version_id == version.id
            ):
                return TemplateOutcome(
                    template=template, version=version, replayed=True
                )
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_ACTIVATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            previous_version_id = (
                str(activation.template_version_id) if activation is not None else None
            )
            if activation is None:
                activation = self.activations.add(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    category=template.category,
                    template_id=template.id,
                    template_version_id=version.id,
                    actor_id=context.actor_id,
                    activated_at=_now(),
                )
            else:
                activation.template_id = template.id
                activation.template_version_id = version.id
                activation.activated_by = context.actor_id
                activation.activated_at = _now()
                self._session.flush()
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.activated",
                entity_type="project_triage_template_activation",
                entity_id=activation.id,
                actor_id=context.actor_id,
                snapshot={
                    "project_id": str(project_id),
                    "category": template.category,
                    "template_id": str(template.id),
                    "template_version_id": str(version.id),
                    "version": version.version,
                    "previous_template_version_id": previous_version_id,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=200,
                response_body={
                    "template_id": str(template.id),
                    "template_version_id": str(version.id),
                },
            )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise _conflict(
                "Another activation won the race; retry against the current version.",
                code="TEMPLATE_VERSION_CONFLICT",
            )
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=template, version=version)

    def archive_template(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_ARCHIVE_OPERATION,
                "template_id": str(template_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_ARCHIVE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                template = self.templates.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                )
                if template is None:
                    raise _not_found()
                return TemplateOutcome(template=template, replayed=True)
        try:
            self._lock_project(context.workspace_id, project_id)
            template = self.templates.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            if template is None:
                raise _not_found()
            if if_match is not None and if_match != project_template_etag(template):
                raise _precondition_failed()
            if template.status == "archived":
                return TemplateOutcome(template=template, replayed=True)
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_ARCHIVE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            template.status = "archived"
            template.updated_at = _now()
            activation = self.activations.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                category=template.category,
            )
            if activation is not None and activation.template_id == template.id:
                self.activations.delete(activation)
            self._session.flush()
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.archived",
                entity_type="project_triage_template",
                entity_id=template.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template.id),
                    "project_id": str(project_id),
                    "category": template.category,
                    "status": template.status,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=200,
                response_body={"template_id": str(template.id)},
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=template)

    def deprecate_template(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> TemplateOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": TEMPLATE_DEPRECATE_OPERATION,
                "template_id": str(template_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                TEMPLATE_DEPRECATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                template = self.templates.get(
                    workspace_id=context.workspace_id,
                    project_id=project_id,
                    template_id=template_id,
                )
                if template is None:
                    raise _not_found()
                return TemplateOutcome(template=template, replayed=True)
        try:
            template = self.templates.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                template_id=template_id,
            )
            if template is None:
                raise _not_found()
            if if_match is not None and if_match != project_template_etag(template):
                raise _precondition_failed()
            if template.status == "archived":
                raise _conflict(
                    "An archived template cannot be deprecated.",
                    code="TEMPLATE_VERSION_IMMUTABLE",
                )
            if template.status == "deprecated":
                return TemplateOutcome(template=template, replayed=True)
            record = self._reserve(
                context.workspace_id,
                TEMPLATE_DEPRECATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            template.status = "deprecated"
            template.updated_at = _now()
            self._session.flush()
            self.audit.append(
                workspace_id=context.workspace_id,
                action="triage_template.deprecated",
                entity_type="project_triage_template",
                entity_id=template.id,
                actor_id=context.actor_id,
                snapshot={
                    "template_id": str(template.id),
                    "project_id": str(project_id),
                    "category": template.category,
                    "status": template.status,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                response_status=200,
                response_body={"template_id": str(template.id)},
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return TemplateOutcome(template=template)

    # -- reads ------------------------------------------------------------

    def get_template(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
    ) -> tuple[
        ProjectTriageTemplate,
        list[ProjectTriageTemplateVersion],
        ProjectTriageTemplateActivation | None,
    ]:
        template = self.templates.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )
        if template is None:
            raise _not_found()
        versions = self.versions.list_for_template(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )
        activation = self.activations.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            category=template.category,
        )
        return template, versions, activation

    def list_templates(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        category: str | None,
        status: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        after=None,
        descending: bool = False,
    ) -> list[ProjectTriageTemplate]:
        self._require_project(context.workspace_id, project_id)
        if category is not None:
            self._validate_category(category)
        if status is not None and status not in TRIAGE_TEMPLATE_STATUS_VALUES:
            raise _validation("Unknown template status filter.")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        return self.templates.list_page(
            workspace_id=context.workspace_id,
            project_id=project_id,
            category=category,
            status=status,
            limit=limit + 1,
            after=after,
            descending=descending,
        )

    def list_versions(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        template_id: UUID,
    ) -> list[ProjectTriageTemplateVersion]:
        template = self.templates.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )
        if template is None:
            raise _not_found()
        return self.versions.list_for_template(
            workspace_id=context.workspace_id,
            project_id=project_id,
            template_id=template_id,
        )

    # -- effective context / triage integration ---------------------------

    def resolve_effective(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        category: str,
    ) -> tuple[
        ProjectTriageConfiguration | None,
        ProjectTriageTemplate | None,
        ProjectTriageTemplateVersion | None,
    ]:
        configuration = self.configurations.get(
            workspace_id=workspace_id, project_id=project_id
        )
        activation = self.activations.get(
            workspace_id=workspace_id, project_id=project_id, category=category
        )
        if activation is None:
            return configuration, None, None
        template = self.templates.get(
            workspace_id=workspace_id,
            project_id=project_id,
            template_id=activation.template_id,
        )
        version = self.versions.get(
            workspace_id=workspace_id,
            project_id=project_id,
            template_id=activation.template_id,
            version_id=activation.template_version_id,
        )
        if template is None or version is None:
            return configuration, None, None
        if template.status == "archived" or version.status != "published":
            return configuration, None, None
        return configuration, template, version

    def effective_triage_context(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID,
        category: str,
        custom_fields: dict | None,
        action: str = "triage",
        current_category: str | None = None,
        triage_notes: str | None = None,
        business_impact: str | None = None,
        business_urgency: str | None = None,
    ) -> EffectiveTriageContext:
        return self._build_effective_context(
            workspace_id=context.workspace_id,
            project_id=project_id,
            category=category,
            custom_fields=custom_fields,
            action=action,
            current_category=current_category,
            triage_notes=triage_notes,
            business_impact=business_impact,
            business_urgency=business_urgency,
        )

    def preview(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID,
        category: str,
        custom_fields: dict | None,
        triage_notes: str | None = None,
        business_impact: str | None = None,
        business_urgency: str | None = None,
    ) -> dict:
        self._require_project(context.workspace_id, project_id)
        try:
            effective = self._build_effective_context(
                workspace_id=context.workspace_id,
                project_id=project_id,
                category=category,
                custom_fields=custom_fields,
                action="triage",
                current_category=None,
                triage_notes=triage_notes,
                business_impact=business_impact,
                business_urgency=business_urgency,
            )
        except ProblemError as exc:
            return {
                "valid": False,
                "code": exc.code,
                "errors": exc.errors or [],
                "effective_template": None,
                "normalized_custom_fields": None,
            }
        template = effective.version
        return {
            "valid": True,
            "code": None,
            "errors": [],
            "effective_template": (
                {
                    "template_id": str(template.template_id),
                    "template_version_id": str(template.id),
                    "version": template.version,
                    "schema_version": template.schema_version,
                    "category": category,
                }
                if template is not None
                else None
            ),
            "normalized_custom_fields": effective.custom_fields,
        }

    def assert_proposal_eligible(
        self, context: AuthorizationContext, consultation
    ) -> None:
        configuration, _template, version = self.resolve_effective(
            workspace_id=context.workspace_id,
            project_id=consultation.project_id,
            category=consultation.category,
        )
        configuration_rules = (
            configuration.workflow_rules
            if configuration is not None and configuration.enabled
            else {}
        )
        template_rules = (
            (version.definition or {}).get("workflow") if version is not None else {}
        )
        rules = merge_workflow_rules(configuration_rules, template_rules)
        required = rules.get("require_evidence_for_categories") or []
        if consultation.category not in required:
            return
        evidence = self.evidence.list_for_consultation(
            workspace_id=context.workspace_id,
            consultation_id=consultation.id,
        )
        evaluate_workflow(
            rules,
            category=consultation.category,
            action="proposal",
            has_evidence=bool(evidence),
        )

    def _build_effective_context(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        category: str,
        custom_fields: dict | None,
        action: str,
        current_category: str | None,
        triage_notes: str | None,
        business_impact: str | None,
        business_urgency: str | None,
    ) -> EffectiveTriageContext:
        self._validate_category(category)
        configuration, template, version = self.resolve_effective(
            workspace_id=workspace_id, project_id=project_id, category=category
        )
        configuration_enabled = bool(configuration and configuration.enabled)
        configuration_rules = (
            configuration.workflow_rules if configuration_enabled else {}
        )
        template_definition = version.definition if version is not None else {}
        template_rules = template_definition.get("workflow") or {}
        rules = merge_workflow_rules(configuration_rules, template_rules)
        rules.setdefault("require_justification_for_reclassification", True)

        if rules.get("require_template_for_new_triage") and version is None:
            raise _unprocessable(
                "The project requires an active template for this category.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )

        fields: list[dict] = []
        if configuration_enabled:
            for field in configuration.custom_fields or []:
                if category in field.get("categories", []):
                    fields.append(dict(field))
        if version is not None:
            for field in template_definition.get("fields", []):
                if field.get("status") != "active":
                    continue
                if category not in field.get("categories", []):
                    continue
                fields.append(dict(field))
        seen: set[str] = set()
        for field in fields:
            if field["key"] in seen:
                raise _conflict(
                    "The project configuration and active template define the same "
                    "custom field key.",
                    code="TRIAGE_CONFIGURATION_CONFLICT",
                )
            seen.add(field["key"])

        template_defaults = template_definition.get("defaults") or {}
        for field in fields:
            if field["key"] in template_defaults:
                field["default"] = template_defaults[field["key"]]

        required_keys: set[str] = set()
        if version is not None:
            required_keys.update(template_definition.get("required_fields") or [])
        if configuration_enabled:
            required_keys.update(
                (configuration.required_fields or {}).get(category, [])
            )
        unknown_required = [
            key
            for key in required_keys
            if key not in seen and key not in CORE_CRITERIA_KEYS
        ]
        if unknown_required:
            raise _conflict(
                "The project requires a field that is not defined by the active "
                "template or the baseline category contract.",
                code="TRIAGE_CONFIGURATION_CONFLICT",
            )

        normalized_values = apply_and_validate_field_values(
            fields,
            custom_fields,
            required_keys=frozenset(key for key in required_keys if key in seen),
        )
        evaluate_workflow(
            rules,
            category=category,
            action=action,
            current_category=current_category,
            triage_notes=triage_notes,
            business_impact=business_impact,
            business_urgency=business_urgency,
        )
        snapshot = {
            "source": (
                "project_template"
                if version is not None
                else (
                    "project_configuration"
                    if configuration_enabled
                    else "baseline"
                )
            ),
            "category": category,
            "schema_version": version.schema_version if version is not None else 1,
            "configuration_version": (
                configuration.version if configuration is not None else None
            ),
            "template": (
                {
                    "template_id": str(template.id),
                    "template_version_id": str(version.id),
                    "key": template.key,
                    "name": template.name,
                    "version": version.version,
                    "schema_version": version.schema_version,
                }
                if template is not None and version is not None
                else None
            ),
            "fields": fields,
            "required_fields": sorted(required_keys),
            "workflow_rules": rules,
            "deterministic": True,
        }
        return EffectiveTriageContext(
            category=category,
            custom_fields=normalized_values,
            template=template,
            version=version,
            snapshot=snapshot,
        )

    # -- internals --------------------------------------------------------

    def _validate_required_references(
        self, required_fields: dict[str, list[str]], custom_fields: list[dict]
    ) -> None:
        keys = {field["key"] for field in custom_fields}
        applicable: dict[str, set[str]] = {
            category: {
                field["key"]
                for field in custom_fields
                if category in field.get("categories", [])
            }
            for category in TRIAGE_CATEGORY_VALUES
        }
        for category, required in required_fields.items():
            for key in required:
                if key in CORE_CRITERIA_KEYS:
                    continue
                if key not in keys:
                    raise _unprocessable(
                        "A required field is not defined by the project configuration.",
                        code="TRIAGE_CONFIGURATION_CONFLICT",
                    )
                if key not in applicable[category]:
                    raise _unprocessable(
                        "A required field is not applicable to its category.",
                        code="TRIAGE_CONFIGURATION_CONFLICT",
                    )

    def _require_project(self, workspace_id: UUID, project_id: UUID) -> None:
        if (
            self.projects.get(workspace_id=workspace_id, project_id=project_id)
            is None
        ):
            raise _not_found()

    def _lock_project(self, workspace_id: UUID, project_id: UUID) -> None:
        statement = (
            select(Project)
            .where(
                Project.workspace_id == workspace_id, Project.id == project_id
            )
            .with_for_update()
        )
        if self._session.execute(statement).scalar_one_or_none() is None:
            raise _not_found()

    def _lock_activation(
        self, workspace_id: UUID, project_id: UUID, category: str
    ) -> None:
        key = f"triage-activation:{workspace_id}:{project_id}:{category}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )

    @staticmethod
    def _validate_category(category: str) -> None:
        if category not in TRIAGE_CATEGORY_VALUES:
            raise _validation("Unknown triage category.")

    def _validate_template_metadata(
        self, key: str, name: str, description: str | None
    ) -> None:
        if (
            not isinstance(key, str)
            or not 2 <= len(key) <= 64
            or key[0] not in "abcdefghijklmnopqrstuvwxyz"
            or any(
                char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in key
            )
        ):
            raise _validation("The template key is invalid.")
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            raise _validation("A template name must be 1 to 120 characters.")
        if description is not None and (
            not isinstance(description, str)
            or len(description) > MAX_TEMPLATE_DESCRIPTION
        ):
            raise _validation("A template description is too long.")

    def _reserve(self, workspace_id, operation, idempotency_key, request_fingerprint):
        if idempotency_key is None:
            return None
        return self.idempotency.reserve(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def _complete(self, record, *, response_status, response_body) -> None:
        if record is not None:
            self.idempotency.complete(
                record,
                response_status=response_status,
                response_body=response_body,
            )

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict | None:
        stored = self.idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise ProblemError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                detail="The idempotency key was reused with a different request.",
                title="Conflict",
            )
        return stored.response_body or {}
