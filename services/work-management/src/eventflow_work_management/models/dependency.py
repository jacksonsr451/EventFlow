"""Directional WorkItem dependency edges (Issue #30).

An edge means "the blocking WorkItem must finish before the blocked WorkItem".
The table is directional and tenant-scoped; a WorkItem may never depend on
itself. Cycles are rejected by the service under a workspace advisory lock, and
this unique constraint makes duplicate edges impossible even under concurrency.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin


class WorkItemDependency(CreatedAtMixin, Base):
    """A single directed blocking relation between two WorkItems."""

    __tablename__ = "work_item_dependencies"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blocking_work_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blocked_work_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_work_item_dependencies_workspace_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "blocking_work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_work_item_dependencies_workspace_blocking",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "blocked_work_item_id"],
            ["work_items.workspace_id", "work_items.id"],
            name="fk_work_item_dependencies_workspace_blocked",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_work_item_dependencies_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "blocking_work_item_id",
            "blocked_work_item_id",
            name="uq_work_item_dependencies_edge",
        ),
        CheckConstraint(
            "blocking_work_item_id <> blocked_work_item_id", name="no_self_edge"
        ),
        Index(
            "ix_work_item_dependencies_blocking",
            "workspace_id",
            "blocking_work_item_id",
        ),
        Index(
            "ix_work_item_dependencies_blocked",
            "workspace_id",
            "blocked_work_item_id",
        ),
    )
