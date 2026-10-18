"""Approval decision routes (Issue #7).

A role-authorized reviewer approves, rejects, or returns a proposal for
revision. An approval atomically generates the ``WorkItem`` and its initial
``BoardCard``; a rejection or change request only records the decision. The
``Idempotency-Key`` header is mandatory so a retried decision replays its
original result instead of duplicating downstream work.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.models import Approval, BoardCard, WorkItem
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.approval import ApprovalService

router = APIRouter(tags=["Approvals"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
DECISION_PATTERN = "^(approved|rejected|changes_requested)$"


class DecideProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_version: int = Field(ge=1)
    decision: str = Field(pattern=DECISION_PATTERN)
    decision_justification: str = Field(min_length=3)
    target_board_id: UUID | None = None


def _authorize(
    session: Session,
    principal: AuthenticatedPrincipal,
    workspace_id: UUID,
    action: Action,
):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


def _require_idempotency_key(request: Request) -> str:
    supplied = request.headers.get("idempotency-key")
    if supplied is None:
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is required.",
            title="Invalid request",
        )
    if not IDEMPOTENCY_KEY_PATTERN.match(supplied):
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is malformed.",
            title="Invalid request",
        )
    return supplied


def _approval_payload(approval: Approval) -> dict:
    return {
        "approval_id": approval.id,
        "proposal_id": approval.proposal_id,
        "proposal_version": approval.proposal_version,
        "workspace_id": approval.workspace_id,
        "decider_id": approval.decider_id,
        "decision": approval.decision,
        "decision_justification": approval.decision_justification,
        "idempotency_key": approval.idempotency_key,
        "decided_at": approval.decided_at,
        "audit_snapshot_hash": approval.audit_snapshot_hash,
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


def _board_card_payload(board_card: BoardCard) -> dict:
    return {
        "card_id": board_card.id,
        "workspace_id": board_card.workspace_id,
        "board_id": board_card.board_id,
        "column_id": board_card.column_id,
        "work_item_id": board_card.work_item_id,
        "rank": board_card.rank,
        "title": board_card.title,
        "priority": board_card.priority,
        "category": board_card.category,
        "assignee_id": board_card.assignee_id,
        "created_at": board_card.created_at,
        "updated_at": board_card.updated_at,
    }


@router.post(
    "/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide"
)
def decide_proposal(
    workspace_id: UUID,
    proposal_id: UUID,
    payload: DecideProposalRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.APPROVAL_DECIDE)
    outcome = ApprovalService(session).decide(
        context,
        proposal_id,
        decision=payload.decision,
        proposal_version=payload.proposal_version,
        justification=payload.decision_justification,
        target_board_id=payload.target_board_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_require_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = outcome.etag
    body: dict = {"approval": _approval_payload(outcome.approval)}
    if outcome.work_item is not None:
        body["work_item"] = _work_item_payload(outcome.work_item)
    if outcome.board_card is not None:
        body["board_card"] = _board_card_payload(outcome.board_card)
    return body
