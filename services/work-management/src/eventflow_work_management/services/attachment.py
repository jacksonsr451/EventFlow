"""Attachment application service (Issue #4).

Uploads are hostile until proven otherwise. The service:

* derives the tenant and actor from the verified principal, never the body;
* validates the filename (no path material), size, and content type;
* sniffs the real content type and requires it to match the declared type;
* scans through an injected :class:`MalwareScanner` and fails closed: an
  ``unknown`` verdict is quarantined and never becomes available;
* stores object bytes only after they pass the allowlist, addressed by an opaque
  random ``storage_key`` that is never derived from the client filename;
* records every accepted, quarantined, rejected, and deleted object in the
  append-only audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import ADMINISTRATOR_ROLES
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import ConsultationAttachment
from eventflow_work_management.repositories.attachment_repository import (
    AttachmentRepository,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
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
    classify as _classify,
    conflict as _conflict,
    not_found as _not_found,
    validate_upload,
)

UPLOAD_OPERATION = "attachment.upload"

MAX_ATTACHMENTS_PER_CONSULTATION = 25


def attachment_etag(attachment: ConsultationAttachment) -> str:
    """Strong validator over the persisted attachment version."""
    return (
        '"'
        + fingerprint(
            [
                "attachment",
                str(attachment.id),
                attachment.checksum_sha256,
                attachment.status,
            ]
        )
        + '"'
    )


@dataclass(frozen=True, slots=True)
class AttachmentResult:
    attachment: ConsultationAttachment
    replayed: bool


@dataclass(frozen=True, slots=True)
class AttachmentDownload:
    attachment: ConsultationAttachment
    content: bytes


class AttachmentService:
    """Authorization, validation, scanning, and persistence for attachments."""

    def __init__(
        self, session: Session, scanner: MalwareScanner | None = None
    ) -> None:
        self._session = session
        self._scanner: MalwareScanner = scanner or UnconfiguredMalwareScanner()
        self.attachments = AttachmentRepository(session)
        self.consultations = ConsultationRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    # -- upload -----------------------------------------------------------

    def upload(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        *,
        file_name: str,
        content_type: str,
        content_base64: str,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> AttachmentResult:
        validated = validate_upload(
            file_name=file_name,
            content_type=content_type,
            content_base64=content_base64,
        )
        normalized_name = validated.file_name
        data = validated.data
        detected = validated.content_type
        checksum = validated.checksum_sha256
        request_fingerprint = fingerprint(
            {
                "consultation_id": str(consultation_id),
                "file_name": normalized_name,
                "content_type": content_type,
                "checksum_sha256": checksum,
                "size_bytes": len(data),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, UPLOAD_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            self._require_consultation(context.workspace_id, consultation_id)
            if (
                self.attachments.count_for_consultation(
                    workspace_id=context.workspace_id,
                    consultation_id=consultation_id,
                )
                >= MAX_ATTACHMENTS_PER_CONSULTATION
            ):
                raise _conflict(
                    "The consultation has reached its attachment limit.",
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

            scan = self._scanner.scan(content=data, content_type=detected)
            status, rejection_reason, audit_action = _classify(scan.verdict)
            attachment = self.attachments.add(
                workspace_id=context.workspace_id,
                consultation_id=consultation_id,
                uploaded_by=context.actor_id,
                file_name=normalized_name,
                declared_content_type=content_type,
                detected_content_type=detected,
                size_bytes=len(data),
                checksum_sha256=checksum,
                storage_key=uuid4().hex,
                status=status,
                scan_verdict=scan.verdict,
                rejection_reason=rejection_reason,
            )
            if status != REJECTED_STATUS:
                self.attachments.add_blob(
                    attachment_id=attachment.id,
                    workspace_id=context.workspace_id,
                    data=data,
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action=audit_action,
                entity_type="consultation",
                entity_id=consultation_id,
                actor_id=context.actor_id,
                snapshot={
                    "consultation_id": str(consultation_id),
                    "attachment_id": str(attachment.id),
                    "file_name": normalized_name,
                    "content_type": detected,
                    "size_bytes": len(data),
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
                    UPLOAD_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return AttachmentResult(attachment=attachment, replayed=False)

    # -- reads ------------------------------------------------------------

    def list_for_consultation(
        self, context: AuthorizationContext, consultation_id: UUID
    ) -> list[ConsultationAttachment]:
        self._require_consultation(context.workspace_id, consultation_id)
        return self.attachments.list_for_consultation(
            workspace_id=context.workspace_id, consultation_id=consultation_id
        )

    def get(
        self, context: AuthorizationContext, consultation_id: UUID, attachment_id: UUID
    ) -> ConsultationAttachment:
        self._require_consultation(context.workspace_id, consultation_id)
        attachment = self.attachments.get(
            workspace_id=context.workspace_id,
            consultation_id=consultation_id,
            attachment_id=attachment_id,
        )
        if attachment is None:
            raise _not_found()
        return attachment

    def download(
        self, context: AuthorizationContext, consultation_id: UUID, attachment_id: UUID
    ) -> AttachmentDownload:
        attachment = self.get(context, consultation_id, attachment_id)
        if attachment.status != AVAILABLE_STATUS:
            raise _conflict(
                "The attachment is not available for download.",
                code="ATTACHMENT_QUARANTINED",
            )
        blob = self.attachments.get_blob(attachment_id=attachment.id)
        if blob is None:
            raise _not_found()
        return AttachmentDownload(attachment=attachment, content=blob.data)

    # -- delete -----------------------------------------------------------

    def delete(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        attachment_id: UUID,
        *,
        correlation_id: UUID | None = None,
    ) -> None:
        try:
            attachment = self.get(context, consultation_id, attachment_id)
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
                entity_type="consultation",
                entity_id=consultation_id,
                actor_id=context.actor_id,
                snapshot={
                    "consultation_id": str(consultation_id),
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

    def _require_consultation(self, workspace_id: UUID, consultation_id: UUID) -> None:
        if (
            self.consultations.get(
                workspace_id=workspace_id, consultation_id=consultation_id
            )
            is None
        ):
            raise _not_found()

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> AttachmentResult | None:
        stored = self.idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
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
        attachment = self.attachments.get_by_id(
            workspace_id=stored.workspace_id, attachment_id=UUID(attachment_id)
        )
        if attachment is None:
            return None
        return AttachmentResult(attachment=attachment, replayed=True)
