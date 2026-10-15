"""Integration tests: migrating a real PostgreSQL database up and down."""

from __future__ import annotations

from sqlalchemy import Engine, text

from support import (
    require_database_url,
    run_downgrade,
    run_migrations,
    temporary_empty_database,
)

EXPECTED_TABLES = {
    "workspaces",
    "projects",
    "consultations",
    "proposals",
    "approvals",
    "work_items",
    "boards",
    "board_cards",
    "audit_records",
    "idempotency_records",
    "remote_integration_references",
}

EXPECTED_TRIGGERS = {
    "trg_work_items_origin_guard",
    "trg_audit_records_no_update",
    "trg_audit_records_no_delete",
}


def _tables(engine: Engine) -> set[str]:
    query = text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def _triggers(engine: Engine) -> set[str]:
    query = text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def _functions(engine: Engine) -> set[str]:
    query = text("SELECT proname FROM pg_proc WHERE proname LIKE 'eventflow_%'")
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


def _revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_schema_guards_and_revision():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        assert "workspaces" not in _tables(engine)

        run_migrations(url)

        tables = _tables(engine)
        assert EXPECTED_TABLES <= tables
        assert "alembic_version" in tables
        assert _revision(engine) == "0001_initial"
        assert EXPECTED_TRIGGERS <= _triggers(engine)
        assert {"eventflow_validate_work_item_origin", "eventflow_audit_records_block_mutation"} <= _functions(engine)


def test_upgrade_is_idempotent():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_migrations(url)
        assert _revision(engine) == "0001_initial"


def test_downgrade_removes_tables_triggers_and_functions():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_downgrade(url)

        remaining = EXPECTED_TABLES & _tables(engine)
        assert not remaining
        assert not (_functions(engine) & {"eventflow_validate_work_item_origin", "eventflow_audit_records_block_mutation"})
        assert not (_triggers(engine) & EXPECTED_TRIGGERS)
