"""Persistence helpers for trusted identities and authentication audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from eventflow_work_management.models.authentication import (
    AuthenticationSecurityEvent,
    ExternalIdentity,
)


class DisabledIdentityError(RuntimeError):
    """The verified provider identity is disabled in EventFlow."""


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_or_create(
        self, *, issuer: str, subject: str
    ) -> tuple[ExternalIdentity, bool]:
        """Resolve one provider identity; INSERT .. ON CONFLICT handles first-login races."""
        statement = (
            insert(ExternalIdentity)
            .values(id=uuid4(), issuer=issuer, subject=subject)
            .on_conflict_do_nothing(index_elements=["issuer", "subject"])
            .returning(ExternalIdentity.id)
        )
        inserted_id = self.session.execute(statement).scalar_one_or_none()
        created = inserted_id is not None
        identity = self.session.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
            )
        ).scalar_one()
        if identity.disabled_at is not None:
            raise DisabledIdentityError("identity is disabled")
        return identity, created


class AuthenticationAuditRepository:
    """Append-only authentication event writer using the global security boundary."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        event_type: str,
        outcome: str,
        severity: str = "info",
        actor_id: UUID | None = None,
        subject: str | None = None,
        correlation_id: UUID | None = None,
        source: str = "backend",
        reason: str | None = None,
    ) -> AuthenticationSecurityEvent:
        details = {"reason": reason} if reason else {}
        event = AuthenticationSecurityEvent(
            id=uuid4(),
            event_type=event_type,
            severity=severity,
            outcome=outcome,
            actor_type="user" if actor_id else "unknown",
            actor_id=str(actor_id) if actor_id else None,
            subject=subject,
            correlation_id=correlation_id,
            source=source,
            details=details,
            occurred_at=datetime.now(UTC),
        )
        self.session.add(event)
        return event
