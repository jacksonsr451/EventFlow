"""FastAPI application factory for the Work Management authentication boundary."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from eventflow_work_management.api.auth_routes import router as authentication_router
from eventflow_work_management.api.errors import (
    authentication_dependency_error_handler,
    authentication_error_handler,
    oidc_error_handler,
    problem_response,
)
from eventflow_work_management.config import database_url
from eventflow_work_management.db.engine import create_engine_from_url, session_factory
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.security.errors import (
    AuthenticationDependencyError,
    AuthenticationError,
)
from eventflow_work_management.security.logging import install_access_log_redaction
from eventflow_work_management.security.oidc import OIDCClient, OIDCError
from eventflow_work_management.security.service import AuthenticationService

logger = logging.getLogger("eventflow_work_management.authentication")


def create_app(
    *,
    settings: AuthSettings | None = None,
    engine: Engine | None = None,
    session_factory_override: sessionmaker | None = None,
    oidc_client: OIDCClient | None = None,
) -> FastAPI:
    """Construct the API and dependency graph; no authentication bypass exists."""
    auth_settings = settings or AuthSettings.from_env()
    install_access_log_redaction()
    owned_engine = engine
    if session_factory_override is not None:
        session_factory_instance = session_factory_override
    else:
        if owned_engine is None:
            owned_engine = create_engine_from_url(database_url())
        session_factory_instance = session_factory(owned_engine)

    oidc = oidc_client or OIDCClient(auth_settings)
    cipher = TokenCipher(auth_settings.token_encryption_keys)
    authentication_service = AuthenticationService(auth_settings, oidc, cipher)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        oidc.close()
        if owned_engine is not None:
            owned_engine.dispose()

    app = FastAPI(
        title="EventFlow Work Management Authentication API",
        version="1.0.0",
        docs_url=None if not auth_settings.development else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.auth_settings = auth_settings
    app.state.session_factory = session_factory_instance
    app.state.authentication_service = authentication_service
    app.state.oidc_client = oidc
    app.state.database_engine = owned_engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(auth_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        raw_correlation = request.headers.get("x-correlation-id")
        try:
            request.state.correlation_id = UUID(raw_correlation) if raw_correlation else uuid4()
        except (ValueError, TypeError):
            request.state.correlation_id = uuid4()
        response = await call_next(request)
        response.headers.setdefault("X-Correlation-ID", str(request.state.correlation_id))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    app.add_exception_handler(AuthenticationError, authentication_error_handler)
    app.add_exception_handler(
        AuthenticationDependencyError, authentication_dependency_error_handler
    )
    app.add_exception_handler(OIDCError, oidc_error_handler)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        return problem_response(
            request,
            status_code=400,
            title="Invalid request",
            detail="One or more request fields are invalid.",
            code="VALIDATION_ERROR",
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        status = exc.status_code
        safe = {
            401: ("Authentication required", "Authentication is required or invalid.", "UNAUTHORIZED"),
            403: ("Forbidden", "The requested action is not permitted.", "FORBIDDEN"),
            404: ("Not found", "The requested resource was not found.", "NOT_FOUND"),
            503: ("Service unavailable", "An authentication dependency is unavailable.", "DEPENDENCY_UNAVAILABLE"),
        }.get(status, ("Request failed", "The request could not be completed.", "INVALID_STATE"))
        return problem_response(
            request,
            status_code=status,
            title=safe[0],
            detail=safe[1],
            code=safe[2],
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # Do not log exception text or stack traces: upstream exceptions may
        # contain tokens, authorization codes, or SQL parameters.
        logger.error(
            "unexpected_authentication_error",
            extra={"correlation_id": str(request.state.correlation_id)},
        )
        return problem_response(
            request,
            status_code=500,
            title="Internal server error",
            detail="The request could not be completed.",
            code="INTERNAL_ERROR",
        )

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        session = session_factory_instance()
        try:
            session.execute(text("SELECT 1"))
            oidc.discovery()
        except Exception as exc:
            # Readiness responses are deliberately generic and do not expose
            # provider/database details.
            raise HTTPException(status_code=503, detail="Dependencies are not ready") from exc
        finally:
            session.close()
        return {"status": "ready"}

    app.include_router(authentication_router)

    return app
