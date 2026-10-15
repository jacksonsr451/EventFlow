"""Runtime configuration for the Work Management service.

Configuration is environment-driven; no credentials are hard-coded or committed.
"""

from __future__ import annotations

import os

DATABASE_URL_ENV = "EVENTFLOW_DATABASE_URL"
TEST_DATABASE_URL_ENV = "EVENTFLOW_TEST_DATABASE_URL"


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


def test_admin_url() -> str | None:
    """Return the URL used to create throwaway databases for integration tests.

    Tests connect to an existing database and create/drop per-test databases;
    they never touch production schemas.
    """
    return os.environ.get(TEST_DATABASE_URL_ENV) or os.environ.get(DATABASE_URL_ENV)
