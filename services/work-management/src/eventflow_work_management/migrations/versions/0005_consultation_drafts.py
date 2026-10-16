"""Add the DRAFT consultation status (Issue #4)."""

from __future__ import annotations

from alembic import op

revision = "0005_consultation_drafts"
down_revision = "0004_consultation_triage_detail"
branch_labels = None
depends_on = None

_STATUS_WITH_DRAFT = (
    "status IN ('draft', 'open', 'triaging', 'proposed', 'duplicate', "
    "'rejected', 'closed', 'reopened')"
)
_STATUS_WITHOUT_DRAFT = (
    "status IN ('open', 'triaging', 'proposed', 'duplicate', "
    "'rejected', 'closed', 'reopened')"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_consultations_status_values"),
        "consultations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_consultations_status_values"),
        "consultations",
        _STATUS_WITH_DRAFT,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_consultations_status_values"),
        "consultations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_consultations_status_values"),
        "consultations",
        _STATUS_WITHOUT_DRAFT,
    )
