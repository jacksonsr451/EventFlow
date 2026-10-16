"""Trusted internal principal created only after token or session validation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Verified external identity resolved to EventFlow's stable internal UUID."""

    user_id: UUID
    issuer: str
    subject: str
    session_id: UUID | None = None
