"""Idempotency record repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import IdempotencyRecord
from eventflow_work_management.repositories.base import Repository


class IdempotencyRepository(Repository):
    """Stores and retrieves idempotent operation results."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get(
        self, *, workspace_id: UUID, operation: str, idempotency_key: str
    ) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.workspace_id == workspace_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def reserve(
        self,
        *,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IdempotencyRecord:
        """Reserve a key inside the current transaction.

        Raises ``IntegrityError`` if the key already exists, which the caller
        translates into a replay or a conflict.
        """
        record = IdempotencyRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def complete(
        self,
        record: IdempotencyRecord,
        *,
        response_status: int,
        response_body: dict | None,
    ) -> None:
        """Attach the stored response to a reserved key."""
        record.response_status = response_status
        record.response_body = response_body
        self._session.flush()
