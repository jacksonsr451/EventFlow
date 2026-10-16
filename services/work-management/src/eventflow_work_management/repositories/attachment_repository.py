"""Attachment and evidence repositories (Issue #4).

These repositories only flush; the owning service commits once so an upload, its
audit record, and its idempotency reservation land in a single transaction.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    ConsultationAttachment,
    ConsultationAttachmentBlob,
    ConsultationEvidence,
)
from eventflow_work_management.repositories.base import Repository


class AttachmentRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        consultation_id: UUID,
        uploaded_by: UUID,
        file_name: str,
        declared_content_type: str,
        detected_content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        storage_key: str,
        status: str,
        scan_verdict: str,
        rejection_reason: str | None = None,
    ) -> ConsultationAttachment:
        attachment = ConsultationAttachment(
            id=uuid4(),
            workspace_id=workspace_id,
            consultation_id=consultation_id,
            uploaded_by=uploaded_by,
            file_name=file_name,
            declared_content_type=declared_content_type,
            detected_content_type=detected_content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            storage_key=storage_key,
            status=status,
            scan_verdict=scan_verdict,
            rejection_reason=rejection_reason,
        )
        self._session.add(attachment)
        self._session.flush()
        return attachment

    def add_blob(
        self, *, attachment_id: UUID, workspace_id: UUID, data: bytes
    ) -> ConsultationAttachmentBlob:
        blob = ConsultationAttachmentBlob(
            attachment_id=attachment_id, workspace_id=workspace_id, data=data
        )
        self._session.add(blob)
        self._session.flush()
        return blob

    def get(
        self, *, workspace_id: UUID, consultation_id: UUID, attachment_id: UUID
    ) -> ConsultationAttachment | None:
        statement = select(ConsultationAttachment).where(
            ConsultationAttachment.workspace_id == workspace_id,
            ConsultationAttachment.consultation_id == consultation_id,
            ConsultationAttachment.id == attachment_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_id(
        self, *, workspace_id: UUID, attachment_id: UUID
    ) -> ConsultationAttachment | None:
        statement = select(ConsultationAttachment).where(
            ConsultationAttachment.workspace_id == workspace_id,
            ConsultationAttachment.id == attachment_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_blob(self, *, attachment_id: UUID) -> ConsultationAttachmentBlob | None:
        statement = select(ConsultationAttachmentBlob).where(
            ConsultationAttachmentBlob.attachment_id == attachment_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_consultation(
        self, *, workspace_id: UUID, consultation_id: UUID
    ) -> list[ConsultationAttachment]:
        statement = (
            select(ConsultationAttachment)
            .where(
                ConsultationAttachment.workspace_id == workspace_id,
                ConsultationAttachment.consultation_id == consultation_id,
            )
            .order_by(
                ConsultationAttachment.created_at, ConsultationAttachment.id
            )
        )
        return list(self._session.execute(statement).scalars())

    def count_for_consultation(
        self, *, workspace_id: UUID, consultation_id: UUID
    ) -> int:
        statement = select(func.count()).select_from(ConsultationAttachment).where(
            ConsultationAttachment.workspace_id == workspace_id,
            ConsultationAttachment.consultation_id == consultation_id,
        )
        return int(self._session.execute(statement).scalar_one())

    def delete(self, attachment: ConsultationAttachment) -> None:
        self._session.delete(attachment)
        self._session.flush()


class EvidenceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        consultation_id: UUID,
        created_by: UUID,
        kind: str,
        description: str | None,
        content: str | None,
        attachment_id: UUID | None,
    ) -> ConsultationEvidence:
        evidence = ConsultationEvidence(
            id=uuid4(),
            workspace_id=workspace_id,
            consultation_id=consultation_id,
            created_by=created_by,
            kind=kind,
            description=description,
            content=content,
            attachment_id=attachment_id,
        )
        self._session.add(evidence)
        self._session.flush()
        return evidence

    def get(
        self, *, workspace_id: UUID, consultation_id: UUID, evidence_id: UUID
    ) -> ConsultationEvidence | None:
        statement = select(ConsultationEvidence).where(
            ConsultationEvidence.workspace_id == workspace_id,
            ConsultationEvidence.consultation_id == consultation_id,
            ConsultationEvidence.id == evidence_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_id(
        self, *, workspace_id: UUID, evidence_id: UUID
    ) -> ConsultationEvidence | None:
        statement = select(ConsultationEvidence).where(
            ConsultationEvidence.workspace_id == workspace_id,
            ConsultationEvidence.id == evidence_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_consultation(
        self, *, workspace_id: UUID, consultation_id: UUID
    ) -> list[ConsultationEvidence]:
        statement = (
            select(ConsultationEvidence)
            .where(
                ConsultationEvidence.workspace_id == workspace_id,
                ConsultationEvidence.consultation_id == consultation_id,
            )
            .order_by(ConsultationEvidence.created_at, ConsultationEvidence.id)
        )
        return list(self._session.execute(statement).scalars())
