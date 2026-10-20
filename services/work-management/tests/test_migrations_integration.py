"""Integration tests: migrating a real PostgreSQL database up and down."""

from __future__ import annotations

import re
from pathlib import Path

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
    "project_repositories",
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
    "entity_comments",
    "entity_attachments",
    "entity_attachment_blobs",
    "sla_policies",
    "sla_instances",
    "sla_pause_intervals",
    "sla_events",
    "work_item_dependencies",
    "notifications",
    "notification_preferences",
    "notification_deliveries",
    "project_triage_configurations",
    "project_triage_templates",
    "project_triage_template_versions",
    "project_triage_template_activations",
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
    "trg_entity_comments_no_rewrite",
    "trg_entity_comments_no_delete",
    "trg_entity_comments_no_truncate",
    "trg_triage_template_versions_no_update",
    "trg_triage_template_versions_no_delete",
    "trg_triage_template_versions_no_truncate",
}

EXPECTED_FUNCTIONS = {
    "eventflow_validate_work_item_origin",
    "eventflow_validate_remote_reference",
    "eventflow_audit_records_block_mutation",
    "eventflow_proposal_revisions_block_mutation",
    "eventflow_card_movements_block_mutation",
    "eventflow_entity_comments_block_rewrite",
    "eventflow_entity_comments_block_mutation",
    "eventflow_triage_template_versions_block_mutation",
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
    "fk_project_repositories_workspace_project",
    "uq_project_repositories_identity",
    "uq_project_repositories_workspace_id",
    "uq_project_triage_configurations_workspace_project",
    "uq_project_triage_configurations_workspace_id",
    "fk_project_triage_configurations_workspace_project",
    "ck_project_triage_configurations_version_positive",
    "ck_project_triage_configurations_required_fields_is_object",
    "ck_project_triage_configurations_custom_fields_is_array",
    "ck_project_triage_configurations_workflow_rules_is_object",
    "uq_project_triage_templates_scope_key",
    "uq_project_triage_templates_scope_id",
    "uq_project_triage_templates_workspace_id",
    "fk_project_triage_templates_workspace_project",
    "ck_project_triage_templates_category_values",
    "ck_project_triage_templates_status_values",
    "ck_project_triage_templates_key_format",
    "ck_project_triage_templates_name_length",
    "ck_project_triage_templates_description_length",
    "uq_project_triage_template_versions_scope_version",
    "uq_project_triage_template_versions_scope_id",
    "uq_project_triage_template_versions_workspace_id",
    "fk_project_triage_template_versions_scope_template",
    "ck_project_triage_template_versions_version_positive",
    "ck_project_triage_template_versions_status_values",
    "ck_project_triage_template_versions_definition_is_object",
    "ck_project_triage_template_versions_published_at_consistency",
    "ck_project_triage_template_versions_published_actor_consistency",
    "uq_project_triage_template_activations_scope_category",
    "uq_project_triage_template_activations_workspace_id",
    "fk_project_triage_template_activations_workspace_project",
    "fk_project_triage_template_activations_scope_template",
    "fk_project_triage_template_activations_scope_version",
    "ck_project_triage_template_activations_category_values",
    "ck_consultations_triage_template_version_positive",
    "ck_consultations_triage_template_schema_version_positive",
    "ck_consultations_triage_template_snapshot_is_object",
    "ck_consultations_triage_custom_fields_is_object",
}

EXPECTED_HEAD = "0012_project_triage_config"
VERSIONS_DIR = Path(__file__).resolve().parents[1] / (
    "src/eventflow_work_management/migrations/versions"
)


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
        assert _revision(engine) == EXPECTED_HEAD
        assert EXPECTED_TRIGGERS <= _triggers(engine)
        assert EXPECTED_FUNCTIONS <= _functions(engine)
        assert EXPECTED_CONSTRAINTS <= _constraints(engine)


def test_upgrade_is_idempotent():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_migrations(url)
        assert _revision(engine) == EXPECTED_HEAD


def test_revision_ids_fit_the_alembic_version_column():
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        match = re.search(
            r'^revision(?:: str)? = "([^"]+)"', source, re.MULTILINE
        )
        assert match is not None, f"{path.name} does not declare a revision"
        revision = match.group(1)
        assert len(revision) <= 32, (
            f"{path.name} revision {revision!r} exceeds the 32-character "
            "alembic_version column"
        )


def test_downgrade_removes_tables_triggers_and_functions():
    admin_url = require_database_url()
    with temporary_empty_database(admin_url) as (url, engine):
        run_migrations(url)
        run_downgrade(url)

        remaining = EXPECTED_TABLES & _tables(engine)
        assert not remaining
        assert not (_functions(engine) & EXPECTED_FUNCTIONS)
        assert not (_triggers(engine) & EXPECTED_TRIGGERS)
