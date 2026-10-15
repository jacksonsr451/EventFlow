"""WorkItem repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import WorkItem
from eventflow_work_management.repositories.base import Repository


class WorkItemRepository(Repository):
    """Creates WorkItems; the database trigger validates their origin."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create_from_approved_proposal(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        proposal_id: UUID,
        proposal_version: int,
        approval_id: UUID,
        title: str,
        description: str,
        acceptance_criteria: list,
        category: str,
        priority: str,
        status: str = "ready",
        assignee_id: UUID | None = None,
        external_issue_links: list | None = None,
    ) -> WorkItem:
        work_item = WorkItem(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            origin_proposal_id=proposal_id,
            origin_proposal_version=proposal_version,
            origin_approval_id=approval_id,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            category=category,
            priority=priority,
            status=status,
            assignee_id=assignee_id,
            external_issue_links=external_issue_links or [],
        )
        self._session.add(work_item)
        self._session.commit()
        return work_item

    def get(self, *, workspace_id: UUID, work_item_id: UUID) -> WorkItem | None:
        statement = select(WorkItem).where(
            WorkItem.workspace_id == workspace_id, WorkItem.id == work_item_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_project(self, *, workspace_id: UUID, project_id: UUID) -> list[WorkItem]:
        statement = (
            select(WorkItem)
            .where(WorkItem.workspace_id == workspace_id, WorkItem.project_id == project_id)
            .order_by(WorkItem.created_at)
        )
        return list(self._session.execute(statement).scalars())
