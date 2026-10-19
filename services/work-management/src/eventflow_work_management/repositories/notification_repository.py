"""Persistence for durable notifications, preferences and deliveries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from eventflow_work_management.repositories.base import Repository


class NotificationRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        recipient_id: UUID,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        title: str,
        body: str,
        payload: dict,
        dedup_key: str,
    ) -> Notification:
        notification = Notification(
            id=uuid4(),
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
        self._session.add(notification)
        self._session.flush()
        return notification

    def get_by_dedup(
        self, *, workspace_id: UUID, dedup_key: str
    ) -> Notification | None:
        statement = select(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.dedup_key == dedup_key,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get(self, *, workspace_id: UUID, notification_id: UUID) -> Notification | None:
        statement = select(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.id == notification_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, notification_id: UUID
    ) -> Notification | None:
        statement = (
            select(Notification)
            .where(
                Notification.workspace_id == workspace_id,
                Notification.id == notification_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        recipient_id: UUID,
        unread_only: bool,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[Notification]:
        statement = select(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.recipient_id == recipient_id,
        )
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        if after is not None:
            statement = statement.where(
                tuple_(Notification.created_at, Notification.id) > after
            )
        statement = statement.order_by(
            Notification.created_at, Notification.id
        ).limit(limit)
        return list(self._session.execute(statement).scalars())

    def unread_count(self, *, workspace_id: UUID, recipient_id: UUID) -> int:
        statement = select(func.count()).select_from(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.recipient_id == recipient_id,
            Notification.read_at.is_(None),
        )
        return int(self._session.execute(statement).scalar_one())


class NotificationPreferenceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def list_for_recipient(
        self, *, workspace_id: UUID, recipient_id: UUID
    ) -> list[NotificationPreference]:
        statement = (
            select(NotificationPreference)
            .where(
                NotificationPreference.workspace_id == workspace_id,
                NotificationPreference.recipient_id == recipient_id,
            )
            .order_by(NotificationPreference.event_type)
        )
        return list(self._session.execute(statement).scalars())

    def get(
        self, *, workspace_id: UUID, recipient_id: UUID, event_type: str
    ) -> NotificationPreference | None:
        statement = select(NotificationPreference).where(
            NotificationPreference.workspace_id == workspace_id,
            NotificationPreference.recipient_id == recipient_id,
            NotificationPreference.event_type == event_type,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def upsert(
        self,
        *,
        workspace_id: UUID,
        recipient_id: UUID,
        event_type: str,
        in_app: bool,
        email: bool,
    ) -> NotificationPreference:
        preference = self.get(
            workspace_id=workspace_id,
            recipient_id=recipient_id,
            event_type=event_type,
        )
        if preference is None:
            preference = NotificationPreference(
                id=uuid4(),
                workspace_id=workspace_id,
                recipient_id=recipient_id,
                event_type=event_type,
                in_app=in_app,
                email=email,
            )
            self._session.add(preference)
        elif preference.in_app != in_app or preference.email != email:
            preference.in_app = in_app
            preference.email = email
            preference.version += 1
        self._session.flush()
        return preference

    def enabled_channels(
        self, *, workspace_id: UUID, recipient_id: UUID, event_type: str
    ) -> tuple[bool, bool]:
        """Return ``(in_app, email)``; defaults are in-app on, email off."""
        preference = self.get(
            workspace_id=workspace_id,
            recipient_id=recipient_id,
            event_type=event_type,
        )
        if preference is None:
            return True, False
        return preference.in_app, preference.email


class NotificationDeliveryRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        notification_id: UUID,
        channel: str,
        status: str = "pending",
        next_attempt_at: datetime | None = None,
    ) -> NotificationDelivery:
        delivery = NotificationDelivery(
            id=uuid4(),
            workspace_id=workspace_id,
            notification_id=notification_id,
            channel=channel,
            status=status,
            next_attempt_at=next_attempt_at,
        )
        self._session.add(delivery)
        self._session.flush()
        return delivery

    def get_by_notification(
        self, *, notification_id: UUID
    ) -> list[NotificationDelivery]:
        statement = (
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.channel)
        )
        return list(self._session.execute(statement).scalars())

    def list_due(self, *, now: datetime, limit: int) -> list[NotificationDelivery]:
        statement = (
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(("pending", "failed")),
                NotificationDelivery.next_attempt_at.is_not(None),
                NotificationDelivery.next_attempt_at <= now,
            )
            .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.execute(statement).scalars())
