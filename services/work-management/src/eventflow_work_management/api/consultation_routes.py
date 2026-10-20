"""Authenticated consultation intake, read, and triage routes (Issue #4).

The tenant and actor are derived from the verified principal and the path
locator, never from the request body. Mutating routes require Origin + CSRF for
cookie-authenticated callers and accept an optional ``Idempotency-Key``;
``triage`` additionally honours a strong ``If-Match`` validator.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union
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
from eventflow_work_management.models import Consultation
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.consultation import (
    ConsultationService,
    consultation_etag,
)
from eventflow_work_management.services.triage_criteria import (
    CRITERIA_FIELD_FOR_CATEGORY,
    BugCriteria,
    ChoreCriteria,
    DocsCriteria,
    FeatureCriteria,
    SecurityCriteria,
    triage_templates,
)

router = APIRouter(tags=["Consultations"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
ORIGIN_PATTERN = "^(web|vscode|desktop|external)$"
PRIORITY_PATTERN = "^(critical|high|medium|low)$"
CATEGORY_PATTERN = "^(bug|feature|chore|docs|security)$"


class CreateConsultationRequest(BaseModel):
    project_id: UUID
    origin: str = Field(pattern=ORIGIN_PATTERN)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5)
    category: str | None = Field(default=None, pattern=CATEGORY_PATTERN)
    editor_context: dict | None = None
    external_references: list[str] | None = None


class UpdateConsultationDraftRequest(BaseModel):
    project_id: UUID | None = None
    origin: str | None = Field(default=None, pattern=ORIGIN_PATTERN)
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=5)
    category: str | None = Field(default=None, pattern=CATEGORY_PATTERN)
    editor_context: dict | None = None
    external_references: list[str] | None = None


class _TriageRequest(BaseModel):
    """Shared fields for every category-specific triage variant."""

    model_config = ConfigDict(extra="forbid")

    priority: str = Field(pattern=PRIORITY_PATTERN)
    triage_notes: str = Field(min_length=5)
    business_impact: str | None = Field(
        default=None, pattern="^(critical|high|moderate|low)$"
    )
    business_urgency: str | None = Field(
        default=None, pattern="^(immediate|elevated|normal|low)$"
    )
    priority_override_reason: str | None = Field(default=None, min_length=10, max_length=300)


class BugTriageRequest(_TriageRequest):
    category: Literal["bug"]
    bug_criteria: BugCriteria


class FeatureTriageRequest(_TriageRequest):
    category: Literal["feature"]
    feature_criteria: FeatureCriteria


class ChoreTriageRequest(_TriageRequest):
    category: Literal["chore"]
    chore_criteria: ChoreCriteria


class DocsTriageRequest(_TriageRequest):
    category: Literal["docs"]
    docs_criteria: DocsCriteria


class SecurityTriageRequest(_TriageRequest):
    category: Literal["security"]
    security_criteria: SecurityCriteria


# The backend discriminated union is authoritative: the ``category`` field
# selects exactly one criteria variant, mirroring the published ``oneOf`` +
# ``discriminator`` contract.
TriageConsultationRequest = Annotated[
    Union[
        BugTriageRequest,
        FeatureTriageRequest,
        ChoreTriageRequest,
        DocsTriageRequest,
        SecurityTriageRequest,
    ],
    Field(discriminator="category"),
]


class ReclassifyConsultationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    justification: str = Field(min_length=10)
    triage: TriageConsultationRequest


def _criteria_for(payload) -> dict:
    """Return the single validated criteria object for a triage variant."""
    field = CRITERIA_FIELD_FOR_CATEGORY[payload.category]
    return getattr(payload, field).model_dump()


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


def _consultation_payload(consultation: Consultation) -> dict:
    return {
        "consultation_id": consultation.id,
        "workspace_id": consultation.workspace_id,
        "project_id": consultation.project_id,
        "author_id": consultation.author_id,
        "assignee_id": consultation.assignee_id,
        "origin": consultation.origin,
        "title": consultation.title,
        "description": consultation.description,
        "category": consultation.category,
        "status": consultation.status,
        "priority": consultation.priority,
        "editor_context": consultation.editor_context,
        "external_references": consultation.external_references,
        "active_proposal_id": consultation.active_proposal_id,
        "created_at": consultation.created_at,
        "updated_at": consultation.updated_at,
    }


@router.post("/v1/workspaces/{workspace_id}/consultations", status_code=201)
def create_consultation(
    workspace_id: UUID,
    payload: CreateConsultationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_CREATE)
    result = ConsultationService(session).submit(
        context,
        project_id=payload.project_id,
        origin=payload.origin,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        editor_context=payload.editor_context,
        external_references=payload.external_references,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/consultations/{result.consultation.id}"
    )
    return _consultation_payload(result.consultation)


@router.post("/v1/workspaces/{workspace_id}/consultations/drafts", status_code=201)
def create_consultation_draft(
    workspace_id: UUID,
    payload: CreateConsultationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_CREATE)
    result = ConsultationService(session).create_draft(
        context,
        project_id=payload.project_id,
        origin=payload.origin,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        editor_context=payload.editor_context,
        external_references=payload.external_references,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/consultations/{result.consultation.id}"
    )
    return _consultation_payload(result.consultation)


@router.get("/v1/workspaces/{workspace_id}/consultations")
def list_consultations(
    workspace_id: UUID,
    response: Response,
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_READ)
    items, next_cursor = ConsultationService(session).list_page(
        context,
        status=status,
        category=category,
        priority=priority,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    response.headers["ETag"] = (
        '"'
        + fingerprint(
            [
                str(workspace_id),
                [f"{item.id}{item.updated_at.isoformat()}" for item in items],
                next_cursor,
            ]
        )
        + '"'
    )
    return {
        "items": [_consultation_payload(item) for item in items],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }


@router.get("/v1/workspaces/{workspace_id}/consultations/triage-templates")
def list_consultation_triage_templates(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    _authorize(session, principal, workspace_id, Action.CONSULTATION_TRIAGE)
    templates = triage_templates()
    response.headers["ETag"] = (
        '"' + fingerprint(["triage-templates", [t["category"] for t in templates]]) + '"'
    )
    return {"templates": templates}


@router.get("/v1/workspaces/{workspace_id}/consultations/{consultation_id}")
def get_consultation(
    workspace_id: UUID,
    consultation_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_READ)
    consultation = ConsultationService(session).get(context, consultation_id)
    response.headers["ETag"] = consultation_etag(consultation)
    return _consultation_payload(consultation)


@router.patch("/v1/workspaces/{workspace_id}/consultations/{consultation_id}")
def update_consultation_draft(
    workspace_id: UUID,
    consultation_id: UUID,
    payload: UpdateConsultationDraftRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_UPDATE)
    result = ConsultationService(session).update_draft(
        context,
        consultation_id,
        changes=payload.model_dump(exclude_unset=True),
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    return _consultation_payload(result.consultation)


@router.post("/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit")
def submit_consultation_draft(
    workspace_id: UUID,
    consultation_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_SUBMIT)
    result = ConsultationService(session).submit_draft(
        context,
        consultation_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    return _consultation_payload(result.consultation)


@router.post("/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage")
def triage_consultation(
    workspace_id: UUID,
    consultation_id: UUID,
    payload: TriageConsultationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_TRIAGE)
    result = ConsultationService(session).triage(
        context,
        consultation_id,
        category=payload.category,
        priority=payload.priority,
        triage_notes=payload.triage_notes,
        criteria=_criteria_for(payload),
        business_impact=payload.business_impact,
        business_urgency=payload.business_urgency,
        priority_override_reason=payload.priority_override_reason,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    return _consultation_payload(result.consultation)


@router.post("/v1/workspaces/{workspace_id}/consultations/{consultation_id}/reclassify")
def reclassify_consultation(
    workspace_id: UUID,
    consultation_id: UUID,
    payload: ReclassifyConsultationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.CONSULTATION_TRIAGE)
    triage = payload.triage
    result = ConsultationService(session).reclassify(
        context,
        consultation_id,
        category=triage.category,
        priority=triage.priority,
        triage_notes=triage.triage_notes,
        criteria=_criteria_for(triage),
        justification=payload.justification,
        business_impact=triage.business_impact,
        business_urgency=triage.business_urgency,
        priority_override_reason=triage.priority_override_reason,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = consultation_etag(result.consultation)
    return _consultation_payload(result.consultation)
