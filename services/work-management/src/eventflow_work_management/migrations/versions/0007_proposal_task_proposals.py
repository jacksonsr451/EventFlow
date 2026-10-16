"""Consultation task proposals: multiple independent proposals with revisions.

Issue #6 lets one triaged consultation yield zero, one, or many independent
proposals. This migration:

* removes the old ``(consultation_id, version)`` uniqueness so two proposals of
  the same consultation can each start at version 1 (the version counter is now
  scoped to ``proposal_id``);
* adds the ``checklist`` payload and the duplication/supersede links;
* adds the append-only ``proposal_revisions`` history table and the tenant-scoped
  ``proposal_evidence`` association.

No Approval, WorkItem, BoardCard, or remote issue is created by this change.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_proposal_task_proposals"
down_revision = "0006_attachments_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The version counter is scoped to a proposal, not a consultation.
    op.drop_constraint(
        "uq_proposals_consultation_version", "proposals", type_="unique"
    )

    op.add_column(
        "proposals",
        sa.Column(
            "checklist",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "proposals",
        sa.Column("duplicated_from_proposal_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "proposals",
        sa.Column("superseded_by_proposal_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_proposals_checklist_is_array"),
        "proposals",
        "jsonb_typeof(checklist) = 'array'",
    )
    op.create_foreign_key(
        "fk_proposals_workspace_duplicated_from",
        "proposals",
        "proposals",
        ["workspace_id", "duplicated_from_proposal_id"],
        ["workspace_id", "id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_proposals_workspace_superseded_by",
        "proposals",
        "proposals",
        ["workspace_id", "superseded_by_proposal_id"],
        ["workspace_id", "id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "proposal_revisions",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_proposal_revisions_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name=op.f("ck_proposal_revisions_snapshot_is_object"),
        ),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) BETWEEN 1 AND 200",
            name=op.f("ck_proposal_revisions_summary_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposal_revisions_workspace_proposal",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_revisions")),
        sa.UniqueConstraint(
            "proposal_id", "version", name="uq_proposal_revisions_proposal_version"
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_proposal_revisions_workspace_id"
        ),
    )
    op.create_index(
        "ix_proposal_revisions_workspace_id",
        "proposal_revisions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_proposal_revisions_proposal_id",
        "proposal_revisions",
        ["proposal_id"],
    )

    op.create_table(
        "proposal_evidence",
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposal_evidence_workspace_proposal",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["consultation_evidence.workspace_id", "consultation_evidence.id"],
            name="fk_proposal_evidence_workspace_evidence",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "proposal_id", "evidence_id", name="pk_proposal_evidence"
        ),
    )
    op.create_index(
        "ix_proposal_evidence_workspace_id", "proposal_evidence", ["workspace_id"]
    )
    op.create_index(
        "ix_proposal_evidence_evidence_id", "proposal_evidence", ["evidence_id"]
    )

    # Proposal revisions are an append-only, tamper-evident history.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION eventflow_proposal_revisions_block_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'proposal_revisions is append-only'
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_proposal_revisions_no_update
        BEFORE UPDATE ON proposal_revisions
        FOR EACH ROW EXECUTE FUNCTION eventflow_proposal_revisions_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_proposal_revisions_no_delete
        BEFORE DELETE ON proposal_revisions
        FOR EACH ROW EXECUTE FUNCTION eventflow_proposal_revisions_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_proposal_revisions_no_truncate
        BEFORE TRUNCATE ON proposal_revisions
        FOR EACH STATEMENT EXECUTE FUNCTION eventflow_proposal_revisions_block_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_proposal_revisions_no_truncate ON proposal_revisions")
    op.execute("DROP TRIGGER IF EXISTS trg_proposal_revisions_no_delete ON proposal_revisions")
    op.execute("DROP TRIGGER IF EXISTS trg_proposal_revisions_no_update ON proposal_revisions")
    op.execute("DROP FUNCTION IF EXISTS eventflow_proposal_revisions_block_mutation()")

    op.drop_index("ix_proposal_evidence_evidence_id", table_name="proposal_evidence")
    op.drop_index("ix_proposal_evidence_workspace_id", table_name="proposal_evidence")
    op.drop_table("proposal_evidence")

    op.drop_index("ix_proposal_revisions_proposal_id", table_name="proposal_revisions")
    op.drop_index("ix_proposal_revisions_workspace_id", table_name="proposal_revisions")
    op.drop_table("proposal_revisions")

    op.drop_constraint(
        "fk_proposals_workspace_superseded_by", "proposals", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_proposals_workspace_duplicated_from", "proposals", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("ck_proposals_checklist_is_array"), "proposals", type_="check"
    )
    op.drop_column("proposals", "superseded_by_proposal_id")
    op.drop_column("proposals", "duplicated_from_proposal_id")
    op.drop_column("proposals", "checklist")
    op.create_unique_constraint(
        "uq_proposals_consultation_version",
        "proposals",
        ["consultation_id", "version"],
    )
