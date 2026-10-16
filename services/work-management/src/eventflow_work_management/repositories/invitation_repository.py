"""Workspace invitation repository (Issue #9)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models.membership import WorkspaceInvitation
from eventflow_work_management.repositories.base import Repository


class InvitationRepository(Repository):
    """Reads and mutates identity-bound workspace invitations.

    Only the digest of the bearer token is persisted; mutating methods flush and
    the service commits once with the audit record.
    """

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        invited_user_id: UUID,
        invited_email: str | None,
        role: str,
        token_digest: str,
        invited_by: UUID,
        expires_at: datetime,
    ) -> WorkspaceInvitation:
        invitation = WorkspaceInvitation(
            id=uuid4(),
            workspace_id=workspace_id,
            invited_user_id=invited_user_id,
            invited_email=invited_email,
            role=role,
            state="pending",
            token_digest=token_digest,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        self._session.add(invitation)
        self._session.flush()
        return invitation

    def get(
        self, *, workspace_id: UUID, invitation_id: UUID
    ) -> WorkspaceInvitation | None:
        statement = select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.id == invitation_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_digest_for_update(self, token_digest: str) -> WorkspaceInvitation | None:
        statement = (
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.token_digest == token_digest)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def find_pending(
        self, *, workspace_id: UUID, invited_user_id: UUID
    ) -> WorkspaceInvitation | None:
        statement = select(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.invited_user_id == invited_user_id,
            WorkspaceInvitation.state == "pending",
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_workspace(self, workspace_id: UUID) -> list[WorkspaceInvitation]:
        statement = (
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.workspace_id == workspace_id)
            .order_by(WorkspaceInvitation.created_at, WorkspaceInvitation.id)
        )
        return list(self._session.execute(statement).scalars())

    def mark_accepted(self, invitation: WorkspaceInvitation) -> None:
        invitation.state = "accepted"
        invitation.accepted_at = datetime.now(UTC)
        self._session.flush()

    def mark_expired(self, invitation: WorkspaceInvitation) -> None:
        invitation.state = "expired"
        self._session.flush()

    def revoke(self, invitation: WorkspaceInvitation, *, reason: str) -> None:
        invitation.state = "revoked"
        invitation.revoked_at = datetime.now(UTC)
        invitation.revoke_reason = reason
        self._session.flush()
