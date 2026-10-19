"""Durable notification service and dispatcher (Issue #30).

Domain services call :class:`NotificationService` inside their own transaction.
The service never performs network I/O: it writes a notification row plus its
delivery rows, and a separate worker drains deliveries. This keeps external
delivery outside database transactions and makes at-least-once delivery
explicit. There is no claim of exactly-once external delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from eventflow_work_management.repositories.notification_repository import (
    NotificationDeliveryRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
)
from eventflow_work_management.security.errors import ProblemError

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30
_MAX_ERROR_LENGTH = 300


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404,
        code="NOT_FOUND",
        detail="The requested resource was not found.",
        title="Not found",
    )


@dataclass(frozen=True)
class NotificationOutcome:
    notification: Notification
    replayed: bool = False


class NotificationService:
    """Writes durable notifications with deduplication and delivery rows."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._notifications = NotificationRepository(session)
        self._preferences = NotificationPreferenceRepository(session)
        self._deliveries = NotificationDeliveryRepository(session)

    def emit(
        self,
        *,
        workspace_id: UUID,
        recipient_id: UUID | None,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        title: str,
        body: str,
        payload: dict,
        dedup_key: str,
    ) -> Notification | None:
        """Create one notification unless its dedup key already exists.

        A ``None`` recipient is a no-op: notifications are only ever addressed
        to a trusted identity, never to a client-supplied one.
        """
        if recipient_id is None:
            return None
        existing = self._notifications.get_by_dedup(
            workspace_id=workspace_id, dedup_key=dedup_key
        )
        if existing is not None:
            return existing
        occurred = _now()
        notification = self._notifications.add(
            workspace_id=workspace_id,
            recipient_id=recipient_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            body=body,
            payload=payload,
            dedup_key=dedup_key,
        )
        in_app, email = self._preferences.enabled_channels(
            workspace_id=workspace_id,
            recipient_id=recipient_id,
            event_type=event_type,
        )
        if in_app:
            delivery = self._deliveries.add(
                workspace_id=workspace_id,
                notification_id=notification.id,
                channel="in_app",
            )
            delivery.status = "delivered"
            delivery.delivered_at = occurred
            delivery.attempts = 1
        if email:
            self._deliveries.add(
                workspace_id=workspace_id,
                notification_id=notification.id,
                channel="email",
                status="pending",
                next_attempt_at=occurred,
            )
        return notification

    def list_page(
        self,
        context,
        *,
        unread_only: bool = False,
        limit: int,
        after=None,
    ) -> tuple[list[Notification], int]:
        rows = self._notifications.list_page(
            workspace_id=context.workspace_id,
            recipient_id=context.actor_id,
            unread_only=unread_only,
            limit=limit + 1,
            after=after,
        )
        unread = self._notifications.unread_count(
            workspace_id=context.workspace_id, recipient_id=context.actor_id
        )
        return rows, unread

    def mark_read(
        self, context, notification_id: UUID, *, read: bool
    ) -> Notification:
        notification = self._notifications.get_for_update(
            workspace_id=context.workspace_id, notification_id=notification_id
        )
        if notification is None or notification.recipient_id != context.actor_id:
            raise _not_found()
        notification.read_at = _now() if read else None
        self._session.commit()
        return notification

    def unread_count(self, context) -> int:
        return self._notifications.unread_count(
            workspace_id=context.workspace_id, recipient_id=context.actor_id
        )

    def list_preferences(self, context) -> list[NotificationPreference]:
        return self._preferences.list_for_recipient(
            workspace_id=context.workspace_id, recipient_id=context.actor_id
        )

    def update_preference(
        self, context, *, event_type: str, in_app: bool, email: bool
    ) -> NotificationPreference:
        preference = self._preferences.upsert(
            workspace_id=context.workspace_id,
            recipient_id=context.actor_id,
            event_type=event_type,
            in_app=in_app,
            email=email,
        )
        self._session.commit()
        return preference

    def deliveries_for(self, notification_id: UUID) -> list[NotificationDelivery]:
        return self._deliveries.get_by_notification(notification_id=notification_id)


class NotificationDispatcher:
    """Drains pending deliveries with retry, backoff and terminal states.

    The default channel adapters are intentionally inert: with no provider
    configured an ``email`` delivery is marked ``unavailable`` rather than
    pretending it was delivered.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._deliveries = NotificationDeliveryRepository(session)

    def run_once(self, *, now: datetime | None = None, limit: int = 100) -> int:
        moment = now or _now()
        processed = 0
        for delivery in self._deliveries.list_due(now=moment, limit=limit):
            delivered, error = self._dispatch(delivery)
            delivery.attempts += 1
            if delivered:
                delivery.status = "delivered"
                delivery.delivered_at = moment
                delivery.last_error = None
                delivery.next_attempt_at = None
            else:
                delivery.last_error = (error or "delivery failed")[:_MAX_ERROR_LENGTH]
                if delivery.attempts >= MAX_ATTEMPTS:
                    delivery.status = "exhausted"
                    delivery.next_attempt_at = None
                else:
                    delivery.status = "failed"
                    delay = BASE_BACKOFF_SECONDS * (2 ** (delivery.attempts - 1))
                    delivery.next_attempt_at = moment + timedelta(seconds=delay)
            processed += 1
        self._session.commit()
        return processed

    @staticmethod
    def _dispatch(delivery: NotificationDelivery) -> tuple[bool, str | None]:
        if delivery.channel == "in_app":
            return True, None
        return False, "no email transport is configured"
