"""Consultation task proposal routes (Issue #6).

The tenant and actor are derived from the verified principal and the path
locator, never from the request body. A triaged consultation may yield zero,
one, or many independent proposals; these routes let a caller preview, draft,
edit, submit, list, duplicate, and read the revision history of a proposal.
None of them creates an Approval, WorkItem, BoardCard, or remote issue.
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
from eventflow_work_management.models import Proposal, ProposalRevision
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.proposal import ProposalService, proposal_etag

router = APIRouter(tags=["Proposals"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
CATEGORY_PATTERN = "^(bug|feature|chore|docs|security)$"
PRIORITY_PATTERN = "^(critical|high|medium|low)$"


class ChecklistItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID | None = None
    text: str = Field(min_length=1, max_length=200)
    done: bool = False


class CreateProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consultation_id: UUID
    title: str = Field(min_length=5, max_length=200)
    technical_description: str = Field(min_length=10)
    scope: str = Field(min_length=5)
    justification: str = Field(min_length=5)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=50)
    category: str = Field(pattern=CATEGORY_PATTERN)
    priority: str = Field(pattern=PRIORITY_PATTERN)
    checklist: list[ChecklistItemRequest] | None = Field(default=None, max_length=100)
    risks: list[str] | None = Field(default=None, max_length=50)
    dependencies: list[str] | None = Field(default=None, max_length=50)
    evidence_ids: list[UUID] | None = Field(default=None, max_length=50)
    estimated_hours: float | None = Field(default=None, ge=0.5, le=9999.99)


class UpdateProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=5, max_length=200)
    technical_description: str | None = Field(default=None, min_length=10)
    scope: str | None = Field(default=None, min_length=5)
    justification: str | None = Field(default=None, min_length=5)
    acceptance_criteria: list[str] | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, pattern=CATEGORY_PATTERN)
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    checklist: list[ChecklistItemRequest] | None = Field(default=None, max_length=100)
    risks: list[str] | None = Field(default=None, max_length=50)
    dependencies: list[str] | None = Field(default=None, max_length=50)
    evidence_ids: list[UUID] | None = Field(default=None, max_length=50)
    estimated_hours: float | None = Field(default=None, ge=0.5, le=9999.99)


class DuplicateProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=5, max_length=200)
    supersede_source: bool = False


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


def _proposal_payload(proposal: Proposal, evidence_ids: list[UUID]) -> dict:
    return {
        "proposal_id": proposal.id,
        "consultation_id": proposal.consultation_id,
        "workspace_id": proposal.workspace_id,
        "project_id": proposal.project_id,
        "version": proposal.version,
        "title": proposal.title,
        "technical_description": proposal.technical_description,
        "scope": proposal.scope,
        "justification": proposal.justification,
        "acceptance_criteria": proposal.acceptance_criteria,
        "checklist": proposal.checklist,
        "category": proposal.category,
        "priority": proposal.priority,
        "risks": proposal.risks,
        "dependencies": proposal.dependencies,
        "evidence": evidence_ids,
        "estimated_hours": (
            float(proposal.estimated_hours)
            if proposal.estimated_hours is not None
            else None
        ),
        "status": proposal.status,
        "proposer_id": proposal.proposer_id,
        "reviewer_id": proposal.reviewer_id,
        "duplicated_from_proposal_id": proposal.duplicated_from_proposal_id,
        "superseded_by_proposal_id": proposal.superseded_by_proposal_id,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


def _revision_payload(revision: ProposalRevision) -> dict:
    return {
        "revision_id": revision.id,
        "proposal_id": revision.proposal_id,
        "workspace_id": revision.workspace_id,
        "version": revision.version,
        "author_id": revision.author_id,
        "summary": revision.summary,
        "snapshot": revision.snapshot,
        "created_at": revision.created_at,
    }


def _collection_etag(workspace_id: UUID, parts: list[str], next_cursor: str | None) -> str:
    return '"' + fingerprint([str(workspace_id), parts, next_cursor]) + '"'


@router.post("/v1/workspaces/{workspace_id}/proposals/preview")
def preview_proposal(
    workspace_id: UUID,
    payload: CreateProposalRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_CREATE)
    preview = ProposalService(session).preview(
        context,
        consultation_id=payload.consultation_id,
        title=payload.title,
        technical_description=payload.technical_description,
        scope=payload.scope,
        justification=payload.justification,
        acceptance_criteria=payload.acceptance_criteria,
        category=payload.category,
        priority=payload.priority,
        checklist=[item.model_dump() for item in payload.checklist]
        if payload.checklist is not None
        else None,
        risks=payload.risks,
        dependencies=payload.dependencies,
        evidence_ids=payload.evidence_ids,
        estimated_hours=payload.estimated_hours,
    )
    response.headers["ETag"] = '"' + fingerprint(["proposal-preview", preview]) + '"'
    return preview


@router.post("/v1/workspaces/{workspace_id}/proposals", status_code=201)
def create_proposal(
    workspace_id: UUID,
    payload: CreateProposalRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_CREATE)
    result = ProposalService(session).create(
        context,
        consultation_id=payload.consultation_id,
        title=payload.title,
        technical_description=payload.technical_description,
        scope=payload.scope,
        justification=payload.justification,
        acceptance_criteria=payload.acceptance_criteria,
        category=payload.category,
        priority=payload.priority,
        checklist=[item.model_dump() for item in payload.checklist]
        if payload.checklist is not None
        else None,
        risks=payload.risks,
        dependencies=payload.dependencies,
        evidence_ids=payload.evidence_ids,
        estimated_hours=payload.estimated_hours,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    evidence_ids = ProposalService(session).evidence_ids(context, result.proposal.id)
    response.headers["ETag"] = proposal_etag(result.proposal)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/proposals/{result.proposal.id}"
    )
    return _proposal_payload(result.proposal, evidence_ids)


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/proposals"
)
def list_proposals(
    workspace_id: UUID,
    consultation_id: UUID,
    response: Response,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_READ)
    service = ProposalService(session)
    items, next_cursor = service.list_page(
        context,
        consultation_id,
        status=status,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.version}{item.updated_at.isoformat()}" for item in items],
        next_cursor,
    )
    return {
        "items": [
            _proposal_payload(item, service.evidence_ids(context, item.id))
            for item in items
        ],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


@router.get("/v1/workspaces/{workspace_id}/proposals/{proposal_id}")
def get_proposal(
    workspace_id: UUID,
    proposal_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_READ)
    service = ProposalService(session)
    proposal = service.get(context, proposal_id)
    response.headers["ETag"] = proposal_etag(proposal)
    return _proposal_payload(proposal, service.evidence_ids(context, proposal.id))


@router.get("/v1/workspaces/{workspace_id}/proposals/{proposal_id}/revisions")
def list_proposal_revisions(
    workspace_id: UUID,
    proposal_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_READ)
    revisions, next_cursor = ProposalService(session).list_revisions_page(
        context, proposal_id, limit=limit, cursor=cursor
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.version}" for item in revisions],
        next_cursor,
    )
    return {
        "items": [_revision_payload(item) for item in revisions],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


@router.patch("/v1/workspaces/{workspace_id}/proposals/{proposal_id}")
def update_proposal(
    workspace_id: UUID,
    proposal_id: UUID,
    payload: UpdateProposalRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_UPDATE)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("checklist") is not None:
        changes["checklist"] = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in changes["checklist"]
        ]
    service = ProposalService(session)
    result = service.update(
        context,
        proposal_id,
        changes=changes,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = proposal_etag(result.proposal)
    return _proposal_payload(
        result.proposal, service.evidence_ids(context, result.proposal.id)
    )


@router.post("/v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit")
def submit_proposal_for_review(
    workspace_id: UUID,
    proposal_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_SUBMIT)
    service = ProposalService(session)
    result = service.submit(
        context,
        proposal_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = proposal_etag(result.proposal)
    return _proposal_payload(
        result.proposal, service.evidence_ids(context, result.proposal.id)
    )


@router.post(
    "/v1/workspaces/{workspace_id}/proposals/{proposal_id}/duplicate",
    status_code=201,
)
def duplicate_proposal(
    workspace_id: UUID,
    proposal_id: UUID,
    payload: DuplicateProposalRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROPOSAL_DUPLICATE)
    service = ProposalService(session)
    result = service.duplicate(
        context,
        proposal_id,
        title=payload.title,
        supersede_source=payload.supersede_source,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = proposal_etag(result.proposal)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/proposals/{result.proposal.id}"
    )
    return _proposal_payload(
        result.proposal, service.evidence_ids(context, result.proposal.id)
    )
