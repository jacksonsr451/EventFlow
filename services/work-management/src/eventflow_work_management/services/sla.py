"""SLA policy management, instance clocks and breach evaluation (Issue #30).

The SLA subsystem is durable: policy versions are immutable snapshots, each
WorkItem gets at most one instance pinned to a policy version, pause intervals
are stored explicitly, and every state change writes an append-only
``sla_events`` row. Breach detection never relies on in-memory timers: a worker
selects due rows with ``FOR UPDATE SKIP LOCKED`` and this service can also
evaluate one instance synchronously on read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import SlaInstance, SlaPolicy, WorkItem
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.sla_repository import (
    SlaEventRepository,
    SlaInstanceRepository,
    SlaPauseIntervalRepository,
    SlaPolicyRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.business_calendar import (
    CalendarError,
    add_working_minutes,
    parse_business_hours,
    parse_holidays,
    resolve_timezone,
    warning_at,
)
from eventflow_work_management.services.notifications import (
    NotificationService,
    redact_work_item_notification,
)

POLICY_CREATE_OPERATION = "sla_policy.create"
POLICY_VERSION_OPERATION = "sla_policy.version"
POLICY_ACTIVATE_OPERATION = "sla_policy.activate"

STATUS_VALUES = ("draft", "active", "retired")
TERMINAL_INSTANCE_STATUSES = ("fulfilled", "breached", "cancelled")


def _now() -> datetime:
    return datetime.now(UTC)


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


def sla_policy_etag(policy: SlaPolicy) -> str:
    return (
        '"'
        + fingerprint(
            [
                "sla-policy",
                str(policy.id),
                policy.version,
                policy.status,
                policy.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def sla_instance_etag(instance: SlaInstance) -> str:
    return (
        '"'
        + fingerprint(
            [
                "sla-instance",
                str(instance.id),
                instance.status,
                instance.version,
                instance.updated_at.isoformat(),
            ]
        )
        + '"'
    )


@dataclass(frozen=True)
class SlaPolicyOutcome:
    policy: SlaPolicy
    replayed: bool = False


@dataclass(frozen=True)
class SlaInstanceOutcome:
    instance: SlaInstance
    events: list
    work_item: WorkItem


class SlaPolicyService:
    """Versioned, scoped SLA policy CRUD."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._policies = SlaPolicyRepository(session)
        self._projects = ProjectRepository(session)
        self._audit = AuditRepository(session)
        self._idempotency = IdempotencyRepository(session)

    def _validate_calendar(
        self,
        *,
        timezone: str,
        business_hours: dict | None,
        holidays: list | None,
    ) -> tuple[dict, list]:
        try:
            resolve_timezone(timezone)
            parse_business_hours(business_hours)
            parsed_holidays = parse_holidays(holidays)
        except CalendarError as exc:
            raise _validation(str(exc)) from exc
        return business_hours or {}, sorted(
            item.isoformat() for item in parsed_holidays
        )

    def _validate_targets(
        self, response_minutes: int | None, resolution_minutes: int | None
    ) -> None:
        for label, value in (
            ("response_minutes", response_minutes),
            ("resolution_minutes", resolution_minutes),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise _validation(f"{label} must be a positive integer.")
        if response_minutes is None and resolution_minutes is None:
            raise _validation("At least one of response/resolution is required.")

    def _require_project(self, context, project_id: UUID | None) -> None:
        if project_id is None:
            return
        if (
            self._projects.get(
                workspace_id=context.workspace_id, project_id=project_id
            )
            is None
        ):
            raise _not_found()

    def _validate_pause_statuses(self, pause_statuses: list | None) -> list:
        from eventflow_work_management.models.enums import WORK_ITEM_STATUS_VALUES

        values = list(pause_statuses or ["blocked"])
        for value in values:
            if value not in WORK_ITEM_STATUS_VALUES:
                raise _validation("Unknown pause status.")
        return values

    def create(
        self,
        context,
        *,
        name: str,
        project_id: UUID | None,
        response_minutes: int | None,
        resolution_minutes: int | None,
        timezone: str,
        business_hours: dict | None,
        holidays: list | None,
        pause_statuses: list | None,
        warning_threshold_percent: int,
        activate: bool,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> SlaPolicyOutcome:
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            raise _validation("A policy name must be 1 to 120 characters.")
        self._validate_targets(response_minutes, resolution_minutes)
        if not 1 <= warning_threshold_percent <= 99:
            raise _validation("The warning threshold must be between 1 and 99.")
        hours, holiday_list = self._validate_calendar(
            timezone=timezone, business_hours=business_hours, holidays=holidays
        )
        pause = self._validate_pause_statuses(pause_statuses)
        self._require_project(context, project_id)

        request_fingerprint = fingerprint(
            {
                "operation": POLICY_CREATE_OPERATION,
                "name": name,
                "project_id": str(project_id) if project_id else None,
                "response_minutes": response_minutes,
                "resolution_minutes": resolution_minutes,
                "timezone": timezone,
                "business_hours": hours,
                "holidays": holiday_list,
                "pause_statuses": pause,
                "warning_threshold_percent": warning_threshold_percent,
                "activate": activate,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                POLICY_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                policy = self._policies.get(
                    workspace_id=context.workspace_id,
                    policy_id=UUID(str(replay["policy_id"])),
                )
                if policy is None:
                    raise _not_found()
                return SlaPolicyOutcome(policy=policy, replayed=True)

        latest = self._policies.latest_version(
            workspace_id=context.workspace_id, project_id=project_id, name=name
        )
        version = (latest.version + 1) if latest is not None else 1
        try:
            record = (
                self._idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=POLICY_CREATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            policy = self._policies.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                name=name,
                version=version,
                response_minutes=response_minutes,
                resolution_minutes=resolution_minutes,
                timezone=timezone,
                business_hours=hours,
                holidays=holiday_list,
                pause_statuses=pause,
                warning_threshold_percent=warning_threshold_percent,
                created_by=context.actor_id,
                supersedes_id=latest.id if latest is not None else None,
            )
            if activate:
                self._activate(policy, context)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="sla_policy.created",
                entity_type="sla_policy",
                entity_id=policy.id,
                actor_id=context.actor_id,
                snapshot={
                    "policy_id": str(policy.id),
                    "name": name,
                    "project_id": str(project_id) if project_id else None,
                    "version": version,
                    "status": policy.status,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._idempotency.complete(
                    record, response_status=201, response_body={"policy_id": str(policy.id)}
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    POLICY_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    policy = self._policies.get(
                        workspace_id=context.workspace_id,
                        policy_id=UUID(str(replay["policy_id"])),
                    )
                    if policy is not None:
                        return SlaPolicyOutcome(policy=policy, replayed=True)
            raise _conflict("An SLA policy with this version already exists.")
        except ProblemError:
            self._session.rollback()
            raise
        return SlaPolicyOutcome(policy=policy)

    def create_version(
        self,
        context,
        policy_id: UUID,
        *,
        response_minutes: int | None = None,
        resolution_minutes: int | None = None,
        timezone: str | None = None,
        business_hours: dict | None = None,
        holidays: list | None = None,
        pause_statuses: list | None = None,
        warning_threshold_percent: int | None = None,
        activate: bool = False,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> SlaPolicyOutcome:
        base = self._policies.get(
            workspace_id=context.workspace_id, policy_id=policy_id
        )
        if base is None:
            raise _not_found()
        return self.create(
            context,
            name=base.name,
            project_id=base.project_id,
            response_minutes=(
                base.response_minutes if response_minutes is None else response_minutes
            ),
            resolution_minutes=(
                base.resolution_minutes
                if resolution_minutes is None
                else resolution_minutes
            ),
            timezone=timezone or base.timezone,
            business_hours=(
                base.business_hours if business_hours is None else business_hours
            ),
            holidays=base.holidays if holidays is None else holidays,
            pause_statuses=(
                base.pause_statuses if pause_statuses is None else pause_statuses
            ),
            warning_threshold_percent=(
                base.warning_threshold_percent
                if warning_threshold_percent is None
                else warning_threshold_percent
            ),
            activate=activate,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def activate(
        self,
        context,
        policy_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> SlaPolicyOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": POLICY_ACTIVATE_OPERATION,
                "policy_id": str(policy_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                POLICY_ACTIVATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                policy = self._policies.get(
                    workspace_id=context.workspace_id,
                    policy_id=UUID(str(replay["policy_id"])),
                )
                if policy is None:
                    raise _not_found()
                return SlaPolicyOutcome(policy=policy, replayed=True)
        try:
            policy = self._policies.get_for_update(
                workspace_id=context.workspace_id, policy_id=policy_id
            )
            if policy is None:
                raise _not_found()
            if if_match is not None and if_match != sla_policy_etag(policy):
                raise _precondition_failed()
            if policy.status == "active":
                return SlaPolicyOutcome(policy=policy, replayed=True)
            record = (
                self._idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=POLICY_ACTIVATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            self._activate(policy, context)
            self._audit.append(
                workspace_id=context.workspace_id,
                action="sla_policy.activated",
                entity_type="sla_policy",
                entity_id=policy.id,
                actor_id=context.actor_id,
                snapshot={
                    "policy_id": str(policy.id),
                    "name": policy.name,
                    "version": policy.version,
                    "project_id": str(policy.project_id) if policy.project_id else None,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self._idempotency.complete(
                    record, response_status=200, response_body={"policy_id": str(policy.id)}
                )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return SlaPolicyOutcome(policy=policy)

    def _activate(self, policy: SlaPolicy, context) -> None:
        existing = self._policies.active_by_name(
            workspace_id=policy.workspace_id,
            project_id=policy.project_id,
            name=policy.name,
            exclude_id=policy.id,
        )
        if existing is not None:
            existing.status = "retired"
            existing.retired_at = _now()
        policy.status = "active"
        policy.activated_at = _now()
        policy.retired_at = None

    def get(self, context, policy_id: UUID) -> SlaPolicy:
        policy = self._policies.get(
            workspace_id=context.workspace_id, policy_id=policy_id
        )
        if policy is None:
            raise _not_found()
        return policy

    def list_page(
        self,
        context,
        *,
        project_id: UUID | None,
        status: str | None,
        limit: int,
        after=None,
    ) -> list[SlaPolicy]:
        if status is not None and status not in STATUS_VALUES:
            raise _validation("Unknown SLA policy status filter.")
        return self._policies.list_page(
            workspace_id=context.workspace_id,
            project_id=project_id,
            include_workspace_default=True,
            status=status,
            limit=limit + 1,
            after=after,
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


class SlaService:
    """Instance clocks, pause/resume, fulfilment and breach evaluation."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._policies = SlaPolicyRepository(session)
        self._instances = SlaInstanceRepository(session)
        self._pauses = SlaPauseIntervalRepository(session)
        self._events = SlaEventRepository(session)
        self._notifications = NotificationService(session)
        self._audit = AuditRepository(session)

    # -- resolution / creation -------------------------------------------

    def resolve_policy(self, *, workspace_id: UUID, project_id: UUID) -> SlaPolicy | None:
        return self._policies.active_for_project(
            workspace_id=workspace_id, project_id=project_id
        )

    def ensure_instance(
        self, work_item: WorkItem, *, now: datetime | None = None
    ) -> SlaInstance | None:
        existing = self._instances.get_for_work_item(
            workspace_id=work_item.workspace_id, work_item_id=work_item.id
        )
        if existing is not None:
            return existing
        policy = self.resolve_policy(
            workspace_id=work_item.workspace_id, project_id=work_item.project_id
        )
        if policy is None:
            return None
        moment = now or _now()
        started_at = work_item.created_at
        if started_at is None:
            started_at = moment
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        snapshot = _policy_snapshot(policy)
        response_due = _due_at(started_at, policy, policy.response_minutes)
        resolution_due = _due_at(started_at, policy, policy.resolution_minutes)
        instance = self._instances.add(
            workspace_id=work_item.workspace_id,
            project_id=work_item.project_id,
            work_item_id=work_item.id,
            policy_id=policy.id,
            policy_version=policy.version,
            policy_snapshot=snapshot,
            status="running",
            started_at=started_at,
            response_due_at=response_due,
            resolution_due_at=resolution_due,
            next_evaluation_at=_next_evaluation(
                moment=moment,
                response_due=response_due,
                resolution_due=resolution_due,
                warning_at_response=_warning_at(
                    started_at, snapshot.get("response_minutes"), snapshot
                ),
                warning_at_resolution=_warning_at(
                    started_at, snapshot.get("resolution_minutes"), snapshot
                ),
            ),
        )
        self._events.append(
            workspace_id=work_item.workspace_id,
            instance_id=instance.id,
            event_type="started",
            due_at=started_at,
            occurred_at=moment,
            payload={
                "policy_id": str(policy.id),
                "policy_version": policy.version,
                "response_due_at": response_due.isoformat() if response_due else None,
                "resolution_due_at": (
                    resolution_due.isoformat() if resolution_due else None
                ),
            },
        )
        return instance

    def get_for_work_item(
        self, context, work_item: WorkItem, *, now: datetime | None = None
    ) -> SlaInstance | None:
        moment = now or _now()
        instance = self.ensure_instance(work_item, now=moment)
        if instance is None:
            return None
        self.sync_with_status(work_item, now=moment)
        self.evaluate(instance, work_item, now=moment)
        self._session.commit()
        return instance

    def events_for(self, instance: SlaInstance) -> list:
        return self._events.list_for_instance(
            workspace_id=instance.workspace_id, instance_id=instance.id
        )

    def pauses_for(self, instance: SlaInstance) -> list:
        return self._pauses.list_for_instance(
            workspace_id=instance.workspace_id, instance_id=instance.id
        )

    # -- lifecycle --------------------------------------------------------

    def sync_with_status(self, work_item: WorkItem, *, now: datetime | None = None) -> None:
        moment = now or _now()
        instance = self._instances.get_for_work_item(
            workspace_id=work_item.workspace_id, work_item_id=work_item.id
        )
        if instance is None or instance.status in TERMINAL_INSTANCE_STATUSES:
            return
        pause_statuses = tuple((instance.policy_snapshot or {}).get("pause_statuses", []))
        should_pause = work_item.status in pause_statuses
        if should_pause and instance.status != "paused":
            self._pause(instance, reason=f"status:{work_item.status}", now=moment)
        elif not should_pause and instance.status == "paused":
            self._resume(instance, now=moment)
        if work_item.status == "in_progress" and instance.first_response_at is None:
            instance.first_response_at = moment
        if work_item.status == "done":
            self._fulfil(instance, work_item, now=moment)
        elif work_item.status == "cancelled":
            self._cancel(instance, now=moment)
        self._refresh_next_evaluation(instance, moment=moment)

    def pause_for_status(
        self, work_item: WorkItem, *, reason: str, now: datetime | None = None
    ) -> None:
        instance = self.ensure_instance(work_item, now=now)
        if instance is None or instance.status in TERMINAL_INSTANCE_STATUSES:
            return
        if instance.status != "paused":
            self._pause(instance, reason=reason, now=now or _now())

    def resume_from_status(
        self, work_item: WorkItem, *, now: datetime | None = None
    ) -> None:
        instance = self._instances.get_for_work_item(
            workspace_id=work_item.workspace_id, work_item_id=work_item.id
        )
        if instance is None or instance.status != "paused":
            return
        self._resume(instance, now=now or _now())

    def _pause(self, instance: SlaInstance, *, reason: str, now: datetime) -> None:
        instance.status = "paused"
        instance.active_pause_started_at = now
        instance.next_evaluation_at = None
        instance.version += 1
        self._pauses.open_interval(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            reason=reason,
            started_at=now,
        )
        self._events.append(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            event_type="paused",
            due_at=now,
            occurred_at=now,
            payload={"reason": reason},
        )

    def _resume(self, instance: SlaInstance, *, now: datetime) -> None:
        open_interval = self._pauses.open_for_instance(
            workspace_id=instance.workspace_id, instance_id=instance.id
        )
        if open_interval is not None:
            started = open_interval.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            seconds = max(0, int((now - started).total_seconds()))
            self._pauses.close_interval(open_interval, ended_at=now, seconds=seconds)
            instance.paused_seconds += seconds
            shift = _timedelta_seconds(seconds)
            if instance.response_due_at is not None:
                instance.response_due_at += shift
            if instance.resolution_due_at is not None:
                instance.resolution_due_at += shift
        instance.status = "running"
        instance.active_pause_started_at = None
        instance.version += 1
        self._events.append(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            event_type="resumed",
            due_at=now,
            occurred_at=now,
        )

    def _fulfil(
        self, instance: SlaInstance, work_item: WorkItem, *, now: datetime
    ) -> None:
        if instance.active_pause_started_at is not None:
            open_interval = self._pauses.open_for_instance(
                workspace_id=instance.workspace_id, instance_id=instance.id
            )
            if open_interval is not None:
                started = open_interval.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                seconds = max(0, int((now - started).total_seconds()))
                self._pauses.close_interval(
                    open_interval, ended_at=now, seconds=seconds
                )
                instance.paused_seconds += seconds
            instance.active_pause_started_at = None
        instance.resolved_at = now
        if instance.first_response_at is None:
            instance.first_response_at = now
        breached = (
            instance.breach_response_at is not None
            or instance.breach_resolution_at is not None
        )
        instance.status = "breached" if breached else "fulfilled"
        instance.version += 1
        instance.next_evaluation_at = None
        self._events.append(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            event_type="fulfilled",
            due_at=now,
            occurred_at=now,
        )
        if not breached:
            self._notify(
                instance,
                work_item,
                event_type="sla.fulfilled",
                title=f"SLA fulfilled: {work_item.title}",
                body="The work item was completed within its SLA targets.",
                payload={"resolved_at": now.isoformat()},
                dedup_suffix="fulfilled",
            )

    def _cancel(self, instance: SlaInstance, *, now: datetime) -> None:
        if instance.active_pause_started_at is not None:
            open_interval = self._pauses.open_for_instance(
                workspace_id=instance.workspace_id, instance_id=instance.id
            )
            if open_interval is not None:
                started = open_interval.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                seconds = max(0, int((now - started).total_seconds()))
                self._pauses.close_interval(
                    open_interval, ended_at=now, seconds=seconds
                )
                instance.paused_seconds += seconds
            instance.active_pause_started_at = None
        instance.status = "cancelled"
        instance.cancelled_at = now
        instance.version += 1
        instance.next_evaluation_at = None
        self._events.append(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            event_type="cancelled",
            due_at=now,
            occurred_at=now,
        )

    # -- evaluation -------------------------------------------------------

    def evaluate(
        self, instance: SlaInstance, work_item: WorkItem, *, now: datetime
    ) -> None:
        if instance.status in ("fulfilled", "cancelled", "paused"):
            if instance.status == "paused":
                instance.next_evaluation_at = None
            return
        snapshot = instance.policy_snapshot or {}
        threshold = int(snapshot.get("warning_threshold_percent", 75))
        response_warning = _warning_at(
            instance.started_at,
            snapshot.get("response_minutes"),
            snapshot,
            threshold=threshold,
            paused_seconds=instance.paused_seconds,
        )
        resolution_warning = _warning_at(
            instance.started_at,
            snapshot.get("resolution_minutes"),
            snapshot,
            threshold=threshold,
            paused_seconds=instance.paused_seconds,
        )
        self._maybe_warning(
            instance, work_item, "response", response_warning, now
        )
        self._maybe_warning(
            instance, work_item, "resolution", resolution_warning, now
        )
        self._maybe_breach(instance, work_item, "response", now)
        self._maybe_breach(instance, work_item, "resolution", now)
        if (
            instance.breach_response_at is not None
            or instance.breach_resolution_at is not None
        ):
            instance.status = "breached"
        self._refresh_next_evaluation(instance, moment=now)

    def _record_event(
        self,
        instance: SlaInstance,
        event_type: str,
        due_at: datetime,
        *,
        now: datetime,
        payload: dict | None = None,
    ) -> bool:
        existing = self._events.get(
            instance_id=instance.id, event_type=event_type, due_at=due_at
        )
        if existing is not None:
            return False
        self._events.append(
            workspace_id=instance.workspace_id,
            instance_id=instance.id,
            event_type=event_type,
            due_at=due_at,
            occurred_at=now,
            payload=payload or {},
        )
        return True

    def _maybe_warning(
        self,
        instance: SlaInstance,
        work_item: WorkItem,
        target: str,
        warning_at: datetime | None,
        now: datetime,
    ) -> None:
        if warning_at is None or now < warning_at:
            return
        already = (
            instance.warning_response_at
            if target == "response"
            else instance.warning_resolution_at
        )
        if already is not None:
            return
        if target == "response" and instance.first_response_at is not None:
            return
        if target == "resolution" and instance.resolved_at is not None:
            return
        if not self._record_event(
            instance, f"warning_{target}", warning_at, now=now
        ):
            return
        if target == "response":
            instance.warning_response_at = now
        else:
            instance.warning_resolution_at = now
        self._notify(
            instance,
            work_item,
            event_type="sla.warning",
            title=f"SLA warning: {work_item.title}",
            body=f"The {target} target is approaching for this work item.",
            payload={"target": target, "due_at": warning_at.isoformat()},
            dedup_suffix=f"warning:{target}:{warning_at.isoformat()}",
        )

    def _maybe_breach(
        self,
        instance: SlaInstance,
        work_item: WorkItem,
        target: str,
        now: datetime,
    ) -> None:
        due = (
            instance.response_due_at if target == "response" else instance.resolution_due_at
        )
        if due is None or now < due:
            return
        already = (
            instance.breach_response_at
            if target == "response"
            else instance.breach_resolution_at
        )
        if already is not None:
            return
        if target == "response" and instance.first_response_at is not None:
            return
        if target == "resolution" and instance.resolved_at is not None:
            return
        if not self._record_event(instance, f"breach_{target}", due, now=now):
            return
        if target == "response":
            instance.breach_response_at = now
        else:
            instance.breach_resolution_at = now
        instance.version += 1
        self._notify(
            instance,
            work_item,
            event_type="sla.breached",
            title=f"SLA breached: {work_item.title}",
            body=f"The {target} SLA target was missed for this work item.",
            payload={"target": target, "due_at": due.isoformat()},
            dedup_suffix=f"breach:{target}:{due.isoformat()}",
        )

    def _notify(
        self,
        instance: SlaInstance,
        work_item: WorkItem,
        *,
        event_type: str,
        title: str,
        body: str,
        payload: dict,
        dedup_suffix: str,
    ) -> None:
        title, body, payload = redact_work_item_notification(
            work_item,
            title=title,
            body=body,
            payload={**payload, "work_item_id": str(work_item.id)},
        )
        self._notifications.emit(
            workspace_id=instance.workspace_id,
            recipient_id=work_item.assignee_id,
            event_type=event_type,
            entity_type="work_item",
            entity_id=work_item.id,
            title=title,
            body=body,
            payload=payload,
            dedup_key=f"{event_type}:{instance.id}:{dedup_suffix}",
        )

    def _refresh_next_evaluation(
        self, instance: SlaInstance, *, moment: datetime
    ) -> None:
        if instance.status in TERMINAL_INSTANCE_STATUSES or instance.status == "paused":
            instance.next_evaluation_at = None
            return
        snapshot = instance.policy_snapshot or {}
        threshold = int(snapshot.get("warning_threshold_percent", 75))
        candidates: list[datetime] = []
        if instance.first_response_at is None:
            if instance.response_due_at is not None:
                candidates.append(instance.response_due_at)
            warning = _warning_at(
                instance.started_at,
                snapshot.get("response_minutes"),
                snapshot,
                threshold=threshold,
                paused_seconds=instance.paused_seconds,
            )
            if warning is not None:
                candidates.append(warning)
        if instance.resolved_at is None:
            if instance.resolution_due_at is not None:
                candidates.append(instance.resolution_due_at)
            warning = _warning_at(
                instance.started_at,
                snapshot.get("resolution_minutes"),
                snapshot,
                threshold=threshold,
                paused_seconds=instance.paused_seconds,
            )
            if warning is not None:
                candidates.append(warning)
        future = [item for item in candidates if item > moment]
        instance.next_evaluation_at = (
            min(future) if future else min(candidates) if candidates else None
        )


# -- pure helpers ---------------------------------------------------------


def _policy_snapshot(policy: SlaPolicy) -> dict:
    return {
        "policy_id": str(policy.id),
        "name": policy.name,
        "version": policy.version,
        "response_minutes": policy.response_minutes,
        "resolution_minutes": policy.resolution_minutes,
        "timezone": policy.timezone,
        "business_hours": policy.business_hours,
        "holidays": policy.holidays,
        "pause_statuses": policy.pause_statuses,
        "warning_threshold_percent": policy.warning_threshold_percent,
    }


def _due_at(started_at: datetime, policy: SlaPolicy, minutes: int | None) -> datetime | None:
    if minutes is None:
        return None
    return add_working_minutes(
        started_at,
        minutes,
        timezone=policy.timezone,
        business_hours=policy.business_hours,
        holidays=policy.holidays,
    )


def _warning_at(
    started_at: datetime,
    minutes: int | None,
    snapshot: dict,
    *,
    threshold: int | None = None,
    paused_seconds: int = 0,
) -> datetime | None:
    if minutes is None:
        return None
    percent = (
        threshold
        if threshold is not None
        else int(snapshot.get("warning_threshold_percent", 75))
    )
    return warning_at(
        started_at,
        minutes,
        percent,
        timezone=snapshot.get("timezone", "UTC"),
        business_hours=snapshot.get("business_hours"),
        holidays=snapshot.get("holidays"),
        paused_seconds=paused_seconds,
    )


def _timedelta_seconds(seconds: int):
    return timedelta(seconds=seconds)


def _next_evaluation(
    *,
    moment: datetime,
    response_due: datetime | None,
    resolution_due: datetime | None,
    warning_at_response: datetime | None,
    warning_at_resolution: datetime | None,
) -> datetime | None:
    candidates = [
        item
        for item in (
            response_due,
            resolution_due,
            warning_at_response,
            warning_at_resolution,
        )
        if item is not None
    ]
    if not candidates:
        return None
    future = [item for item in candidates if item > moment]
    return min(future) if future else min(candidates)
