"""BoardColumn and CardMovement repositories (Issue #8)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import BoardColumn, CardMovement
from eventflow_work_management.repositories.base import Repository


class BoardColumnRepository(Repository):
    """Reads and writes the independently managed column definitions."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        board_id: UUID,
        key: str,
        name: str,
        position: int,
        mapped_status: str,
        wip_limit: int | None,
    ) -> BoardColumn:
        column = BoardColumn(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            board_id=board_id,
            key=key,
            name=name,
            position=position,
            mapped_status=mapped_status,
            wip_limit=wip_limit,
        )
        self._session.add(column)
        self._session.flush()
        return column

    def get(self, *, workspace_id: UUID, column_id: UUID) -> BoardColumn | None:
        statement = select(BoardColumn).where(
            BoardColumn.workspace_id == workspace_id, BoardColumn.id == column_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_key(self, *, board_id: UUID, key: str) -> BoardColumn | None:
        statement = select(BoardColumn).where(
            BoardColumn.board_id == board_id, BoardColumn.key == key
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, *, workspace_id: UUID, column_id: UUID) -> BoardColumn | None:
        statement = (
            select(BoardColumn)
            .where(
                BoardColumn.workspace_id == workspace_id, BoardColumn.id == column_id
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_key_for_update(self, *, board_id: UUID, key: str) -> BoardColumn | None:
        statement = (
            select(BoardColumn)
            .where(BoardColumn.board_id == board_id, BoardColumn.key == key)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_board(
        self, *, workspace_id: UUID, board_id: UUID
    ) -> list[BoardColumn]:
        statement = (
            select(BoardColumn)
            .where(
                BoardColumn.workspace_id == workspace_id,
                BoardColumn.board_id == board_id,
            )
            .order_by(BoardColumn.position, BoardColumn.key)
        )
        return list(self._session.execute(statement).scalars())

    def count_for_board(self, *, board_id: UUID) -> int:
        statement = select(func.count()).select_from(BoardColumn).where(
            BoardColumn.board_id == board_id
        )
        return int(self._session.execute(statement).scalar_one())

    def set_position(self, column: BoardColumn, *, position: int) -> None:
        column.position = position
        self._session.flush()

    def delete(self, column: BoardColumn) -> None:
        self._session.delete(column)
        self._session.flush()


class CardMovementRepository(Repository):
    """Appends to and reads the append-only card movement history."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def append(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        board_id: UUID,
        card_id: UUID,
        from_column_id: str | None,
        to_column_id: str,
        from_rank: str | None,
        to_rank: str,
        from_status: str | None,
        to_status: str,
        actor_id: UUID | None,
        occurred_at: datetime,
        correlation_id: UUID | None = None,
    ) -> CardMovement:
        movement = CardMovement(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            board_id=board_id,
            card_id=card_id,
            from_column_id=from_column_id,
            to_column_id=to_column_id,
            from_rank=from_rank,
            to_rank=to_rank,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        self._session.add(movement)
        self._session.flush()
        return movement

    def list_page(
        self,
        *,
        workspace_id: UUID,
        card_id: UUID,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[CardMovement]:
        statement = select(CardMovement).where(
            CardMovement.workspace_id == workspace_id,
            CardMovement.card_id == card_id,
        )
        if after is not None:
            occurred_at, after_id = after
            statement = statement.where(
                tuple_(CardMovement.occurred_at, CardMovement.id)
                > tuple_(occurred_at, after_id)
            )
        statement = statement.order_by(
            CardMovement.occurred_at, CardMovement.id
        ).limit(limit)
        return list(self._session.execute(statement).scalars())
