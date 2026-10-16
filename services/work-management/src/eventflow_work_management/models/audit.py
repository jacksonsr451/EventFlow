"""Append-only audit record model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin, check_regex

SHA256_PATTERN = "^[0-9a-f]{64}$"


class AuditRecord(CreatedAtMixin, Base):
    """Immutable record of a Work Management state change.

    The initial migration installs triggers that reject ``UPDATE`` and
    ``DELETE``, making this table append-only at the database level.
    """

    __tablename__ = "audit_records"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("char_length(action) >= 3", name="action_min_length"),
        CheckConstraint("char_length(entity_type) >= 3", name="entity_type_min_length"),
        CheckConstraint(
            check_regex("snapshot_hash", SHA256_PATTERN), name="snapshot_hash_format"
        ),
        Index(
            "ix_audit_records_workspace_entity",
            "workspace_id",
            "entity_type",
            "entity_id",
        ),
        Index("ix_audit_records_occurred_at", "occurred_at"),
    )
