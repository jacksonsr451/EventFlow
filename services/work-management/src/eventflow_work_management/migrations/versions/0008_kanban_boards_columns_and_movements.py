"""Configurable Kanban boards, columns and card movement history (Issue #8).

Adds:

* ``boards.version`` and ``boards.archived_at`` for optimistic concurrency and
  board archival;
* ``board_columns``: independently managed, ordered column definitions with a
  stable ``key``, a canonical ``WorkItem`` status mapping and an optional WIP
  limit;
* ``card_movements``: the append-only movement history for a board card.

No Approval, WorkItem or BoardCard is created directly by this migration and the
approval-only WorkItem provenance invariant is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_kanban_boards_columns"
down_revision: str | None = "0007_proposal_task_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "boards",
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
    )
    op.add_column(
        "boards",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_boards_version_positive"), "boards", "version >= 1"
    )

    op.create_table(
        "board_columns",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("board_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("mapped_status", sa.String(length=16), nullable=False),
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z0-9][a-z0-9_-]{0,79}$'",
            name=op.f("ck_board_columns_key_format"),
        ),
        sa.CheckConstraint(
            "char_length(name) >= 1", name=op.f("ck_board_columns_name_min_length")
        ),
        sa.CheckConstraint(
            "mapped_status IN ('ready', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')",
            name=op.f("ck_board_columns_mapped_status_values"),
        ),
        sa.CheckConstraint(
            "wip_limit IS NULL OR wip_limit >= 1",
            name=op.f("ck_board_columns_wip_limit_positive"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_board_columns_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "board_id"],
            ["boards.workspace_id", "boards.project_id", "boards.id"],
            name="fk_board_columns_workspace_project_board",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_columns")),
        sa.UniqueConstraint("board_id", "key", name="uq_board_columns_board_key"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_board_columns_workspace_id"
        ),
    )
    op.create_index(
        "ix_board_columns_board_position", "board_columns", ["board_id", "position"]
    )
    op.create_index(
        "ix_board_columns_workspace_id", "board_columns", ["workspace_id"]
    )

    op.create_table(
        "card_movements",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("board_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("card_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("from_column_id", sa.String(length=80), nullable=True),
        sa.Column("to_column_id", sa.String(length=80), nullable=False),
        sa.Column("from_rank", sa.String(length=64), nullable=True),
        sa.Column("to_rank", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "to_rank ~ '^[0-9a-zA-Z_-]+$'",
            name=op.f("ck_card_movements_to_rank_format"),
        ),
        sa.CheckConstraint(
            "from_rank IS NULL OR from_rank ~ '^[0-9a-zA-Z_-]+$'",
            name=op.f("ck_card_movements_from_rank_format"),
        ),
        sa.CheckConstraint(
            "to_status IN ('ready', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')",
            name=op.f("ck_card_movements_to_status_values"),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('ready', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')",
            name=op.f("ck_card_movements_from_status_values"),
        ),
        sa.CheckConstraint(
            "char_length(to_column_id) >= 1",
            name=op.f("ck_card_movements_to_column_id_min_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "board_id"],
            ["boards.workspace_id", "boards.project_id", "boards.id"],
            name="fk_card_movements_workspace_project_board",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "card_id"],
            ["board_cards.workspace_id", "board_cards.id"],
            name="fk_card_movements_workspace_card",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_movements")),
    )
    op.create_index(
        "ix_card_movements_workspace_card",
        "card_movements",
        ["workspace_id", "card_id", "occurred_at"],
    )
    op.create_index("ix_card_movements_board_id", "card_movements", ["board_id"])

    # The movement history is append-only and tamper-evident.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION eventflow_card_movements_block_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'card_movements is append-only'
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_card_movements_no_update
        BEFORE UPDATE ON card_movements
        FOR EACH ROW EXECUTE FUNCTION eventflow_card_movements_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_card_movements_no_delete
        BEFORE DELETE ON card_movements
        FOR EACH ROW EXECUTE FUNCTION eventflow_card_movements_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_card_movements_no_truncate
        BEFORE TRUNCATE ON card_movements
        FOR EACH STATEMENT EXECUTE FUNCTION eventflow_card_movements_block_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_card_movements_no_truncate ON card_movements")
    op.execute("DROP TRIGGER IF EXISTS trg_card_movements_no_delete ON card_movements")
    op.execute("DROP TRIGGER IF EXISTS trg_card_movements_no_update ON card_movements")
    op.execute("DROP FUNCTION IF EXISTS eventflow_card_movements_block_mutation()")

    op.drop_index("ix_card_movements_board_id", table_name="card_movements")
    op.drop_index("ix_card_movements_workspace_card", table_name="card_movements")
    op.drop_table("card_movements")

    op.drop_index("ix_board_columns_workspace_id", table_name="board_columns")
    op.drop_index("ix_board_columns_board_position", table_name="board_columns")
    op.drop_table("board_columns")

    op.drop_constraint(op.f("ck_boards_version_positive"), "boards", type_="check")
    op.drop_column("boards", "archived_at")
    op.drop_column("boards", "version")
