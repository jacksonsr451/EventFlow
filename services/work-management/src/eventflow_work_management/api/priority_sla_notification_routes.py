"""Business priority, SLA, dependency and notification routes (Issue #30).

Tenant isolation is uniform: the workspace always comes from the verified path
and the resolved membership, never from a request body. Priority overrides, SLA
policy management and dependency mutations require their own RBAC actions;
notification reads and preferences are personal to the authenticated actor.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    authenticated_principal,
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import (
    Notification,
    NotificationPreference,
    SlaEvent,
    SlaInstance,
    SlaPauseInterval,
    SlaPolicy,
    WorkItemDependency,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.dependencies import DependencyService
from eventflow_work_management.services.notifications import NotificationService
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)
from eventflow_work_management.services.priority_management import PriorityService
from eventflow_work_management.services.sla import (
    SlaPolicyService,
    SlaService,
    sla_instance_etag,
    sla_policy_etag,
)

router = APIRouter(tags=["Priority, SLA and notifications"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
PRIORITY_PATTERN = "^(critical|high|medium|low)$"
IMPACT_PATTERN = "^(critical|high|moderate|low)$"
URGENCY_PATTERN = "^(immediate|elevated|normal|low)$"
POLICY_STATUS_PATTERN = "^(draft|active|retired)$"
EVENT_PATTERN = (
    "^(dependency\\.created|dependency\\.removed|sla\\.warning|sla\\.breached|"
    "sla\\.fulfilled|work_item\\.priority_overridden|work_item\\.blocked)$"
)


class CalendarModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    business_hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    holidays: list[str] = Field(default_factory=list)
    pause_statuses: list[str] = Field(default_factory=lambda: ["blocked"])


class CreateSlaPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    response_minutes: int | None = Field(default=None, ge=1)
    resolution_minutes: int | None = Field(default=None, ge=1)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    business_hours: dict[str, list[list[str]]] = Field(default_factory=dict)
    holidays: list[str] = Field(default_factory=list)
    pause_statuses: list[str] = Field(default_factory=lambda: ["blocked"])
    warning_threshold_percent: int = Field(default=75, ge=1, le=99)
    activate: bool = False


class CreateSlaPolicyVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_minutes: int | None = Field(default=None, ge=1)
    resolution_minutes: int | None = Field(default=None, ge=1)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    business_hours: dict[str, list[list[str]]] | None = None
    holidays: list[str] | None = None
    pause_statuses: list[str] | None = None
    warning_threshold_percent: int | None = Field(default=None, ge=1, le=99)
    activate: bool = False


class OverridePriorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: str = Field(pattern=PRIORITY_PATTERN)
    reason: str = Field(min_length=10, max_length=300)


class CreateDependencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocking_work_item_id: UUID


class MarkNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool


class UpdatePreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_app: bool
    email: bool


def _authorize(session, principal, workspace_id, action):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


def _idempotency_key(request: Request) -> str | None:
    supplied = request.headers.get("idempotency-key")
    if supplied is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.match(supplied):
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is malformed.",
            title="Invalid request",
        )
    return supplied


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _collection_etag(workspace_id: UUID, parts: list[str], *extra: object) -> str:
    return '"' + fingerprint([str(workspace_id), parts, *extra]) + '"'


def _notification_etag(notification: Notification) -> str:
    return '"' + fingerprint(
        [
            str(notification.id),
            notification.read_at.isoformat() if notification.read_at else None,
        ]
    ) + '"'


def _preference_etag(preference: NotificationPreference) -> str:
    return '"' + fingerprint(
        [str(preference.id), preference.version, str(preference.updated_at)]
    ) + '"'


def _policy_payload(policy: SlaPolicy) -> dict:
    return {
        "policy_id": policy.id,
        "workspace_id": policy.workspace_id,
        "project_id": policy.project_id,
        "name": policy.name,
        "version": policy.version,
        "status": policy.status,
        "response_minutes": policy.response_minutes,
        "resolution_minutes": policy.resolution_minutes,
        "timezone": policy.timezone,
        "business_hours": policy.business_hours,
        "holidays": policy.holidays,
        "pause_statuses": policy.pause_statuses,
        "warning_threshold_percent": policy.warning_threshold_percent,
        "created_by": policy.created_by,
        "activated_at": policy.activated_at,
        "retired_at": policy.retired_at,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def _event_payload(event: SlaEvent) -> dict:
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "due_at": event.due_at,
        "occurred_at": event.occurred_at,
        "payload": event.payload,
    }


def _pause_payload(pause: SlaPauseInterval) -> dict:
    return {
        "pause_id": pause.id,
        "reason": pause.reason,
        "started_at": pause.started_at,
        "ended_at": pause.ended_at,
        "seconds": pause.seconds,
    }


def _instance_payload(instance: SlaInstance) -> dict:
    return {
        "sla_instance_id": instance.id,
        "work_item_id": instance.work_item_id,
        "project_id": instance.project_id,
        "policy_id": instance.policy_id,
        "policy_version": instance.policy_version,
        "policy_snapshot": instance.policy_snapshot,
        "status": instance.status,
        "started_at": instance.started_at,
        "response_due_at": instance.response_due_at,
        "resolution_due_at": instance.resolution_due_at,
        "first_response_at": instance.first_response_at,
        "resolved_at": instance.resolved_at,
        "paused_seconds": instance.paused_seconds,
        "warning_response_at": instance.warning_response_at,
        "warning_resolution_at": instance.warning_resolution_at,
        "breach_response_at": instance.breach_response_at,
        "breach_resolution_at": instance.breach_resolution_at,
        "next_evaluation_at": instance.next_evaluation_at,
        "updated_at": instance.updated_at,
    }


def _dependency_payload(edge: WorkItemDependency) -> dict:
    return {
        "dependency_id": edge.id,
        "blocking_work_item_id": edge.blocking_work_item_id,
        "blocked_work_item_id": edge.blocked_work_item_id,
        "created_by": edge.created_by,
        "created_at": edge.created_at,
    }


def _notification_payload(notification: Notification) -> dict:
    return {
        "notification_id": notification.id,
        "event_type": notification.event_type,
        "entity_type": notification.entity_type,
        "entity_id": notification.entity_id,
        "title": notification.title,
        "body": notification.body,
        "payload": notification.payload,
        "read_at": notification.read_at,
        "created_at": notification.created_at,
    }


def _preference_payload(preference: NotificationPreference) -> dict:
    return {
        "event_type": preference.event_type,
        "in_app": preference.in_app,
        "email": preference.email,
        "version": preference.version,
        "updated_at": preference.updated_at,
    }


# -- SLA policies ---------------------------------------------------------


@router.post("/v1/workspaces/{workspace_id}/sla-policies", status_code=201)
def create_sla_policy(
    workspace_id: UUID,
    payload: CreateSlaPolicyRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_POLICY_MANAGE)
    outcome = SlaPolicyService(session).create(
        context,
        name=payload.name,
        project_id=payload.project_id,
        response_minutes=payload.response_minutes,
        resolution_minutes=payload.resolution_minutes,
        timezone=payload.timezone,
        business_hours=payload.business_hours,
        holidays=payload.holidays,
        pause_statuses=payload.pause_statuses,
        warning_threshold_percent=payload.warning_threshold_percent,
        activate=payload.activate,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = sla_policy_etag(outcome.policy)
    return _policy_payload(outcome.policy)


@router.get("/v1/workspaces/{workspace_id}/sla-policies")
def list_sla_policies(
    workspace_id: UUID,
    response: Response,
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, pattern=POLICY_STATUS_PATTERN),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_POLICY_READ)
    after = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
            after = (decoded["created_at"], decoded["id"])
        except (CursorError, KeyError):
            raise _validation("The pagination cursor is invalid.")
    rows = SlaPolicyService(session).list_page(
        context,
        project_id=project_id,
        status=status,
        limit=limit,
        after=after,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor({"created_at": page[-1].created_at}, page[-1].id)
        if has_more and page
        else None
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.version}{item.updated_at.isoformat()}" for item in page],
        next_cursor,
    )
    return {
        "items": [_policy_payload(item) for item in page],
        "page_info": {"has_more": has_more, "next_cursor": next_cursor},
    }


@router.get("/v1/workspaces/{workspace_id}/sla-policies/{policy_id}")
def get_sla_policy(
    workspace_id: UUID,
    policy_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_POLICY_READ)
    policy = SlaPolicyService(session).get(context, policy_id)
    response.headers["ETag"] = sla_policy_etag(policy)
    return _policy_payload(policy)


@router.post("/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/versions", status_code=201)
def create_sla_policy_version(
    workspace_id: UUID,
    policy_id: UUID,
    payload: CreateSlaPolicyVersionRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_POLICY_MANAGE)
    outcome = SlaPolicyService(session).create_version(
        context,
        policy_id,
        response_minutes=payload.response_minutes,
        resolution_minutes=payload.resolution_minutes,
        timezone=payload.timezone,
        business_hours=payload.business_hours,
        holidays=payload.holidays,
        pause_statuses=payload.pause_statuses,
        warning_threshold_percent=payload.warning_threshold_percent,
        activate=payload.activate,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = sla_policy_etag(outcome.policy)
    return _policy_payload(outcome.policy)


@router.post("/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/activate")
def activate_sla_policy(
    workspace_id: UUID,
    policy_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_POLICY_MANAGE)
    outcome = SlaPolicyService(session).activate(
        context,
        policy_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = sla_policy_etag(outcome.policy)
    return _policy_payload(outcome.policy)


# -- WorkItem SLA ---------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/work-items/{work_item_id}/sla")
def get_work_item_sla(
    workspace_id: UUID,
    work_item_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.SLA_READ)
    service = SlaService(session)
    work_item = PriorityService(session).get(context, work_item_id)
    instance = service.get_for_work_item(context, work_item)
    if instance is None:
        response.headers["ETag"] = _collection_etag(workspace_id, ["no-sla", str(work_item_id)])
        return {
            "work_item_id": work_item_id,
            "instance": None,
            "events": [],
            "pauses": [],
        }
    events = service.events_for(instance)
    pauses = service.pauses_for(instance)
    response.headers["ETag"] = sla_instance_etag(instance)
    return {
        "work_item_id": work_item_id,
        "instance": _instance_payload(instance),
        "events": [_event_payload(event) for event in events],
        "pauses": [_pause_payload(pause) for pause in pauses],
    }


# -- priority override ----------------------------------------------------


@router.patch("/v1/workspaces/{workspace_id}/work-items/{work_item_id}/priority")
def override_priority(
    workspace_id: UUID,
    work_item_id: UUID,
    payload: OverridePriorityRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PRIORITY_OVERRIDE)
    work_item = PriorityService(session).override(
        context,
        work_item_id,
        priority=payload.priority,
        reason=payload.reason,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    from eventflow_work_management.services.board_management import work_item_etag

    response.headers["ETag"] = work_item_etag(work_item)
    return {
        "work_item_id": work_item.id,
        "priority": work_item.priority,
        "calculated_priority": work_item.calculated_priority,
        "priority_override_reason": work_item.priority_override_reason,
        "priority_overridden_by": work_item.priority_overridden_by,
    }


# -- dependencies ---------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies")
def list_dependencies(
    workspace_id: UUID,
    work_item_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.DEPENDENCY_READ)
    result = DependencyService(session).list(context, work_item_id)
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [str(edge.id) for edge in result.blockers + result.dependents],
        str(work_item_id),
    )
    return {
        "work_item_id": result.work_item.id,
        "blockers": [_dependency_payload(edge) for edge in result.blockers],
        "dependents": [_dependency_payload(edge) for edge in result.dependents],
        "unresolved_blocker_ids": [
            str(item) for item in result.unresolved_blocker_ids
        ],
    }


@router.post(
    "/v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies",
    status_code=201,
)
def create_dependency(
    workspace_id: UUID,
    work_item_id: UUID,
    payload: CreateDependencyRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.DEPENDENCY_MANAGE)
    outcome = DependencyService(session).create(
        context,
        work_item_id,
        blocking_work_item_id=payload.blocking_work_item_id,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies/"
        f"{outcome.edge.id}"
    )
    response.headers["ETag"] = '"' + fingerprint([str(outcome.edge.id)]) + '"'
    return _dependency_payload(outcome.edge)


@router.delete(
    "/v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies/{dependency_id}",
    status_code=204,
)
def delete_dependency(
    workspace_id: UUID,
    work_item_id: UUID,
    dependency_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.DEPENDENCY_MANAGE)
    DependencyService(session).delete(
        context,
        work_item_id,
        dependency_id,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.status_code = 204
    return response


# -- notifications --------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/notifications")
def list_notifications(
    workspace_id: UUID,
    response: Response,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.NOTIFICATION_READ)
    after = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor)
            after = (decoded["created_at"], decoded["id"])
        except (CursorError, KeyError):
            raise _validation("The pagination cursor is invalid.")
    rows, unread = NotificationService(session).list_page(
        context, unread_only=unread_only, limit=limit, after=after
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor({"created_at": page[-1].created_at}, page[-1].id)
        if has_more and page
        else None
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [f"{item.id}{item.read_at.isoformat() if item.read_at else ''}" for item in page],
        next_cursor,
    )
    return {
        "items": [_notification_payload(item) for item in page],
        "unread_count": unread,
        "page_info": {"has_more": has_more, "next_cursor": next_cursor},
    }


@router.patch("/v1/workspaces/{workspace_id}/notifications/{notification_id}")
def mark_notification(
    workspace_id: UUID,
    notification_id: UUID,
    payload: MarkNotificationRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.NOTIFICATION_PREFERENCE_MANAGE
    )
    notification = NotificationService(session).mark_read(
        context, notification_id, read=payload.read
    )
    response.headers["ETag"] = _notification_etag(notification)
    return _notification_payload(notification)


@router.get("/v1/workspaces/{workspace_id}/notification-preferences")
def list_notification_preferences(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.NOTIFICATION_READ)
    preferences = NotificationService(session).list_preferences(context)
    response.headers["ETag"] = _collection_etag(
        workspace_id, [str(item.id) for item in preferences]
    )
    return {"items": [_preference_payload(item) for item in preferences]}


@router.put(
    "/v1/workspaces/{workspace_id}/notification-preferences/{event_type}"
)
def update_notification_preference(
    workspace_id: UUID,
    event_type: str,
    payload: UpdatePreferenceRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    if not re.match(EVENT_PATTERN, event_type):
        raise _validation("Unknown notification event type.")
    context = _authorize(
        session, principal, workspace_id, Action.NOTIFICATION_PREFERENCE_MANAGE
    )
    preference = NotificationService(session).update_preference(
        context, event_type=event_type, in_app=payload.in_app, email=payload.email
    )
    response.headers["ETag"] = _preference_etag(preference)
    return _preference_payload(preference)
