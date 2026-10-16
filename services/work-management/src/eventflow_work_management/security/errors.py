"""Sanitized authentication errors for RFC 9457 transport mapping."""

from __future__ import annotations


class AuthenticationError(Exception):
    def __init__(
        self,
        *,
        status_code: int = 401,
        code: str = "UNAUTHORIZED",
        detail: str = "Authentication is required or invalid.",
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class AuthenticationDependencyError(Exception):
    """A required authentication dependency is temporarily unavailable."""


class ProblemError(Exception):
    """A sanitized, HTTP-mappable problem raised by the domain and authorization.

    Carries the RFC 9457 members the transport layer needs without leaking
    internal state. The message is deliberately generic and safe to return.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        title: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title
