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
    "board_columns",
    "board_cards",
    "card_movements",
    "audit_records",
    "idempotency_records",
    "remote_integration_references",
    "external_identities",
    "authentication_sessions",
    "oidc_login_transactions",
    "authentication_security_events",
    "workspace_memberships",
    "workspace_invitations",
    "consultation_attachments",
    "consultation_attachment_blobs",
    "consultation_evidence",
    "proposal_revisions",
    "proposal_evidence",
}

EXPECTED_TRIGGERS = {
    "trg_work_items_origin_guard",
    "trg_audit_records_no_update",
    "trg_audit_records_no_delete",
    "trg_audit_records_no_truncate",
    "trg_remote_references_entity_guard",
    "trg_proposal_revisions_no_update",
    "trg_proposal_revisions_no_delete",
    "trg_proposal_revisions_no_truncate",
    "trg_card_movements_no_update",
    "trg_card_movements_no_delete",
    "trg_card_movements_no_truncate",
}

EXPECTED_FUNCTIONS = {
    "eventflow_validate_work_item_origin",
    "eventflow_validate_remote_reference",
    "eventflow_audit_records_block_mutation",
    "eventflow_proposal_revisions_block_mutation",
    "eventflow_card_movements_block_mutation",
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


def _constraints(engine: Engine) -> set[str]:
    query = text(
        "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace"
    )
    with engine.connect() as connection:
        return set(connection.execute(query).scalars())


EXPECTED_CONSTRAINTS = {
    "uq_work_items_origin_proposal",
    "uq_work_items_workspace_project_id",
    "uq_boards_workspace_project_id",
    "fk_board_cards_workspace_project_board",
    "fk_board_cards_workspace_project_work_item",
}


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
        assert _revision(engine) == "0008_kanban_boards_columns"
        assert EXPECTED_TRIGGERS <= _triggers(engine)
        assert EXPECTED_FUNCTIONS <= _functions(engine)
        assert EXPECTED_CONSTRAINTS <= _constraints(engine)


def test_upgrade_is_idempotent():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_migrations(url)
        assert _revision(engine) == "0008_kanban_boards_columns"


def test_downgrade_removes_tables_triggers_and_functions():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_downgrade(url)

        remaining = EXPECTED_TABLES & _tables(engine)
        assert not remaining
        assert not (_functions(engine) & EXPECTED_FUNCTIONS)
        assert not (_triggers(engine) & EXPECTED_TRIGGERS)
