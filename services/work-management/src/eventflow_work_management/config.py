"""Runtime configuration for the Work Management service.

Configuration is environment-driven; no credentials are hard-coded or committed.
"""

from __future__ import annotations

import os
import re

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_URL_ENV = "EVENTFLOW_DATABASE_URL"
TEST_DATABASE_URL_ENV = "EVENTFLOW_TEST_DATABASE_URL"

TEST_DATABASE_NAME_PREFIX = "eventflow_test_"
TEST_DATABASE_NAME_PATTERN = re.compile(r"^eventflow_test_[0-9a-f]{12}$")

_RESERVED_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def database_url() -> str:
    """Return the configured PostgreSQL URL for the service.

    The URL must use the ``postgresql+psycopg`` dialect (psycopg 3).
    """
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise ConfigurationError(
            f"{DATABASE_URL_ENV} is not set; configure a postgresql+psycopg URL"
        )
    return url


def test_admin_url() -> str:
    """Return the explicitly configured admin URL for throwaway test databases.

    Fails closed: it never falls back to :data:`DATABASE_URL_ENV`, so a
    destructive test operation can never target the application database by
    accident. A missing or unsafe value raises :class:`ConfigurationError`.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        raise ConfigurationError(
            f"{TEST_DATABASE_URL_ENV} is not set; destructive test operations require "
            f"an explicitly configured test administrative database and never fall "
            f"back to {DATABASE_URL_ENV}"
        )
    return validate_test_admin_url(url)


def validate_test_admin_url(url: str | None) -> str:
    """Validate an administrative connection used to create throwaway databases.

    The connection itself may point at a maintenance database (``postgres`` or a
    dedicated database), but it must be a well-formed ``postgresql+psycopg`` URL
    with an explicit database name. Passwords are never included in errors.
    """
    if not url or not url.strip():
        raise ConfigurationError("test administrative database URL is missing or empty")
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError) as exc:
        raise ConfigurationError(
            f"test administrative database URL is malformed: {_mask(url)}"
        ) from exc
    if not parsed.database:
        raise ConfigurationError(
            "test administrative database URL must name a database to connect to"
        )
    if parsed.database in {"template0", "template1"}:
        raise ConfigurationError(
            f"refusing to use reserved database {parsed.database!r} as a test "
            "administrative database"
        )
    return url


def assert_safe_test_database_name(name: str) -> str:
    """Reject destructive operations against any name that is not a test database.

    Only generated throwaway databases of the form ``eventflow_test_<12 hex>`` are
    allowed, so ``CREATE``/``DROP`` can never target ``postgres``, a template, an
    empty name, or a production database.
    """
    if (
        not name
        or name in _RESERVED_DATABASE_NAMES
        or not TEST_DATABASE_NAME_PATTERN.match(name)
    ):
        raise ConfigurationError(
            f"refusing destructive test operation on unsafe database name {name!r}; "
            f"test databases must match {TEST_DATABASE_NAME_PREFIX}<12 hex chars>"
        )
    return name


def _mask(url: str) -> str:
    """Render a URL without its password for safe error reporting."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "<unparseable database URL>"
