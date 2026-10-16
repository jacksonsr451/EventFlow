"""Unit tests for fail-closed test database configuration (F-10).

These tests never open a connection: they exercise the validation layer that
guards destructive test operations. Passwords in fixtures are fake.
"""

from __future__ import annotations

import os

import testrunner
from eventflow_work_management import config
from support import temporary_empty_database

VALID_TEST_URL = "postgresql+psycopg://tester:secret@localhost:5432/eventflow"
PRODUCTION_URL = "postgresql+psycopg://prod_user:prod_pass@prod-db:5432/eventflow"


class _env:
    """Temporarily set/remove the database environment variables."""

    def __init__(self, **values: str | None) -> None:
        self._values = values
        self._saved: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self._values.items():
            self._saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def test_missing_test_admin_url_is_rejected():
    with _env(EVENTFLOW_TEST_DATABASE_URL=None, EVENTFLOW_DATABASE_URL=None):
        with testrunner.raises(config.ConfigurationError):
            config.test_admin_url()
        with testrunner.raises(config.ConfigurationError):
            config.validate_test_admin_url(None)
        with testrunner.raises(config.ConfigurationError):
            config.validate_test_admin_url("")


def test_explicit_valid_test_admin_url_is_returned():
    with _env(EVENTFLOW_TEST_DATABASE_URL=VALID_TEST_URL):
        assert config.test_admin_url() == VALID_TEST_URL
        assert config.validate_test_admin_url(VALID_TEST_URL) == VALID_TEST_URL


def test_application_url_is_never_used_as_test_admin_fallback():
    with _env(EVENTFLOW_TEST_DATABASE_URL=None, EVENTFLOW_DATABASE_URL=PRODUCTION_URL):
        with testrunner.raises(config.ConfigurationError) as caught:
            config.test_admin_url()
        assert PRODUCTION_URL not in str(caught.value)
        assert "prod_pass" not in str(caught.value)


def test_maintenance_database_is_accepted_as_admin_connection():
    url = "postgresql+psycopg://tester:secret@localhost:5432/postgres"
    assert config.validate_test_admin_url(url) == url
    with testrunner.raises(config.ConfigurationError):
        config.assert_safe_test_database_name("postgres")


def test_invalid_test_database_names_are_rejected():
    for unsafe in (
        "",
        "postgres",
        "template0",
        "template1",
        "eventflow",
        "eventflow_test_",
        "eventflow_test_ZZZZZZZZZZZZ",
        "eventflow_test_1234",
        "public",
    ):
        with testrunner.raises(config.ConfigurationError):
            config.assert_safe_test_database_name(unsafe)

    assert (
        config.assert_safe_test_database_name("eventflow_test_0123456789ab")
        == "eventflow_test_0123456789ab"
    )


def test_malformed_test_admin_url_is_rejected():
    for malformed in ("not a url", "postgresql+psycopg://", "://missing-scheme"):
        with testrunner.raises(config.ConfigurationError):
            config.validate_test_admin_url(malformed)


def test_error_messages_do_not_leak_passwords():
    reserved = "postgresql+psycopg://user:supersecret@localhost:5432/template1"
    with testrunner.raises(config.ConfigurationError) as caught:
        config.validate_test_admin_url(reserved)
    assert "supersecret" not in str(caught.value)

    no_database = "postgresql+psycopg://user:supersecret@localhost:5432/"
    with testrunner.raises(config.ConfigurationError) as caught:
        config.validate_test_admin_url(no_database)
    assert "supersecret" not in str(caught.value)

    malformed = "postgresql+psycopg://user:supersecret@:::not-a-port/db"
    with testrunner.raises(config.ConfigurationError) as caught:
        config.validate_test_admin_url(malformed)
    assert "supersecret" not in str(caught.value)


def test_ci_shared_configuration_is_supported():
    with _env(
        EVENTFLOW_TEST_DATABASE_URL=VALID_TEST_URL,
        EVENTFLOW_DATABASE_URL=VALID_TEST_URL,
    ):
        assert config.test_admin_url() == VALID_TEST_URL


def test_cleanup_protection_rejects_unsafe_admin_target():
    unsafe = "postgresql+psycopg://user:supersecret@localhost:5432/template1"
    with testrunner.raises(config.ConfigurationError) as caught:
        with temporary_empty_database(unsafe):
            raise AssertionError("must not connect to an unsafe admin target")
    assert "supersecret" not in str(caught.value)
