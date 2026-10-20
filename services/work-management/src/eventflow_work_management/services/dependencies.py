"""WorkItem dependency graph service (Issue #30).

Dependencies are directional and acyclic. Cycle prevention is enforced in the
database transaction under a workspace advisory lock, not by a pre-check in the
application: two concurrent edge insertions cannot both succeed and create a
cycle. Duplicate edges are impossible via a unique constraint.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import WorkItem, WorkItemDependency
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.dependency_repository import (
    WorkItemDependencyRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.work_item_repository import (
    WorkItemRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.notifications import (
    NotificationService,
    redact_work_item_notification,
)

DEPENDENCY_CREATE_OPERATION = "work_item_dependency.create"
DEPENDENCY_DELETE_OPERATION = "work_item_dependency.delete"


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


def _conflict(detail: str, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _idempotency_conflict() -> ProblemError:
    return ProblemError(
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        detail="The idempotency key was reused with a different request.",
        title="Conflict",
    )


@dataclass(frozen=True)
class DependencyList:
    work_item: WorkItem
    blockers: list[WorkItemDependency]
    dependents: list[WorkItemDependency]
    unresolved_blocker_ids: list[UUID]


@dataclass(frozen=True)
class DependencyOutcome:
    edge: WorkItemDependency
    replayed: bool = False


class DependencyService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._dependencies = WorkItemDependencyRepository(session)
        self._work_items = WorkItemRepository(session)
        self._audit = AuditRepository(session)
        self._idempotency = IdempotencyRepository(session)
        self._notifications = NotificationService(session)

    def _require_item(self, context, work_item_id: UUID, *, for_update: bool = False) -> WorkItem:
        item = (
            self._work_items.get_for_update(
                workspace_id=context.workspace_id, work_item_id=work_item_id
            )
            if for_update
            else self._work_items.get(
                workspace_id=context.workspace_id, work_item_id=work_item_id
            )
        )
        if item is None:
            raise _not_found()
        return item

    def list(self, context, work_item_id: UUID) -> DependencyList:
        work_item = self._require_item(context, work_item_id)
        blockers = self._dependencies.list_dependencies_of(
            workspace_id=context.workspace_id, work_item_id=work_item_id
        )
        dependents = self._dependencies.list_dependents_of(
            workspace_id=context.workspace_id, work_item_id=work_item_id
        )
        unresolved = [
            item.id
            for item in self._dependencies.unresolved_blockers(
                workspace_id=context.workspace_id, work_item_id=work_item_id
            )
        ]
        return DependencyList(
            work_item=work_item,
            blockers=blockers,
            dependents=dependents,
            unresolved_blocker_ids=unresolved,
        )

    def create(
        self,
        context,
        blocked_work_item_id: UUID,
        *,
        blocking_work_item_id: UUID,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> DependencyOutcome:
        if blocking_work_item_id == blocked_work_item_id:
            raise _validation("A work item cannot depend on itself.")
        request_fingerprint = fingerprint(
            {
                "operation": DEPENDENCY_CREATE_OPERATION,
                "blocked_work_item_id": str(blocked_work_item_id),
                "blocking_work_item_id": str(blocking_work_item_id),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                DEPENDENCY_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                edge = self._dependencies.get(
                    workspace_id=context.workspace_id,
                    dependency_id=UUID(str(replay["dependency_id"])),
                )
                if edge is None:
                    raise _not_found()
                return DependencyOutcome(edge=edge, replayed=True)

        try:
            self._dependencies.acquire_workspace_lock(context.workspace_id)
            blocked = self._require_item(context, blocked_work_item_id, for_update=True)
            blocking = self._require_item(context, blocking_work_item_id, for_update=True)
            record = (
                self._idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=DEPENDENCY_CREATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            existing = self._dependencies.get_edge(
                workspace_id=context.workspace_id,
                blocking_work_item_id=blocking.id,
                blocked_work_item_id=blocked.id,
            )
            if existing is not None:
                if record is not None:
                    self._idempotency.complete(
                        record,
                        response_status=201,
                        response_body={"dependency_id": str(existing.id)},
                    )
                self._session.commit()
                return DependencyOutcome(edge=existing, replayed=True)
            if self._dependencies.would_create_cycle(
                workspace_id=context.workspace_id,
                blocking_work_item_id=blocking.id,
                blocked_work_item_id=blocked.id,
            ):
                raise _conflict(
                    "This dependency would create a cycle.", code="DEPENDENCY_CYCLE"
                )
            edge = self._dependencies.add(
                workspace_id=context.workspace_id,
                project_id=blocked.project_id,
                blocking_work_item_id=blocking.id,
                blocked_work_item_id=blocked.id,
                created_by=context.actor_id,
            )
            self._audit.append(
                workspace_id=context.workspace_id,
                action="work_item_dependency.created",
                entity_type="work_item_dependency",
                entity_id=edge.id,
                actor_id=context.actor_id,
                snapshot={
                    "dependency_id": str(edge.id),
                    "blocking_work_item_id": str(blocking.id),
                    "blocked_work_item_id": str(blocked.id),
                },
                correlation_id=correlation_id,
            )
            title, body, payload = redact_work_item_notification(
                blocked,
                blocking,
                title=f"Dependency added: {blocked.title}",
                body=f"A new blocker was linked: {blocking.title}.",
                payload={
                    "work_item_id": str(blocked.id),
                    "blocking_work_item_id": str(blocking.id),
                },
            )
            self._notifications.emit(
                workspace_id=context.workspace_id,
                recipient_id=blocked.assignee_id,
                event_type="dependency.created",
                entity_type="work_item",
                entity_id=blocked.id,
                title=title,
                body=body,
                payload=payload,
                dedup_key=f"dependency.created:{edge.id}",
            )
            if record is not None:
                self._idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"dependency_id": str(edge.id)},
                )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    DEPENDENCY_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    edge = self._dependencies.get(
                        workspace_id=context.workspace_id,
                        dependency_id=UUID(str(replay["dependency_id"])),
                    )
                    if edge is not None:
                        return DependencyOutcome(edge=edge, replayed=True)
            raise _conflict(
                "The dependency could not be recorded.", code="DEPENDENCY_CYCLE"
            ) from exc
        except ProblemError:
            self._session.rollback()
            raise
        return DependencyOutcome(edge=edge)

    def delete(
        self,
        context,
        work_item_id: UUID,
        dependency_id: UUID,
        *,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        request_fingerprint = fingerprint(
            {
                "operation": DEPENDENCY_DELETE_OPERATION,
                "work_item_id": str(work_item_id),
                "dependency_id": str(dependency_id),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                DEPENDENCY_DELETE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return
        try:
            self._dependencies.acquire_workspace_lock(context.workspace_id)
            edge = self._dependencies.get(
                workspace_id=context.workspace_id, dependency_id=dependency_id
            )
            if edge is None:
                raise _not_found()
            if edge.blocked_work_item_id != work_item_id and (
                edge.blocking_work_item_id != work_item_id
            ):
                raise _not_found()
            record = (
                self._idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=DEPENDENCY_DELETE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            blocked = self._work_items.get(
                workspace_id=context.workspace_id,
                work_item_id=edge.blocked_work_item_id,
            )
            self._dependencies.delete(edge)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="work_item_dependency.removed",
                entity_type="work_item_dependency",
                entity_id=edge.id,
                actor_id=context.actor_id,
                snapshot={
                    "dependency_id": str(edge.id),
                    "blocking_work_item_id": str(edge.blocking_work_item_id),
                    "blocked_work_item_id": str(edge.blocked_work_item_id),
                },
                correlation_id=correlation_id,
            )
            if blocked is not None:
                title, body, payload = redact_work_item_notification(
                    blocked,
                    title=f"Dependency removed: {blocked.title}",
                    body="A blocker was removed from this work item.",
                    payload={
                        "work_item_id": str(blocked.id),
                        "blocking_work_item_id": str(edge.blocking_work_item_id),
                    },
                )
                self._notifications.emit(
                    workspace_id=context.workspace_id,
                    recipient_id=blocked.assignee_id,
                    event_type="dependency.removed",
                    entity_type="work_item",
                    entity_id=blocked.id,
                    title=title,
                    body=body,
                    payload=payload,
                    dedup_key=f"dependency.removed:{edge.id}",
                )
            if record is not None:
                self._idempotency.complete(record, response_status=204, response_body={})
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise

    def unresolved_blockers(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> list[WorkItem]:
        return self._dependencies.unresolved_blockers(
            workspace_id=workspace_id, work_item_id=work_item_id
        )

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
