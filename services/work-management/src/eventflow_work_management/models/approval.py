"""Approval model: an immutable decision over one Proposal version."""

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
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin, check_in, check_regex
from eventflow_work_management.models.enums import APPROVAL_DECISION_VALUES

SHA256_PATTERN = "^[0-9a-f]{64}$"


class Approval(CreatedAtMixin, Base):
    """A decision recorded by an approver for a specific proposal version."""

    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_version: Mapped[int] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decider_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_justification: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_approvals_workspace_proposal",
            ondelete="CASCADE",
        ),
        UniqueConstraint("proposal_id", "proposal_version", name="uq_approvals_proposal_version"),
        UniqueConstraint("workspace_id", "id", name="uq_approvals_workspace_id"),
        CheckConstraint(check_in("decision", APPROVAL_DECISION_VALUES), name="decision_values"),
        CheckConstraint("proposal_version >= 1", name="proposal_version_positive"),
        CheckConstraint(
            "char_length(decision_justification) >= 3", name="justification_min_length"
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 128", name="idempotency_key_length"
        ),
        CheckConstraint(check_regex("audit_snapshot_hash", SHA256_PATTERN), name="snapshot_hash_format"),
        Index("ix_approvals_workspace_id", "workspace_id"),
        Index("ix_approvals_proposal_id", "proposal_id"),
    )
