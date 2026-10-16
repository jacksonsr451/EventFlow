"""Add persisted triage detail to consultations (Issue #4)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_consultation_triage_detail"
down_revision = "0003_workspace_membership_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("consultations", sa.Column("triage_notes", sa.Text(), nullable=True))
    op.add_column(
        "consultations",
        sa.Column("triage_criteria", JSONB(), nullable=True),
    )
    op.add_column(
        "consultations", sa.Column("triaged_by", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.add_column(
        "consultations",
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_consultations_triage_criteria_is_object"),
        "consultations",
        "triage_criteria IS NULL OR jsonb_typeof(triage_criteria) = 'object'",
    )
    op.create_check_constraint(
        op.f("ck_consultations_triage_notes_min_length"),
        "consultations",
        "triage_notes IS NULL OR char_length(triage_notes) >= 5",
    )
    op.create_check_constraint(
        op.f("ck_consultations_triage_actor_consistency"),
        "consultations",
        "(triaged_at IS NULL) = (triaged_by IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_consultations_triage_actor_consistency"),
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_consultations_triage_notes_min_length"),
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_consultations_triage_criteria_is_object"),
        "consultations",
        type_="check",
    )
    op.drop_column("consultations", "triaged_at")
    op.drop_column("consultations", "triaged_by")
    op.drop_column("consultations", "triage_criteria")
    op.drop_column("consultations", "triage_notes")
