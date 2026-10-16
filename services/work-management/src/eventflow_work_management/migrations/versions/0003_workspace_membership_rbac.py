"""Add workspace memberships and invitations for RBAC (Issue #9)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_workspace_membership_rbac"
down_revision = "0002_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("invited_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'contributor', 'triager', 'approver', 'admin', 'owner')", name=op.f("ck_workspace_memberships_role_values")),
        sa.CheckConstraint("state IN ('active', 'revoked')", name=op.f("ck_workspace_memberships_state_values")),
        sa.CheckConstraint("revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64", name=op.f("ck_workspace_memberships_revoke_reason_length")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_memberships_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["external_identities.id"], name=op.f("fk_workspace_memberships_user_id_external_identities"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by"], ["external_identities.id"], name=op.f("fk_workspace_memberships_invited_by_external_identities"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_memberships")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workspace_memberships_workspace_id"),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])
    op.create_index(
        "uq_workspace_memberships_active_user",
        "workspace_memberships",
        ["workspace_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invited_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'contributor', 'triager', 'approver', 'admin', 'owner')", name=op.f("ck_workspace_invitations_role_values")),
        sa.CheckConstraint("state IN ('pending', 'accepted', 'revoked', 'expired')", name=op.f("ck_workspace_invitations_state_values")),
        sa.CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_workspace_invitations_token_digest_format")),
        sa.CheckConstraint("invited_email IS NULL OR char_length(invited_email) BETWEEN 3 AND 320", name=op.f("ck_workspace_invitations_invited_email_length")),
        sa.CheckConstraint("revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64", name=op.f("ck_workspace_invitations_revoke_reason_length")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_invitations_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_user_id"], ["external_identities.id"], name=op.f("fk_workspace_invitations_invited_user_id_external_identities"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by"], ["external_identities.id"], name=op.f("fk_workspace_invitations_invited_by_external_identities"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invitations")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workspace_invitations_workspace_id"),
        sa.UniqueConstraint("token_digest", name="uq_workspace_invitations_token_digest"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index("ix_workspace_invitations_invited_user_id", "workspace_invitations", ["invited_user_id"])
    op.create_index(
        "uq_workspace_invitations_pending_invitee",
        "workspace_invitations",
        ["workspace_id", "invited_user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_invitations_pending_invitee", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_invited_user_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_id", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
    op.drop_index("uq_workspace_memberships_active_user", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
