"""Board and BoardCard repositories."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
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
        board = Board(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            columns=columns or [],
        )
        self._session.add(board)
        self._session.commit()
        return board

    def get(self, *, workspace_id: UUID, board_id: UUID) -> Board | None:
        statement = select(Board).where(
            Board.workspace_id == workspace_id, Board.id == board_id
        )
        return self._session.execute(statement).scalar_one_or_none()


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
