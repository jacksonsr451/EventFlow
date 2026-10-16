"""OIDC login, identity resolution and server-side session lifecycle."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from eventflow_work_management.models.authentication import (
    AuthenticationSession,
    ExternalIdentity,
    OIDCLoginTransaction,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import (
    TokenCipher,
    digest_token,
    random_cookie_value,
    random_url_token,
)
from eventflow_work_management.security.errors import (
    AuthenticationDependencyError,
    AuthenticationError,
)
from eventflow_work_management.security.oidc import (
    OIDCClient,
    OIDCError,
    OIDCProviderUnavailable,
)
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.security.repository import (
    AuthenticationAuditRepository,
    DisabledIdentityError,
    IdentityRepository,
)


@dataclass(frozen=True, slots=True)
class LoginStart:
    authorization_url: str
    browser_binding: str


@dataclass(frozen=True, slots=True)
class SessionGrant:
    cookie_value: str
    principal: AuthenticatedPrincipal
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ActiveSession:
    principal: AuthenticatedPrincipal
    csrf_token: str
    expires_at: datetime
    source: str


def _now() -> datetime:
    return datetime.now(UTC)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class AuthenticationService:
    def __init__(
        self,
        settings: AuthSettings,
        oidc: OIDCClient,
        cipher: TokenCipher,
    ) -> None:
        self.settings = settings
        self.oidc = oidc
        self.cipher = cipher

    def begin_web_login(self, session: Session) -> LoginStart:
        now = _now()
        state = random_url_token(32)
        nonce = random_url_token(32)
        verifier = random_url_token(48)
        browser_binding = random_cookie_value()
        state_digest = digest_token(state)

        # Expired one-use transactions contain encrypted PKCE verifiers. Purge
        # them opportunistically; the short TTL is also enforced at consumption.
        session.execute(
            delete(OIDCLoginTransaction).where(OIDCLoginTransaction.expires_at <= now)
        )
        transaction = OIDCLoginTransaction(
            id=uuid4(),
            state_digest=state_digest,
            browser_binding_digest=digest_token(browser_binding),
            nonce_digest=digest_token(nonce),
            verifier_ciphertext=self.cipher.encrypt(verifier),
            redirect_uri=self.settings.redirect_uri,
            expires_at=now + timedelta(seconds=self.settings.state_ttl_seconds),
        )
        session.add(transaction)
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise
        return LoginStart(
            authorization_url=self.oidc.authorization_url(
                state=state,
                nonce=nonce,
                challenge=_pkce_challenge(verifier),
            ),
            browser_binding=browser_binding,
        )

    def complete_web_login(
        self,
        session: Session,
        *,
        code: str,
        state: str,
        browser_binding: str | None,
        correlation_id: UUID | None,
    ) -> SessionGrant:
        now = _now()
        state_digest = digest_token(state)
        transaction = session.execute(
            select(OIDCLoginTransaction)
            .where(OIDCLoginTransaction.state_digest == state_digest)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            transaction is None
            or browser_binding is None
            or not hmac.compare_digest(
                transaction.browser_binding_digest, digest_token(browser_binding)
            )
            or transaction.expires_at <= now
            or transaction.consumed_at is not None
        ):
            replayed = transaction is not None and transaction.consumed_at is not None
            AuthenticationAuditRepository(session).append(
                event_type="auth.replay_detected" if replayed else "auth.failure",
                outcome="denied",
                severity="high" if replayed else "medium",
                correlation_id=correlation_id,
                source="web",
                reason="invalid_or_replayed_oauth_transaction",
            )
            session.commit()
            raise AuthenticationError(
                status_code=400,
                code="VALIDATION_ERROR",
                detail="The authentication response is invalid or expired.",
            )

        # Consume the state before contacting the provider so a concurrent callback
        # cannot exchange the same code twice. A failed exchange requires a fresh login.
        transaction.consumed_at = now
        verifier_ciphertext = transaction.verifier_ciphertext
        nonce_digest = transaction.nonce_digest
        redirect_uri = transaction.redirect_uri
        session.commit()

        try:
            if redirect_uri != self.settings.redirect_uri:
                raise OIDCError("redirect URI changed during authentication")
            token_set = self.oidc.exchange_code(
                code=code,
                verifier=self.cipher.decrypt(verifier_ciphertext),
            )
            if not token_set.id_token:
                raise OIDCError("OIDC response did not contain an ID token")
            if not token_set.refresh_token or not token_set.refresh_expires_at:
                raise OIDCError("OIDC response did not contain a bounded refresh token")
            id_claims = self.oidc.validate_id_token(
                token_set.id_token,
                nonce_digest=nonce_digest,
            )
            access_claims = self.oidc.validate_access_token(token_set.access_token)
            if (
                id_claims["sub"] != access_claims["sub"]
                or id_claims["iss"] != access_claims["iss"]
            ):
                raise OIDCError("ID token and access token identities do not match")
        except OIDCProviderUnavailable as exc:
            AuthenticationAuditRepository(session).append(
                event_type="auth.failure",
                outcome="failure",
                severity="medium",
                correlation_id=correlation_id,
                source="web",
                reason="identity_provider_unavailable",
            )
            session.commit()
            raise AuthenticationDependencyError(
                "Identity provider is unavailable"
            ) from exc
        except OIDCError as exc:
            AuthenticationAuditRepository(session).append(
                event_type="auth.failure",
                outcome="failure",
                severity="medium",
                correlation_id=correlation_id,
                source="web",
                reason=(
                    f"oidc_failure:{type(exc).__name__}:{exc}"[:256]
                ),
            )
            session.commit()
            raise AuthenticationError(
                status_code=401,
                code="UNAUTHORIZED",
                detail="Authentication failed.",
            ) from exc

        try:
            identity, _created = IdentityRepository(session).resolve_or_create(
                issuer=id_claims["iss"], subject=id_claims["sub"]
            )
        except DisabledIdentityError as exc:
            AuthenticationAuditRepository(session).append(
                event_type="auth.failure",
                outcome="denied",
                severity="high",
                correlation_id=correlation_id,
                source="web",
                reason="disabled_identity",
            )
            session.commit()
            raise AuthenticationError(
                status_code=401,
                code="UNAUTHORIZED",
                detail="Authentication failed.",
            ) from exc

        cookie_value = random_cookie_value()
        csrf_token = random_cookie_value()
        absolute_expires = now + timedelta(
            seconds=self.settings.session_absolute_seconds
        )
        idle_expires = min(
            now + timedelta(seconds=self.settings.session_idle_seconds),
            absolute_expires,
        )
        session_record = AuthenticationSession(
            id=uuid4(),
            identity_id=identity.id,
            session_token_digest=digest_token(cookie_value),
            csrf_token_digest=digest_token(csrf_token),
            csrf_token_ciphertext=self.cipher.encrypt(csrf_token),
            client_id=self.settings.web_client_id,
            source="web",
            access_token_ciphertext=self.cipher.encrypt(token_set.access_token),
            refresh_token_ciphertext=(
                self.cipher.encrypt(token_set.refresh_token)
                if token_set.refresh_token
                else None
            ),
            access_expires_at=datetime.fromtimestamp(token_set.access_expires_at, UTC),
            refresh_expires_at=(
                datetime.fromtimestamp(token_set.refresh_expires_at, UTC)
                if token_set.refresh_expires_at
                else None
            ),
            last_seen_at=now,
            idle_expires_at=idle_expires,
            absolute_expires_at=absolute_expires,
        )
        session.add(session_record)
        audit = AuthenticationAuditRepository(session)
        audit.append(
            event_type="auth.success",
            outcome="success",
            actor_id=identity.id,
            correlation_id=correlation_id,
            source="web",
        )
        audit.append(
            event_type="session.created",
            outcome="success",
            actor_id=identity.id,
            subject=str(session_record.id),
            correlation_id=correlation_id,
            source="web",
        )
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise
        return SessionGrant(
            cookie_value=cookie_value,
            principal=AuthenticatedPrincipal(
                user_id=identity.id,
                issuer=identity.issuer,
                subject=identity.subject,
                session_id=session_record.id,
            ),
            csrf_token=csrf_token,
            # The cookie may live for the absolute session maximum; the server
            # enforces the shorter rolling idle timeout on every request.
            expires_at=absolute_expires,
        )

    def resolve_bearer_principal(
        self,
        session: Session,
        token: str,
        *,
        correlation_id: UUID | None,
        source: str,
    ) -> AuthenticatedPrincipal:
        try:
            claims = self.oidc.validate_access_token(token)
            identity, _created = IdentityRepository(session).resolve_or_create(
                issuer=claims["iss"], subject=claims["sub"]
            )
            session.commit()
        except OIDCProviderUnavailable as exc:
            session.rollback()
            raise AuthenticationDependencyError(
                "Identity provider is unavailable"
            ) from exc
        except (OIDCError, DisabledIdentityError) as exc:
            session.rollback()
            AuthenticationAuditRepository(session).append(
                event_type="auth.failure",
                outcome="denied",
                severity="medium",
                correlation_id=correlation_id,
                source=source,
                reason="invalid_bearer_token_or_disabled_identity",
            )
            session.commit()
            raise AuthenticationError(
                status_code=401,
                code="UNAUTHORIZED",
                detail="Authentication is required or invalid.",
            ) from exc
        return AuthenticatedPrincipal(
            user_id=identity.id,
            issuer=identity.issuer,
            subject=identity.subject,
        )

    def resolve_session_principal(
        self,
        session: Session,
        cookie_value: str,
        *,
        correlation_id: UUID | None,
        source: str,
        refresh: bool = False,
    ) -> ActiveSession:
        now = _now()
        record = session.execute(
            select(AuthenticationSession)
            .where(
                AuthenticationSession.session_token_digest == digest_token(cookie_value)
            )
            .with_for_update()
        ).scalar_one_or_none()
        if record is None:
            raise AuthenticationError()
        # Resolve through the mapped model without accepting identity information
        # from the request. The relationship is deliberately a stored UUID FK.
        identity = session.get(ExternalIdentity, record.identity_id)
        if identity is None or identity.disabled_at is not None:
            self._revoke_locked(
                session, record, now, "identity_disabled", correlation_id, source
            )
            AuthenticationAuditRepository(session).append(
                event_type="session.revoked",
                outcome="denied",
                severity="high",
                actor_id=record.identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="identity_disabled",
            )
            session.commit()
            raise AuthenticationError()
        if record.revoked_at is not None:
            raise AuthenticationError()
        if now >= record.absolute_expires_at or now >= record.idle_expires_at:
            self._revoke_locked(
                session, record, now, "session_expired", correlation_id, source
            )
            AuthenticationAuditRepository(session).append(
                event_type="session.expired",
                outcome="denied",
                actor_id=identity.id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
            )
            session.commit()
            raise AuthenticationError()

        if refresh and record.access_expires_at <= now + timedelta(
            seconds=self.settings.refresh_before_expiry_seconds
        ):
            self._refresh_locked(session, record, identity.id, correlation_id, source)
            now = _now()

        record.last_seen_at = now
        record.idle_expires_at = min(
            now + timedelta(seconds=self.settings.session_idle_seconds),
            record.absolute_expires_at,
        )
        try:
            csrf_token = self.cipher.decrypt(record.csrf_token_ciphertext)
        except Exception as exc:
            self._revoke_locked(
                session, record, now, "session_state_invalid", correlation_id, source
            )
            session.commit()
            raise AuthenticationError() from exc
        principal = AuthenticatedPrincipal(
            user_id=identity.id,
            issuer=identity.issuer,
            subject=identity.subject,
            session_id=record.id,
        )
        expires_at = record.idle_expires_at
        session.commit()
        return ActiveSession(principal, csrf_token, expires_at, source)

    def _refresh_locked(
        self,
        session: Session,
        record: AuthenticationSession,
        identity_id: UUID,
        correlation_id: UUID | None,
        source: str,
    ) -> None:
        now = _now()
        if not record.refresh_token_ciphertext or (
            record.refresh_expires_at and record.refresh_expires_at <= now
        ):
            self._revoke_locked(
                session, record, now, "refresh_unavailable", correlation_id, source
            )
            AuthenticationAuditRepository(session).append(
                event_type="auth.refresh_failure",
                outcome="denied",
                severity="medium",
                actor_id=identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="refresh_token_unavailable",
            )
            session.commit()
            raise AuthenticationError()
        try:
            old_refresh = self.cipher.decrypt(record.refresh_token_ciphertext)
            token_set = self.oidc.refresh(old_refresh)
            claims = self.oidc.validate_access_token(token_set.access_token)
            from eventflow_work_management.models.authentication import ExternalIdentity

            identity = session.get(ExternalIdentity, identity_id)
            if (
                identity is None
                or claims["iss"] != identity.issuer
                or claims["sub"] != identity.subject
            ):
                raise OIDCError("refresh returned a different identity")
            if not token_set.refresh_token:
                raise OIDCError("Keycloak did not rotate the configured refresh token")
            if hmac.compare_digest(token_set.refresh_token, old_refresh):
                raise OIDCError("Keycloak returned the previous refresh token")
        except OIDCProviderUnavailable as exc:
            session.rollback()
            AuthenticationAuditRepository(session).append(
                event_type="auth.refresh_failure",
                outcome="failure",
                severity="medium",
                actor_id=identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="identity_provider_unavailable",
            )
            session.commit()
            raise AuthenticationDependencyError(
                "Identity provider is unavailable"
            ) from exc
        except OIDCError as exc:
            self._revoke_locked(
                session, record, now, "refresh_rejected", correlation_id, source
            )
            AuthenticationAuditRepository(session).append(
                event_type="auth.refresh_failure",
                outcome="failure",
                severity="medium",
                actor_id=identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="provider_refresh_rejected",
            )
            session.commit()
            raise AuthenticationError() from exc
        record.access_token_ciphertext = self.cipher.encrypt(token_set.access_token)
        record.refresh_token_ciphertext = self.cipher.encrypt(token_set.refresh_token)
        record.access_expires_at = datetime.fromtimestamp(
            token_set.access_expires_at, UTC
        )
        record.refresh_expires_at = (
            datetime.fromtimestamp(token_set.refresh_expires_at, UTC)
            if token_set.refresh_expires_at
            else record.refresh_expires_at
        )
        AuthenticationAuditRepository(session).append(
            event_type="auth.refresh_success",
            outcome="success",
            actor_id=identity_id,
            subject=str(record.id),
            correlation_id=correlation_id,
            source=source,
        )

    def revoke_session(
        self,
        session: Session,
        cookie_value: str,
        *,
        correlation_id: UUID | None,
        source: str = "web",
    ) -> None:
        record = session.execute(
            select(AuthenticationSession)
            .where(
                AuthenticationSession.session_token_digest == digest_token(cookie_value)
            )
            .with_for_update()
        ).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            session.rollback()
            return
        now = _now()
        refresh_token = None
        decrypt_failed = False
        if record.refresh_token_ciphertext:
            try:
                refresh_token = self.cipher.decrypt(record.refresh_token_ciphertext)
            except Exception:
                decrypt_failed = True
        identity_id = record.identity_id
        self._revoke_locked(session, record, now, "logout", correlation_id, source)
        AuthenticationAuditRepository(session).append(
            event_type="auth.logout",
            outcome="success",
            actor_id=identity_id,
            subject=str(record.id),
            correlation_id=correlation_id,
            source=source,
        )
        AuthenticationAuditRepository(session).append(
            event_type="session.revoked",
            outcome="success",
            actor_id=identity_id,
            subject=str(record.id),
            correlation_id=correlation_id,
            source=source,
            reason="logout",
        )
        if decrypt_failed:
            AuthenticationAuditRepository(session).append(
                event_type="credential.revoked",
                outcome="failure",
                severity="high",
                actor_id=identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="stored_refresh_credential_unreadable",
            )
        session.commit()
        if refresh_token:
            try:
                self.oidc.revoke(refresh_token)
            except OIDCError:
                # Local session revocation is authoritative even if Keycloak is
                # temporarily unavailable; never restore a local session.
                AuthenticationAuditRepository(session).append(
                    event_type="credential.revoked",
                    outcome="failure",
                    severity="medium",
                    actor_id=identity_id,
                    subject=str(record.id),
                    correlation_id=correlation_id,
                    source=source,
                    reason="provider_revocation_unavailable",
                )
                session.commit()

    def revoke_session_by_id(
        self,
        session: Session,
        session_id: UUID,
        *,
        identity_id: UUID,
        correlation_id: UUID | None,
        source: str,
    ) -> None:
        record = session.execute(
            select(AuthenticationSession)
            .where(
                AuthenticationSession.id == session_id,
                AuthenticationSession.identity_id == identity_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            session.rollback()
            return
        refresh_token = None
        decrypt_failed = False
        if record.refresh_token_ciphertext:
            try:
                refresh_token = self.cipher.decrypt(record.refresh_token_ciphertext)
            except Exception:
                decrypt_failed = True
        self._revoke_locked(
            session, record, _now(), "user_revoked", correlation_id, source
        )
        AuthenticationAuditRepository(session).append(
            event_type="session.revoked",
            outcome="success",
            actor_id=identity_id,
            subject=str(record.id),
            correlation_id=correlation_id,
            source=source,
            reason="user_revoked_session",
        )
        if decrypt_failed:
            AuthenticationAuditRepository(session).append(
                event_type="credential.revoked",
                outcome="failure",
                severity="high",
                actor_id=identity_id,
                subject=str(record.id),
                correlation_id=correlation_id,
                source=source,
                reason="stored_refresh_credential_unreadable",
            )
        session.commit()
        if refresh_token:
            try:
                self.oidc.revoke(refresh_token)
            except OIDCError:
                AuthenticationAuditRepository(session).append(
                    event_type="credential.revoked",
                    outcome="failure",
                    severity="medium",
                    actor_id=identity_id,
                    subject=str(record.id),
                    correlation_id=correlation_id,
                    source=source,
                    reason="provider_revocation_unavailable",
                )
                session.commit()

    def verify_csrf(
        self, session: Session, principal: AuthenticatedPrincipal, value: str | None
    ) -> bool:
        if principal.session_id is None or not value:
            return False
        record = session.get(AuthenticationSession, principal.session_id)
        return bool(
            record
            and record.revoked_at is None
            and record.idle_expires_at > _now()
            and record.absolute_expires_at > _now()
            and hmac.compare_digest(record.csrf_token_digest, digest_token(value))
        )

    def verify_cookie_csrf(
        self, session: Session, cookie_value: str, csrf_value: str | None
    ) -> bool:
        """Check Origin-bound CSRF proof before performing a token refresh or mutation."""
        if not csrf_value:
            return False
        record = session.execute(
            select(AuthenticationSession).where(
                AuthenticationSession.session_token_digest == digest_token(cookie_value)
            )
        ).scalar_one_or_none()
        now = _now()
        return bool(
            record
            and record.revoked_at is None
            and record.idle_expires_at > now
            and record.absolute_expires_at > now
            and hmac.compare_digest(record.csrf_token_digest, digest_token(csrf_value))
        )

    @staticmethod
    def _revoke_locked(
        session: Session,
        record: AuthenticationSession,
        now: datetime,
        reason: str,
        correlation_id: UUID | None,
        source: str,
    ) -> None:
        record.revoked_at = now
        record.revoke_reason = reason
        record.access_token_ciphertext = ""
        record.refresh_token_ciphertext = None
        # Keep no CSRF capability after revocation.
        record.csrf_token_ciphertext = ""
