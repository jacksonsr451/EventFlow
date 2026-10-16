"""Consultation attachment metadata and stored object models (Issue #4).

Attachments are hostile by default. Metadata is separated from the stored bytes
so list and detail reads never load object content, and the object is addressed
by an opaque ``storage_key`` that is never derived from the client filename
(AT-07). Content is stored in a per-tenant namespace with no public path (AT-04).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    check_in,
    check_regex,
)
from eventflow_work_management.models.enums import (
    ATTACHMENT_SCAN_VERDICT_VALUES,
    ATTACHMENT_STATUS_VALUES,
)

SHA256_PATTERN = "^[0-9a-f]{64}$"
STORAGE_KEY_PATTERN = "^[0-9a-f]{32}$"


class ConsultationAttachment(TimestampMixin, Base):
    """Metadata for one uploaded consultation attachment."""

    __tablename__ = "consultation_attachments"

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
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'quarantined'")
    )
    scan_verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "consultation_id"],
            ["consultations.workspace_id", "consultations.id"],
            name="fk_consultation_attachments_workspace_consultation",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_consultation_attachments_workspace_id"
        ),
        UniqueConstraint("storage_key", name="uq_consultation_attachments_storage_key"),
        CheckConstraint(
            check_in("status", ATTACHMENT_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint(
            check_in("scan_verdict", ATTACHMENT_SCAN_VERDICT_VALUES),
            name="scan_verdict_values",
        ),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255", name="file_name_length"
        ),
        CheckConstraint(
            "char_length(declared_content_type) BETWEEN 1 AND 255",
            name="declared_content_type_length",
        ),
        CheckConstraint(
            "char_length(detected_content_type) BETWEEN 1 AND 255",
            name="detected_content_type_length",
        ),
        CheckConstraint(
            check_regex("checksum_sha256", SHA256_PATTERN), name="checksum_format"
        ),
        CheckConstraint(
            check_regex("storage_key", STORAGE_KEY_PATTERN), name="storage_key_format"
        ),
        CheckConstraint(
            "rejection_reason IS NULL OR char_length(rejection_reason) BETWEEN 1 AND 120",
            name="rejection_reason_length",
        ),
        # A quarantined or available attachment must have been scanned; a rejected
        # attachment records why it was refused.
        CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name="rejection_reason_consistency",
        ),
        Index("ix_consultation_attachments_workspace_id", "workspace_id"),
        Index("ix_consultation_attachments_consultation_id", "consultation_id"),
    )


class ConsultationAttachmentBlob(CreatedAtMixin, Base):
    """The stored bytes for one attachment, kept out of metadata reads."""

    __tablename__ = "consultation_attachment_blobs"

    attachment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("consultation_attachments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        Index("ix_consultation_attachment_blobs_workspace_id", "workspace_id"),
    )
