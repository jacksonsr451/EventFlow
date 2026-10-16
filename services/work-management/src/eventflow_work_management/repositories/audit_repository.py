"""Append-only audit repository."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import AuditRecord
from eventflow_work_management.repositories.base import Repository


class AuditRepository(Repository):
    """Writes and reads append-only audit records."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def append(
        self,
        *,
        workspace_id: UUID,
        action: str,
        entity_type: str,
        entity_id: UUID,
        actor_id: UUID | None = None,
        snapshot: dict | None = None,
        correlation_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditRecord:
        """Add an audit record and flush it within the current transaction.

        The hash is derived from the canonical snapshot so tampering is
        detectable independently of row access controls.
        """
        record = AuditRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at or datetime.now(UTC),
            snapshot=snapshot,
            snapshot_hash=fingerprint(snapshot)
            if snapshot is not None
            else fingerprint({}),
            correlation_id=correlation_id,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_entity(
        self, workspace_id: UUID, entity_type: str, entity_id: UUID
    ) -> list[AuditRecord]:
        """Return the audit trail for one entity, oldest first."""
        statement = (
            select(AuditRecord)
            .where(
                AuditRecord.workspace_id == workspace_id,
                AuditRecord.entity_type == entity_type,
                AuditRecord.entity_id == entity_id,
            )
            .order_by(AuditRecord.occurred_at, AuditRecord.created_at)
        )
        return list(self._session.execute(statement).scalars())

    def list_page_for_entity(
        self,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[AuditRecord]:
        """Return a keyset page of the audit trail, oldest first."""
        statement = select(AuditRecord).where(
            AuditRecord.workspace_id == workspace_id,
            AuditRecord.entity_type == entity_type,
            AuditRecord.entity_id == entity_id,
        )
        if after is not None:
            occurred_at, after_id = after
            statement = statement.where(
                tuple_(AuditRecord.occurred_at, AuditRecord.id)
                > tuple_(occurred_at, after_id)
            )
        statement = statement.order_by(
            AuditRecord.occurred_at, AuditRecord.id
        ).limit(limit)
        return list(self._session.execute(statement).scalars())
