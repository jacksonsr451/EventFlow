"""Generic entity attachment repository (Issue #29).

Mirrors the consultation attachment repository, but scoped by
``(workspace_id, entity_type, entity_id)`` instead of a consultation id. It only
flushes; the owning service commits once.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eventflow_work_management.models import EntityAttachment, EntityAttachmentBlob
from eventflow_work_management.repositories.base import Repository


class EntityAttachmentRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        entity_type: str,
        entity_id: UUID,
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
    ) -> EntityAttachment:
        attachment = EntityAttachment(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
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
    ) -> EntityAttachmentBlob:
        blob = EntityAttachmentBlob(
            attachment_id=attachment_id, workspace_id=workspace_id, data=data
        )
        self._session.add(blob)
        self._session.flush()
        return blob

    def get(
        self,
        *,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        attachment_id: UUID,
    ) -> EntityAttachment | None:
        statement = select(EntityAttachment).where(
            EntityAttachment.workspace_id == workspace_id,
            EntityAttachment.entity_type == entity_type,
            EntityAttachment.entity_id == entity_id,
            EntityAttachment.id == attachment_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_id(
        self, *, workspace_id: UUID, attachment_id: UUID
    ) -> EntityAttachment | None:
        statement = select(EntityAttachment).where(
            EntityAttachment.workspace_id == workspace_id,
            EntityAttachment.id == attachment_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_blob(self, *, attachment_id: UUID) -> EntityAttachmentBlob | None:
        statement = select(EntityAttachmentBlob).where(
            EntityAttachmentBlob.attachment_id == attachment_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_entity(
        self, *, workspace_id: UUID, entity_type: str, entity_id: UUID
    ) -> list[EntityAttachment]:
        statement = (
            select(EntityAttachment)
            .where(
                EntityAttachment.workspace_id == workspace_id,
                EntityAttachment.entity_type == entity_type,
                EntityAttachment.entity_id == entity_id,
            )
            .order_by(EntityAttachment.created_at, EntityAttachment.id)
        )
        return list(self._session.execute(statement).scalars())

    def count_for_entity(
        self, *, workspace_id: UUID, entity_type: str, entity_id: UUID
    ) -> int:
        statement = select(func.count()).select_from(EntityAttachment).where(
            EntityAttachment.workspace_id == workspace_id,
            EntityAttachment.entity_type == entity_type,
            EntityAttachment.entity_id == entity_id,
        )
        return int(self._session.execute(statement).scalar_one())

    def delete(self, attachment: EntityAttachment) -> None:
        self._session.delete(attachment)
        self._session.flush()
