"""Workspace and Project repositories."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import Project, Workspace
from eventflow_work_management.models.membership import WorkspaceMembership
from eventflow_work_management.repositories.base import Repository


class WorkspaceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(self, *, name: str, slug: str) -> Workspace:
        workspace = Workspace(id=uuid4(), name=name, slug=slug)
        self._session.add(workspace)
        self._session.commit()
        return workspace

    def add(self, *, name: str, slug: str) -> Workspace:
        """Add a workspace and flush without committing.

        The owning service commits once so workspace creation, the founding
        owner membership, and the audit record are atomic.
        """
        workspace = Workspace(id=uuid4(), name=name, slug=slug)
        self._session.add(workspace)
        self._session.flush()
        return workspace

    def get(self, workspace_id: UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)

    def find_by_slug(self, slug: str) -> Workspace | None:
        statement = select(Workspace).where(Workspace.slug == slug)
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, workspace_id: UUID) -> Workspace | None:
        statement = (
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_user(self, user_id: UUID) -> list[Workspace]:
        statement = (
            select(Workspace)
            .join(
                WorkspaceMembership,
                WorkspaceMembership.workspace_id == Workspace.id,
            )
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.state == "active",
            )
            .order_by(Workspace.created_at, Workspace.id)
        )
        return list(self._session.execute(statement).scalars())

    def update_name(self, workspace: Workspace, name: str) -> None:
        workspace.name = name
        self._session.flush()


class ProjectRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(
        self,
        *,
        workspace_id: UUID,
        key: str,
        name: str,
        description: str | None = None,
    ) -> Project:
        project = Project(
            id=uuid4(),
            workspace_id=workspace_id,
            key=key,
            name=name,
            description=description,
        )
        self._session.add(project)
        self._session.commit()
        return project

    def add(
        self,
        *,
        workspace_id: UUID,
        key: str,
        name: str,
        description: str | None = None,
    ) -> Project:
        project = Project(
            id=uuid4(),
            workspace_id=workspace_id,
            key=key,
            name=name,
            description=description,
        )
        self._session.add(project)
        self._session.flush()
        return project

    def get(self, *, workspace_id: UUID, project_id: UUID) -> Project | None:
        statement = select(Project).where(
            Project.workspace_id == workspace_id, Project.id == project_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_workspace(self, workspace_id: UUID) -> list[Project]:
        statement = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at, Project.id)
        )
        return list(self._session.execute(statement).scalars())

    def update(
        self,
        project: Project,
        *,
        name: str | None,
        description: str | None,
        update_description: bool,
    ) -> None:
        if name is not None:
            project.name = name
        if update_description:
            project.description = description
        self._session.flush()
