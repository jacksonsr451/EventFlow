"""Project triage configuration and versioned template routes (Issue #41).

Project administrators own *additive* triage requirements on top of the existing
differentiated category contract. Reads are available to every workspace role;
mutations require the dedicated configuration/template management actions. Every
project-scoped path binds the workspace from the verified principal and the
project from the path, never from the body.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    authenticated_principal,
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import (
    ProjectTriageConfiguration,
    ProjectTriageTemplate,
    ProjectTriageTemplateActivation,
    ProjectTriageTemplateVersion,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)
from eventflow_work_management.services.triage_configuration import (
    TriageConfigurationService,
    project_configuration_etag,
    project_template_activation_etag,
    project_template_etag,
    project_template_version_etag,
)

router = APIRouter(tags=["Triage"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
CATEGORY_PATTERN = "^(bug|feature|chore|docs|security)$"
TEMPLATE_STATUS_PATTERN = "^(active|deprecated|archived)$"
IMPACT_PATTERN = "^(critical|high|moderate|low)$"
URGENCY_PATTERN = "^(immediate|elevated|normal|low)$"


class UpdateTriageConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    required_fields: dict[str, list[str]] | None = None
    custom_fields: list[dict] | None = None
    workflow_rules: dict | None = None


class CreateProjectTriageTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern=CATEGORY_PATTERN)
    key: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    definition: dict


class CreateProjectTriageTemplateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict


class TriageValidationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    category: str = Field(pattern=CATEGORY_PATTERN)
    custom_fields: dict | None = None
    triage_notes: str | None = Field(default=None, min_length=1)
    business_impact: str | None = Field(default=None, pattern=IMPACT_PATTERN)
    business_urgency: str | None = Field(default=None, pattern=URGENCY_PATTERN)


def _authorize(session, principal, workspace_id, action):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


def _idempotency_key(request: Request) -> str | None:
    supplied = request.headers.get("idempotency-key")
    if supplied is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.match(supplied):
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is malformed.",
            title="Invalid request",
        )
    return supplied


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _collection_etag(
    workspace_id: UUID, project_id: UUID, parts, *extra: object
) -> str:
    return (
        '"' + fingerprint([str(workspace_id), str(project_id), parts, *extra]) + '"'
    )


def _configuration_payload(
    configuration: ProjectTriageConfiguration | None,
    workspace_id: UUID,
    project_id: UUID,
) -> dict:
    if configuration is None:
        return {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "enabled": False,
            "required_fields": {},
            "custom_fields": [],
            "workflow_rules": {},
            "version": 0,
            "updated_at": None,
        }
    return {
        "workspace_id": configuration.workspace_id,
        "project_id": configuration.project_id,
        "enabled": configuration.enabled,
        "required_fields": configuration.required_fields,
        "custom_fields": configuration.custom_fields,
        "workflow_rules": configuration.workflow_rules,
        "version": configuration.version,
        "updated_at": configuration.updated_at,
    }


def _template_payload(
    template: ProjectTriageTemplate,
    activation: ProjectTriageTemplateActivation | None = None,
) -> dict:
    return {
        "template_id": template.id,
        "workspace_id": template.workspace_id,
        "project_id": template.project_id,
        "category": template.category,
        "key": template.key,
        "name": template.name,
        "description": template.description,
        "status": template.status,
        "created_by": template.created_by,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "activation": (
            _activation_payload(activation) if activation is not None else None
        ),
    }


def _version_payload(version: ProjectTriageTemplateVersion) -> dict:
    return {
        "template_version_id": version.id,
        "template_id": version.template_id,
        "workspace_id": version.workspace_id,
        "project_id": version.project_id,
        "version": version.version,
        "schema_version": version.schema_version,
        "status": version.status,
        "definition": version.definition,
        "created_by": version.created_by,
        "published_by": version.published_by,
        "published_at": version.published_at,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }


def _activation_payload(activation: ProjectTriageTemplateActivation) -> dict:
    return {
        "category": activation.category,
        "template_id": activation.template_id,
        "template_version_id": activation.template_version_id,
        "activated_by": activation.activated_by,
        "activated_at": activation.activated_at,
    }


def _template_detail(template, versions, activation) -> dict:
    return {
        "template": _template_payload(template, activation),
        "versions": [_version_payload(version) for version in versions],
        "activation": (
            _activation_payload(activation) if activation is not None else None
        ),
    }


# -- configuration ---------------------------------------------------------


@router.get(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-configuration"
)
def get_project_triage_configuration(
    workspace_id: UUID,
    project_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_CONFIGURATION_READ
    )
    configuration = TriageConfigurationService(session).get_configuration(
        context, project_id
    )
    response.headers["ETag"] = project_configuration_etag(
        configuration, workspace_id, project_id
    )
    return _configuration_payload(configuration, workspace_id, project_id)


@router.put(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-configuration"
)
def update_project_triage_configuration(
    workspace_id: UUID,
    project_id: UUID,
    payload: UpdateTriageConfigurationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_CONFIGURATION_MANAGE
    )
    outcome = TriageConfigurationService(session).update_configuration(
        context,
        project_id,
        enabled=payload.enabled,
        required_fields=payload.required_fields,
        custom_fields=payload.custom_fields,
        workflow_rules=payload.workflow_rules,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_configuration_etag(
        outcome.configuration, workspace_id, project_id
    )
    return _configuration_payload(
        outcome.configuration, workspace_id, project_id
    )


# -- templates -------------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates")
def list_project_triage_templates(
    workspace_id: UUID,
    project_id: UUID,
    response: Response,
    category: str | None = Query(default=None, pattern=CATEGORY_PATTERN),
    status: str | None = Query(default=None, pattern=TEMPLATE_STATUS_PATTERN),
    sort: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.TRIAGE_TEMPLATE_READ)
    sort_token = (sort or "created_at").strip()
    descending = sort_token.startswith("-")
    if sort_token.lstrip("-") != "created_at":
        raise _validation("The sort parameter is invalid.")
    after = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
            created_at = decoded.get("created_at")
            if not isinstance(created_at, datetime):
                raise CursorError("cursor is missing created_at")
            after = (created_at, decoded["id"])
        except (CursorError, KeyError, TypeError):
            raise _validation("The pagination cursor is invalid.")
    rows = TriageConfigurationService(session).list_templates(
        context,
        project_id,
        category=category,
        status=status,
        limit=limit,
        after=after,
        descending=descending,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor({"created_at": page[-1].created_at}, page[-1].id)
        if has_more and page
        else None
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        project_id,
        [f"{item.id}{item.status}{item.updated_at.isoformat()}" for item in page],
        next_cursor,
    )
    return {
        "items": [_template_payload(item) for item in page],
        "page_info": {"has_more": has_more, "next_cursor": next_cursor},
    }


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates",
    status_code=201,
)
def create_project_triage_template(
    workspace_id: UUID,
    project_id: UUID,
    payload: CreateProjectTriageTemplateRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    outcome = TriageConfigurationService(session).create_template(
        context,
        project_id,
        category=payload.category,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        definition=payload.definition,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_template_etag(outcome.template)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
        f"{outcome.template.id}"
    )
    return _template_payload(outcome.template)


@router.get(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/{template_id}"
)
def get_project_triage_template(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.TRIAGE_TEMPLATE_READ)
    template, versions, activation = TriageConfigurationService(
        session
    ).get_template(context, project_id, template_id)
    response.headers["ETag"] = project_template_etag(template)
    return _template_detail(template, versions, activation)


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
    "{template_id}/versions",
    status_code=201,
)
def create_project_triage_template_version(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    payload: CreateProjectTriageTemplateVersionRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    outcome = TriageConfigurationService(session).create_version(
        context,
        project_id,
        template_id,
        definition=payload.definition,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    assert outcome.version is not None
    response.headers["ETag"] = project_template_version_etag(outcome.version)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
        f"{template_id}/versions/{outcome.version.id}"
    )
    return _version_payload(outcome.version)


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
    "{template_id}/versions/{version_id}/publish"
)
def publish_project_triage_template_version(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    version_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    outcome = TriageConfigurationService(session).publish_version(
        context,
        project_id,
        template_id,
        version_id,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    assert outcome.version is not None
    response.headers["ETag"] = project_template_version_etag(outcome.version)
    return _version_payload(outcome.version)


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
    "{template_id}/versions/{version_id}/activate"
)
def activate_project_triage_template_version(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    version_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    service = TriageConfigurationService(session)
    outcome = service.activate_version(
        context,
        project_id,
        template_id,
        version_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    activation = service.activations.get(
        workspace_id=context.workspace_id,
        project_id=project_id,
        category=outcome.template.category,
    )
    response.headers["ETag"] = project_template_activation_etag(
        activation, workspace_id, project_id, outcome.template.category
    )
    return _template_payload(outcome.template, activation)


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
    "{template_id}/archive"
)
def archive_project_triage_template(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    outcome = TriageConfigurationService(session).archive_template(
        context,
        project_id,
        template_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_template_etag(outcome.template)
    return _template_payload(outcome.template)


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates/"
    "{template_id}/deprecate"
)
def deprecate_project_triage_template(
    workspace_id: UUID,
    project_id: UUID,
    template_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.TRIAGE_TEMPLATE_MANAGE
    )
    outcome = TriageConfigurationService(session).deprecate_template(
        context,
        project_id,
        template_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_template_etag(outcome.template)
    return _template_payload(outcome.template)


# -- preview ---------------------------------------------------------------


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/triage-validation/preview"
)
def preview_project_triage_validation(
    workspace_id: UUID,
    project_id: UUID,
    payload: TriageValidationPreviewRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_TRIAGE)
    if payload.project_id != project_id:
        raise _validation("The project_id in the body must match the path.")
    result = TriageConfigurationService(session).preview(
        context,
        project_id=project_id,
        category=payload.category,
        custom_fields=payload.custom_fields,
        triage_notes=payload.triage_notes,
        business_impact=payload.business_impact,
        business_urgency=payload.business_urgency,
    )
    response.headers["ETag"] = '"' + fingerprint(
        [str(workspace_id), str(project_id), result]
    ) + '"'
    return result
