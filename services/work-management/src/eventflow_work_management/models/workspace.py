"""Workspace (tenant) and Project models."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, TimestampMixin, check_regex

SLUG_PATTERN = "^[a-z0-9]+(-[a-z0-9]+)*$"
KEY_PATTERN = "^[A-Z][A-Z0-9]{1,9}$"


class Workspace(TimestampMixin, Base):
    """Tenant boundary. Every tenant-owned row references exactly one workspace."""

    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        CheckConstraint("char_length(name) >= 3", name="name_min_length"),
        CheckConstraint(check_regex("slug", SLUG_PATTERN), name="slug_format"),
    )


class Project(TimestampMixin, Base):
    """A unit of work grouping inside a workspace."""

    __tablename__ = "projects"

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
    key: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_projects_workspace_key"),
        UniqueConstraint("workspace_id", "id", name="uq_projects_workspace_id"),
        CheckConstraint("char_length(name) >= 3", name="name_min_length"),
        CheckConstraint(check_regex("key", KEY_PATTERN), name="key_format"),
        Index("ix_projects_workspace_id", "workspace_id"),
    )
