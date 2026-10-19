"""Generic entity attachment application service (Issue #29).

Proposals, work items, and board cards use this service; consultations keep
their original Issue #4 service and tables. Both paths share
``services.attachment_support`` so the size bound, filename rules, content-type
sniffing, and fail-closed scan classification cannot diverge.

Bytes are served only when the scan verdict made the attachment ``available``.
A quarantined or rejected object never exposes content.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import ADMINISTRATOR_ROLES
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import EntityAttachment
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.entity_attachment_repository import (
    EntityAttachmentRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.security.attachment_scanner import (
    MalwareScanner,
    UnconfiguredMalwareScanner,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.attachment_support import (
    AVAILABLE_STATUS,
    REJECTED_STATUS,
    classify,
    conflict,
    not_found,
    validate_upload,
)
from eventflow_work_management.services.entity_access import resolve_entity

UPLOAD_OPERATION = "entity_attachment.upload"

MAX_ATTACHMENTS_PER_ENTITY = 25


@dataclass(frozen=True, slots=True)
class EntityAttachmentResult:
    attachment: EntityAttachment
    replayed: bool


@dataclass(frozen=True, slots=True)
class EntityAttachmentDownload:
    attachment: EntityAttachment
    content: bytes


def entity_attachment_etag(attachment: EntityAttachment) -> str:
    return (
        '"'
        + fingerprint(
            [
                "entity_attachment",
                str(attachment.id),
                attachment.entity_type,
                str(attachment.entity_id),
                attachment.checksum_sha256,
                attachment.status,
            ]
        )
        + '"'
    )


class EntityAttachmentService:
    """Authorization, validation, scanning, and persistence for attachments."""

    def __init__(
        self, session: Session, scanner: MalwareScanner | None = None
    ) -> None:
        self._session = session
        self._scanner: MalwareScanner = scanner or UnconfiguredMalwareScanner()
        self.attachments = EntityAttachmentRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    # -- upload -----------------------------------------------------------

    def upload(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        file_name: str,
        content_type: str,
        content_base64: str,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> EntityAttachmentResult:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
            for_attachment=True,
        )
        validated = validate_upload(
            file_name=file_name,
            content_type=content_type,
            content_base64=content_base64,
        )
        request_fingerprint = fingerprint(
            {
                "entity_type": entity.entity_type,
                "entity_id": str(entity.entity_id),
                "file_name": validated.file_name,
                "content_type": validated.content_type,
                "checksum_sha256": validated.checksum_sha256,
                "size_bytes": len(validated.data),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                entity.entity_type,
                entity.entity_id,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay

        try:
            if (
                self.attachments.count_for_entity(
                    workspace_id=context.workspace_id,
                    entity_type=entity.entity_type,
                    entity_id=entity.entity_id,
                )
                >= MAX_ATTACHMENTS_PER_ENTITY
            ):
                raise conflict(
                    "The entity has reached its attachment limit.",
                    code="ATTACHMENT_LIMIT_REACHED",
                )
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=UPLOAD_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            scan = self._scanner.scan(
                content=validated.data, content_type=validated.content_type
            )
            status, rejection_reason, audit_action = classify(scan.verdict)
            attachment = self.attachments.add(
                workspace_id=context.workspace_id,
                project_id=entity.project_id,
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                uploaded_by=context.actor_id,
                file_name=validated.file_name,
                declared_content_type=content_type,
                detected_content_type=validated.content_type,
                size_bytes=len(validated.data),
                checksum_sha256=validated.checksum_sha256,
                storage_key=uuid4().hex,
                status=status,
                scan_verdict=scan.verdict,
                rejection_reason=rejection_reason,
            )
            if status != REJECTED_STATUS:
                self.attachments.add_blob(
                    attachment_id=attachment.id,
                    workspace_id=context.workspace_id,
                    data=validated.data,
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action=audit_action,
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                actor_id=context.actor_id,
                snapshot={
                    "entity_type": entity.entity_type,
                    "entity_id": str(entity.entity_id),
                    "attachment_id": str(attachment.id),
                    "file_name": validated.file_name,
                    "content_type": validated.content_type,
                    "size_bytes": len(validated.data),
                    "status": status,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"attachment_id": str(attachment.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    entity.entity_type,
                    entity.entity_id,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return EntityAttachmentResult(attachment=attachment, replayed=False)

    # -- reads ------------------------------------------------------------

    def list_for_entity(
        self, context: AuthorizationContext, *, collection: str, entity_id: UUID
    ) -> list[EntityAttachment]:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
            for_attachment=True,
        )
        return self.attachments.list_for_entity(
            workspace_id=context.workspace_id,
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
        )

    def get(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        attachment_id: UUID,
    ) -> EntityAttachment:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
            for_attachment=True,
        )
        attachment = self.attachments.get(
            workspace_id=context.workspace_id,
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
            attachment_id=attachment_id,
        )
        if attachment is None:
            raise not_found()
        return attachment

    def download(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        attachment_id: UUID,
    ) -> EntityAttachmentDownload:
        attachment = self.get(
            context,
            collection=collection,
            entity_id=entity_id,
            attachment_id=attachment_id,
        )
        if attachment.status != AVAILABLE_STATUS:
            raise conflict(
                "The attachment is not available for download.",
                code="ATTACHMENT_QUARANTINED",
            )
        blob = self.attachments.get_blob(attachment_id=attachment.id)
        if blob is None:
            raise not_found()
        return EntityAttachmentDownload(attachment=attachment, content=blob.data)

    # -- delete -----------------------------------------------------------

    def delete(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        attachment_id: UUID,
        correlation_id: UUID | None = None,
    ) -> None:
        try:
            attachment = self.get(
                context,
                collection=collection,
                entity_id=entity_id,
                attachment_id=attachment_id,
            )
            if (
                attachment.uploaded_by != context.actor_id
                and context.role not in ADMINISTRATOR_ROLES
            ):
                raise ProblemError(
                    status_code=403,
                    code="FORBIDDEN",
                    detail="Only the uploader or a workspace administrator may delete this.",
                    title="Forbidden",
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="attachment.deleted",
                entity_type=attachment.entity_type,
                entity_id=attachment.entity_id,
                actor_id=context.actor_id,
                snapshot={
                    "entity_type": attachment.entity_type,
                    "entity_id": str(attachment.entity_id),
                    "attachment_id": str(attachment.id),
                    "file_name": attachment.file_name,
                },
                correlation_id=correlation_id,
            )
            self.attachments.delete(attachment)
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise

    # -- internals --------------------------------------------------------

    def _replay(
        self,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> EntityAttachmentResult | None:
        stored = self.idempotency.get(
            workspace_id=workspace_id,
            operation=UPLOAD_OPERATION,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise ProblemError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                detail="The idempotency key was reused with a different request.",
                title="Conflict",
            )
        attachment_id = (
            stored.response_body.get("attachment_id") if stored.response_body else None
        )
        if attachment_id is None:
            return None
        attachment = self.attachments.get(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            attachment_id=UUID(attachment_id),
        )
        if attachment is None:
            return None
        return EntityAttachmentResult(attachment=attachment, replayed=True)
