"""WorkItem repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
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
        """Create and commit one WorkItem (standalone unit of work)."""
        work_item = self.build_from_approved_proposal(
            workspace_id=workspace_id,
            project_id=project_id,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approval_id=approval_id,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            category=category,
            priority=priority,
            status=status,
            assignee_id=assignee_id,
            external_issue_links=external_issue_links,
        )
        self._session.commit()
        return work_item

    def build_from_approved_proposal(
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
        """Add and flush a WorkItem inside the caller's transaction.

        It never commits, so an approval can create the WorkItem and its
        BoardCard atomically in a single transaction.
        """
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
        self._session.flush()
        return work_item

    def get(self, *, workspace_id: UUID, work_item_id: UUID) -> WorkItem | None:
        statement = select(WorkItem).where(
            WorkItem.workspace_id == workspace_id, WorkItem.id == work_item_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> WorkItem | None:
        statement = (
            select(WorkItem)
            .where(
                WorkItem.workspace_id == workspace_id, WorkItem.id == work_item_id
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assignee_id: UUID | None = None,
        sort_key: str = "created_at",
        descending: bool = False,
        limit: int,
        after: tuple | None = None,
    ) -> list[WorkItem]:
        column = getattr(WorkItem, sort_key)
        statement = select(WorkItem).where(WorkItem.workspace_id == workspace_id)
        if project_id is not None:
            statement = statement.where(WorkItem.project_id == project_id)
        if status is not None:
            statement = statement.where(WorkItem.status == status)
        if category is not None:
            statement = statement.where(WorkItem.category == category)
        if priority is not None:
            statement = statement.where(WorkItem.priority == priority)
        if assignee_id is not None:
            statement = statement.where(WorkItem.assignee_id == assignee_id)
        if after is not None:
            value, after_id = after
            if descending:
                statement = statement.where(
                    tuple_(column, WorkItem.id) < tuple_(value, after_id)
                )
            else:
                statement = statement.where(
                    tuple_(column, WorkItem.id) > tuple_(value, after_id)
                )
        if descending:
            statement = statement.order_by(column.desc(), WorkItem.id.desc())
        else:
            statement = statement.order_by(column, WorkItem.id)
        return list(self._session.execute(statement.limit(limit)).scalars())

    def set_status(self, work_item: WorkItem, *, status: str) -> None:
        work_item.status = status
        self._session.flush()

    def list_for_project(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> list[WorkItem]:
        statement = (
            select(WorkItem)
            .where(
                WorkItem.workspace_id == workspace_id, WorkItem.project_id == project_id
            )
            .order_by(WorkItem.created_at)
        )
        return list(self._session.execute(statement).scalars())
