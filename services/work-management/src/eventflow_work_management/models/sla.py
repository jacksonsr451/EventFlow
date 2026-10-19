"""Versioned SLA policies, instances, pause intervals and append-only events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, TimestampMixin, check_in
from eventflow_work_management.models.enums import (
    SLA_EVENT_TYPE_VALUES,
    SLA_INSTANCE_STATUS_VALUES,
    SLA_POLICY_STATUS_VALUES,
)


class SlaPolicy(TimestampMixin, Base):
    """One immutable version of an SLA target definition.

    A policy is scoped to a workspace default (``project_id`` null) or to one
    project. ``response_minutes`` and ``resolution_minutes`` are business
    minutes interpreted through ``timezone``/``business_hours``/``holidays``.
    """

    __tablename__ = "sla_policies"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'")
    )
    response_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'UTC'")
    )
    business_hours: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    holidays: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    pause_statuses: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[\"blocked\"]'::jsonb")
    )
    warning_threshold_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("75")
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_sla_policies_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_sla_policies_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "name",
            "version",
            name="uq_sla_policies_scope_name_version",
        ),
        CheckConstraint(
            check_in("status", SLA_POLICY_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint(
            "version >= 1", name="version_positive"
        ),
        CheckConstraint(
            "response_minutes IS NULL OR response_minutes >= 1",
            name="response_minutes_positive",
        ),
        CheckConstraint(
            "resolution_minutes IS NULL OR resolution_minutes >= 1",
            name="resolution_minutes_positive",
        ),
        CheckConstraint(
            "response_minutes IS NOT NULL OR resolution_minutes IS NOT NULL",
            name="at_least_one_target",
        ),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("char_length(timezone) BETWEEN 1 AND 64", name="timezone_length"),
        CheckConstraint(
            "warning_threshold_percent BETWEEN 1 AND 99",
            name="warning_threshold_range",
        ),
        CheckConstraint(
            "jsonb_typeof(business_hours) = 'object'", name="business_hours_is_object"
        ),
        CheckConstraint("jsonb_typeof(holidays) = 'array'", name="holidays_is_array"),
        CheckConstraint(
            "jsonb_typeof(pause_statuses) = 'array'", name="pause_statuses_is_array"
        ),
        CheckConstraint(
            "(status = 'active') = (activated_at IS NOT NULL)",
            name="activated_consistency",
        ),
        CheckConstraint(
            "(status = 'retired') = (retired_at IS NOT NULL)",
            name="retired_consistency",
        ),
        Index("ix_sla_policies_workspace_id", "workspace_id"),
        Index("ix_sla_policies_project_id", "project_id"),
        Index(
            "uq_sla_policies_active_workspace",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("status = 'active' AND project_id IS NULL"),
        ),
        Index(
            "uq_sla_policies_active_project",
            "workspace_id",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("status = 'active' AND project_id IS NOT NULL"),
        ),
    )


class SlaInstance(TimestampMixin, Base):
    """The SLA clock for exactly one WorkItem, pinned to a policy version."""

    __tablename__ = "sla_instances"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'running'")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    active_pause_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warning_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warning_resolution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    breach_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    breach_resolution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_evaluation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_sla_instances_workspace_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_sla_instances_workspace_work_item",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "policy_id"],
            ["sla_policies.workspace_id", "sla_policies.id"],
            name="fk_sla_instances_workspace_policy",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_sla_instances_workspace_id"),
        UniqueConstraint(
            "workspace_id", "work_item_id", name="uq_sla_instances_work_item"
        ),
        CheckConstraint(
            check_in("status", SLA_INSTANCE_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        CheckConstraint("paused_seconds >= 0", name="paused_seconds_non_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'", name="snapshot_is_object"
        ),
        CheckConstraint(
            "(status = 'paused') = (active_pause_started_at IS NOT NULL)",
            name="pause_consistency",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="cancelled_consistency",
        ),
        CheckConstraint(
            "breach_resolution_at IS NULL OR resolution_due_at IS NOT NULL",
            name="resolution_breach_requires_target",
        ),
        CheckConstraint(
            "breach_response_at IS NULL OR response_due_at IS NOT NULL",
            name="response_breach_requires_target",
        ),
        Index("ix_sla_instances_workspace_id", "workspace_id"),
        Index("ix_sla_instances_project_id", "project_id"),
        Index(
            "ix_sla_instances_due",
            "workspace_id",
            "status",
            "next_evaluation_at",
            "id",
        ),
    )


class SlaPauseInterval(Base):
    """One closed or open pause interval; the sum feeds ``paused_seconds``."""

    __tablename__ = "sla_pause_intervals"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    instance_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "instance_id"],
            ["sla_instances.workspace_id", "sla_instances.id"],
            name="fk_sla_pause_intervals_workspace_instance",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_sla_pause_intervals_workspace_id"
        ),
        CheckConstraint(
            "seconds IS NULL OR seconds >= 0", name="seconds_non_negative"
        ),
        CheckConstraint(
            "(ended_at IS NULL) = (seconds IS NULL)", name="closed_interval_consistency"
        ),
        Index("ix_sla_pause_intervals_instance_id", "instance_id"),
    )


class SlaEvent(Base):
    """Append-only SLA event history; also the durable notification source."""

    __tablename__ = "sla_events"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    instance_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "instance_id"],
            ["sla_instances.workspace_id", "sla_instances.id"],
            name="fk_sla_events_workspace_instance",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_sla_events_workspace_id"),
        CheckConstraint(
            check_in("event_type", SLA_EVENT_TYPE_VALUES), name="event_type_values"
        ),
        UniqueConstraint(
            "instance_id",
            "event_type",
            "due_at",
            name="uq_sla_events_instance_type_due",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index("ix_sla_events_instance_id", "instance_id"),
    )
