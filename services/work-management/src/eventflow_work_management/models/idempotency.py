"""Idempotency record model (ADR-007 section 3.6, ADR-008 section 5)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin, check_regex

SHA256_PATTERN = "^[0-9a-f]{64}$"


class IdempotencyRecord(CreatedAtMixin, Base):
    """Stores the response of one idempotent operation per client key.

    The record is written in the same transaction as the domain change so a
    retry returns the stored response without repeating side effects.
    """

    __tablename__ = "idempotency_records"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_records_scope_key",
        ),
        CheckConstraint("char_length(operation) >= 1", name="operation_min_length"),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 128",
            name="idempotency_key_length",
        ),
        CheckConstraint(
            check_regex("request_fingerprint", SHA256_PATTERN),
            name="fingerprint_format",
        ),
        Index("ix_idempotency_records_workspace_id", "workspace_id"),
    )
