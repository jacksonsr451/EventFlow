"""Proposal model.

A Proposal is an independent, reviewable plan derived from a Consultation
(Issue #6). One consultation may produce zero, one, or many proposals: each
proposal is its own aggregate with its own ``proposal_id`` and its own revision
history, so the version counter is scoped to the proposal and starts at 1. A
proposal never creates an Approval, WorkItem, BoardCard, or remote issue.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, TimestampMixin, check_in
from eventflow_work_management.models.enums import (
    PRIORITY_VALUES,
    PROPOSAL_STATUS_VALUES,
    TRIAGE_CATEGORY_VALUES,
)


class Proposal(TimestampMixin, Base):
    """One independent proposal (aggregate root) derived from a consultation.

    The row always holds the current revision; every accepted content edit
    writes an immutable ``proposal_revisions`` snapshot and increments
    ``version``. Independent proposals never share a version counter.
    """

    __tablename__ = "proposals"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    consultation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    technical_description: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=False)
    checklist: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    risks: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    dependencies: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    estimated_hours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'draft'")
    )
    proposer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    duplicated_from_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    superseded_by_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "consultation_id"],
            [
                "consultations.workspace_id",
                "consultations.project_id",
                "consultations.id",
            ],
            name="fk_proposals_workspace_project_consultation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_proposals_workspace_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "duplicated_from_proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposals_workspace_duplicated_from",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "superseded_by_proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposals_workspace_superseded_by",
            ondelete="SET NULL",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_proposals_workspace_id"),
        UniqueConstraint(
            "workspace_id", "project_id", "id", name="uq_proposals_workspace_project_id"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("char_length(title) >= 5", name="title_min_length"),
        CheckConstraint(
            "char_length(technical_description) >= 10", name="description_min_length"
        ),
        CheckConstraint("char_length(scope) >= 5", name="scope_min_length"),
        CheckConstraint(
            "char_length(justification) >= 5", name="justification_min_length"
        ),
        CheckConstraint(
            check_in("category", TRIAGE_CATEGORY_VALUES), name="category_values"
        ),
        CheckConstraint(check_in("priority", PRIORITY_VALUES), name="priority_values"),
        CheckConstraint(
            check_in("status", PROPOSAL_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint(
            "estimated_hours IS NULL OR estimated_hours >= 0.5",
            name="estimated_hours_minimum",
        ),
        CheckConstraint(
            "jsonb_typeof(acceptance_criteria) = 'array'", name="criteria_is_array"
        ),
        CheckConstraint(
            "jsonb_array_length(acceptance_criteria) >= 1", name="criteria_not_empty"
        ),
        CheckConstraint("jsonb_typeof(checklist) = 'array'", name="checklist_is_array"),
        CheckConstraint("jsonb_typeof(risks) = 'array'", name="risks_is_array"),
        CheckConstraint(
            "jsonb_typeof(dependencies) = 'array'", name="dependencies_is_array"
        ),
        Index("ix_proposals_workspace_id", "workspace_id"),
        Index("ix_proposals_consultation_id", "consultation_id"),
        Index("ix_proposals_status", "status"),
    )
