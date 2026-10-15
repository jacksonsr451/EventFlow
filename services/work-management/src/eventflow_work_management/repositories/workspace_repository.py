"""Workspace and Project repositories."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import Project, Workspace
from eventflow_work_management.repositories.base import Repository


class WorkspaceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(self, *, name: str, slug: str) -> Workspace:
        workspace = Workspace(id=uuid4(), name=name, slug=slug)
        self._session.add(workspace)
        self._session.commit()
        return workspace

    def get(self, workspace_id: UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)


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

    def get(self, *, workspace_id: UUID, project_id: UUID) -> Project | None:
        statement = select(Project).where(
            Project.workspace_id == workspace_id, Project.id == project_id
        )
        return self._session.execute(statement).scalar_one_or_none()
