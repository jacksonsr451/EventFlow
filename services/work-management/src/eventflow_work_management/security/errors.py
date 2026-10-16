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
