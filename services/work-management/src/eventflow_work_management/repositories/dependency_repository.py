"""Persistence and cycle detection for WorkItem dependency edges."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from eventflow_work_management.models import WorkItem, WorkItemDependency
from eventflow_work_management.repositories.base import Repository

_CYCLE_SQL = text(
    """
    WITH RECURSIVE reachable(node) AS (
        SELECT CAST(:start_id AS uuid)
        UNION
        SELECT d.blocked_work_item_id
        FROM work_item_dependencies d
        JOIN reachable r ON d.blocking_work_item_id = r.node
        WHERE d.workspace_id = :workspace_id
    )
    SELECT 1 FROM reachable WHERE node = CAST(:target_id AS uuid) LIMIT 1
    """
)


class WorkItemDependencyRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def acquire_workspace_lock(self, workspace_id: UUID) -> None:
        """Serialize graph mutations for one workspace in this transaction."""
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"work-item-dependencies:{workspace_id}"},
        )

    def get(
        self, *, workspace_id: UUID, dependency_id: UUID
    ) -> WorkItemDependency | None:
        statement = select(WorkItemDependency).where(
            WorkItemDependency.workspace_id == workspace_id,
            WorkItemDependency.id == dependency_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_edge(
        self,
        *,
        workspace_id: UUID,
        blocking_work_item_id: UUID,
        blocked_work_item_id: UUID,
    ) -> WorkItemDependency | None:
        statement = select(WorkItemDependency).where(
            WorkItemDependency.workspace_id == workspace_id,
            WorkItemDependency.blocking_work_item_id == blocking_work_item_id,
            WorkItemDependency.blocked_work_item_id == blocked_work_item_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        blocking_work_item_id: UUID,
        blocked_work_item_id: UUID,
        created_by: UUID,
    ) -> WorkItemDependency:
        edge = WorkItemDependency(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            blocking_work_item_id=blocking_work_item_id,
            blocked_work_item_id=blocked_work_item_id,
            created_by=created_by,
        )
        self._session.add(edge)
        self._session.flush()
        return edge

    def delete(self, edge: WorkItemDependency) -> None:
        self._session.delete(edge)
        self._session.flush()

    def would_create_cycle(
        self,
        *,
        workspace_id: UUID,
        blocking_work_item_id: UUID,
        blocked_work_item_id: UUID,
    ) -> bool:
        """Whether adding blocking->blocked closes a cycle.

        A cycle exists when ``blocking`` is already reachable from ``blocked``
        by following existing edges (blocking -> blocked).
        """
        row = self._session.execute(
            _CYCLE_SQL,
            {
                "workspace_id": workspace_id,
                "start_id": blocked_work_item_id,
                "target_id": blocking_work_item_id,
            },
        ).first()
        return row is not None

    def list_dependencies_of(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> list[WorkItemDependency]:
        """Edges where the given WorkItem is blocked by another."""
        statement = (
            select(WorkItemDependency)
            .where(
                WorkItemDependency.workspace_id == workspace_id,
                WorkItemDependency.blocked_work_item_id == work_item_id,
            )
            .order_by(WorkItemDependency.created_at, WorkItemDependency.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_dependents_of(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> list[WorkItemDependency]:
        """Edges where the given WorkItem blocks another."""
        statement = (
            select(WorkItemDependency)
            .where(
                WorkItemDependency.workspace_id == workspace_id,
                WorkItemDependency.blocking_work_item_id == work_item_id,
            )
            .order_by(WorkItemDependency.created_at, WorkItemDependency.id)
        )
        return list(self._session.execute(statement).scalars())

    def unresolved_blockers(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> list[WorkItem]:
        statement = (
            select(WorkItem)
            .join(
                WorkItemDependency,
                (WorkItemDependency.blocking_work_item_id == WorkItem.id)
                & (WorkItemDependency.workspace_id == WorkItem.workspace_id),
            )
            .where(
                WorkItemDependency.workspace_id == workspace_id,
                WorkItemDependency.blocked_work_item_id == work_item_id,
                WorkItem.status.notin_(("done", "cancelled")),
            )
        )
        return list(self._session.execute(statement).scalars())
