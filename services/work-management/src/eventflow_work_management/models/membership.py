"""Workspace membership and invitation models (Issue #9).

A ``WorkspaceMembership`` binds one verified internal identity
(``external_identities.id``) to one workspace with a single role and state. A
``WorkspaceInvitation`` records a pending, identity-bound offer to join a
workspace; the bearer token is never stored, only its digest.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import (
    Base,
    TimestampMixin,
    check_in,
    check_regex,
)
from eventflow_work_management.models.enums import (
    INVITATION_STATE_VALUES,
    MEMBERSHIP_STATE_VALUES,
    WORKSPACE_ROLE_VALUES,
)

TOKEN_DIGEST_PATTERN = "^[0-9a-f]{64}$"


class WorkspaceMembership(TimestampMixin, Base):
    """The tenant-scoped authorization binding for one identity."""

    __tablename__ = "workspace_memberships"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    invited_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_workspace_memberships_workspace_id"
        ),
        CheckConstraint(check_in("role", WORKSPACE_ROLE_VALUES), name="role_values"),
        CheckConstraint(
            check_in("state", MEMBERSHIP_STATE_VALUES), name="state_values"
        ),
        CheckConstraint(
            "revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64",
            name="revoke_reason_length",
        ),
        # One active membership per identity and workspace; revoked rows are kept
        # for the audit trail without blocking re-invitation.
        Index(
            "uq_workspace_memberships_active_user",
            "workspace_id",
            "user_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_workspace_memberships_workspace_id", "workspace_id"),
        Index("ix_workspace_memberships_user_id", "user_id"),
    )


class WorkspaceInvitation(TimestampMixin, Base):
    """A pending, identity-bound offer to join a workspace."""

    __tablename__ = "workspace_invitations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    invited_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_workspace_invitations_workspace_id"
        ),
        UniqueConstraint("token_digest", name="uq_workspace_invitations_token_digest"),
        CheckConstraint(check_in("role", WORKSPACE_ROLE_VALUES), name="role_values"),
        CheckConstraint(
            check_in("state", INVITATION_STATE_VALUES), name="state_values"
        ),
        CheckConstraint(
            check_regex("token_digest", TOKEN_DIGEST_PATTERN),
            name="token_digest_format",
        ),
        CheckConstraint(
            "invited_email IS NULL OR char_length(invited_email) BETWEEN 3 AND 320",
            name="invited_email_length",
        ),
        CheckConstraint(
            "revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64",
            name="revoke_reason_length",
        ),
        # At most one pending invitation per identity and workspace.
        Index(
            "uq_workspace_invitations_pending_invitee",
            "workspace_id",
            "invited_user_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
        Index("ix_workspace_invitations_workspace_id", "workspace_id"),
        Index("ix_workspace_invitations_invited_user_id", "invited_user_id"),
    )
