"""Generic entity attachment models (Issue #29).

Consultations keep their original ``consultation_attachments`` tables. Every
other commentable entity reuses the same fail-closed lifecycle through this
generic pair of tables: metadata is separated from bytes, and the bytes are
addressed by an opaque ``storage_key`` that is never derived from the filename.
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
    ENTITY_TYPE_VALUES,
)

SHA256_PATTERN = "^[0-9a-f]{64}$"
STORAGE_KEY_PATTERN = "^[0-9a-f]{32}$"


class EntityAttachment(TimestampMixin, Base):
    """Metadata for one attachment on a generic Work Management entity."""

    __tablename__ = "entity_attachments"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_entity_attachments_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_entity_attachments_workspace_id"
        ),
        UniqueConstraint(
            "storage_key", name="uq_entity_attachments_storage_key"
        ),
        CheckConstraint(
            check_in("entity_type", ENTITY_TYPE_VALUES), name="entity_type_values"
        ),
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
        CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)",
            name="rejection_reason_consistency",
        ),
        Index(
            "ix_entity_attachments_entity",
            "workspace_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index("ix_entity_attachments_workspace_id", "workspace_id"),
        Index("ix_entity_attachments_project_id", "project_id"),
    )


class EntityAttachmentBlob(CreatedAtMixin, Base):
    """The stored bytes for one generic entity attachment."""

    __tablename__ = "entity_attachment_blobs"

    attachment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("entity_attachments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        Index("ix_entity_attachment_blobs_workspace_id", "workspace_id"),
    )
