"""Durable notifications, per-user preferences and delivery attempts.

Notifications are written inside the same transaction as the domain change that
produced them, so no external call ever happens inside a database transaction.
Delivery is a separate durable queue drained by a worker with retry/backoff and
terminal states; ``unavailable`` means no configured transport accepted the
message and the message is deliberately not claimed as delivered. Read state is
per notification and independent of delivery state.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
    NOTIFICATION_CHANNEL_VALUES,
    NOTIFICATION_DELIVERY_STATUS_VALUES,
    NOTIFICATION_EVENT_VALUES,
)


class Notification(TimestampMixin, Base):
    """One durable notification for one trusted recipient."""

    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_notifications_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_notifications_workspace_id"),
        UniqueConstraint(
            "workspace_id", "dedup_key", name="uq_notifications_workspace_dedup"
        ),
        CheckConstraint(
            check_in("event_type", NOTIFICATION_EVENT_VALUES), name="event_type_values"
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="payload_is_object"
        ),
        CheckConstraint(
            "char_length(dedup_key) BETWEEN 1 AND 200", name="dedup_key_length"
        ),
        Index(
            "ix_notifications_recipient",
            "workspace_id",
            "recipient_id",
            "created_at",
            "id",
        ),
    )


class NotificationPreference(TimestampMixin, Base):
    """Per-recipient opt-in for one notification event type."""

    __tablename__ = "notification_preferences"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    recipient_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    in_app: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_notification_preferences_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_notification_preferences_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "recipient_id",
            "event_type",
            name="uq_notification_preferences_scope",
        ),
        CheckConstraint(
            check_in("event_type", NOTIFICATION_EVENT_VALUES), name="event_type_values"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "ix_notification_preferences_recipient",
            "workspace_id",
            "recipient_id",
        ),
    )


class NotificationDelivery(TimestampMixin, Base):
    """A durable delivery attempt row for one notification and channel."""

    __tablename__ = "notification_deliveries"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    notification_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["notifications.workspace_id", "notifications.id"],
            name="fk_notification_deliveries_workspace_notification",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_notification_deliveries_workspace_id"
        ),
        UniqueConstraint(
            "notification_id", "channel", name="uq_notification_deliveries_channel"
        ),
        CheckConstraint(
            check_in("channel", NOTIFICATION_CHANNEL_VALUES), name="channel_values"
        ),
        CheckConstraint(
            check_in("status", NOTIFICATION_DELIVERY_STATUS_VALUES),
            name="status_values",
        ),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="delivered_consistency",
        ),
        Index(
            "ix_notification_deliveries_dispatch",
            "workspace_id",
            "status",
            "next_attempt_at",
            "id",
        ),
    )
