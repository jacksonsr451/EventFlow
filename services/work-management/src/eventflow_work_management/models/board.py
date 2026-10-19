"""Board, BoardColumn, BoardCard and CardMovement models (Issues #7, #8).

A ``Board`` is an ordered set of configurable ``BoardColumn`` definitions for one
project. A ``BoardCard`` places one approved-``WorkItem`` on a board column at an
opaque rank; a ``CardMovement`` is the append-only movement history of that card.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    check_in,
    check_regex,
)
from eventflow_work_management.models.enums import (
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
    WORK_ITEM_STATUS_VALUES,
)

RANK_PATTERN = "^[0-9a-zA-Z_-]+$"
COLUMN_KEY_PATTERN = "^[a-z0-9][a-z0-9_-]{0,79}$"


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
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_boards_workspace_id", "workspace_id"),
        Index("ix_boards_project_id", "project_id"),
    )


class BoardColumn(TimestampMixin, Base):
    """A configurable column definition belonging to exactly one board.

    The ``key`` is the stable column identifier referenced by
    ``board_cards.column_id`` and listed in ``boards.columns``. ``mapped_status``
    binds the column to a canonical ``WorkItem`` status, and ``wip_limit`` (NULL
    means unlimited) bounds how many cards the column may hold.
    """

    __tablename__ = "board_columns"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    board_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    mapped_status: Mapped[str] = mapped_column(String(16), nullable=False)
    wip_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "board_id"],
            ["boards.workspace_id", "boards.project_id", "boards.id"],
            name="fk_board_columns_workspace_project_board",
            ondelete="CASCADE",
        ),
        UniqueConstraint("board_id", "key", name="uq_board_columns_board_key"),
        UniqueConstraint("workspace_id", "id", name="uq_board_columns_workspace_id"),
        CheckConstraint(
            check_regex("key", COLUMN_KEY_PATTERN), name="key_format"
        ),
        CheckConstraint("char_length(name) >= 1", name="name_min_length"),
        CheckConstraint(
            check_in("mapped_status", WORK_ITEM_STATUS_VALUES),
            name="mapped_status_values",
        ),
        CheckConstraint("wip_limit IS NULL OR wip_limit >= 1", name="wip_limit_positive"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_board_columns_board_position", "board_id", "position"),
        Index("ix_board_columns_workspace_id", "workspace_id"),
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


class CardMovement(CreatedAtMixin, Base):
    """An append-only record of one board-card move.

    The initial migration installs triggers that reject ``UPDATE`` and
    ``DELETE``, so the movement history cannot be rewritten. Historical column
    identifiers are stored as strings without a foreign key so the history
    survives later column reconfiguration.
    """

    __tablename__ = "card_movements"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    board_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    card_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_column_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_column_id: Mapped[str] = mapped_column(String(80), nullable=False)
    from_rank: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_rank: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "board_id"],
            ["boards.workspace_id", "boards.project_id", "boards.id"],
            name="fk_card_movements_workspace_project_board",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "card_id"],
            ["board_cards.workspace_id", "board_cards.id"],
            name="fk_card_movements_workspace_card",
            ondelete="CASCADE",
        ),
        CheckConstraint(check_regex("to_rank", RANK_PATTERN), name="to_rank_format"),
        CheckConstraint(
            "from_rank IS NULL OR " + check_regex("from_rank", RANK_PATTERN),
            name="from_rank_format",
        ),
        CheckConstraint(
            check_in("to_status", WORK_ITEM_STATUS_VALUES), name="to_status_values"
        ),
        CheckConstraint(
            "from_status IS NULL OR "
            + check_in("from_status", WORK_ITEM_STATUS_VALUES),
            name="from_status_values",
        ),
        CheckConstraint(
            "char_length(to_column_id) >= 1", name="to_column_id_min_length"
        ),
        Index(
            "ix_card_movements_workspace_card",
            "workspace_id",
            "card_id",
            "occurred_at",
        ),
        Index("ix_card_movements_board_id", "board_id"),
    )
