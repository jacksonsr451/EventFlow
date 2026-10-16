"""Add consultation attachments and evidence (Issue #4).

Attachments store hostile content behind a fail-closed lifecycle: metadata in
``consultation_attachments``, bytes in ``consultation_attachment_blobs``, and a
per-tenant composite foreign key so an attachment can never cross a workspace
boundary (AT-04). ``consultation_evidence`` records structured justification and
may reference an attachment.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_attachments_evidence"
down_revision = "0005_consultation_drafts"
branch_labels = None
depends_on = None

_ATTACHMENT_STATUS = "status IN ('quarantined', 'available', 'rejected')"
_SCAN_VERDICT = "scan_verdict IN ('clean', 'infected', 'unknown')"
_KIND = "kind IN ('text', 'link', 'attachment')"
_KIND_CONTENT_CONSISTENCY = (
    "(kind = 'attachment' AND attachment_id IS NOT NULL AND content IS NULL) "
    "OR (kind IN ('text', 'link') AND content IS NOT NULL AND attachment_id IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "consultation_attachments",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("consultation_id", sa.Uuid(as_uuid=True), nullable=False),
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
            _ATTACHMENT_STATUS, name=op.f("ck_consultation_attachments_status_values")
        ),
        sa.CheckConstraint(
            _SCAN_VERDICT, name=op.f("ck_consultation_attachments_scan_verdict_values")
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("ck_consultation_attachments_size_non_negative"),
        ),
        sa.CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255",
            name=op.f("ck_consultation_attachments_file_name_length"),
        ),
        sa.CheckConstraint(
            "char_length(declared_content_type) BETWEEN 1 AND 255",
            name=op.f("ck_consultation_attachments_declared_content_type_length"),
        ),
        sa.CheckConstraint(
            "char_length(detected_content_type) BETWEEN 1 AND 255",
            name=op.f("ck_consultation_attachments_detected_content_type_length"),
        ),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_consultation_attachments_checksum_format"),
        ),
        sa.CheckConstraint(
            "storage_key ~ '^[0-9a-f]{32}$'",
            name=op.f("ck_consultation_attachments_storage_key_format"),
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR char_length(rejection_reason) BETWEEN 1 AND 120",
            name=op.f("ck_consultation_attachments_rejection_reason_length"),
        ),
        sa.CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name=op.f("ck_consultation_attachments_rejection_reason_consistency"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_consultation_attachments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "consultation_id"],
            ["consultations.workspace_id", "consultations.id"],
            name="fk_consultation_attachments_workspace_consultation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultation_attachments")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_consultation_attachments_workspace_id"
        ),
        sa.UniqueConstraint(
            "storage_key", name="uq_consultation_attachments_storage_key"
        ),
    )
    op.create_index(
        "ix_consultation_attachments_workspace_id",
        "consultation_attachments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_consultation_attachments_consultation_id",
        "consultation_attachments",
        ["consultation_id"],
    )

    op.create_table(
        "consultation_attachment_blobs",
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
            ["consultation_attachments.id"],
            name=op.f(
                "fk_consultation_attachment_blobs_attachment_id_consultation_attachments"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_consultation_attachment_blobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "attachment_id", name=op.f("pk_consultation_attachment_blobs")
        ),
    )
    op.create_index(
        "ix_consultation_attachment_blobs_workspace_id",
        "consultation_attachment_blobs",
        ["workspace_id"],
    )

    op.create_table(
        "consultation_evidence",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("consultation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("attachment_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_KIND, name=op.f("ck_consultation_evidence_kind_values")),
        sa.CheckConstraint(
            _KIND_CONTENT_CONSISTENCY,
            name=op.f("ck_consultation_evidence_kind_content_consistency"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) BETWEEN 1 AND 500",
            name=op.f("ck_consultation_evidence_description_length"),
        ),
        sa.CheckConstraint(
            "content IS NULL OR char_length(content) BETWEEN 1 AND 4096",
            name=op.f("ck_consultation_evidence_content_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_consultation_evidence_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "consultation_id"],
            ["consultations.workspace_id", "consultations.id"],
            name="fk_consultation_evidence_workspace_consultation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["consultation_attachments.id"],
            name=op.f(
                "fk_consultation_evidence_attachment_id_consultation_attachments"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultation_evidence")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_consultation_evidence_workspace_id"
        ),
    )
    op.create_index(
        "ix_consultation_evidence_workspace_id",
        "consultation_evidence",
        ["workspace_id"],
    )
    op.create_index(
        "ix_consultation_evidence_consultation_id",
        "consultation_evidence",
        ["consultation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consultation_evidence_consultation_id", table_name="consultation_evidence"
    )
    op.drop_index(
        "ix_consultation_evidence_workspace_id", table_name="consultation_evidence"
    )
    op.drop_table("consultation_evidence")
    op.drop_index(
        "ix_consultation_attachment_blobs_workspace_id",
        table_name="consultation_attachment_blobs",
    )
    op.drop_table("consultation_attachment_blobs")
    op.drop_index(
        "ix_consultation_attachments_consultation_id",
        table_name="consultation_attachments",
    )
    op.drop_index(
        "ix_consultation_attachments_workspace_id",
        table_name="consultation_attachments",
    )
    op.drop_table("consultation_attachments")
