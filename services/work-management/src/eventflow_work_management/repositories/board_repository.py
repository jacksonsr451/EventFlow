"""Board and BoardCard repositories."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import Board, BoardCard
from eventflow_work_management.repositories.base import Repository
from eventflow_work_management.repositories.errors import EntityNotFound


class BoardRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        name: str,
        columns: list | None = None,
    ) -> Board:
        board = self.add(
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            columns=columns,
        )
        self._session.commit()
        return board

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        name: str,
        columns: list | None = None,
    ) -> Board:
        """Add and flush a board inside the caller's transaction."""
        board = Board(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            columns=columns or [],
            version=1,
        )
        self._session.add(board)
        self._session.flush()
        return board

    def get(self, *, workspace_id: UUID, board_id: UUID) -> Board | None:
        statement = select(Board).where(
            Board.workspace_id == workspace_id, Board.id == board_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, *, workspace_id: UUID, board_id: UUID) -> Board | None:
        statement = (
            select(Board)
            .where(Board.workspace_id == workspace_id, Board.id == board_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
        include_archived: bool = True,
    ) -> list[Board]:
        statement = select(Board).where(Board.workspace_id == workspace_id)
        if project_id is not None:
            statement = statement.where(Board.project_id == project_id)
        if not include_archived:
            statement = statement.where(Board.archived_at.is_(None))
        statement = statement.order_by(Board.created_at, Board.id)
        return list(self._session.execute(statement).scalars())

    def set_columns(self, board: Board, *, columns: list[str]) -> None:
        board.columns = list(columns)
        self._session.flush()

    def touch(self, board: Board) -> None:
        """Bump the optimistic-concurrency version of a board."""
        board.version = board.version + 1
        self._session.flush()

    def archive(self, board: Board, *, archived_at: datetime) -> None:
        board.archived_at = archived_at
        self._session.flush()


class BoardCardRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add_card(
        self,
        *,
        workspace_id: UUID,
        board_id: UUID,
        work_item_id: UUID,
        column_id: str,
        rank: str,
        title: str,
        priority: str,
        category: str,
        assignee_id: UUID | None = None,
    ) -> BoardCard:
        """Create and commit one card (standalone unit of work)."""
        card = self.build_card(
            workspace_id=workspace_id,
            board_id=board_id,
            work_item_id=work_item_id,
            column_id=column_id,
            rank=rank,
            title=title,
            priority=priority,
            category=category,
            assignee_id=assignee_id,
        )
        self._session.commit()
        return card

    def build_card(
        self,
        *,
        workspace_id: UUID,
        board_id: UUID,
        work_item_id: UUID,
        column_id: str,
        rank: str,
        title: str,
        priority: str,
        category: str,
        assignee_id: UUID | None = None,
    ) -> BoardCard:
        """Add and flush a card inside the caller's transaction.

        It never commits, so the card can be created atomically with the
        approval and WorkItem that authorize it.
        """
        board = self._session.get(Board, board_id)
        if board is None or board.workspace_id != workspace_id:
            raise EntityNotFound("board not found in workspace")
        card = BoardCard(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=board.project_id,
            board_id=board_id,
            work_item_id=work_item_id,
            column_id=column_id,
            rank=rank,
            title=title,
            priority=priority,
            category=category,
            assignee_id=assignee_id,
        )
        self._session.add(card)
        self._session.flush()
        return card

    def get(self, *, workspace_id: UUID, card_id: UUID) -> BoardCard | None:
        statement = select(BoardCard).where(
            BoardCard.workspace_id == workspace_id, BoardCard.id == card_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, *, workspace_id: UUID, card_id: UUID) -> BoardCard | None:
        statement = (
            select(BoardCard)
            .where(
                BoardCard.workspace_id == workspace_id, BoardCard.id == card_id
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_board(
        self, *, workspace_id: UUID, board_id: UUID
    ) -> list[BoardCard]:
        statement = (
            select(BoardCard)
            .where(
                BoardCard.workspace_id == workspace_id,
                BoardCard.board_id == board_id,
            )
            .order_by(BoardCard.column_id, BoardCard.rank, BoardCard.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_page(
        self,
        *,
        workspace_id: UUID,
        board_id: UUID,
        column_id: str | None = None,
        sort_key: str = "rank",
        descending: bool = False,
        limit: int,
        after: tuple | None = None,
    ) -> list[BoardCard]:
        column = getattr(BoardCard, sort_key)
        statement = select(BoardCard).where(
            BoardCard.workspace_id == workspace_id,
            BoardCard.board_id == board_id,
        )
        if column_id is not None:
            statement = statement.where(BoardCard.column_id == column_id)
        if after is not None:
            value, after_id = after
            if descending:
                statement = statement.where(
                    tuple_(column, BoardCard.id) < tuple_(value, after_id)
                )
            else:
                statement = statement.where(
                    tuple_(column, BoardCard.id) > tuple_(value, after_id)
                )
        if descending:
            statement = statement.order_by(column.desc(), BoardCard.id.desc())
        else:
            statement = statement.order_by(column, BoardCard.id)
        return list(self._session.execute(statement.limit(limit)).scalars())

    def list_ranks_in_column(
        self,
        *,
        board_id: UUID,
        column_id: str,
        exclude_card_id: UUID | None = None,
    ) -> list[str]:
        statement = select(BoardCard.rank).where(
            BoardCard.board_id == board_id, BoardCard.column_id == column_id
        )
        if exclude_card_id is not None:
            statement = statement.where(BoardCard.id != exclude_card_id)
        statement = statement.order_by(BoardCard.rank)
        return list(self._session.execute(statement).scalars())

    def count_in_column(self, *, board_id: UUID, column_id: str) -> int:
        statement = select(func.count()).select_from(BoardCard).where(
            BoardCard.board_id == board_id, BoardCard.column_id == column_id
        )
        return int(self._session.execute(statement).scalar_one())

    def apply_move(self, card: BoardCard, *, column_id: str, rank: str) -> None:
        card.column_id = column_id
        card.rank = rank
        self._session.flush()

    def move(
        self,
        *,
        workspace_id: UUID,
        card_id: UUID,
        column_id: str,
        rank: str,
    ) -> BoardCard:
        card = self.get(workspace_id=workspace_id, card_id=card_id)
        if card is None:
            raise EntityNotFound("board card not found")
        card.column_id = column_id
        card.rank = rank
        self._session.commit()
        return card
