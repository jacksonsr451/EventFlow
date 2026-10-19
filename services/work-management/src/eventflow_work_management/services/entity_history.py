"""Generic entity history projection (Issue #29).

History is a read-only projection of the append-only audit trail. The audit
table is immutable at the database level; this service only reads it and never
creates, rewrites, or deletes entries.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.models import AuditRecord
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.entity_access import resolve_entity
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request",
    )


class EntityHistoryService:
    """Read-only access to a generic entity audit timeline."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.audit = AuditRepository(session)

    def list_page(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[AuditRecord], str | None]:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
        )
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")

        after = None
        if cursor is not None:
            try:
                payload = decode_cursor(cursor)
                after = (payload["occurred_at"], payload["id"])
            except (CursorError, KeyError, TypeError, ValueError) as exc:
                raise _validation("The pagination cursor is invalid.") from exc

        rows = self.audit.list_page_for_entity(
            context.workspace_id,
            entity.entity_type,
            entity.entity_id,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor({"occurred_at": last.occurred_at}, last.id)
        return page, next_cursor
