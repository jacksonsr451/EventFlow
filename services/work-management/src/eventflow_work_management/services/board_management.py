"""Configurable Kanban board, column and card service (Issue #8).

This service owns the persistent, concurrency-safe Kanban subsystem:

* boards and their independently managed column definitions (stable ``key``,
  ordered ``position``, canonical ``mapped_status`` and optional ``wip_limit``);
* server-authoritative, deterministic card ordering;
* card moves with lifecycle transitions, WIP enforcement, movement history and
  optimistic concurrency;
* WorkItem reads.

Every mutation is a single unit of work: it authorizes through the resolved
``AuthorizationContext`` (route layer), validates, changes rows under the
necessary row locks, appends an audit record (and a movement record for moves),
optionally records an idempotent response, and commits once. No BoardCard or
WorkItem is ever created here: cards remain a projection of approved work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Board, BoardCard, BoardColumn, WorkItem
from eventflow_work_management.models.enums import (
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
    WORK_ITEM_STATUS_VALUES,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.board_column_repository import (
    BoardColumnRepository,
    CardMovementRepository,
)
from eventflow_work_management.repositories.board_repository import (
    BoardCardRepository,
    BoardRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.work_item_repository import (
    WorkItemRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.board_ranking import (
    RankSpaceExhausted,
    rank_for_position,
)
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)
from eventflow_work_management.services.work_item_transitions import (
    is_valid_transition,
)

BOARD_CREATE_OPERATION = "board.create"
BOARD_UPDATE_OPERATION = "board.update"
COLUMN_CREATE_OPERATION = "board_column.create"
COLUMN_UPDATE_OPERATION = "board_column.update"
COLUMN_DELETE_OPERATION = "board_column.delete"
CARD_MOVE_OPERATION = "board_card.move"

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

BOARD_SORT_COLUMNS = {"created_at", "updated_at", "name"}
CARD_SORT_COLUMNS = {"rank", "created_at", "updated_at", "priority"}
WORK_ITEM_SORT_COLUMNS = {"created_at", "updated_at", "priority", "status"}

DEFAULT_COLUMNS: tuple[dict, ...] = (
    {"key": "ready", "name": "Ready", "mapped_status": "ready"},
    {"key": "in_progress", "name": "In Progress", "mapped_status": "in_progress"},
    {"key": "in_review", "name": "In Review", "mapped_status": "in_review"},
    {"key": "done", "name": "Done", "mapped_status": "done"},
)

_NOT_FOUND = "The requested resource was not found."


def _now() -> datetime:
    return datetime.now(UTC)


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _conflict(detail: str, *, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def _idempotency_conflict() -> ProblemError:
    return ProblemError(
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        detail="The idempotency key was reused with a different request.",
        title="Conflict",
    )


def board_etag(board: Board) -> str:
    return (
        '"'
        + fingerprint(
            ["board", str(board.id), board.version, board.updated_at.isoformat()]
        )
        + '"'
    )


def column_etag(column: BoardColumn) -> str:
    return (
        '"'
        + fingerprint(
            [
                "board-column",
                str(column.id),
                column.key,
                column.position,
                column.mapped_status,
                column.wip_limit,
                column.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def card_etag(card: BoardCard) -> str:
    return (
        '"'
        + fingerprint(
            ["board-card", str(card.id), card.column_id, card.rank, card.updated_at.isoformat()]
        )
        + '"'
    )


def work_item_etag(work_item: WorkItem) -> str:
    return (
        '"'
        + fingerprint(
            ["work-item", str(work_item.id), work_item.status, work_item.updated_at.isoformat()]
        )
        + '"'
    )


@dataclass(frozen=True)
class BoardOutcome:
    board: Board
    columns: list[BoardColumn]
    replayed: bool = False


@dataclass(frozen=True)
class ColumnOutcome:
    column: BoardColumn
    replayed: bool = False


@dataclass(frozen=True)
class CardMoveOutcome:
    card: BoardCard
    work_item: WorkItem
    movement_id: UUID
    replayed: bool = False


def _parse_sort(
    sort: str | None, allowed: frozenset[str], default_key: str
) -> tuple[str, bool]:
    if not sort:
        return default_key, False
    token = sort.split(",", 1)[0].strip()
    if not token:
        raise _validation("The sort parameter is invalid.")
    descending = token.startswith("-")
    key = token[1:] if descending else token
    if key not in allowed:
        raise _validation("The sort parameter is invalid.")
    return key, descending


def _page_cursor(cursor: str) -> dict[str, object]:
    try:
        return decode_cursor(cursor)
    except CursorError as exc:
        raise _validation("The pagination cursor is invalid.") from exc


class _BaseService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._boards = BoardRepository(session)
        self._columns = BoardColumnRepository(session)
        self._cards = BoardCardRepository(session)
        self._movements = CardMovementRepository(session)
        self._work_items = WorkItemRepository(session)
        self._projects = ProjectRepository(session)
        self._audit = AuditRepository(session)
        self._idempotency = IdempotencyRepository(session)

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict | None:
        stored = self._idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise _idempotency_conflict()
        return stored.response_body or {}

    def _reserve(
        self,
        context: AuthorizationContext,
        operation: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ):
        if idempotency_key is None:
            return None
        return self._idempotency.reserve(
            workspace_id=context.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def _complete(self, record, status: int, body: dict) -> None:
        self._idempotency.complete(record, response_status=status, response_body=body)


class BoardService(_BaseService):
    """Board creation, listing, reads, updates and archival."""

    def create(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID,
        name: str,
        columns: list[dict] | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> BoardOutcome:
        specs = self._normalize_columns(columns)
        request_fingerprint = fingerprint(
            {
                "operation": BOARD_CREATE_OPERATION,
                "project_id": str(project_id),
                "name": name,
                "columns": specs,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                BOARD_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_board(context, replay)

        self._require_project(context, project_id)
        try:
            record = self._reserve(
                context, BOARD_CREATE_OPERATION, idempotency_key, request_fingerprint
            )
            board = self._boards.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                name=name,
                columns=[],
            )
            created: list[BoardColumn] = []
            for position, spec in enumerate(specs):
                created.append(
                    self._columns.add(
                        workspace_id=context.workspace_id,
                        project_id=project_id,
                        board_id=board.id,
                        key=spec["key"],
                        name=spec["name"],
                        position=position,
                        mapped_status=spec["mapped_status"],
                        wip_limit=spec.get("wip_limit"),
                    )
                )
            self._boards.set_columns(board, columns=[column.key for column in created])
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.created",
                entity_type="board",
                entity_id=board.id,
                actor_id=context.actor_id,
                snapshot={
                    "board_id": str(board.id),
                    "project_id": str(project_id),
                    "name": name,
                    "columns": [column.key for column in created],
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._complete(record, 201, {"board_id": str(board.id)})
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    BOARD_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return self._replay_board(context, replay)
            raise _conflict("A board could not be created.", code="CONFLICT")
        except ProblemError:
            self._session.rollback()
            raise
        return BoardOutcome(board=board, columns=created)

    def get(self, context: AuthorizationContext, board_id: UUID) -> BoardOutcome:
        board = self._boards.get(workspace_id=context.workspace_id, board_id=board_id)
        if board is None:
            raise _not_found()
        columns = self._columns.list_for_board(
            workspace_id=context.workspace_id, board_id=board_id
        )
        return BoardOutcome(board=board, columns=columns)

    def list_boards(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[Board]:
        if project_id is not None:
            self._require_project(context, project_id)
        return self._boards.list_for_project(
            workspace_id=context.workspace_id,
            project_id=project_id,
            include_archived=include_archived,
        )

    def update(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        *,
        name: str | None = None,
        archived: bool | None = None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> BoardOutcome:
        if name is None and archived is None:
            raise _validation("At least one board field must be provided.")
        request_fingerprint = fingerprint(
            {
                "operation": BOARD_UPDATE_OPERATION,
                "board_id": str(board_id),
                "name": name,
                "archived": archived,
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                BOARD_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_board(context, replay)

        try:
            board = self._boards.get_for_update(
                workspace_id=context.workspace_id, board_id=board_id
            )
            if board is None:
                raise _not_found()
            if if_match is not None and if_match != board_etag(board):
                raise _precondition_failed()
            record = self._reserve(
                context, BOARD_UPDATE_OPERATION, idempotency_key, request_fingerprint
            )
            if name is not None:
                board.name = name
            if archived is not None:
                board.archived_at = _now() if archived else None
            board.updated_at = _now()
            self._boards.touch(board)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.updated",
                entity_type="board",
                entity_id=board.id,
                actor_id=context.actor_id,
                snapshot={
                    "board_id": str(board.id),
                    "name": board.name,
                    "archived": board.archived_at is not None,
                    "version": board.version,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._complete(record, 200, {"board_id": str(board.id)})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        columns = self._columns.list_for_board(
            workspace_id=context.workspace_id, board_id=board.id
        )
        return BoardOutcome(board=board, columns=columns)

    # -- internals --------------------------------------------------------

    def _require_project(self, context: AuthorizationContext, project_id: UUID) -> None:
        if (
            self._projects.get(
                workspace_id=context.workspace_id, project_id=project_id
            )
            is None
        ):
            raise _not_found()

    def _normalize_columns(self, columns: list[dict] | None) -> list[dict]:
        raw = list(columns) if columns else [dict(item) for item in DEFAULT_COLUMNS]
        normalized: list[dict] = []
        seen_keys: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise _validation("Each board column must be an object.")
            unexpected = set(item) - {"key", "name", "mapped_status", "wip_limit"}
            if unexpected:
                raise _validation("Unexpected board column field(s).")
            key = item.get("key")
            if not isinstance(key, str) or not (1 <= len(key) <= 80):
                raise _validation("Each board column key must be 1 to 80 characters.")
            name = item.get("name")
            if not isinstance(name, str) or not (1 <= len(name) <= 120):
                raise _validation("Each board column name must be 1 to 120 characters.")
            mapped_status = item.get("mapped_status")
            if mapped_status not in WORK_ITEM_STATUS_VALUES:
                raise _validation("Unknown board column mapped status.")
            wip_limit = item.get("wip_limit")
            if wip_limit is not None and (
                isinstance(wip_limit, bool)
                or not isinstance(wip_limit, int)
                or wip_limit < 1
            ):
                raise _validation("A column WIP limit must be a positive integer.")
            if key in seen_keys:
                raise _validation("Board column keys must be unique.")
            seen_keys.add(key)
            normalized.append(
                {
                    "key": key,
                    "name": name,
                    "mapped_status": mapped_status,
                    "wip_limit": wip_limit,
                }
            )
        return normalized

    def _replay_board(
        self, context: AuthorizationContext, body: dict
    ) -> BoardOutcome:
        board_id = body.get("board_id")
        if board_id is None:
            raise _conflict(
                "The original board response is unavailable.", code="INVALID_STATE"
            )
        board = self._boards.get(
            workspace_id=context.workspace_id, board_id=UUID(str(board_id))
        )
        if board is None:
            raise _not_found()
        columns = self._columns.list_for_board(
            workspace_id=context.workspace_id, board_id=board.id
        )
        return BoardOutcome(board=board, columns=columns, replayed=True)


class BoardColumnService(_BaseService):
    """Independently managed board column definitions."""

    def list_columns(
        self, context: AuthorizationContext, board_id: UUID
    ) -> list[BoardColumn]:
        self._require_board(context, board_id)
        return self._columns.list_for_board(
            workspace_id=context.workspace_id, board_id=board_id
        )

    def create(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        *,
        key: str,
        name: str,
        mapped_status: str,
        wip_limit: int | None = None,
        position: int | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ColumnOutcome:
        self._validate_key(key)
        self._validate_name(name)
        if mapped_status not in WORK_ITEM_STATUS_VALUES:
            raise _validation("Unknown column mapped status.")
        if wip_limit is not None and (isinstance(wip_limit, bool) or wip_limit < 1):
            raise _validation("A column WIP limit must be a positive integer.")
        request_fingerprint = fingerprint(
            {
                "operation": COLUMN_CREATE_OPERATION,
                "board_id": str(board_id),
                "key": key,
                "name": name,
                "mapped_status": mapped_status,
                "wip_limit": wip_limit,
                "position": position,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                COLUMN_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_column(context, replay)

        try:
            board = self._require_board(context, board_id, for_update=True)
            record = self._reserve(
                context, COLUMN_CREATE_OPERATION, idempotency_key, request_fingerprint
            )
            if self._columns.get_by_key(board_id=board_id, key=key) is not None:
                raise _conflict("A column with this key already exists.", code="DUPLICATE_KEY")
            existing = self._columns.list_for_board(
                workspace_id=context.workspace_id, board_id=board_id
            )
            if position is None:
                position = len(existing)
            if not 0 <= position <= len(existing):
                raise _validation("The column position is out of range.")
            for column in existing:
                if column.position >= position:
                    self._columns.set_position(column, position=column.position + 1)
            created = self._columns.add(
                workspace_id=context.workspace_id,
                project_id=board.project_id,
                board_id=board_id,
                key=key,
                name=name,
                position=position,
                mapped_status=mapped_status,
                wip_limit=wip_limit,
            )
            self._sync_columns(context, board)
            self._touch(context, board)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.column.created",
                entity_type="board_column",
                entity_id=created.id,
                actor_id=context.actor_id,
                snapshot={
                    "board_id": str(board_id),
                    "column_id": str(created.id),
                    "key": created.key,
                    "position": created.position,
                    "mapped_status": created.mapped_status,
                    "wip_limit": created.wip_limit,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._complete(record, 201, {"column_id": str(created.id)})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return ColumnOutcome(column=created)

    def update(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        column_id: UUID,
        *,
        name: str | None = None,
        mapped_status: str | None = None,
        wip_limit: int | None = None,
        position: int | None = None,
        clear_wip_limit: bool = False,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ColumnOutcome:
        if (
            name is None
            and mapped_status is None
            and wip_limit is None
            and position is None
            and not clear_wip_limit
        ):
            raise _validation("At least one column field must be provided.")
        if mapped_status is not None and mapped_status not in WORK_ITEM_STATUS_VALUES:
            raise _validation("Unknown column mapped status.")
        if wip_limit is not None and (isinstance(wip_limit, bool) or wip_limit < 1):
            raise _validation("A column WIP limit must be a positive integer.")
        request_fingerprint = fingerprint(
            {
                "operation": COLUMN_UPDATE_OPERATION,
                "board_id": str(board_id),
                "column_id": str(column_id),
                "name": name,
                "mapped_status": mapped_status,
                "wip_limit": wip_limit,
                "clear_wip_limit": clear_wip_limit,
                "position": position,
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                COLUMN_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_column(context, replay)

        try:
            board = self._require_board(context, board_id, for_update=True)
            column = self._columns.get_for_update(
                workspace_id=context.workspace_id, column_id=column_id
            )
            if column is None or column.board_id != board_id:
                raise _not_found()
            if if_match is not None and if_match != column_etag(column):
                raise _precondition_failed()
            record = self._reserve(
                context, COLUMN_UPDATE_OPERATION, idempotency_key, request_fingerprint
            )
            if name is not None:
                self._validate_name(name)
                column.name = name
            if mapped_status is not None:
                column.mapped_status = mapped_status
            if clear_wip_limit:
                column.wip_limit = None
            elif wip_limit is not None:
                column.wip_limit = wip_limit
            if position is not None:
                self._reposition(context, board, column, position)
            column.updated_at = _now()
            self._sync_columns(context, board)
            self._touch(context, board)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.column.updated",
                entity_type="board_column",
                entity_id=column.id,
                actor_id=context.actor_id,
                snapshot={
                    "board_id": str(board_id),
                    "column_id": str(column.id),
                    "key": column.key,
                    "position": column.position,
                    "mapped_status": column.mapped_status,
                    "wip_limit": column.wip_limit,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._complete(record, 200, {"column_id": str(column.id)})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return ColumnOutcome(column=column)

    def delete(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        column_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        request_fingerprint = fingerprint(
            {
                "operation": COLUMN_DELETE_OPERATION,
                "board_id": str(board_id),
                "column_id": str(column_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                COLUMN_DELETE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return
        try:
            board = self._require_board(context, board_id, for_update=True)
            column = self._columns.get_for_update(
                workspace_id=context.workspace_id, column_id=column_id
            )
            if column is None or column.board_id != board_id:
                raise _not_found()
            if if_match is not None and if_match != column_etag(column):
                raise _precondition_failed()
            if self._columns.count_for_board(board_id=board_id) <= 1:
                raise _conflict(
                    "A board must keep at least one column.", code="LAST_COLUMN"
                )
            if self._cards.count_in_column(board_id=board_id, column_id=column.key) > 0:
                raise _conflict(
                    "A column that still holds cards cannot be removed.",
                    code="COLUMN_NOT_EMPTY",
                )
            record = self._reserve(
                context, COLUMN_DELETE_OPERATION, idempotency_key, request_fingerprint
            )
            self._columns.delete(column)
            remaining = self._columns.list_for_board(
                workspace_id=context.workspace_id, board_id=board_id
            )
            for position, item in enumerate(remaining):
                self._columns.set_position(item, position=position)
            self._sync_columns(context, board)
            self._touch(context, board)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.column.deleted",
                entity_type="board_column",
                entity_id=column_id,
                actor_id=context.actor_id,
                snapshot={"board_id": str(board_id), "column_id": str(column_id)},
                correlation_id=correlation_id,
            )
            if record is not None:
                self._complete(record, 204, {})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise

    # -- internals --------------------------------------------------------

    def _require_board(
        self, context: AuthorizationContext, board_id: UUID, *, for_update: bool = False
    ) -> Board:
        board = (
            self._boards.get_for_update(
                workspace_id=context.workspace_id, board_id=board_id
            )
            if for_update
            else self._boards.get(workspace_id=context.workspace_id, board_id=board_id)
        )
        if board is None:
            raise _not_found()
        return board

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not re.match(r"^[a-z0-9][a-z0-9_-]{0,79}$", key):
            raise _validation("A column key must be a lowercase slug up to 80 characters.")

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            raise _validation("A column name must be 1 to 120 characters.")

    def _reposition(
        self,
        context: AuthorizationContext,
        board: Board,
        column: BoardColumn,
        position: int,
    ) -> None:
        ordered = [
            item
            for item in self._columns.list_for_board(
                workspace_id=context.workspace_id, board_id=board.id
            )
            if item.id != column.id
        ]
        if not 0 <= position <= len(ordered):
            raise _validation("The column position is out of range.")
        ordered.insert(position, column)
        for index, item in enumerate(ordered):
            self._columns.set_position(item, position=index)

    def _sync_columns(self, context: AuthorizationContext, board: Board) -> None:
        ordered = self._columns.list_for_board(
            workspace_id=context.workspace_id, board_id=board.id
        )
        self._boards.set_columns(board, columns=[item.key for item in ordered])

    def _touch(self, context: AuthorizationContext, board: Board) -> None:
        board.updated_at = _now()
        self._boards.touch(board)

    def _replay_column(
        self, context: AuthorizationContext, body: dict
    ) -> ColumnOutcome:
        column_id = body.get("column_id")
        if column_id is None:
            raise _conflict(
                "The original column response is unavailable.", code="INVALID_STATE"
            )
        column = self._columns.get(
            workspace_id=context.workspace_id, column_id=UUID(str(column_id))
        )
        if column is None:
            raise _not_found()
        return ColumnOutcome(column=column, replayed=True)


class BoardCardService(_BaseService):
    """Board card reads and concurrency-safe moves."""

    def get(
        self, context: AuthorizationContext, board_id: UUID, card_id: UUID
    ) -> BoardCard:
        card = self._cards.get(workspace_id=context.workspace_id, card_id=card_id)
        if card is None or card.board_id != board_id:
            raise _not_found()
        return card

    def list_cards(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        *,
        column_id: str | None = None,
        sort: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[BoardCard], str | None]:
        if (
            self._boards.get(workspace_id=context.workspace_id, board_id=board_id)
            is None
        ):
            raise _not_found()
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        sort_key, descending = _parse_sort(
            sort, frozenset(CARD_SORT_COLUMNS), "rank"
        )
        after = None
        if cursor is not None:
            payload = _page_cursor(cursor)
            after = (payload.get(sort_key), payload.get("id"))
            if after[1] is None:
                raise _validation("The pagination cursor is invalid.")
        rows = self._cards.list_page(
            workspace_id=context.workspace_id,
            board_id=board_id,
            column_id=column_id,
            sort_key=sort_key,
            descending=descending,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor({sort_key: getattr(last, sort_key)}, last.id)
        return page, next_cursor

    def list_movements(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        card_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        sort: str | None = None,
    ) -> tuple[list, str | None, BoardCard]:
        card = self.get(context, board_id, card_id)
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        if sort is not None:
            _parse_sort(sort, frozenset({"occurred_at"}), "occurred_at")
        after = None
        if cursor is not None:
            payload = _page_cursor(cursor)
            after = (payload.get("occurred_at"), payload.get("id"))
            if not isinstance(after[0], datetime) or not isinstance(after[1], UUID):
                raise _validation("The pagination cursor is invalid.")
        rows = self._movements.list_page(
            workspace_id=context.workspace_id,
            card_id=card_id,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor({"occurred_at": last.occurred_at}, last.id)
        return page, next_cursor, card

    def move(
        self,
        context: AuthorizationContext,
        board_id: UUID,
        card_id: UUID,
        *,
        target_column_id: str,
        target_rank: str,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> CardMoveOutcome:
        if not isinstance(target_column_id, str) or not 1 <= len(target_column_id) <= 80:
            raise _validation("target_column_id must be 1 to 80 characters.")
        if not isinstance(target_rank, str) or not 1 <= len(target_rank) <= 64:
            raise _validation("target_rank must be 1 to 64 characters.")
        request_fingerprint = fingerprint(
            {
                "operation": CARD_MOVE_OPERATION,
                "board_id": str(board_id),
                "card_id": str(card_id),
                "target_column_id": target_column_id,
                "target_rank": target_rank,
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                CARD_MOVE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_move(context, replay)

        try:
            board = self._boards.get_for_update(
                workspace_id=context.workspace_id, board_id=board_id
            )
            if board is None:
                raise _not_found()
            card = self._cards.get_for_update(
                workspace_id=context.workspace_id, card_id=card_id
            )
            if card is None or card.board_id != board_id:
                raise _not_found()
            if if_match is not None and if_match != card_etag(card):
                raise _precondition_failed()
            target = self._columns.get_by_key_for_update(
                board_id=board_id, key=target_column_id
            )
            if target is None:
                raise _conflict(
                    "The destination column is not defined by the board.",
                    code="UNKNOWN_COLUMN",
                )
            work_item = self._work_items.get_for_update(
                workspace_id=context.workspace_id, work_item_id=card.work_item_id
            )
            if work_item is None:
                raise _not_found()
            source_key = card.column_id
            source_status = self._resolve_status(board_id, source_key, work_item.status)
            if not is_valid_transition(source_status, target.mapped_status):
                raise _conflict(
                    f"The WorkItem cannot move from {source_status} to "
                    f"{target.mapped_status}.",
                    code="INVALID_TRANSITION",
                )
            if (
                target.wip_limit is not None
                and card.column_id != target_column_id
                and self._cards.count_in_column(
                    board_id=board_id, column_id=target_column_id
                )
                >= target.wip_limit
            ):
                raise _conflict(
                    "The destination column has reached its WIP limit.",
                    code="WIP_LIMIT_EXCEEDED",
                )
            record = self._reserve(
                context, CARD_MOVE_OPERATION, idempotency_key, request_fingerprint
            )
            siblings = self._cards.list_ranks_in_column(
                board_id=board_id,
                column_id=target_column_id,
                exclude_card_id=card.id,
            )
            try:
                new_rank = rank_for_position(siblings, target_rank)
            except RankSpaceExhausted as exc:
                raise _conflict(
                    "The board column is full; reorder the column before inserting.",
                    code="RANK_SPACE_EXHAUSTED",
                ) from exc
            occurred_at = _now()
            from_column_id = card.column_id
            from_rank = card.rank
            from_status = source_status
            self._cards.apply_move(card, column_id=target_column_id, rank=new_rank)
            card.updated_at = occurred_at
            if work_item.status != target.mapped_status:
                self._work_items.set_status(work_item, status=target.mapped_status)
                work_item.updated_at = occurred_at
            movement = self._movements.append(
                workspace_id=context.workspace_id,
                project_id=board.project_id,
                board_id=board_id,
                card_id=card.id,
                from_column_id=from_column_id,
                to_column_id=target_column_id,
                from_rank=from_rank,
                to_rank=new_rank,
                from_status=from_status,
                to_status=target.mapped_status,
                actor_id=context.actor_id,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
            self._audit.append(
                workspace_id=context.workspace_id,
                action="board.card.moved",
                entity_type="board_card",
                entity_id=card.id,
                actor_id=context.actor_id,
                snapshot={
                    "board_id": str(board_id),
                    "card_id": str(card.id),
                    "from_column_id": from_column_id,
                    "to_column_id": target_column_id,
                    "from_status": from_status,
                    "to_status": target.mapped_status,
                },
                correlation_id=correlation_id,
                occurred_at=occurred_at,
            )
            if record is not None:
                self._complete(record, 200, {"card_id": str(card.id)})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return CardMoveOutcome(
            card=card, work_item=work_item, movement_id=movement.id
        )

    # -- internals --------------------------------------------------------

    def _resolve_status(
        self, board_id: UUID, column_key: str, fallback: str
    ) -> str:
        column = self._columns.get_by_key(board_id=board_id, key=column_key)
        if column is not None:
            return column.mapped_status
        if column_key in WORK_ITEM_STATUS_VALUES:
            return column_key
        return fallback

    def _replay_move(
        self, context: AuthorizationContext, body: dict
    ) -> CardMoveOutcome:
        card_id = body.get("card_id")
        if card_id is None:
            raise _conflict(
                "The original card response is unavailable.", code="INVALID_STATE"
            )
        card = self._cards.get(
            workspace_id=context.workspace_id, card_id=UUID(str(card_id))
        )
        if card is None:
            raise _not_found()
        work_item = self._work_items.get(
            workspace_id=context.workspace_id, work_item_id=card.work_item_id
        )
        if work_item is None:
            raise _not_found()
        return CardMoveOutcome(
            card=card, work_item=work_item, movement_id=card.id, replayed=True
        )


class WorkItemService(_BaseService):
    """WorkItem reads (Issue #8 exposes list and detail)."""

    def get(self, context: AuthorizationContext, work_item_id: UUID) -> WorkItem:
        work_item = self._work_items.get(
            workspace_id=context.workspace_id, work_item_id=work_item_id
        )
        if work_item is None:
            raise _not_found()
        return work_item

    def list_page(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID | None = None,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assignee_id: UUID | None = None,
        sort: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[WorkItem], str | None]:
        if status is not None and status not in WORK_ITEM_STATUS_VALUES:
            raise _validation("Unknown work item status filter.")
        if category is not None and category not in TRIAGE_CATEGORY_VALUES:
            raise _validation("Unknown work item category filter.")
        if priority is not None and priority not in PRIORITY_VALUES:
            raise _validation("Unknown work item priority filter.")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        sort_key, descending = _parse_sort(
            sort, frozenset(WORK_ITEM_SORT_COLUMNS), "created_at"
        )
        after = None
        if cursor is not None:
            payload = _page_cursor(cursor)
            after = (payload.get(sort_key), payload.get("id"))
            if after[1] is None:
                raise _validation("The pagination cursor is invalid.")
        rows = self._work_items.list_page(
            workspace_id=context.workspace_id,
            project_id=project_id,
            status=status,
            category=category,
            priority=priority,
            assignee_id=assignee_id,
            sort_key=sort_key,
            descending=descending,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor({sort_key: getattr(last, sort_key)}, last.id)
        return page, next_cursor
