"""Configurable Kanban board, column, card and work-item routes (Issue #8).

The tenant is always derived from the verified principal and the path locator,
never from a request body. Board, column and card mutations require
``board:manage`` (contributor or higher); reads require ``board:read``. Card
creation is deliberately absent: a card exists only as a projection of an
approved ``WorkItem``.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    authenticated_principal,
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Board, BoardCard, BoardColumn, WorkItem
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.board_management import (
    BoardCardService,
    BoardColumnService,
    BoardService,
    WorkItemService,
    board_etag,
    card_etag,
    column_etag,
    work_item_etag,
)

router = APIRouter(tags=["Boards"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
COLUMN_KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,79}$"
WORK_ITEM_STATUS_PATTERN = "^(ready|in_progress|in_review|blocked|done|cancelled)$"
CATEGORY_PATTERN = "^(bug|feature|chore|docs|security)$"
PRIORITY_PATTERN = "^(critical|high|medium|low)$"
RANK_PATTERN = "^[0-9a-zA-Z_-]+$"

_BOARD_ROLES = ["contributor", "admin", "owner"]
_READ_ROLES = ["contributor", "triager", "approver", "admin", "owner", "viewer"]


class BoardColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=COLUMN_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    mapped_status: str = Field(pattern=WORK_ITEM_STATUS_PATTERN)
    wip_limit: int | None = Field(default=None, ge=1)


class CreateBoardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str = Field(min_length=1, max_length=120)
    columns: list[BoardColumnInput] | None = Field(default=None, max_length=50)


class UpdateBoardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class CreateBoardColumnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=COLUMN_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    mapped_status: str = Field(pattern=WORK_ITEM_STATUS_PATTERN)
    wip_limit: int | None = Field(default=None, ge=1)
    position: int | None = Field(default=None, ge=0)


class UpdateBoardColumnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    mapped_status: str | None = Field(default=None, pattern=WORK_ITEM_STATUS_PATTERN)
    wip_limit: int | None = Field(default=None, ge=1)
    position: int | None = Field(default=None, ge=0)


class MoveBoardCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_column_id: str = Field(min_length=1, max_length=80)
    target_rank: str = Field(min_length=1, max_length=64, pattern=RANK_PATTERN)


def _authorize(
    session: Session,
    principal: AuthenticatedPrincipal,
    workspace_id: UUID,
    action: Action,
):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


def _idempotency_key(request: Request) -> str | None:
    supplied = request.headers.get("idempotency-key")
    if supplied is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.match(supplied):
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is malformed.",
            title="Invalid request",
        )
    return supplied


def _collection_etag(workspace_id: UUID, parts: list[str], *extra: object) -> str:
    return '"' + fingerprint([str(workspace_id), parts, *extra]) + '"'


def _board_payload(board: Board, column_keys: list[str]) -> dict:
    return {
        "board_id": board.id,
        "workspace_id": board.workspace_id,
        "project_id": board.project_id,
        "name": board.name,
        "columns": column_keys,
        "version": board.version,
        "archived_at": board.archived_at,
        "created_at": board.created_at,
        "updated_at": board.updated_at,
    }


def _board_column_keys(outcome) -> list[str]:  # noqa: ANN001 - service outcome
    keys = [column.key for column in outcome.columns]
    return keys or list(outcome.board.columns or [])


def _column_payload(column: BoardColumn) -> dict:
    return {
        "column_id": column.id,
        "workspace_id": column.workspace_id,
        "project_id": column.project_id,
        "board_id": column.board_id,
        "key": column.key,
        "name": column.name,
        "position": column.position,
        "mapped_status": column.mapped_status,
        "wip_limit": column.wip_limit,
        "created_at": column.created_at,
        "updated_at": column.updated_at,
    }


def _card_payload(card: BoardCard) -> dict:
    return {
        "card_id": card.id,
        "workspace_id": card.workspace_id,
        "board_id": card.board_id,
        "column_id": card.column_id,
        "work_item_id": card.work_item_id,
        "rank": card.rank,
        "title": card.title,
        "priority": card.priority,
        "category": card.category,
        "assignee_id": card.assignee_id,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


def _movement_payload(movement) -> dict:  # noqa: ANN001 - ORM entity
    return {
        "movement_id": movement.id,
        "workspace_id": movement.workspace_id,
        "project_id": movement.project_id,
        "board_id": movement.board_id,
        "card_id": movement.card_id,
        "from_column_id": movement.from_column_id,
        "to_column_id": movement.to_column_id,
        "from_rank": movement.from_rank,
        "to_rank": movement.to_rank,
        "from_status": movement.from_status,
        "to_status": movement.to_status,
        "actor_id": movement.actor_id,
        "correlation_id": movement.correlation_id,
        "occurred_at": movement.occurred_at,
        "created_at": movement.created_at,
    }


def _work_item_payload(work_item: WorkItem) -> dict:
    return {
        "work_item_id": work_item.id,
        "workspace_id": work_item.workspace_id,
        "project_id": work_item.project_id,
        "origin_proposal_id": work_item.origin_proposal_id,
        "origin_proposal_version": work_item.origin_proposal_version,
        "origin_approval_id": work_item.origin_approval_id,
        "title": work_item.title,
        "description": work_item.description,
        "acceptance_criteria": work_item.acceptance_criteria,
        "category": work_item.category,
        "priority": work_item.priority,
        "status": work_item.status,
        "assignee_id": work_item.assignee_id,
        "external_issue_links": work_item.external_issue_links,
        "created_at": work_item.created_at,
        "updated_at": work_item.updated_at,
    }


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@router.post("/v1/workspaces/{workspace_id}/boards", status_code=201)
def create_board(
    workspace_id: UUID,
    payload: CreateBoardRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    outcome = BoardService(session).create(
        context,
        project_id=payload.project_id,
        name=payload.name,
        columns=[item.model_dump() for item in payload.columns]
        if payload.columns is not None
        else None,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = board_etag(outcome.board)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/boards/{outcome.board.id}"
    )
    return _board_payload(outcome.board, _board_column_keys(outcome))


@router.get("/v1/workspaces/{workspace_id}/boards")
def list_boards(
    workspace_id: UUID,
    response: Response,
    project_id: UUID | None = Query(default=None),
    include_archived: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    boards = BoardService(session).list_boards(
        context, project_id=project_id, include_archived=include_archived
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [str(board.id) + board.updated_at.isoformat() for board in boards],
    )
    return [
        _board_payload(board, list(board.columns or [])) for board in boards
    ]


@router.get("/v1/workspaces/{workspace_id}/boards/{board_id}")
def get_board(
    workspace_id: UUID,
    board_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    outcome = BoardService(session).get(context, board_id)
    response.headers["ETag"] = board_etag(outcome.board)
    return _board_payload(
        outcome.board, _board_column_keys(outcome)
    )


@router.patch("/v1/workspaces/{workspace_id}/boards/{board_id}")
def update_board(
    workspace_id: UUID,
    board_id: UUID,
    payload: UpdateBoardRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    outcome = BoardService(session).update(
        context,
        board_id,
        name=payload.name,
        archived=payload.archived,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = board_etag(outcome.board)
    return _board_payload(outcome.board, _board_column_keys(outcome))


# ---------------------------------------------------------------------------
# Board columns
# ---------------------------------------------------------------------------


@router.post(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/columns", status_code=201
)
def create_board_column(
    workspace_id: UUID,
    board_id: UUID,
    payload: CreateBoardColumnRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    outcome = BoardColumnService(session).create(
        context,
        board_id,
        key=payload.key,
        name=payload.name,
        mapped_status=payload.mapped_status,
        wip_limit=payload.wip_limit,
        position=payload.position,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = column_etag(outcome.column)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/boards/{board_id}"
        f"/columns/{outcome.column.id}"
    )
    return _column_payload(outcome.column)


@router.get("/v1/workspaces/{workspace_id}/boards/{board_id}/columns")
def list_board_columns(
    workspace_id: UUID,
    board_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    columns = BoardColumnService(session).list_columns(context, board_id)
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{column.id}{column.position}{column.updated_at.isoformat()}" for column in columns],
    )
    return [_column_payload(column) for column in columns]


@router.patch(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/columns/{column_id}"
)
def update_board_column(
    workspace_id: UUID,
    board_id: UUID,
    column_id: UUID,
    payload: UpdateBoardColumnRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    outcome = BoardColumnService(session).update(
        context,
        board_id,
        column_id,
        name=payload.name,
        mapped_status=payload.mapped_status,
        wip_limit=payload.wip_limit,
        position=payload.position,
        clear_wip_limit="wip_limit" in payload.model_fields_set
        and payload.wip_limit is None,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = column_etag(outcome.column)
    return _column_payload(outcome.column)


@router.delete(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/columns/{column_id}",
    status_code=204,
)
def delete_board_column(
    workspace_id: UUID,
    board_id: UUID,
    column_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    BoardColumnService(session).delete(
        context,
        board_id,
        column_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.status_code = 204
    return response


# ---------------------------------------------------------------------------
# Board cards
# ---------------------------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/boards/{board_id}/cards")
def list_board_cards(
    workspace_id: UUID,
    board_id: UUID,
    response: Response,
    column_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    page, next_cursor = BoardCardService(session).list_cards(
        context,
        board_id,
        column_id=column_id,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{card.id}{card.rank}{card.updated_at.isoformat()}" for card in page],
        next_cursor,
    )
    return {
        "items": [_card_payload(card) for card in page],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


@router.get(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}"
)
def get_board_card(
    workspace_id: UUID,
    board_id: UUID,
    card_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    card = BoardCardService(session).get(context, board_id, card_id)
    response.headers["ETag"] = card_etag(card)
    return _card_payload(card)


@router.patch(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}"
)
def move_board_card(
    workspace_id: UUID,
    board_id: UUID,
    card_id: UUID,
    payload: MoveBoardCardRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_MANAGE)
    outcome = BoardCardService(session).move(
        context,
        board_id,
        card_id,
        target_column_id=payload.target_column_id,
        target_rank=payload.target_rank,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = card_etag(outcome.card)
    return _card_payload(outcome.card)


@router.get(
    "/v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}/movements"
)
def list_card_movements(
    workspace_id: UUID,
    board_id: UUID,
    card_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.BOARD_READ)
    movements, next_cursor, _ = BoardCardService(session).list_movements(
        context, board_id, card_id, limit=limit, cursor=cursor, sort=sort
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{movement.id}{movement.occurred_at.isoformat()}" for movement in movements],
        next_cursor,
    )
    return {
        "items": [_movement_payload(movement) for movement in movements],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


# ---------------------------------------------------------------------------
# Work items
# ---------------------------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/work-items")
def list_work_items(
    workspace_id: UUID,
    response: Response,
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, pattern=WORK_ITEM_STATUS_PATTERN),
    category: str | None = Query(default=None, pattern=CATEGORY_PATTERN),
    priority: str | None = Query(default=None, pattern=PRIORITY_PATTERN),
    assignee_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.WORK_ITEM_READ)
    items, next_cursor = WorkItemService(session).list_page(
        context,
        project_id=project_id,
        status=status,
        category=category,
        priority=priority,
        assignee_id=assignee_id,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.status}{item.updated_at.isoformat()}" for item in items],
        next_cursor,
    )
    return {
        "items": [_work_item_payload(item) for item in items],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


@router.get("/v1/workspaces/{workspace_id}/work-items/{work_item_id}")
def get_work_item(
    workspace_id: UUID,
    work_item_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.WORK_ITEM_READ)
    work_item = WorkItemService(session).get(context, work_item_id)
    response.headers["ETag"] = work_item_etag(work_item)
    return _work_item_payload(work_item)
