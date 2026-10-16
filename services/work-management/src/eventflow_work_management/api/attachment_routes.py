"""Consultation attachment, evidence, and history routes (Issue #4).

The tenant and actor are derived from the verified principal and the path
locator, never from the request body. Attachment bytes travel as base64 in a JSON
body so the upload reuses the authenticated JSON transport; the service enforces
the size limit and the content-type allowlist on the decoded bytes.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
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
from eventflow_work_management.models import AuditRecord, ConsultationAttachment
from eventflow_work_management.models.evidence import ConsultationEvidence
from eventflow_work_management.security.attachment_scanner import MalwareScanner
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.attachment import (
    AttachmentService,
    attachment_etag,
)
from eventflow_work_management.services.evidence import EvidenceService
from eventflow_work_management.services.history import ConsultationHistoryService

router = APIRouter(tags=["Attachments"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
EVIDENCE_KIND_PATTERN = "^(text|link|attachment)$"


class CreateAttachmentRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=8_388_608)


class CreateEvidenceRequest(BaseModel):
    kind: str = Field(pattern=EVIDENCE_KIND_PATTERN)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=4096)
    attachment_id: UUID | None = None


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


def _scanner(request: Request) -> MalwareScanner:
    return request.app.state.malware_scanner


def _attachment_payload(attachment: ConsultationAttachment) -> dict:
    return {
        "attachment_id": attachment.id,
        "workspace_id": attachment.workspace_id,
        "consultation_id": attachment.consultation_id,
        "file_name": attachment.file_name,
        "content_type": attachment.detected_content_type,
        "size_bytes": attachment.size_bytes,
        "checksum_sha256": attachment.checksum_sha256,
        "status": attachment.status,
        "scan_verdict": attachment.scan_verdict,
        "rejection_reason": attachment.rejection_reason,
        "uploaded_by": attachment.uploaded_by,
        "created_at": attachment.created_at,
    }


def _evidence_payload(evidence: ConsultationEvidence) -> dict:
    return {
        "evidence_id": evidence.id,
        "workspace_id": evidence.workspace_id,
        "consultation_id": evidence.consultation_id,
        "kind": evidence.kind,
        "description": evidence.description,
        "content": evidence.content,
        "attachment_id": evidence.attachment_id,
        "created_by": evidence.created_by,
        "created_at": evidence.created_at,
    }


def _history_payload(record: AuditRecord) -> dict:
    return {
        "audit_id": record.id,
        "workspace_id": record.workspace_id,
        "actor_id": record.actor_id,
        "action": record.action,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "occurred_at": record.occurred_at,
        "snapshot": record.snapshot,
        "snapshot_hash": record.snapshot_hash,
        "correlation_id": record.correlation_id,
    }


def _collection_etag(workspace_id: UUID, parts: list[str], next_cursor: str | None) -> str:
    return '"' + fingerprint([str(workspace_id), parts, next_cursor]) + '"'


@router.post(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/attachments",
    status_code=201,
)
def create_consultation_attachment(
    workspace_id: UUID,
    consultation_id: UUID,
    payload: CreateAttachmentRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.ATTACHMENT_UPLOAD
    )
    result = AttachmentService(session, _scanner(request)).upload(
        context,
        consultation_id,
        file_name=payload.file_name,
        content_type=payload.content_type,
        content_base64=payload.content_base64,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = attachment_etag(result.attachment)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
        f"/attachments/{result.attachment.id}"
    )
    return _attachment_payload(result.attachment)


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/attachments"
)
def list_consultation_attachments(
    workspace_id: UUID,
    consultation_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.ATTACHMENT_READ
    )
    items = AttachmentService(session).list_for_consultation(context, consultation_id)
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.status}{item.checksum_sha256}" for item in items],
        None,
    )
    return {"items": [_attachment_payload(item) for item in items]}


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
    "/attachments/{attachment_id}"
)
def get_consultation_attachment(
    workspace_id: UUID,
    consultation_id: UUID,
    attachment_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.ATTACHMENT_READ
    )
    attachment = AttachmentService(session).get(
        context, consultation_id, attachment_id
    )
    response.headers["ETag"] = attachment_etag(attachment)
    return _attachment_payload(attachment)


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
    "/attachments/{attachment_id}/content"
)
def download_consultation_attachment(
    workspace_id: UUID,
    consultation_id: UUID,
    attachment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.ATTACHMENT_READ
    )
    download = AttachmentService(session).download(
        context, consultation_id, attachment_id
    )
    return Response(
        content=download.content,
        media_type="application/octet-stream",
        headers={
            "ETag": attachment_etag(download.attachment),
            "Content-Disposition": (
                f'attachment; filename="{download.attachment.file_name}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
    "/attachments/{attachment_id}",
    status_code=204,
)
def delete_consultation_attachment(
    workspace_id: UUID,
    consultation_id: UUID,
    attachment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.ATTACHMENT_DELETE
    )
    AttachmentService(session).delete(
        context,
        consultation_id,
        attachment_id,
        correlation_id=request_correlation_id,
    )
    return Response(status_code=204)


@router.post(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/evidence",
    status_code=201,
)
def create_consultation_evidence(
    workspace_id: UUID,
    consultation_id: UUID,
    payload: CreateEvidenceRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.EVIDENCE_CREATE
    )
    result = EvidenceService(session).create(
        context,
        consultation_id,
        kind=payload.kind,
        description=payload.description,
        content=payload.content,
        attachment_id=payload.attachment_id,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = '"' + fingerprint(
        ["evidence", str(result.evidence.id)]
    ) + '"'
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
        f"/evidence/{result.evidence.id}"
    )
    return _evidence_payload(result.evidence)


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/evidence"
)
def list_consultation_evidence(
    workspace_id: UUID,
    consultation_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.EVIDENCE_READ
    )
    items = EvidenceService(session).list_for_consultation(context, consultation_id)
    response.headers["ETag"] = _collection_etag(
        workspace_id, [str(item.id) for item in items], None
    )
    return {"items": [_evidence_payload(item) for item in items]}


@router.get(
    "/v1/workspaces/{workspace_id}/consultations/{consultation_id}/history"
)
def list_consultation_history(
    workspace_id: UUID,
    consultation_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.HISTORY_READ
    )
    records, next_cursor = ConsultationHistoryService(session).list_page(
        context, consultation_id, limit=limit, cursor=cursor
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{record.id}{record.snapshot_hash}" for record in records],
        next_cursor,
    )
    return {
        "items": [_history_payload(record) for record in records],
        "page_info": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
    }
