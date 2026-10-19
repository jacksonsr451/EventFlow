"""Add entity comments and generic entity attachments (Issue #29).

Consultations keep their original attachment tables. Every other collaborable
entity (proposal, work item, board card) uses the generic pair
``entity_attachments``/``entity_attachment_blobs`` so there is a single
fail-closed attachment lifecycle.

``entity_comments`` is tombstone-only. Database triggers reject any rewrite of
the author, body, target, or creation time, and reject hard deletes and
truncation, so a deleted comment can only be expressed by the two deletion
columns.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_entity_collaboration"
down_revision = "0008_kanban_boards_columns"
branch_labels = None
depends_on = None

_ENTITY_TYPES = "entity_type IN ('consultation', 'proposal', 'work_item', 'board_card')"
_ATTACHMENT_STATUS = "status IN ('quarantined', 'available', 'rejected')"
_SCAN_VERDICT = "scan_verdict IN ('clean', 'infected', 'unknown')"


def upgrade() -> None:
    op.create_table(
        "entity_comments",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("author_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(as_uuid=True), nullable=True),
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
            _ENTITY_TYPES, name=op.f("ck_entity_comments_entity_type_values")
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000",
            name=op.f("ck_entity_comments_body_length"),
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL) = (deleted_by IS NULL)",
            name=op.f("ck_entity_comments_deletion_consistency"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entity_comments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_entity_comments_workspace_project",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_comments")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_entity_comments_workspace_id"
        ),
    )
    op.create_index("ix_entity_comments_workspace_id", "entity_comments", ["workspace_id"])
    op.create_index("ix_entity_comments_project_id", "entity_comments", ["project_id"])
    op.create_index(
        "ix_entity_comments_entity",
        "entity_comments",
        ["workspace_id", "entity_type", "entity_id", "created_at", "id"],
    )

    op.execute(
        """
        CREATE FUNCTION eventflow_entity_comments_block_rewrite()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.workspace_id <> OLD.workspace_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.entity_type <> OLD.entity_type
               OR NEW.entity_id <> OLD.entity_id
               OR NEW.author_id <> OLD.author_id
               OR NEW.body <> OLD.body
               OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION
                    'entity_comments rows are immutable except for deletion';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE FUNCTION eventflow_entity_comments_block_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'entity_comments rows cannot be deleted or truncated';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_entity_comments_no_rewrite
        BEFORE UPDATE ON entity_comments
        FOR EACH ROW EXECUTE FUNCTION eventflow_entity_comments_block_rewrite();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_entity_comments_no_delete
        BEFORE DELETE ON entity_comments
        FOR EACH ROW EXECUTE FUNCTION eventflow_entity_comments_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_entity_comments_no_truncate
        BEFORE TRUNCATE ON entity_comments
        FOR EACH STATEMENT EXECUTE FUNCTION eventflow_entity_comments_block_mutation();
        """
    )

    op.create_table(
        "entity_attachments",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("declared_content_type", sa.String(length=255), nullable=False),
        sa.Column("detected_content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'quarantined'"),
            nullable=False,
        ),
        sa.Column("scan_verdict", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.String(length=120), nullable=True),
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
            _ENTITY_TYPES, name=op.f("ck_entity_attachments_entity_type_values")
        ),
        sa.CheckConstraint(
            _ATTACHMENT_STATUS, name=op.f("ck_entity_attachments_status_values")
        ),
        sa.CheckConstraint(
            _SCAN_VERDICT, name=op.f("ck_entity_attachments_scan_verdict_values")
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_entity_attachments_size_non_negative")
        ),
        sa.CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255",
            name=op.f("ck_entity_attachments_file_name_length"),
        ),
        sa.CheckConstraint(
            "char_length(declared_content_type) BETWEEN 1 AND 255",
            name=op.f("ck_entity_attachments_declared_content_type_length"),
        ),
        sa.CheckConstraint(
            "char_length(detected_content_type) BETWEEN 1 AND 255",
            name=op.f("ck_entity_attachments_detected_content_type_length"),
        ),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_entity_attachments_checksum_format"),
        ),
        sa.CheckConstraint(
            "storage_key ~ '^[0-9a-f]{32}$'",
            name=op.f("ck_entity_attachments_storage_key_format"),
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR char_length(rejection_reason) BETWEEN 1 AND 120",
            name=op.f("ck_entity_attachments_rejection_reason_length"),
        ),
        sa.CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name=op.f("ck_entity_attachments_rejection_reason_consistency"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entity_attachments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_entity_attachments_workspace_project",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_attachments")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_entity_attachments_workspace_id"
        ),
        sa.UniqueConstraint("storage_key", name="uq_entity_attachments_storage_key"),
    )
    op.create_index(
        "ix_entity_attachments_workspace_id", "entity_attachments", ["workspace_id"]
    )
    op.create_index(
        "ix_entity_attachments_project_id", "entity_attachments", ["project_id"]
    )
    op.create_index(
        "ix_entity_attachments_entity",
        "entity_attachments",
        ["workspace_id", "entity_type", "entity_id", "created_at"],
    )

    op.create_table(
        "entity_attachment_blobs",
        sa.Column("attachment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["entity_attachments.id"],
            name=op.f(
                "fk_entity_attachment_blobs_attachment_id_entity_attachments"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entity_attachment_blobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "attachment_id", name=op.f("pk_entity_attachment_blobs")
        ),
    )
    op.create_index(
        "ix_entity_attachment_blobs_workspace_id",
        "entity_attachment_blobs",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_attachment_blobs_workspace_id",
        table_name="entity_attachment_blobs",
    )
    op.drop_table("entity_attachment_blobs")
    op.drop_index("ix_entity_attachments_entity", table_name="entity_attachments")
    op.drop_index(
        "ix_entity_attachments_project_id", table_name="entity_attachments"
    )
    op.drop_index(
        "ix_entity_attachments_workspace_id", table_name="entity_attachments"
    )
    op.drop_table("entity_attachments")

    op.execute("DROP TRIGGER trg_entity_comments_no_truncate ON entity_comments")
    op.execute("DROP TRIGGER trg_entity_comments_no_delete ON entity_comments")
    op.execute("DROP TRIGGER trg_entity_comments_no_rewrite ON entity_comments")
    op.execute("DROP FUNCTION eventflow_entity_comments_block_mutation()")
    op.execute("DROP FUNCTION eventflow_entity_comments_block_rewrite()")
    op.drop_index("ix_entity_comments_entity", table_name="entity_comments")
    op.drop_index("ix_entity_comments_project_id", table_name="entity_comments")
    op.drop_index("ix_entity_comments_workspace_id", table_name="entity_comments")
    op.drop_table("entity_comments")
