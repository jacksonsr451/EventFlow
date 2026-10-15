"""Repository-level errors with domain meaning."""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for repository errors."""


class EntityNotFound(RepositoryError):
    """The requested entity does not exist in the given workspace."""


class VersionMismatch(RepositoryError):
    """The caller acted on a version other than the current one."""


class AlreadyDecided(RepositoryError):
    """A decision already exists for the proposal version."""


class IdempotencyConflict(RepositoryError):
    """The same idempotency key was reused with a different request."""
