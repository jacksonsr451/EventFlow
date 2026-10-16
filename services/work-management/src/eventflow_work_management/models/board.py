"""Board and BoardCard models."""

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

from eventflow_work_management.db.base import (
    Base,
    TimestampMixin,
    check_in,
    check_regex,
)
from eventflow_work_management.models.enums import (
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
)

RANK_PATTERN = "^[0-9a-zA-Z_-]+$"


class Board(TimestampMixin, Base):
    """An ordered set of columns that groups cards for a project."""

    __tablename__ = "boards"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    columns: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_boards_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_boards_workspace_id"),
        UniqueConstraint(
            "workspace_id", "project_id", "id", name="uq_boards_workspace_project_id"
        ),
        CheckConstraint("char_length(name) >= 1", name="name_min_length"),
        CheckConstraint("jsonb_typeof(columns) = 'array'", name="columns_is_array"),
        Index("ix_boards_workspace_id", "workspace_id"),
        Index("ix_boards_project_id", "project_id"),
    )


class BoardCard(TimestampMixin, Base):
    """A card placing one WorkItem into a board column at a rank."""

    __tablename__ = "board_cards"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    board_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    column_id: Mapped[str] = mapped_column(String(80), nullable=False)
    work_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rank: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "board_id"],
            ["boards.workspace_id", "boards.project_id", "boards.id"],
            name="fk_board_cards_workspace_project_board",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "work_item_id"],
            ["work_items.workspace_id", "work_items.project_id", "work_items.id"],
            name="fk_board_cards_workspace_project_work_item",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "board_id", "work_item_id", name="uq_board_cards_board_work_item"
        ),
        UniqueConstraint(
            "board_id", "column_id", "rank", name="uq_board_cards_column_rank"
        ),
        UniqueConstraint("workspace_id", "id", name="uq_board_cards_workspace_id"),
        CheckConstraint("char_length(column_id) >= 1", name="column_id_min_length"),
        CheckConstraint(check_regex("rank", RANK_PATTERN), name="rank_format"),
        CheckConstraint("char_length(title) >= 3", name="title_min_length"),
        CheckConstraint(check_in("priority", PRIORITY_VALUES), name="priority_values"),
        CheckConstraint(
            check_in("category", TRIAGE_CATEGORY_VALUES), name="category_values"
        ),
        Index("ix_board_cards_workspace_id", "workspace_id"),
        Index("ix_board_cards_project_id", "project_id"),
        Index("ix_board_cards_board_id", "board_id"),
        Index("ix_board_cards_column_id", "column_id"),
    )
