"""Entity comment model (Issue #29).

Comments are collaborative, not authoritative. They are append-only in the sense
that the author, body, and target can never be rewritten: the migration installs
a trigger that rejects such updates. Deletion is a soft-delete tombstone so a
removed comment still proves that it existed without exposing its body through
the API.
"""

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

from eventflow_work_management.db.base import (
    Base,
    TimestampMixin,
    check_in,
)
from eventflow_work_management.models.enums import ENTITY_TYPE_VALUES

MAX_BODY_LENGTH = 4000


class EntityComment(TimestampMixin, Base):
    """One comment on a workspace-scoped Work Management entity."""

    __tablename__ = "entity_comments"

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
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_entity_comments_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_entity_comments_workspace_id"
        ),
        CheckConstraint(
            check_in("entity_type", ENTITY_TYPE_VALUES), name="entity_type_values"
        ),
        CheckConstraint(
            f"char_length(body) BETWEEN 1 AND {MAX_BODY_LENGTH}", name="body_length"
        ),
        CheckConstraint(
            "(deleted_at IS NULL) = (deleted_by IS NULL)", name="deletion_consistency"
        ),
        Index(
            "ix_entity_comments_entity",
            "workspace_id",
            "entity_type",
            "entity_id",
            "created_at",
            "id",
        ),
        Index("ix_entity_comments_workspace_id", "workspace_id"),
        Index("ix_entity_comments_project_id", "project_id"),
    )
