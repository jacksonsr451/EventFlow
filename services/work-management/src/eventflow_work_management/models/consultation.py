"""Consultation model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
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
    BUSINESS_IMPACT_VALUES,
    BUSINESS_URGENCY_VALUES,
    CONSULTATION_STATUS_VALUES,
    ORIGIN_VALUES,
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
)


class Consultation(TimestampMixin, Base):
    """A user-submitted request that may later be triaged into a Proposal."""

    __tablename__ = "consultations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'open'")
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    editor_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    external_references: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    active_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    triage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage_criteria: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    business_impact: Mapped[str | None] = mapped_column(String(16), nullable=True)
    business_urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority_override_reason: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    triaged_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    triaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_consultations_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_consultations_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_consultations_workspace_project_id",
        ),
        CheckConstraint(check_in("origin", ORIGIN_VALUES), name="origin_values"),
        CheckConstraint(
            check_in("status", CONSULTATION_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint(check_in("priority", PRIORITY_VALUES), name="priority_values"),
        CheckConstraint(
            "business_impact IS NULL OR "
            f"{check_in('business_impact', BUSINESS_IMPACT_VALUES)}",
            name="business_impact_values",
        ),
        CheckConstraint(
            "business_urgency IS NULL OR "
            f"{check_in('business_urgency', BUSINESS_URGENCY_VALUES)}",
            name="business_urgency_values",
        ),
        CheckConstraint(
            "priority_override_reason IS NULL OR "
            "char_length(priority_override_reason) BETWEEN 10 AND 300",
            name="priority_override_reason_length",
        ),
        CheckConstraint(
            f"category IS NULL OR {check_in('category', TRIAGE_CATEGORY_VALUES)}",
            name="category_values",
        ),
        CheckConstraint("char_length(title) >= 3", name="title_min_length"),
        CheckConstraint("char_length(description) >= 5", name="description_min_length"),
        CheckConstraint(
            "jsonb_typeof(external_references) = 'array'", name="references_is_array"
        ),
        CheckConstraint(
            "triage_criteria IS NULL OR jsonb_typeof(triage_criteria) = 'object'",
            name="triage_criteria_is_object",
        ),
        CheckConstraint(
            "triage_notes IS NULL OR char_length(triage_notes) >= 5",
            name="triage_notes_min_length",
        ),
        CheckConstraint(
            "(triaged_at IS NULL) = (triaged_by IS NULL)",
            name="triage_actor_consistency",
        ),
        Index("ix_consultations_workspace_id", "workspace_id"),
        Index("ix_consultations_project_id", "project_id"),
        Index("ix_consultations_status", "status"),
    )
