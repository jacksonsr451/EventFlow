"""Validated, environment-driven authentication configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.fernet import Fernet


class AuthenticationConfigurationError(RuntimeError):
    """Authentication cannot start with the supplied configuration."""


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise AuthenticationConfigurationError(f"{name} must be an integer") from exc
    if value < 1 or value > maximum:
        raise AuthenticationConfigurationError(f"{name} is outside the allowed range")
    return value


def _url(value: str, name: str, *, development: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ({"https", "http"} if development else {"https"}):
        raise AuthenticationConfigurationError(
            f"{name} must use HTTPS outside development"
        )
    if (
        not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise AuthenticationConfigurationError(
            f"{name} must be an absolute URL without credentials or fragment"
        )
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise AuthenticationConfigurationError(
            f"{name} may use HTTP only on loopback during development"
        )
    return value.rstrip("/")


@dataclass(frozen=True)
class AuthSettings:
    environment: str
    issuer: str
    audience: str
    web_client_id: str
    native_client_ids: tuple[str, ...]
    redirect_uri: str
    frontend_redirect_uri: str
    allowed_origins: tuple[str, ...]
    token_encryption_keys: tuple[str, ...]
    access_token_leeway_seconds: int = 30
    state_ttl_seconds: int = 600
    session_idle_seconds: int = 1800
    session_absolute_seconds: int = 43200
    refresh_before_expiry_seconds: int = 30
    jwks_cache_seconds: int = 300

    @property
    def development(self) -> bool:
        return self.environment == "development"

    @property
    def secure_cookies(self) -> bool:
        return not self.development

    @property
    def session_cookie_name(self) -> str:
        return (
            "__Host-eventflow_session" if self.secure_cookies else "eventflow_session"
        )

    @property
    def oidc_state_cookie_name(self) -> str:
        return "__Host-eventflow_oidc" if self.secure_cookies else "eventflow_oidc"

    @classmethod
    def from_env(cls) -> AuthSettings:
        # Fail closed unless an operator explicitly opts into loopback-only
        # development settings.
        environment = os.getenv("EVENTFLOW_ENVIRONMENT", "production").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise AuthenticationConfigurationError(
                "EVENTFLOW_ENVIRONMENT must be development, test, or production"
            )
        development = environment in {"development", "test"}
        issuer = _url(
            os.getenv(
                "EVENTFLOW_OIDC_ISSUER", "http://localhost:8082/realms/eventflow"
            ),
            "EVENTFLOW_OIDC_ISSUER",
            development=development,
        )
        redirect_uri = os.getenv(
            "EVENTFLOW_OIDC_REDIRECT_URI", "http://localhost:8000/v1/auth/oidc/callback"
        )
        parsed_redirect = urlparse(redirect_uri)
        if parsed_redirect.scheme not in (
            {"https", "http"} if development else {"https"}
        ):
            raise AuthenticationConfigurationError(
                "EVENTFLOW_OIDC_REDIRECT_URI must use HTTPS outside development"
            )
        if (
            not parsed_redirect.netloc
            or parsed_redirect.username
            or parsed_redirect.password
            or parsed_redirect.fragment
        ):
            raise AuthenticationConfigurationError(
                "EVENTFLOW_OIDC_REDIRECT_URI is invalid"
            )
        if parsed_redirect.scheme == "http" and parsed_redirect.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise AuthenticationConfigurationError(
                "HTTP OIDC redirects are allowed only on loopback during development"
            )

        frontend_redirect = _url(
            os.getenv(
                "EVENTFLOW_WEB_REDIRECT_AFTER_LOGIN",
                "http://localhost:5173/auth/complete",
            ),
            "EVENTFLOW_WEB_REDIRECT_AFTER_LOGIN",
            development=development,
        )
        origins_raw = os.getenv(
            "EVENTFLOW_CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:8000",
        )
        origins = tuple(
            origin.strip().rstrip("/")
            for origin in origins_raw.split(",")
            if origin.strip()
        )
        if not origins or "*" in origins:
            raise AuthenticationConfigurationError(
                "CORS origins must be an explicit non-wildcard allowlist"
            )
        for origin in origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in ({"https", "http"} if development else {"https"})
                or not parsed.netloc
            ):
                raise AuthenticationConfigurationError(
                    "CORS origins must be absolute HTTPS origins (loopback HTTP in development)"
                )
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise AuthenticationConfigurationError(
                    "CORS HTTP origins are allowed only on loopback during development"
                )
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise AuthenticationConfigurationError(
                    "CORS entries must be origins, not URLs with paths"
                )

        keys_raw = os.getenv("EVENTFLOW_TOKEN_ENCRYPTION_KEYS", "")
        keys = tuple(item.strip() for item in keys_raw.split(",") if item.strip())
        if not keys:
            raise AuthenticationConfigurationError(
                "EVENTFLOW_TOKEN_ENCRYPTION_KEYS is required"
            )
        for key in keys:
            try:
                Fernet(key.encode("ascii"))
            except (ValueError, TypeError) as exc:
                raise AuthenticationConfigurationError(
                    "EVENTFLOW_TOKEN_ENCRYPTION_KEYS contains an invalid Fernet key"
                ) from exc

        web_client_id = os.getenv(
            "EVENTFLOW_OIDC_WEB_CLIENT_ID", "eventflow-web-bff"
        ).strip()
        native_client_ids = tuple(
            item.strip()
            for item in os.getenv(
                "EVENTFLOW_OIDC_NATIVE_CLIENT_IDS", "eventflow-desktop,eventflow-vscode"
            ).split(",")
            if item.strip()
        )
        audience = os.getenv("EVENTFLOW_OIDC_API_AUDIENCE", "eventflow-api").strip()
        if not web_client_id or not audience or not native_client_ids:
            raise AuthenticationConfigurationError(
                "OIDC client ID and API audience must be non-empty"
            )

        state_ttl = _positive_int("EVENTFLOW_OIDC_STATE_TTL_SECONDS", 600, maximum=1800)
        idle_seconds = _positive_int(
            "EVENTFLOW_SESSION_IDLE_SECONDS", 1800, maximum=86400
        )
        absolute_seconds = _positive_int(
            "EVENTFLOW_SESSION_ABSOLUTE_SECONDS", 43200, maximum=604800
        )
        if idle_seconds > absolute_seconds:
            raise AuthenticationConfigurationError(
                "session idle timeout must not exceed absolute lifetime"
            )

        return cls(
            environment=environment,
            issuer=issuer,
            audience=audience,
            web_client_id=web_client_id,
            native_client_ids=native_client_ids,
            redirect_uri=redirect_uri,
            frontend_redirect_uri=frontend_redirect,
            allowed_origins=origins,
            token_encryption_keys=keys,
            access_token_leeway_seconds=_positive_int(
                "EVENTFLOW_OIDC_CLOCK_SKEW_SECONDS", 30, maximum=120
            ),
            state_ttl_seconds=state_ttl,
            session_idle_seconds=idle_seconds,
            session_absolute_seconds=absolute_seconds,
            refresh_before_expiry_seconds=_positive_int(
                "EVENTFLOW_REFRESH_BEFORE_EXPIRY_SECONDS", 30, maximum=300
            ),
            jwks_cache_seconds=_positive_int(
                "EVENTFLOW_JWKS_CACHE_SECONDS", 300, maximum=3600
            ),
        )
