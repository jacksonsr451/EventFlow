"""BFF and native-client authentication routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    authenticated_principal,
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.security.errors import AuthenticationError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.security.service import ActiveSession, AuthenticationService

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


class PrincipalResponse(BaseModel):
    user_id: UUID


class SessionResponse(BaseModel):
    user_id: UUID
    session_id: UUID
    expires_at: datetime
    csrf_token: str


class SessionListItem(BaseModel):
    session_id: UUID
    client_id: str
    source: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


@router.get("/oidc/login", include_in_schema=True)
def oidc_login(request: Request, session: Session = Depends(database_session)):
    service: AuthenticationService = request.app.state.authentication_service
    started = service.begin_web_login(session)
    settings = request.app.state.auth_settings
    response = RedirectResponse(started.authorization_url, status_code=302)
    response.set_cookie(
        settings.oidc_state_cookie_name,
        started.browser_binding,
        max_age=settings.state_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/oidc/callback", include_in_schema=True)
def oidc_callback(
    request: Request,
    code: str | None = Query(default=None, min_length=1, max_length=4096),
    state: str | None = Query(default=None, min_length=16, max_length=256),
    error: str | None = Query(default=None, max_length=128),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    if error or code is None or state is None:
        raise AuthenticationError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="Authentication could not be completed.",
        )
    service: AuthenticationService = request.app.state.authentication_service
    settings = request.app.state.auth_settings
    state_cookie = request.cookies.get(settings.oidc_state_cookie_name)
    grant = service.complete_web_login(
        session,
        code=code,
        state=state,
        browser_binding=state_cookie,
        correlation_id=request_correlation_id,
    )
    response = RedirectResponse(settings.frontend_redirect_uri, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        grant.cookie_value,
        max_age=max(0, int((grant.expires_at - datetime.now(UTC)).total_seconds())),
        expires=grant.expires_at,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        settings.oidc_state_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/session", response_model=SessionResponse)
def current_session(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
):
    csrf_token = getattr(request.state, "csrf_token", None)
    if principal.session_id is None or not csrf_token:
        raise AuthenticationError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="A server-managed web session is required.",
        )
    session: ActiveSession = request.state.active_session
    return SessionResponse(
        user_id=principal.user_id,
        session_id=principal.session_id,
        expires_at=session.expires_at,
        csrf_token=csrf_token,
    )


@router.get("/principal", response_model=PrincipalResponse)
def current_principal(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
):
    return PrincipalResponse(user_id=principal.user_id)


@router.post("/refresh", response_model=SessionResponse)
def refresh_session(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    settings = request.app.state.auth_settings
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if principal.session_id is None or not cookie_value:
        raise AuthenticationError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="A server-managed web session is required.",
        )
    active = request.app.state.authentication_service.resolve_session_principal(
        session,
        cookie_value,
        correlation_id=request.state.correlation_id,
        source="web",
        refresh=True,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Correlation-ID"] = str(request.state.correlation_id)
    return SessionResponse(
        user_id=principal.user_id,
        session_id=principal.session_id,
        expires_at=active.expires_at,
        csrf_token=active.csrf_token,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    settings = request.app.state.auth_settings
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value or principal.session_id is None:
        raise AuthenticationError(
            status_code=401,
            code="UNAUTHORIZED",
            detail="A server-managed web session is required.",
        )
    request.app.state.authentication_service.revoke_session(
        session,
        cookie_value,
        correlation_id=request.state.correlation_id,
        source="web",
    )
    response = Response(status_code=204)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/sessions", response_model=list[SessionListItem])
def list_sessions(
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    from eventflow_work_management.models.authentication import AuthenticationSession

    rows = session.execute(
        select(AuthenticationSession)
        .where(AuthenticationSession.identity_id == principal.user_id)
        .order_by(AuthenticationSession.created_at.desc())
    ).scalars()
    now = datetime.now(UTC)
    result = [
        SessionListItem(
            session_id=row.id,
            client_id=row.client_id,
            source=row.source,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=min(row.idle_expires_at, row.absolute_expires_at),
            current=row.id == principal.session_id,
        )
        for row in rows
        if row.revoked_at is None and min(row.idle_expires_at, row.absolute_expires_at) > now
    ]
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
):
    from eventflow_work_management.models.authentication import AuthenticationSession

    target = session.get(AuthenticationSession, session_id)
    if target is None or target.identity_id != principal.user_id:
        # Do not disclose whether another user's session exists.
        raise AuthenticationError(
            status_code=404,
            code="NOT_FOUND",
            detail="The requested session was not found.",
        )
    request.app.state.authentication_service.revoke_session_by_id(
        session,
        session_id,
        identity_id=principal.user_id,
        correlation_id=request.state.correlation_id,
        source="web",
    )
    response.status_code = 204
    response.headers["Cache-Control"] = "no-store"
    if session_id == principal.session_id:
        settings = request.app.state.auth_settings
        response.delete_cookie(
            settings.session_cookie_name,
            path="/",
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
        )
    return response
