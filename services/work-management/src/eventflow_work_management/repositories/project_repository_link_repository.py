"""Data access for project repository associations (Issue #44)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models.project_repository import (
    ProjectRepositoryLink,
)
from eventflow_work_management.repositories.base import Repository


class ProjectRepositoryLinkRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        provider: str,
        provider_instance_id: str,
        remote_repository_id: str,
        repository_full_path: str,
        canonical_repository_url: str,
        display_name: str,
        default_branch: str | None,
        created_by: UUID,
    ) -> ProjectRepositoryLink:
        link = ProjectRepositoryLink(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            provider=provider,
            provider_instance_id=provider_instance_id,
            remote_repository_id=remote_repository_id,
            repository_full_path=repository_full_path,
            canonical_repository_url=canonical_repository_url,
            display_name=display_name,
            default_branch=default_branch,
            status="active",
            verification_status="configured",
            version=1,
            created_by=created_by,
        )
        self._session.add(link)
        self._session.flush()
        return link

    def get(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        repository_id: UUID,
    ) -> ProjectRepositoryLink | None:
        statement = select(ProjectRepositoryLink).where(
            ProjectRepositoryLink.workspace_id == workspace_id,
            ProjectRepositoryLink.project_id == project_id,
            ProjectRepositoryLink.id == repository_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        repository_id: UUID,
    ) -> ProjectRepositoryLink | None:
        statement = (
            select(ProjectRepositoryLink)
            .where(
                ProjectRepositoryLink.workspace_id == workspace_id,
                ProjectRepositoryLink.project_id == project_id,
                ProjectRepositoryLink.id == repository_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def find_identity(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        provider: str,
        provider_instance_id: str,
        remote_repository_id: str,
    ) -> ProjectRepositoryLink | None:
        statement = select(ProjectRepositoryLink).where(
            ProjectRepositoryLink.workspace_id == workspace_id,
            ProjectRepositoryLink.project_id == project_id,
            ProjectRepositoryLink.provider == provider,
            ProjectRepositoryLink.provider_instance_id == provider_instance_id,
            ProjectRepositoryLink.remote_repository_id == remote_repository_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        provider: str | None,
        status: str | None,
        include_archived: bool,
        sort_key: str,
        descending: bool,
        limit: int,
        after: tuple[object, UUID] | None = None,
    ) -> list[ProjectRepositoryLink]:
        column = getattr(ProjectRepositoryLink, sort_key)
        statement = select(ProjectRepositoryLink).where(
            ProjectRepositoryLink.workspace_id == workspace_id,
            ProjectRepositoryLink.project_id == project_id,
        )
        if provider is not None:
            statement = statement.where(ProjectRepositoryLink.provider == provider)
        if status is not None:
            statement = statement.where(ProjectRepositoryLink.status == status)
        elif not include_archived:
            statement = statement.where(ProjectRepositoryLink.status != "archived")
        if after is not None:
            value, after_id = after
            if descending:
                statement = statement.where(
                    tuple_(column, ProjectRepositoryLink.id)
                    < tuple_(value, after_id)
                )
            else:
                statement = statement.where(
                    tuple_(column, ProjectRepositoryLink.id)
                    > tuple_(value, after_id)
                )
        if descending:
            statement = statement.order_by(
                column.desc(), ProjectRepositoryLink.id.desc()
            )
        else:
            statement = statement.order_by(column, ProjectRepositoryLink.id)
        return list(self._session.execute(statement.limit(limit)).scalars())

    def touch(self, link: ProjectRepositoryLink) -> None:
        """Bump the optimistic-concurrency version."""
        link.version = link.version + 1
        self._session.flush()
