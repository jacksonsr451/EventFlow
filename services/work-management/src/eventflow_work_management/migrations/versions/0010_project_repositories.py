"""Add project repository associations (Issue #44).

The unique key is the provider's stable repository identity scoped to one
project and provider instance. URL variants therefore cannot create duplicate
associations. No credentials, installation ids, sync cursors, or verification
tokens are stored here.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_project_repositories"
down_revision = "0009_entity_collaboration"
branch_labels = None
depends_on = None

_PROVIDERS = "provider IN ('github', 'gitlab')"
_STATUS = "status IN ('active', 'inactive', 'archived')"
_VERIFICATION = "verification_status IN ('configured', 'verified')"
_INSTANCE = "provider_instance_id ~ '^[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?$'"
_REMOTE_ID = "remote_repository_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$'"
_FULL_PATH = "repository_full_path ~ '^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'"
_BRANCH = "default_branch ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$'"


def upgrade() -> None:
    op.create_table(
        "project_repositories",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_instance_id", sa.String(length=255), nullable=False),
        sa.Column("remote_repository_id", sa.String(length=120), nullable=False),
        sa.Column("repository_full_path", sa.String(length=255), nullable=False),
        sa.Column("canonical_repository_url", sa.String(length=500), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default=sa.text("'configured'"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _PROVIDERS, name=op.f("ck_project_repositories_provider_values")
        ),
        sa.CheckConstraint(
            _STATUS, name=op.f("ck_project_repositories_status_values")
        ),
        sa.CheckConstraint(
            _VERIFICATION,
            name=op.f("ck_project_repositories_verification_values"),
        ),
        sa.CheckConstraint(
            _INSTANCE,
            name=op.f("ck_project_repositories_provider_instance_format"),
        ),
        sa.CheckConstraint(
            _REMOTE_ID,
            name=op.f("ck_project_repositories_remote_repository_id_format"),
        ),
        sa.CheckConstraint(
            _FULL_PATH,
            name=op.f("ck_project_repositories_repository_full_path_format"),
        ),
        sa.CheckConstraint(
            "canonical_repository_url LIKE 'https://%'",
            name=op.f("ck_project_repositories_canonical_url_https"),
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name=op.f("ck_project_repositories_display_name_length"),
        ),
        sa.CheckConstraint(
            f"default_branch IS NULL OR {_BRANCH}",
            name=op.f("ck_project_repositories_default_branch_format"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_project_repositories_version_positive")
        ),
        sa.CheckConstraint(
            "(status = 'inactive') = (deactivated_at IS NOT NULL)",
            name=op.f("ck_project_repositories_deactivated_consistency"),
        ),
        sa.CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name=op.f("ck_project_repositories_archived_consistency"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_repositories_workspace_project",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_repositories")),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "provider",
            "provider_instance_id",
            "remote_repository_id",
            name="uq_project_repositories_identity",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_project_repositories_workspace_id"
        ),
    )
    op.create_index(
        "ix_project_repositories_workspace_id", "project_repositories", ["workspace_id"]
    )
    op.create_index(
        "ix_project_repositories_project_id", "project_repositories", ["project_id"]
    )
    op.create_index(
        "ix_project_repositories_project_status",
        "project_repositories",
        ["workspace_id", "project_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_project_repositories_remote_identity",
        "project_repositories",
        ["provider", "provider_instance_id", "remote_repository_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_repositories_remote_identity",
        table_name="project_repositories",
    )
    op.drop_index(
        "ix_project_repositories_project_status",
        table_name="project_repositories",
    )
    op.drop_index(
        "ix_project_repositories_project_id",
        table_name="project_repositories",
    )
    op.drop_index(
        "ix_project_repositories_workspace_id",
        table_name="project_repositories",
    )
    op.drop_table("project_repositories")
