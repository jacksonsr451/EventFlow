"""WorkItem model: execution work derived from an approved Proposal."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
    WORK_ITEM_STATUS_VALUES,
)


class WorkItem(TimestampMixin, Base):
    """Executable work that can only originate from an approved Proposal.

    The ``origin_*`` columns, the composite foreign keys and the database
    trigger installed by the initial migration together guarantee that a
    WorkItem cannot be created from a Consultation or an unapproved Proposal.
    """

    __tablename__ = "work_items"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    origin_proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    origin_proposal_version: Mapped[int] = mapped_column(nullable=False)
    origin_approval_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    calculated_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority_override_reason: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    priority_overridden_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ready'")
    )
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    external_issue_links: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_work_items_workspace_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "origin_proposal_id"],
            ["proposals.workspace_id", "proposals.project_id", "proposals.id"],
            name="fk_work_items_workspace_project_proposal",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "origin_approval_id"],
            ["approvals.workspace_id", "approvals.id"],
            name="fk_work_items_workspace_approval",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_work_items_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_work_items_workspace_project_id",
        ),
        UniqueConstraint("origin_proposal_id", name="uq_work_items_origin_proposal"),
        CheckConstraint(
            "origin_proposal_version >= 1", name="proposal_version_positive"
        ),
        CheckConstraint("char_length(title) >= 5", name="title_min_length"),
        CheckConstraint(
            "char_length(description) >= 10", name="description_min_length"
        ),
        CheckConstraint(
            check_in("category", TRIAGE_CATEGORY_VALUES), name="category_values"
        ),
        CheckConstraint(check_in("priority", PRIORITY_VALUES), name="priority_values"),
        CheckConstraint(
            "calculated_priority IS NULL OR "
            f"{check_in('calculated_priority', PRIORITY_VALUES)}",
            name="calculated_priority_values",
        ),
        CheckConstraint(
            "priority_override_reason IS NULL OR "
            "char_length(priority_override_reason) BETWEEN 10 AND 300",
            name="priority_override_reason_length",
        ),
        CheckConstraint(
            "(priority_override_reason IS NULL) = (priority_overridden_by IS NULL)",
            name="priority_override_actor_consistency",
        ),
        CheckConstraint(
            check_in("status", WORK_ITEM_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint(
            "jsonb_typeof(acceptance_criteria) = 'array'", name="criteria_is_array"
        ),
        CheckConstraint(
            "jsonb_array_length(acceptance_criteria) >= 1", name="criteria_not_empty"
        ),
        CheckConstraint(
            "jsonb_typeof(external_issue_links) = 'array'", name="issue_links_is_array"
        ),
        Index("ix_work_items_workspace_id", "workspace_id"),
        Index("ix_work_items_project_id", "project_id"),
        Index("ix_work_items_status", "status"),
    )
