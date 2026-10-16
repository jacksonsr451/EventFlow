"""Consultation evidence application service (Issue #4).

Evidence is structured justification for a consultation. It is either free text,
an external link, or a reference to an available attachment; a reference is only
allowed to an attachment that passed scanning, so quarantined or rejected bytes
can never be cited as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import ConsultationEvidence
from eventflow_work_management.models.enums import EVIDENCE_KIND_VALUES
from eventflow_work_management.repositories.attachment_repository import (
    AttachmentRepository,
    EvidenceRepository,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.attachment import AVAILABLE_STATUS

CREATE_OPERATION = "evidence.create"

ATTACHMENT_KIND = "attachment"

_NOT_FOUND = "The requested resource was not found."


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _validation(detail: str, *, status_code: int = 400) -> ProblemError:
    return ProblemError(
        status_code=status_code,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request" if status_code == 400 else "Unprocessable entity",
    )


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    evidence: ConsultationEvidence
    replayed: bool


class EvidenceService:
    """Authorization, validation, and persistence for consultation evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.evidence = EvidenceRepository(session)
        self.attachments = AttachmentRepository(session)
        self.consultations = ConsultationRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    def create(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        *,
        kind: str,
        description: str | None = None,
        content: str | None = None,
        attachment_id: UUID | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> EvidenceResult:
        self._validate_shape(
            kind=kind, content=content, attachment_id=attachment_id
        )
        request_fingerprint = fingerprint(
            {
                "consultation_id": str(consultation_id),
                "kind": kind,
                "description": description,
                "content": content,
                "attachment_id": str(attachment_id) if attachment_id else None,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, CREATE_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            self._require_consultation(context.workspace_id, consultation_id)
            if kind == ATTACHMENT_KIND and attachment_id is not None:
                attachment = self.attachments.get(
                    workspace_id=context.workspace_id,
                    consultation_id=consultation_id,
                    attachment_id=attachment_id,
                )
                if attachment is None:
                    raise _not_found()
                if attachment.status != AVAILABLE_STATUS:
                    raise ProblemError(
                        status_code=409,
                        code="INVALID_STATE",
                        detail="Only an available attachment can be cited as evidence.",
                        title="Conflict",
                    )
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=CREATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            evidence = self.evidence.add(
                workspace_id=context.workspace_id,
                consultation_id=consultation_id,
                created_by=context.actor_id,
                kind=kind,
                description=description,
                content=content,
                attachment_id=attachment_id,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="evidence.added",
                entity_type="consultation",
                entity_id=consultation_id,
                actor_id=context.actor_id,
                snapshot={
                    "consultation_id": str(consultation_id),
                    "evidence_id": str(evidence.id),
                    "kind": kind,
                    "attachment_id": str(attachment_id) if attachment_id else None,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"evidence_id": str(evidence.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return EvidenceResult(evidence=evidence, replayed=False)

    def list_for_consultation(
        self, context: AuthorizationContext, consultation_id: UUID
    ) -> list[ConsultationEvidence]:
        self._require_consultation(context.workspace_id, consultation_id)
        return self.evidence.list_for_consultation(
            workspace_id=context.workspace_id, consultation_id=consultation_id
        )

    # -- internals --------------------------------------------------------

    @staticmethod
    def _validate_shape(
        *, kind: str, content: str | None, attachment_id: UUID | None
    ) -> None:
        if kind not in EVIDENCE_KIND_VALUES:
            raise _validation("Unknown evidence kind.")
        if kind == ATTACHMENT_KIND:
            if attachment_id is None:
                raise _validation(
                    "Attachment evidence requires an attachment_id.",
                    status_code=422,
                )
            if content is not None:
                raise _validation(
                    "Attachment evidence must not include inline content.",
                    status_code=422,
                )
            return
        if content is None:
            raise _validation(
                "Text and link evidence require content.", status_code=422
            )
        if attachment_id is not None:
            raise _validation(
                "Text and link evidence must not reference an attachment.",
                status_code=422,
            )

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
    ) -> EvidenceResult | None:
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
        evidence_id = (
            stored.response_body.get("evidence_id") if stored.response_body else None
        )
        if evidence_id is None:
            return None
        evidence = self.evidence.get_by_id(
            workspace_id=stored.workspace_id, evidence_id=UUID(evidence_id)
        )
        if evidence is None:
            return None
        return EvidenceResult(evidence=evidence, replayed=True)
