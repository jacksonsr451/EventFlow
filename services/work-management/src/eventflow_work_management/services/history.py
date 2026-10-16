"""Consultation history application service (Issue #4).

History is a read-only projection of the append-only audit trail for one
consultation. Because attachments and evidence record their lifecycle under the
consultation entity, a single timeline shows intake, draft edits, triage,
uploads, evidence, and deletion in order.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.models import AuditRecord
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
)
from eventflow_work_management.security.errors import ProblemError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

ENTITY_TYPE = "consultation"

_NOT_FOUND = "The requested resource was not found."


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request",
    )


def _encode_cursor(occurred_at: datetime, audit_id: UUID) -> str:
    payload = {"t": occurred_at.isoformat(), "id": str(audit_id)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["t"]), UUID(payload["id"])
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _validation("The pagination cursor is invalid.") from exc


class ConsultationHistoryService:
    """Read-only access to the consultation audit timeline."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.consultations = ConsultationRepository(session)
        self.audit = AuditRepository(session)

    def list_page(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[AuditRecord], str | None]:
        if (
            self.consultations.get(
                workspace_id=context.workspace_id, consultation_id=consultation_id
            )
            is None
        ):
            raise _not_found()
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        after = _decode_cursor(cursor) if cursor is not None else None
        rows = self.audit.list_page_for_entity(
            context.workspace_id,
            ENTITY_TYPE,
            consultation_id,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = _encode_cursor(last.occurred_at, last.id)
        return page, next_cursor
