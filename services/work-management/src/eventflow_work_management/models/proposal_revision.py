"""Immutable proposal revision model (Issue #6).

Every accepted content edit appends one snapshot to ``proposal_revisions``. The
rows are append-only (enforced by a database trigger) so the revision history is
tamper-evident. Version numbering is scoped to ``proposal_id`` and starts at 1.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin


class ProposalRevision(CreatedAtMixin, Base):
    """One immutable snapshot of a proposal at a given version."""

    __tablename__ = "proposal_revisions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposal_revisions_workspace_proposal",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "proposal_id", "version", name="uq_proposal_revisions_proposal_version"
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_proposal_revisions_workspace_id"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="snapshot_is_object"),
        CheckConstraint(
            "summary IS NULL OR char_length(summary) BETWEEN 1 AND 200",
            name="summary_length",
        ),
        Index("ix_proposal_revisions_workspace_id", "workspace_id"),
        Index("ix_proposal_revisions_proposal_id", "proposal_id"),
    )
