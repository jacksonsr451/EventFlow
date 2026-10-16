"""FastAPI dependencies for database sessions and authenticated principals."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from eventflow_work_management.security.errors import AuthenticationError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.security.service import AuthenticationService


def database_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def correlation_id(request: Request) -> UUID | None:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, UUID) else None


def authenticated_principal(
    request: Request,
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
) -> AuthenticatedPrincipal:
    service: AuthenticationService = request.app.state.authentication_service
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError()
        source = getattr(request.state, "auth_source", "backend")
        return service.resolve_bearer_principal(
            session,
            token,
            correlation_id=request_correlation_id,
            source=source,
        )

    cookie_name = request.app.state.auth_settings.session_cookie_name
    cookie_value = request.cookies.get(cookie_name)
    if not cookie_value:
        raise AuthenticationError()
    active = service.resolve_session_principal(
        session,
        cookie_value,
        correlation_id=request_correlation_id,
        source="web",
    )
    request.state.active_session = active
    request.state.csrf_token = active.csrf_token
    return active.principal


def require_csrf(
    request: Request,
    session: Session = Depends(database_session),
) -> AuthenticatedPrincipal:
    """Require Origin and a session-bound CSRF token for cookie-authenticated writes."""
    service: AuthenticationService = request.app.state.authentication_service
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError()
        return service.resolve_bearer_principal(
            session,
            token,
            correlation_id=correlation_id(request),
            source="backend",
        )

    cookie_name = request.app.state.auth_settings.session_cookie_name
    cookie_value = request.cookies.get(cookie_name)
    if not cookie_value:
        raise AuthenticationError()
    origin = request.headers.get("origin")
    if origin not in request.app.state.auth_settings.allowed_origins:
        raise AuthenticationError(
            status_code=403,
            code="FORBIDDEN",
            detail="The request origin is not allowed.",
        )
    token = request.headers.get("x-csrf-token")
    if not service.verify_cookie_csrf(session, cookie_value, token):
        raise AuthenticationError(
            status_code=403,
            code="FORBIDDEN",
            detail="The CSRF token is missing or invalid.",
        )
    # Only after Origin and CSRF are valid may authentication refresh or mutate
    # session state.
    active = service.resolve_session_principal(
        session,
        cookie_value,
        correlation_id=correlation_id(request),
        source="web",
    )
    request.state.active_session = active
    request.state.csrf_token = active.csrf_token
    return active.principal
