"""Authorized work-item priority overrides (Issue #30).

The calculated priority remains the single source of truth. An override is an
explicit, reasoned, audited change that preserves the calculated value so the
divergence is always visible.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import WorkItem
from eventflow_work_management.models.enums import PRIORITY_VALUES
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.work_item_repository import (
    WorkItemRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.board_management import work_item_etag
from eventflow_work_management.services.notifications import (
    NotificationService,
    redact_work_item_notification,
)

PRIORITY_OVERRIDE_OPERATION = "work_item.priority_override"


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404,
        code="NOT_FOUND",
        detail="The requested resource was not found.",
        title="Not found",
    )


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def _idempotency_conflict() -> ProblemError:
    return ProblemError(
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        detail="The idempotency key was reused with a different request.",
        title="Conflict",
    )


class PriorityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._work_items = WorkItemRepository(session)
        self._audit = AuditRepository(session)
        self._idempotency = IdempotencyRepository(session)
        self._notifications = NotificationService(session)

    def get(self, context, work_item_id: UUID) -> WorkItem:
        work_item = self._work_items.get(
            workspace_id=context.workspace_id, work_item_id=work_item_id
        )
        if work_item is None:
            raise _not_found()
        return work_item

    def override(
        self,
        context,
        work_item_id: UUID,
        *,
        priority: str,
        reason: str,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> WorkItem:
        if priority not in PRIORITY_VALUES:
            raise _validation("Unknown priority value.")
        if not isinstance(reason, str) or not 10 <= len(reason) <= 300:
            raise _validation("A priority override reason of 10 to 300 characters is required.")

        request_fingerprint = fingerprint(
            {
                "operation": PRIORITY_OVERRIDE_OPERATION,
                "work_item_id": str(work_item_id),
                "priority": priority,
                "reason": reason,
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                PRIORITY_OVERRIDE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self.get(context, work_item_id)

        try:
            work_item = self._work_items.get_for_update(
                workspace_id=context.workspace_id, work_item_id=work_item_id
            )
            if work_item is None:
                raise _not_found()
            if if_match is not None and if_match != work_item_etag(work_item):
                raise _precondition_failed()
            record = (
                self._idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=PRIORITY_OVERRIDE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            previous = work_item.priority
            if work_item.calculated_priority is None:
                work_item.calculated_priority = previous
            work_item.priority = priority
            work_item.priority_override_reason = reason
            work_item.priority_overridden_by = context.actor_id
            self._audit.append(
                workspace_id=context.workspace_id,
                action="work_item.priority_overridden",
                entity_type="work_item",
                entity_id=work_item.id,
                actor_id=context.actor_id,
                snapshot={
                    "work_item_id": str(work_item.id),
                    "previous_priority": previous,
                    "priority": priority,
                    "calculated_priority": work_item.calculated_priority,
                    "reason": reason,
                },
                correlation_id=correlation_id,
            )
            title, body, payload = redact_work_item_notification(
                work_item,
                title=f"Priority changed: {work_item.title}",
                body=f"The priority changed from {previous} to {priority}.",
                payload={
                    "work_item_id": str(work_item.id),
                    "previous_priority": previous,
                    "priority": priority,
                },
            )
            self._notifications.emit(
                workspace_id=context.workspace_id,
                recipient_id=work_item.assignee_id,
                event_type="work_item.priority_overridden",
                entity_type="work_item",
                entity_id=work_item.id,
                title=title,
                body=body,
                payload=payload,
                dedup_key=(
                    f"work_item.priority_overridden:{work_item.id}:"
                    f"{work_item.updated_at.isoformat()}"
                ),
            )
            if record is not None:
                self._idempotency.complete(
                    record, response_status=200, response_body={"work_item_id": str(work_item.id)}
                )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return work_item

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict | None:
        stored = self._idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise _idempotency_conflict()
        return stored.response_body or {}
