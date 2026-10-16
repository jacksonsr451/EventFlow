"""Workspace membership repository (Issue #9)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eventflow_work_management.models.membership import WorkspaceMembership
from eventflow_work_management.models.workspace import Workspace
from eventflow_work_management.repositories.base import Repository


class MembershipRepository(Repository):
    """Reads and mutates tenant-scoped authorization bindings.

    Mutating methods only ``flush``; the owning service commits exactly once so
    a membership change and its audit record share one transaction.
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def find_active(
        self, *, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMembership | None:
        statement = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.state == "active",
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get(
        self, *, workspace_id: UUID, membership_id: UUID
    ) -> WorkspaceMembership | None:
        statement = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.id == membership_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_workspace(self, workspace_id: UUID) -> list[WorkspaceMembership]:
        statement = (
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)
        )
        return list(self._session.execute(statement).scalars())

    def add(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        role: str,
        invited_by: UUID | None = None,
    ) -> WorkspaceMembership:
        membership = WorkspaceMembership(
            id=uuid4(),
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            state="active",
            invited_by=invited_by,
        )
        self._session.add(membership)
        self._session.flush()
        return membership

    def count_active_owners(self, workspace_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == "owner",
                WorkspaceMembership.state == "active",
            )
        )
        return int(self._session.execute(statement).scalar_one())

    def change_role(self, membership: WorkspaceMembership, role: str) -> None:
        membership.role = role
        self._session.flush()

    def revoke(self, membership: WorkspaceMembership, *, reason: str) -> None:
        membership.state = "revoked"
        membership.revoked_at = datetime.now(UTC)
        membership.revoke_reason = reason
        self._session.flush()

    def reactivate(self, membership: WorkspaceMembership, *, role: str) -> None:
        membership.state = "active"
        membership.role = role
        membership.revoked_at = None
        membership.revoke_reason = None
        self._session.flush()

    def lock_workspace(self, workspace_id: UUID) -> bool:
        """Take a row lock on the workspace to serialize membership invariants.

        Returns ``False`` when the workspace row is absent. Concurrent owner
        changes for one workspace queue on this lock, so the "at least one
        owner" invariant is evaluated against a stable membership set.
        """
        statement = (
            select(Workspace.id)
            .where(Workspace.id == workspace_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none() is not None
