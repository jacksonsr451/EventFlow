"""Identity, OIDC transaction, session and authentication audit persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    check_in,
    check_regex,
)

HEX_DIGEST = "^[0-9a-f]{64}$"


class ExternalIdentity(TimestampMixin, Base):
    """Stable internal UUID mapped to one OIDC issuer/subject pair."""

    __tablename__ = "external_identities"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "issuer", "subject", name="uq_external_identities_issuer_subject"
        ),
        CheckConstraint("char_length(issuer) BETWEEN 1 AND 512", name="issuer_length"),
        CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 255", name="subject_length"
        ),
        Index("ix_external_identities_subject", "subject"),
    )


class AuthenticationSession(CreatedAtMixin, Base):
    """Server-side BFF session; browser receives only the opaque cookie token."""

    __tablename__ = "authentication_sessions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    identity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("session_token_digest", name="uq_auth_sessions_token_digest"),
        CheckConstraint(
            check_regex("session_token_digest", HEX_DIGEST), name="token_digest_format"
        ),
        CheckConstraint(
            check_regex("csrf_token_digest", HEX_DIGEST), name="csrf_digest_format"
        ),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at", name="idle_before_absolute_expiry"
        ),
        CheckConstraint(
            "char_length(client_id) BETWEEN 1 AND 80", name="client_id_length"
        ),
        CheckConstraint(
            check_in("source", ("web", "desktop", "vscode")), name="source_values"
        ),
        CheckConstraint(
            "revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64",
            name="revoke_reason_length",
        ),
        Index("ix_auth_sessions_identity_id", "identity_id"),
        Index("ix_auth_sessions_expiry", "idle_expires_at", "absolute_expires_at"),
    )


class OIDCLoginTransaction(CreatedAtMixin, Base):
    """One-use OAuth state, nonce, browser binding and encrypted PKCE verifier."""

    __tablename__ = "oidc_login_transactions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("state_digest", name="uq_oidc_transactions_state_digest"),
        CheckConstraint(
            check_regex("state_digest", HEX_DIGEST), name="state_digest_format"
        ),
        CheckConstraint(
            check_regex("browser_binding_digest", HEX_DIGEST),
            name="browser_digest_format",
        ),
        CheckConstraint(
            check_regex("nonce_digest", HEX_DIGEST), name="nonce_digest_format"
        ),
        CheckConstraint(
            "char_length(redirect_uri) BETWEEN 1 AND 2048", name="redirect_uri_length"
        ),
        Index("ix_oidc_transactions_expiry", "expires_at"),
    )


class AuthenticationSecurityEvent(CreatedAtMixin, Base):
    """Global authentication audit event, separate from workspace-scoped audit rows."""

    __tablename__ = "authentication_security_events"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    subject: Mapped[str | None] = mapped_column(String(256))
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            check_in(
                "event_type",
                (
                    "auth.failure",
                    "auth.success",
                    "auth.replay_detected",
                    "auth.refresh_success",
                    "auth.refresh_failure",
                    "auth.logout",
                    "session.created",
                    "session.expired",
                    "session.revoked",
                    "authz.denial",
                    "credential.revoked",
                ),
            ),
            name="event_type_values",
        ),
        CheckConstraint(
            check_in("severity", ("info", "low", "medium", "high", "critical")),
            name="severity_values",
        ),
        CheckConstraint(
            check_in("outcome", ("success", "denied", "failure")), name="outcome_values"
        ),
        CheckConstraint(
            check_in(
                "actor_type", ("user", "service", "integration", "system", "unknown")
            ),
            name="actor_type_values",
        ),
        CheckConstraint(
            check_in("source", ("web", "desktop", "vscode", "backend", "scheduler")),
            name="source_values",
        ),
        CheckConstraint(
            "actor_id IS NULL OR char_length(actor_id) BETWEEN 1 AND 128",
            name="actor_id_length",
        ),
        CheckConstraint(
            "subject IS NULL OR char_length(subject) BETWEEN 1 AND 256",
            name="subject_length",
        ),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        Index("ix_auth_security_events_occurred_at", "occurred_at"),
        Index("ix_auth_security_events_type_time", "event_type", "occurred_at"),
    )
