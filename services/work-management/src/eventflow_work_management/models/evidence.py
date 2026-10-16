"""Consultation evidence model (Issue #4).

Evidence captures the structured justification attached to a consultation: free
text, an external link, or a reference to a stored attachment. A link or text
entry carries inline ``content``; an attachment entry carries only an
``attachment_id`` so the bytes stay behind the attachment access controls.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin, check_in
from eventflow_work_management.models.enums import EVIDENCE_KIND_VALUES

_KIND_CONTENT_CONSISTENCY = (
    "(kind = 'attachment' AND attachment_id IS NOT NULL AND content IS NULL) "
    "OR (kind IN ('text', 'link') AND content IS NOT NULL AND attachment_id IS NULL)"
)


class ConsultationEvidence(CreatedAtMixin, Base):
    """One piece of evidence attached to a consultation."""

    __tablename__ = "consultation_evidence"

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
    consultation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "consultation_id"],
            ["consultations.workspace_id", "consultations.id"],
            name="fk_consultation_evidence_workspace_consultation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["attachment_id"],
            ["consultation_attachments.id"],
            name="fk_consultation_evidence_attachment_id_consultation_attachments",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_consultation_evidence_workspace_id"
        ),
        CheckConstraint(check_in("kind", EVIDENCE_KIND_VALUES), name="kind_values"),
        CheckConstraint(_KIND_CONTENT_CONSISTENCY, name="kind_content_consistency"),
        CheckConstraint(
            "description IS NULL OR char_length(description) BETWEEN 1 AND 500",
            name="description_length",
        ),
        CheckConstraint(
            "content IS NULL OR char_length(content) BETWEEN 1 AND 4096",
            name="content_length",
        ),
        Index("ix_consultation_evidence_workspace_id", "workspace_id"),
        Index("ix_consultation_evidence_consultation_id", "consultation_id"),
    )
