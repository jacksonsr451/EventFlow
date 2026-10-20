"""RFC 9457 Problem Details helpers for the FastAPI boundary."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from eventflow_work_management.security.errors import (
    AuthenticationDependencyError,
    AuthenticationError,
    ProblemError,
)
from eventflow_work_management.security.oidc import OIDCError, OIDCProviderUnavailable


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    correlation_id: UUID
    code: str
    errors: list[dict] | None = None


def _correlation_id(request: Request) -> UUID:
    current = getattr(request.state, "correlation_id", None)
    if isinstance(current, UUID):
        return current
    return uuid4()


def problem_response(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    errors: list[dict] | None = None,
) -> JSONResponse:
    body = ProblemDetails(
        title=title,
        status=status_code,
        detail=detail,
        correlation_id=_correlation_id(request),
        code=code,
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={
            "X-Correlation-ID": str(body.correlation_id),
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


async def authentication_error_handler(request: Request, exc: AuthenticationError):
    title = {
        400: "Invalid authentication request",
        401: "Authentication required",
        403: "Forbidden",
    }.get(exc.status_code, "Authentication failed")
    return problem_response(
        request,
        status_code=exc.status_code,
        title=title,
        detail=exc.detail,
        code=exc.code,
    )


async def problem_error_handler(request: Request, exc: ProblemError):
    """Map a sanitized domain problem to RFC 9457 without leaking internals."""
    title = exc.title or {
        400: "Invalid request",
        403: "Forbidden",
        404: "Not found",
        409: "Conflict",
        412: "Precondition failed",
    }.get(exc.status_code, "Request failed")
    return problem_response(
        request,
        status_code=exc.status_code,
        title=title,
        detail=exc.detail,
        code=exc.code,
        errors=exc.errors,
    )


async def authentication_dependency_error_handler(
    request: Request, exc: AuthenticationDependencyError
):
    return problem_response(
        request,
        status_code=503,
        title="Authentication dependency unavailable",
        detail="The identity provider is temporarily unavailable.",
        code="DEPENDENCY_UNAVAILABLE",
    )


async def oidc_error_handler(request: Request, exc: OIDCError):
    status = 503 if isinstance(exc, OIDCProviderUnavailable) else 401
    return problem_response(
        request,
        status_code=status,
        title="Authentication failed" if status == 401 else "Authentication dependency unavailable",
        detail=(
            "Authentication is required or invalid."
            if status == 401
            else "The identity provider is temporarily unavailable."
        ),
        code="UNAUTHORIZED" if status == 401 else "DEPENDENCY_UNAVAILABLE",
    )
