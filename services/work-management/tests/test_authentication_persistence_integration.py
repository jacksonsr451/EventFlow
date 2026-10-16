"""PostgreSQL integration tests for authentication persistence guarantees."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock

import testrunner
from eventflow_work_management.models.authentication import (
    AuthenticationSecurityEvent,
    AuthenticationSession,
    ExternalIdentity,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher, digest_token
from eventflow_work_management.security.errors import AuthenticationError
from eventflow_work_management.security.oidc import TokenSet
from eventflow_work_management.security.repository import (
    AuthenticationAuditRepository,
    IdentityRepository,
)
from eventflow_work_management.security.service import AuthenticationService
from sqlalchemy import select, text
from support import require_database_url, session_scope, temporary_database


def test_external_issuer_subject_is_unique_and_resolves_stably():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            first, created = IdentityRepository(session).resolve_or_create(
                issuer="https://id.example.test/realms/eventflow",
                subject="opaque-subject-123",
            )
            session.commit()
            assert created is True
            internal_id = first.id

        with session_scope(engine) as session:
            second, created = IdentityRepository(session).resolve_or_create(
                issuer="https://id.example.test/realms/eventflow",
                subject="opaque-subject-123",
            )
            session.commit()
            assert created is False
            assert second.id == internal_id


def test_concurrent_first_login_maps_to_one_internal_identity():
    with temporary_database(require_database_url()) as (_, engine):
        barrier = Barrier(2)

        def resolve():
            with session_scope(engine) as session:
                barrier.wait(timeout=10)
                identity, created = IdentityRepository(session).resolve_or_create(
                    issuer="https://id.example.test/realms/eventflow",
                    subject="concurrent-subject-456",
                )
                session.commit()
                return identity.id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: resolve(), range(2)))
        assert results[0][0] == results[1][0]
        assert sum(1 for _, created in results if created) == 1
        with session_scope(engine) as session:
            identities = (
                session.execute(
                    select(ExternalIdentity).where(
                        ExternalIdentity.issuer
                        == "https://id.example.test/realms/eventflow",
                        ExternalIdentity.subject == "concurrent-subject-456",
                    )
                )
                .scalars()
                .all()
            )
            assert len(identities) == 1


def test_session_credentials_are_encrypted_and_cookie_values_are_digested():
    cipher = TokenCipher((TokenCipher.generate_key(),))
    raw_cookie = "opaque-session-cookie-secret"
    raw_csrf = "opaque-csrf-token-secret"
    raw_access = "opaque-access-token-secret"
    raw_refresh = "opaque-refresh-token-secret"
    now = datetime.now(UTC)
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            identity, _ = IdentityRepository(session).resolve_or_create(
                issuer="https://id.example.test/realms/eventflow",
                subject="session-subject-789",
            )
            record = AuthenticationSession(
                identity_id=identity.id,
                session_token_digest=digest_token(raw_cookie),
                csrf_token_digest=digest_token(raw_csrf),
                csrf_token_ciphertext=cipher.encrypt(raw_csrf),
                client_id="eventflow-web-bff",
                source="web",
                access_token_ciphertext=cipher.encrypt(raw_access),
                refresh_token_ciphertext=cipher.encrypt(raw_refresh),
                access_expires_at=now + timedelta(minutes=5),
                refresh_expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                idle_expires_at=now + timedelta(minutes=30),
                absolute_expires_at=now + timedelta(hours=12),
            )
            session.add(record)
            session.commit()
            session_id = record.id

        with session_scope(engine) as session:
            record = session.get(AuthenticationSession, session_id)
            assert record is not None
            assert record.session_token_digest == digest_token(raw_cookie)
            assert raw_cookie not in record.session_token_digest
            assert raw_access not in record.access_token_ciphertext
            assert raw_refresh not in record.refresh_token_ciphertext
            assert cipher.decrypt(record.access_token_ciphertext) == raw_access
            assert cipher.decrypt(record.refresh_token_ciphertext) == raw_refresh


def test_expired_session_is_revoked_and_revoked_session_is_rejected():
    now = datetime.now(UTC)
    encryption_key = TokenCipher.generate_key()
    settings = AuthSettings(
        environment="test",
        issuer="https://id.example.test/realms/eventflow",
        audience="eventflow-api",
        web_client_id="eventflow-web-bff",
        native_client_ids=("eventflow-desktop", "eventflow-vscode"),
        redirect_uri="https://api.example.test/v1/auth/oidc/callback",
        frontend_redirect_uri="https://web.example.test/auth/complete",
        allowed_origins=("https://web.example.test",),
        token_encryption_keys=(encryption_key,),
    )
    cipher = TokenCipher((encryption_key,))

    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            identity, _ = IdentityRepository(session).resolve_or_create(
                issuer=settings.issuer,
                subject="expired-session-subject",
            )
            record = AuthenticationSession(
                identity_id=identity.id,
                session_token_digest=digest_token("expired-session-cookie"),
                csrf_token_digest=digest_token("expired-session-csrf"),
                csrf_token_ciphertext=cipher.encrypt("expired-session-csrf"),
                client_id=settings.web_client_id,
                source="web",
                access_token_ciphertext=cipher.encrypt("expired-access-token"),
                refresh_token_ciphertext=cipher.encrypt("expired-refresh-token"),
                access_expires_at=now - timedelta(minutes=1),
                refresh_expires_at=now + timedelta(hours=1),
                last_seen_at=now - timedelta(hours=1),
                idle_expires_at=now - timedelta(seconds=1),
                absolute_expires_at=now + timedelta(hours=1),
            )
            session.add(record)
            session.commit()
            record_id = record.id

        service = AuthenticationService(settings, object(), cipher)
        with session_scope(engine) as session:
            with testrunner.raises(AuthenticationError):
                service.resolve_session_principal(
                    session,
                    "expired-session-cookie",
                    correlation_id=None,
                    source="web",
                )

        with session_scope(engine) as session:
            record = session.get(AuthenticationSession, record_id)
            assert record.revoked_at is not None
            assert record.revoke_reason == "session_expired"
            assert record.access_token_ciphertext == ""
            assert record.refresh_token_ciphertext is None

        with session_scope(engine) as session:
            with testrunner.raises(AuthenticationError):
                service.resolve_session_principal(
                    session,
                    "expired-session-cookie",
                    correlation_id=None,
                    source="web",
                )


def test_authentication_audit_rows_are_append_only():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            identity, _ = IdentityRepository(session).resolve_or_create(
                issuer="https://id.example.test/realms/eventflow",
                subject="audit-subject-111",
            )
            event = AuthenticationAuditRepository(session).append(
                event_type="auth.success",
                outcome="success",
                actor_id=identity.id,
                source="web",
                reason="oidc_login",
            )
            event_id = event.id
            session.commit()

        with session_scope(engine) as session:
            with testrunner.raises(Exception):
                session.execute(
                    text(
                        "UPDATE authentication_security_events "
                        "SET outcome = 'failure' WHERE id = :id"
                    ),
                    {"id": event_id},
                )
                session.commit()
            session.rollback()

        with session_scope(engine) as session:
            assert session.get(AuthenticationSecurityEvent, event_id) is not None


def test_concurrent_bff_refresh_is_serialized_by_postgresql_row_lock():
    admin_url = require_database_url()
    cipher = TokenCipher((TokenCipher.generate_key(),))
    now = datetime.now(UTC)
    calls = 0
    calls_lock = Lock()

    class FakeOIDC:
        def refresh(self, refresh_token):
            nonlocal calls
            assert cipher.decrypt(cipher.encrypt(refresh_token)) == refresh_token
            with calls_lock:
                calls += 1
            time.sleep(0.1)
            epoch = int(time.time())
            return TokenSet(
                access_token="new-access-token",
                refresh_token="rotated-refresh-token",
                access_expires_at=epoch + 300,
                refresh_expires_at=epoch + 3600,
            )

        def validate_access_token(self, token):
            assert token == "new-access-token"
            return {
                "iss": "https://id.example.test/realms/eventflow",
                "sub": "refresh-subject-123",
            }

    settings = AuthSettings(
        environment="test",
        issuer="https://id.example.test/realms/eventflow",
        audience="eventflow-api",
        web_client_id="eventflow-web-bff",
        native_client_ids=("eventflow-desktop", "eventflow-vscode"),
        redirect_uri="https://api.example.test/v1/auth/oidc/callback",
        frontend_redirect_uri="https://web.example.test/auth/complete",
        allowed_origins=("https://web.example.test",),
        token_encryption_keys=(TokenCipher.generate_key(),),
    )
    cipher = TokenCipher(settings.token_encryption_keys)

    with temporary_database(admin_url) as (_, engine):
        with session_scope(engine) as session:
            identity, _ = IdentityRepository(session).resolve_or_create(
                issuer=settings.issuer,
                subject="refresh-subject-123",
            )
            record = AuthenticationSession(
                identity_id=identity.id,
                session_token_digest=digest_token("concurrent-session-cookie"),
                csrf_token_digest=digest_token("concurrent-csrf-token"),
                csrf_token_ciphertext=cipher.encrypt("concurrent-csrf-token"),
                client_id=settings.web_client_id,
                source="web",
                access_token_ciphertext=cipher.encrypt("old-access-token"),
                refresh_token_ciphertext=cipher.encrypt("old-refresh-token"),
                access_expires_at=now - timedelta(seconds=1),
                refresh_expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                idle_expires_at=now + timedelta(minutes=30),
                absolute_expires_at=now + timedelta(hours=12),
            )
            session.add(record)
            session.commit()
            cookie = "concurrent-session-cookie"
            session_id = record.id

        service = AuthenticationService(settings, FakeOIDC(), cipher)
        barrier = Barrier(2)

        def refresh_session():
            from sqlalchemy.orm import Session

            with Session(engine, expire_on_commit=False) as session:
                barrier.wait(timeout=10)
                active = service.resolve_session_principal(
                    session,
                    cookie,
                    correlation_id=None,
                    source="web",
                    refresh=True,
                )
                return active.principal.session_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: refresh_session(), range(2)))
        assert results == [session_id, session_id]
        assert calls == 1
        with session_scope(engine) as session:
            updated = session.get(AuthenticationSession, session_id)
            assert (
                cipher.decrypt(updated.refresh_token_ciphertext)
                == "rotated-refresh-token"
            )
