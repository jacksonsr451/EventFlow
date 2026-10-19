"""Add business priority, SLA, WorkItem dependencies and notifications (#30).

Additive-only migration. Existing consultations and work items keep their
current priority values; the new columns are nullable so no backfill is
destructive. Cycle prevention is enforced by the service under a workspace
advisory lock because a pure CHECK constraint cannot express graph acyclicity.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_priority_sla_dependencies"
down_revision = "0010_project_repositories"
branch_labels = None
depends_on = None

_IMPACT = "business_impact IN ('critical', 'high', 'moderate', 'low')"
_URGENCY = "business_urgency IN ('immediate', 'elevated', 'normal', 'low')"
_PRIORITY = "priority IN ('critical', 'high', 'medium', 'low')"
_OVERRIDE = (
    "priority_override_reason IS NULL OR "
    "char_length(priority_override_reason) BETWEEN 10 AND 300"
)


def upgrade() -> None:
    op.add_column(
        "consultations",
        sa.Column("business_impact", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("business_urgency", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("priority_override_reason", sa.String(length=300), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_consultations_business_impact_values"),
        "consultations",
        f"business_impact IS NULL OR {_IMPACT}",
    )
    op.create_check_constraint(
        op.f("ck_consultations_business_urgency_values"),
        "consultations",
        f"business_urgency IS NULL OR {_URGENCY}",
    )
    op.create_check_constraint(
        op.f("ck_consultations_priority_override_reason_length"),
        "consultations",
        _OVERRIDE,
    )

    op.add_column(
        "work_items",
        sa.Column("calculated_priority", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "work_items",
        sa.Column("priority_override_reason", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "work_items",
        sa.Column("priority_overridden_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_work_items_calculated_priority_values"),
        "work_items",
        f"calculated_priority IS NULL OR calculated_priority IN "
        "('critical', 'high', 'medium', 'low')",
    )
    op.create_check_constraint(
        op.f("ck_work_items_priority_override_reason_length"),
        "work_items",
        _OVERRIDE,
    )
    op.create_check_constraint(
        op.f("ck_work_items_priority_override_actor_consistency"),
        "work_items",
        "(priority_override_reason IS NULL) = (priority_overridden_by IS NULL)",
    )

    op.create_table(
        "sla_policies",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("response_minutes", sa.Integer(), nullable=True),
        sa.Column("resolution_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column(
            "business_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "holidays",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "pause_statuses",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"blocked\"]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warning_threshold_percent",
            sa.Integer(),
            server_default=sa.text("75"),
            nullable=False,
        ),
        sa.Column("supersedes_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_sla_policies_workspace_project",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_policies")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sla_policies_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "name",
            "version",
            name="uq_sla_policies_scope_name_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name=op.f("ck_sla_policies_status_values"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sla_policies_version_positive")),
        sa.CheckConstraint(
            "response_minutes IS NULL OR response_minutes >= 1",
            name=op.f("ck_sla_policies_response_minutes_positive"),
        ),
        sa.CheckConstraint(
            "resolution_minutes IS NULL OR resolution_minutes >= 1",
            name=op.f("ck_sla_policies_resolution_minutes_positive"),
        ),
        sa.CheckConstraint(
            "response_minutes IS NOT NULL OR resolution_minutes IS NOT NULL",
            name=op.f("ck_sla_policies_at_least_one_target"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120",
            name=op.f("ck_sla_policies_name_length"),
        ),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 64",
            name=op.f("ck_sla_policies_timezone_length"),
        ),
        sa.CheckConstraint(
            "warning_threshold_percent BETWEEN 1 AND 99",
            name=op.f("ck_sla_policies_warning_threshold_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(business_hours) = 'object'",
            name=op.f("ck_sla_policies_business_hours_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(holidays) = 'array'",
            name=op.f("ck_sla_policies_holidays_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(pause_statuses) = 'array'",
            name=op.f("ck_sla_policies_pause_statuses_is_array"),
        ),
        sa.CheckConstraint(
            "(status = 'active') = (activated_at IS NOT NULL)",
            name=op.f("ck_sla_policies_activated_consistency"),
        ),
        sa.CheckConstraint(
            "(status = 'retired') = (retired_at IS NOT NULL)",
            name=op.f("ck_sla_policies_retired_consistency"),
        ),
    )
    op.create_index("ix_sla_policies_workspace_id", "sla_policies", ["workspace_id"])
    op.create_index("ix_sla_policies_project_id", "sla_policies", ["project_id"])
    op.create_index(
        "uq_sla_policies_active_workspace",
        "sla_policies",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND project_id IS NULL"),
    )
    op.create_index(
        "uq_sla_policies_active_project",
        "sla_policies",
        ["workspace_id", "project_id", "name"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND project_id IS NOT NULL"),
    )

    op.create_table(
        "sla_instances",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("work_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "paused_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("active_pause_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warning_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warning_resolution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breach_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breach_resolution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_sla_instances_workspace_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_sla_instances_workspace_work_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "policy_id"],
            ["sla_policies.workspace_id", "sla_policies.id"],
            name="fk_sla_instances_workspace_policy",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_instances")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sla_instances_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "work_item_id", name="uq_sla_instances_work_item"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'paused', 'fulfilled', 'breached', "
            "'cancelled')",
            name=op.f("ck_sla_instances_status_values"),
        ),
        sa.CheckConstraint(
            "policy_version >= 1", name=op.f("ck_sla_instances_policy_version_positive")
        ),
        sa.CheckConstraint(
            "paused_seconds >= 0", name=op.f("ck_sla_instances_paused_seconds_non_negative")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sla_instances_version_positive")),
        sa.CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'",
            name=op.f("ck_sla_instances_snapshot_is_object"),
        ),
        sa.CheckConstraint(
            "(status = 'paused') = (active_pause_started_at IS NOT NULL)",
            name=op.f("ck_sla_instances_pause_consistency"),
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name=op.f("ck_sla_instances_cancelled_consistency"),
        ),
        sa.CheckConstraint(
            "breach_resolution_at IS NULL OR resolution_due_at IS NOT NULL",
            name=op.f("ck_sla_instances_resolution_breach_requires_target"),
        ),
        sa.CheckConstraint(
            "breach_response_at IS NULL OR response_due_at IS NOT NULL",
            name=op.f("ck_sla_instances_response_breach_requires_target"),
        ),
    )
    op.create_index("ix_sla_instances_workspace_id", "sla_instances", ["workspace_id"])
    op.create_index("ix_sla_instances_project_id", "sla_instances", ["project_id"])
    op.create_index(
        "ix_sla_instances_due",
        "sla_instances",
        ["workspace_id", "status", "next_evaluation_at", "id"],
    )

    op.create_table(
        "sla_pause_intervals",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("instance_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "instance_id"],
            ["sla_instances.workspace_id", "sla_instances.id"],
            name="fk_sla_pause_intervals_workspace_instance",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_pause_intervals")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_sla_pause_intervals_workspace_id"
        ),
        sa.CheckConstraint(
            "seconds IS NULL OR seconds >= 0",
            name=op.f("ck_sla_pause_intervals_seconds_non_negative"),
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL) = (seconds IS NULL)",
            name=op.f("ck_sla_pause_intervals_closed_interval_consistency"),
        ),
    )
    op.create_index(
        "ix_sla_pause_intervals_instance_id", "sla_pause_intervals", ["instance_id"]
    )

    op.create_table(
        "sla_events",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("instance_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "instance_id"],
            ["sla_instances.workspace_id", "sla_instances.id"],
            name="fk_sla_events_workspace_instance",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sla_events")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sla_events_workspace_id"),
        sa.CheckConstraint(
            "event_type IN ('started', 'paused', 'resumed', 'warning_response', "
            "'warning_resolution', 'breach_response', 'breach_resolution', "
            "'fulfilled', 'cancelled')",
            name=op.f("ck_sla_events_event_type_values"),
        ),
        sa.UniqueConstraint(
            "instance_id",
            "event_type",
            "due_at",
            name="uq_sla_events_instance_type_due",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_sla_events_payload_is_object"),
        ),
    )
    op.create_index("ix_sla_events_instance_id", "sla_events", ["instance_id"])

    op.create_table(
        "work_item_dependencies",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("blocking_work_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("blocked_work_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_work_item_dependencies_workspace_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "blocking_work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_work_item_dependencies_workspace_blocking",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "blocked_work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_work_item_dependencies_workspace_blocked",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_item_dependencies")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_work_item_dependencies_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "blocking_work_item_id",
            "blocked_work_item_id",
            name="uq_work_item_dependencies_edge",
        ),
        sa.CheckConstraint(
            "blocking_work_item_id <> blocked_work_item_id",
            name=op.f("ck_work_item_dependencies_no_self_edge"),
        ),
    )
    op.create_index(
        "ix_work_item_dependencies_blocking",
        "work_item_dependencies",
        ["workspace_id", "blocking_work_item_id"],
    )
    op.create_index(
        "ix_work_item_dependencies_blocked",
        "work_item_dependencies",
        ["workspace_id", "blocked_work_item_id"],
    )

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["external_identities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_notifications_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "dedup_key", name="uq_notifications_workspace_dedup"
        ),
        sa.CheckConstraint(
            "event_type IN ('dependency.created', 'dependency.removed', "
            "'sla.warning', 'sla.breached', 'sla.fulfilled', "
            "'work_item.priority_overridden', 'work_item.blocked')",
            name=op.f("ck_notifications_event_type_values"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_notifications_payload_is_object"),
        ),
        sa.CheckConstraint(
            "char_length(dedup_key) BETWEEN 1 AND 200",
            name=op.f("ck_notifications_dedup_key_length"),
        ),
    )
    op.create_index(
        "ix_notifications_recipient",
        "notifications",
        ["workspace_id", "recipient_id", "created_at", "id"],
    )

    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "in_app", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "email", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["external_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_notification_preferences_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "recipient_id",
            "event_type",
            name="uq_notification_preferences_scope",
        ),
        sa.CheckConstraint(
            "event_type IN ('dependency.created', 'dependency.removed', "
            "'sla.warning', 'sla.breached', 'sla.fulfilled', "
            "'work_item.priority_overridden', 'work_item.blocked')",
            name=op.f("ck_notification_preferences_event_type_values"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_notification_preferences_version_positive")
        ),
    )
    op.create_index(
        "ix_notification_preferences_recipient",
        "notification_preferences",
        ["workspace_id", "recipient_id"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("notification_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["notifications.workspace_id", "notifications.id"],
            name="fk_notification_deliveries_workspace_notification",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_notification_deliveries_workspace_id"
        ),
        sa.UniqueConstraint(
            "notification_id", "channel", name="uq_notification_deliveries_channel"
        ),
        sa.CheckConstraint(
            "channel IN ('in_app', 'email')",
            name=op.f("ck_notification_deliveries_channel_values"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'unavailable', 'exhausted')",
            name=op.f("ck_notification_deliveries_status_values"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_notification_deliveries_attempts_non_negative")
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name=op.f("ck_notification_deliveries_delivered_consistency"),
        ),
    )
    op.create_index(
        "ix_notification_deliveries_dispatch",
        "notification_deliveries",
        ["workspace_id", "status", "next_attempt_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_dispatch", table_name="notification_deliveries"
    )
    op.drop_table("notification_deliveries")
    op.drop_index(
        "ix_notification_preferences_recipient", table_name="notification_preferences"
    )
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_recipient", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(
        "ix_work_item_dependencies_blocked", table_name="work_item_dependencies"
    )
    op.drop_index(
        "ix_work_item_dependencies_blocking", table_name="work_item_dependencies"
    )
    op.drop_table("work_item_dependencies")
    op.drop_index("ix_sla_events_instance_id", table_name="sla_events")
    op.drop_table("sla_events")
    op.drop_index(
        "ix_sla_pause_intervals_instance_id", table_name="sla_pause_intervals"
    )
    op.drop_table("sla_pause_intervals")
    op.drop_index("ix_sla_instances_due", table_name="sla_instances")
    op.drop_index("ix_sla_instances_project_id", table_name="sla_instances")
    op.drop_index("ix_sla_instances_workspace_id", table_name="sla_instances")
    op.drop_table("sla_instances")
    op.drop_index("uq_sla_policies_active_project", table_name="sla_policies")
    op.drop_index("uq_sla_policies_active_workspace", table_name="sla_policies")
    op.drop_index("ix_sla_policies_project_id", table_name="sla_policies")
    op.drop_index("ix_sla_policies_workspace_id", table_name="sla_policies")
    op.drop_table("sla_policies")

    op.drop_constraint(
        op.f("ck_work_items_priority_override_actor_consistency"),
        "work_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_work_items_priority_override_reason_length"),
        "work_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_work_items_calculated_priority_values"), "work_items", type_="check"
    )
    op.drop_column("work_items", "priority_overridden_by")
    op.drop_column("work_items", "priority_override_reason")
    op.drop_column("work_items", "calculated_priority")

    op.drop_constraint(
        op.f("ck_consultations_priority_override_reason_length"),
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_consultations_business_urgency_values"),
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_consultations_business_impact_values"),
        "consultations",
        type_="check",
    )
    op.drop_column("consultations", "priority_override_reason")
    op.drop_column("consultations", "business_urgency")
    op.drop_column("consultations", "business_impact")
