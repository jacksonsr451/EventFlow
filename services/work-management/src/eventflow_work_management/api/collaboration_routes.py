"""Entity collaboration routes: comments, attachments, and history (Issue #29).

The routes are entity-scoped by a public ``entity_collection`` segment
(``consultations``, ``proposals``, ``work-items``, ``board-cards``). Tenant and
actor always come from the verified principal and the path, never the body.

The consultation attachment and history operations keep their original, more
specific paths (Issue #4). This router is registered after them, so those
specific routes continue to win for consultations; the generic handlers still
work for every supported collection.
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
from eventflow_work_management.models import AuditRecord, EntityAttachment, EntityComment
from eventflow_work_management.security.attachment_scanner import MalwareScanner
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.comments import (
    CommentService,
    comment_etag,
)
from eventflow_work_management.services.entity_attachments import (
    EntityAttachmentService,
    entity_attachment_etag,
)
from eventflow_work_management.services.entity_history import EntityHistoryService

router = APIRouter()

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")

COMMENT_ENTITY_PATH = (
    "/v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}/comments"
)
COMMENT_DETAIL_PATH = COMMENT_ENTITY_PATH + "/{comment_id}"
ATTACHMENT_ENTITY_PATH = (
    "/v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}/attachments"
)
ATTACHMENT_DETAIL_PATH = ATTACHMENT_ENTITY_PATH + "/{attachment_id}"
ATTACHMENT_CONTENT_PATH = ATTACHMENT_DETAIL_PATH + "/content"
HISTORY_ENTITY_PATH = (
    "/v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}/history"
)


class CreateCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CreateEntityAttachmentRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=8_388_608)


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


def _comment_payload(comment: EntityComment) -> dict:
    deleted = comment.deleted_at is not None
    return {
        "comment_id": comment.id,
        "workspace_id": comment.workspace_id,
        "project_id": comment.project_id,
        "entity_type": comment.entity_type,
        "entity_id": comment.entity_id,
        "author_id": comment.author_id,
        "body": None if deleted else comment.body,
        "deleted": deleted,
        "deleted_at": comment.deleted_at,
        "created_at": comment.created_at,
    }


def _attachment_payload(attachment: EntityAttachment) -> dict:
    return {
        "attachment_id": attachment.id,
        "workspace_id": attachment.workspace_id,
        "project_id": attachment.project_id,
        "entity_type": attachment.entity_type,
        "entity_id": attachment.entity_id,
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


def _collection_etag(
    workspace_id: UUID, parts: list[str], next_cursor: str | None
) -> str:
    return '"' + fingerprint([str(workspace_id), parts, next_cursor]) + '"'


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@router.post(COMMENT_ENTITY_PATH, status_code=201, tags=["Comments"])
def create_entity_comment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    payload: CreateCommentRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.COMMENT_CREATE)
    result = CommentService(session).create(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        body=payload.body,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = comment_etag(result.comment)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}"
        f"/comments/{result.comment.id}"
    )
    return _comment_payload(result.comment)


@router.get(COMMENT_ENTITY_PATH, tags=["Comments"])
def list_entity_comments(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="created_at"),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.COMMENT_READ)
    comments, next_cursor = CommentService(session).list_page(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [
            f"{comment.id}{comment.deleted_at.isoformat() if comment.deleted_at else ''}"
            for comment in comments
        ],
        next_cursor,
    )
    return {
        "items": [_comment_payload(comment) for comment in comments],
        "page_info": {
            "has_more": next_cursor is not None,
            "next_cursor": next_cursor,
        },
    }


@router.get(COMMENT_DETAIL_PATH, tags=["Comments"])
def get_entity_comment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    comment_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.COMMENT_READ)
    comment = CommentService(session).get(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        comment_id=comment_id,
    )
    response.headers["ETag"] = comment_etag(comment)
    return _comment_payload(comment)


@router.delete(COMMENT_DETAIL_PATH, status_code=204, tags=["Comments"])
def delete_entity_comment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    comment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.COMMENT_DELETE)
    CommentService(session).delete(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        comment_id=comment_id,
        correlation_id=request_correlation_id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


@router.post(ATTACHMENT_ENTITY_PATH, status_code=201, tags=["Attachments"])
def upload_entity_attachment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    payload: CreateEntityAttachmentRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.ATTACHMENT_UPLOAD)
    result = EntityAttachmentService(session, _scanner(request)).upload(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        file_name=payload.file_name,
        content_type=payload.content_type,
        content_base64=payload.content_base64,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = entity_attachment_etag(result.attachment)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}"
        f"/attachments/{result.attachment.id}"
    )
    return _attachment_payload(result.attachment)


@router.get(ATTACHMENT_ENTITY_PATH, tags=["Attachments"])
def list_entity_attachments(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.ATTACHMENT_READ)
    items = EntityAttachmentService(session).list_for_entity(
        context, collection=entity_collection, entity_id=entity_id
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.status}{item.checksum_sha256}" for item in items],
        None,
    )
    return {"items": [_attachment_payload(item) for item in items]}


@router.get(ATTACHMENT_DETAIL_PATH, tags=["Attachments"])
def get_entity_attachment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    attachment_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.ATTACHMENT_READ)
    attachment = EntityAttachmentService(session).get(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        attachment_id=attachment_id,
    )
    response.headers["ETag"] = entity_attachment_etag(attachment)
    return _attachment_payload(attachment)


@router.get(ATTACHMENT_CONTENT_PATH, tags=["Attachments"])
def download_entity_attachment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    attachment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.ATTACHMENT_READ)
    download = EntityAttachmentService(session).download(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        attachment_id=attachment_id,
    )
    return Response(
        content=download.content,
        media_type="application/octet-stream",
        headers={
            "ETag": entity_attachment_etag(download.attachment),
            "Content-Disposition": (
                f'attachment; filename="{download.attachment.file_name}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(ATTACHMENT_DETAIL_PATH, status_code=204, tags=["Attachments"])
def delete_entity_attachment(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    attachment_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.ATTACHMENT_DELETE)
    EntityAttachmentService(session).delete(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        attachment_id=attachment_id,
        correlation_id=request_correlation_id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@router.get(HISTORY_ENTITY_PATH, tags=["History"])
def list_entity_history(
    workspace_id: UUID,
    entity_collection: str,
    entity_id: UUID,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.HISTORY_READ)
    records, next_cursor = EntityHistoryService(session).list_page(
        context,
        collection=entity_collection,
        entity_id=entity_id,
        limit=limit,
        cursor=cursor,
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
