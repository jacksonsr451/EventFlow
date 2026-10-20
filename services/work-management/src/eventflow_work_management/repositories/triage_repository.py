"""Repositories for project triage configuration and templates (Issue #41)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    ProjectTriageConfiguration,
    ProjectTriageTemplate,
    ProjectTriageTemplateActivation,
    ProjectTriageTemplateVersion,
)
from eventflow_work_management.repositories.base import Repository


class ProjectTriageConfigurationRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> ProjectTriageConfiguration | None:
        statement = select(ProjectTriageConfiguration).where(
            ProjectTriageConfiguration.workspace_id == workspace_id,
            ProjectTriageConfiguration.project_id == project_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> ProjectTriageConfiguration | None:
        statement = (
            select(ProjectTriageConfiguration)
            .where(
                ProjectTriageConfiguration.workspace_id == workspace_id,
                ProjectTriageConfiguration.project_id == project_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        enabled: bool,
        required_fields: dict,
        custom_fields: list,
        workflow_rules: dict,
        actor_id: UUID,
    ) -> ProjectTriageConfiguration:
        configuration = ProjectTriageConfiguration(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            enabled=enabled,
            required_fields=required_fields,
            custom_fields=custom_fields,
            workflow_rules=workflow_rules,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(configuration)
        self._session.flush()
        return configuration

    def update(
        self,
        configuration: ProjectTriageConfiguration,
        *,
        enabled: bool,
        required_fields: dict,
        custom_fields: list,
        workflow_rules: dict,
        actor_id: UUID,
        updated_at: datetime,
    ) -> ProjectTriageConfiguration:
        configuration.enabled = enabled
        configuration.required_fields = required_fields
        configuration.custom_fields = custom_fields
        configuration.workflow_rules = workflow_rules
        configuration.version = configuration.version + 1
        configuration.updated_by = actor_id
        configuration.updated_at = updated_at
        self._session.flush()
        return configuration


class ProjectTriageTemplateRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        category: str,
        key: str,
        name: str,
        description: str | None,
        actor_id: UUID,
    ) -> ProjectTriageTemplate:
        template = ProjectTriageTemplate(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            category=category,
            key=key,
            name=name,
            description=description,
            status="active",
            created_by=actor_id,
        )
        self._session.add(template)
        self._session.flush()
        return template

    def get(
        self, *, workspace_id: UUID, project_id: UUID, template_id: UUID
    ) -> ProjectTriageTemplate | None:
        statement = select(ProjectTriageTemplate).where(
            ProjectTriageTemplate.workspace_id == workspace_id,
            ProjectTriageTemplate.project_id == project_id,
            ProjectTriageTemplate.id == template_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, project_id: UUID, template_id: UUID
    ) -> ProjectTriageTemplate | None:
        statement = (
            select(ProjectTriageTemplate)
            .where(
                ProjectTriageTemplate.workspace_id == workspace_id,
                ProjectTriageTemplate.project_id == project_id,
                ProjectTriageTemplate.id == template_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def find_by_key(
        self, *, workspace_id: UUID, project_id: UUID, key: str
    ) -> ProjectTriageTemplate | None:
        statement = select(ProjectTriageTemplate).where(
            ProjectTriageTemplate.workspace_id == workspace_id,
            ProjectTriageTemplate.project_id == project_id,
            ProjectTriageTemplate.key == key,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        category: str | None,
        status: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
        descending: bool = False,
    ) -> list[ProjectTriageTemplate]:
        statement = select(ProjectTriageTemplate).where(
            ProjectTriageTemplate.workspace_id == workspace_id,
            ProjectTriageTemplate.project_id == project_id,
        )
        if category is not None:
            statement = statement.where(ProjectTriageTemplate.category == category)
        if status is not None:
            statement = statement.where(ProjectTriageTemplate.status == status)
        if after is not None:
            created_at, after_id = after
            comparison = (
                tuple_(ProjectTriageTemplate.created_at, ProjectTriageTemplate.id)
                < tuple_(created_at, after_id)
                if descending
                else tuple_(ProjectTriageTemplate.created_at, ProjectTriageTemplate.id)
                > tuple_(created_at, after_id)
            )
            statement = statement.where(comparison)
        ordering = (
            ProjectTriageTemplate.created_at.desc()
            if descending
            else ProjectTriageTemplate.created_at.asc()
        )
        id_ordering = (
            ProjectTriageTemplate.id.desc()
            if descending
            else ProjectTriageTemplate.id.asc()
        )
        statement = statement.order_by(ordering, id_ordering).limit(limit)
        return list(self._session.execute(statement).scalars())


class ProjectTriageTemplateVersionRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        template_id: UUID,
        version: int,
        definition: dict,
        actor_id: UUID,
    ) -> ProjectTriageTemplateVersion:
        record = ProjectTriageTemplateVersion(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            template_id=template_id,
            version=version,
            schema_version=1,
            status="draft",
            definition=definition,
            created_by=actor_id,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        template_id: UUID,
        version_id: UUID,
    ) -> ProjectTriageTemplateVersion | None:
        statement = select(ProjectTriageTemplateVersion).where(
            ProjectTriageTemplateVersion.workspace_id == workspace_id,
            ProjectTriageTemplateVersion.project_id == project_id,
            ProjectTriageTemplateVersion.template_id == template_id,
            ProjectTriageTemplateVersion.id == version_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        template_id: UUID,
        version_id: UUID,
    ) -> ProjectTriageTemplateVersion | None:
        statement = (
            select(ProjectTriageTemplateVersion)
            .where(
                ProjectTriageTemplateVersion.workspace_id == workspace_id,
                ProjectTriageTemplateVersion.project_id == project_id,
                ProjectTriageTemplateVersion.template_id == template_id,
                ProjectTriageTemplateVersion.id == version_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def latest_version(
        self, *, workspace_id: UUID, project_id: UUID, template_id: UUID
    ) -> ProjectTriageTemplateVersion | None:
        statement = (
            select(ProjectTriageTemplateVersion)
            .where(
                ProjectTriageTemplateVersion.workspace_id == workspace_id,
                ProjectTriageTemplateVersion.project_id == project_id,
                ProjectTriageTemplateVersion.template_id == template_id,
            )
            .order_by(ProjectTriageTemplateVersion.version.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def next_version_number(
        self, *, workspace_id: UUID, project_id: UUID, template_id: UUID
    ) -> int:
        statement = select(
            func.coalesce(func.max(ProjectTriageTemplateVersion.version), 0)
        ).where(
            ProjectTriageTemplateVersion.workspace_id == workspace_id,
            ProjectTriageTemplateVersion.project_id == project_id,
            ProjectTriageTemplateVersion.template_id == template_id,
        )
        return int(self._session.execute(statement).scalar_one()) + 1

    def list_for_template(
        self, *, workspace_id: UUID, project_id: UUID, template_id: UUID
    ) -> list[ProjectTriageTemplateVersion]:
        statement = (
            select(ProjectTriageTemplateVersion)
            .where(
                ProjectTriageTemplateVersion.workspace_id == workspace_id,
                ProjectTriageTemplateVersion.project_id == project_id,
                ProjectTriageTemplateVersion.template_id == template_id,
            )
            .order_by(ProjectTriageTemplateVersion.version)
        )
        return list(self._session.execute(statement).scalars())


class ProjectTriageTemplateActivationRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get(
        self, *, workspace_id: UUID, project_id: UUID, category: str
    ) -> ProjectTriageTemplateActivation | None:
        statement = select(ProjectTriageTemplateActivation).where(
            ProjectTriageTemplateActivation.workspace_id == workspace_id,
            ProjectTriageTemplateActivation.project_id == project_id,
            ProjectTriageTemplateActivation.category == category,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, project_id: UUID, category: str
    ) -> ProjectTriageTemplateActivation | None:
        statement = (
            select(ProjectTriageTemplateActivation)
            .where(
                ProjectTriageTemplateActivation.workspace_id == workspace_id,
                ProjectTriageTemplateActivation.project_id == project_id,
                ProjectTriageTemplateActivation.category == category,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        category: str,
        template_id: UUID,
        template_version_id: UUID,
        actor_id: UUID,
        activated_at: datetime,
    ) -> ProjectTriageTemplateActivation:
        activation = ProjectTriageTemplateActivation(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            category=category,
            template_id=template_id,
            template_version_id=template_version_id,
            activated_by=actor_id,
            activated_at=activated_at,
        )
        self._session.add(activation)
        self._session.flush()
        return activation

    def delete(self, activation: ProjectTriageTemplateActivation) -> None:
        self._session.delete(activation)
        self._session.flush()

    def list_for_project(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> list[ProjectTriageTemplateActivation]:
        statement = (
            select(ProjectTriageTemplateActivation)
            .where(
                ProjectTriageTemplateActivation.workspace_id == workspace_id,
                ProjectTriageTemplateActivation.project_id == project_id,
            )
            .order_by(ProjectTriageTemplateActivation.category)
        )
        return list(self._session.execute(statement).scalars())
