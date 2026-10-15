"""Integration test for the database health check."""

from __future__ import annotations

from eventflow_work_management.db.health import check_database_health
from support import migrated_engine, require_database_url


def test_database_health_check_returns_true():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        assert check_database_health(engine) is True
