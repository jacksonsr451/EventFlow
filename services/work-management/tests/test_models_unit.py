"""Unit tests for the SQLAlchemy metadata (no database required)."""

from __future__ import annotations

import pathlib

import testrunner
from eventflow_work_management import models  # noqa: F401  (registers tables)
from eventflow_work_management.db import Base
from eventflow_work_management.models import enums as model_enums
from sqlalchemy import CheckConstraint, UniqueConstraint

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "work_management.yaml"

EXPECTED_TABLES = {
    "workspaces",
    "projects",
    "consultations",
    "proposals",
    "proposal_revisions",
    "proposal_evidence",
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
    "workspace_memberships",
    "workspace_invitations",
    "consultation_attachments",
    "consultation_attachment_blobs",
    "consultation_evidence",
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
}

AUTHENTICATION_TABLES = {
    "external_identities",
    "oidc_login_transactions",
    "authentication_sessions",
    "authentication_security_events",
}

TENANT_TABLES = EXPECTED_TABLES - {"workspaces"}


def test_expected_tables_are_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES | AUTHENTICATION_TABLES


def test_primary_key_naming_convention():
    for name, table in Base.metadata.tables.items():
        assert table.primary_key.name == f"pk_{name}"


def test_tenant_tables_carry_workspace_id():
    for name in TENANT_TABLES:
        table = Base.metadata.tables[name]
        assert "workspace_id" in table.columns, f"{name} is missing workspace_id"
        assert not table.columns["workspace_id"].nullable, (
            f"{name}.workspace_id must be NOT NULL"
        )


def test_approval_has_one_decision_per_proposal_version():
    table = Base.metadata.tables["approvals"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("proposal_id", "proposal_version") in unique_columns


def test_work_item_origin_columns_are_required():
    table = Base.metadata.tables["work_items"]
    for column in (
        "origin_proposal_id",
        "origin_proposal_version",
        "origin_approval_id",
    ):
        assert column in table.columns
        assert not table.columns[column].nullable


def test_work_item_origin_proposal_is_unique():
    table = Base.metadata.tables["work_items"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("origin_proposal_id",) in unique_columns


def test_board_cards_carry_project_id():
    table = Base.metadata.tables["board_cards"]
    assert "project_id" in table.columns
    assert not table.columns["project_id"].nullable


def test_board_card_project_foreign_keys_share_project():
    table = Base.metadata.tables["board_cards"]
    foreign_keys = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.foreign_key_constraints
    }
    assert (
        "fk_board_cards_workspace_project_board",
        ("workspace_id", "project_id", "board_id"),
    ) in foreign_keys
    assert (
        "fk_board_cards_workspace_project_work_item",
        ("workspace_id", "project_id", "work_item_id"),
    ) in foreign_keys


def test_audit_records_are_required_and_hashed():
    table = Base.metadata.tables["audit_records"]
    assert not table.columns["snapshot_hash"].nullable
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any("snapshot_hash_format" in name for name in check_names)


def test_enum_check_values_match_contract():
    yaml = testrunner.importorskip("yaml")

    with SCHEMA_PATH.open(encoding="utf-8") as stream:
        schema = yaml.safe_load(stream)
    defs = schema["$defs"]

    expectations = {
        "Origin": model_enums.ORIGIN_VALUES,
        "TriageCategory": model_enums.TRIAGE_CATEGORY_VALUES,
        "Priority": model_enums.PRIORITY_VALUES,
        "ConsultationStatus": model_enums.CONSULTATION_STATUS_VALUES,
        "ProposalStatus": model_enums.PROPOSAL_STATUS_VALUES,
        "ApprovalDecision": model_enums.APPROVAL_DECISION_VALUES,
        "WorkItemStatus": model_enums.WORK_ITEM_STATUS_VALUES,
        "AttachmentStatus": model_enums.ATTACHMENT_STATUS_VALUES,
        "AttachmentScanVerdict": model_enums.ATTACHMENT_SCAN_VERDICT_VALUES,
        "EvidenceKind": model_enums.EVIDENCE_KIND_VALUES,
    }
    for name, expected in expectations.items():
        assert tuple(defs[name]["enum"]) == expected, (
            f"{name} drifted from the contract"
        )

    provider = defs["RemoteIntegrationReference"]["properties"]["provider"]["enum"]
    resource_type = defs["RemoteIntegrationReference"]["properties"][
        "remote_resource_type"
    ]["enum"]
    assert tuple(provider) == model_enums.REMOTE_PROVIDER_VALUES
    assert tuple(resource_type) == model_enums.REMOTE_RESOURCE_TYPE_VALUES

    assert (
        tuple(defs["RemoteProvider"]["enum"]) == model_enums.REMOTE_PROVIDER_VALUES
    )
    assert (
        tuple(defs["ProjectRepositoryStatus"]["enum"])
        == model_enums.PROJECT_REPOSITORY_STATUS_VALUES
    )
    assert (
        tuple(defs["ProjectRepositoryVerificationStatus"]["enum"])
        == model_enums.PROJECT_REPOSITORY_VERIFICATION_VALUES
    )


def test_project_repositories_deduplicate_on_remote_identity():
    table = Base.metadata.tables["project_repositories"]
    unique_columns = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_columns["uq_project_repositories_identity"] == (
        "workspace_id",
        "project_id",
        "provider",
        "provider_instance_id",
        "remote_repository_id",
    )
    assert unique_columns["uq_project_repositories_workspace_id"] == (
        "workspace_id",
        "id",
    )


def test_project_repositories_bind_workspace_project_and_status():
    table = Base.metadata.tables["project_repositories"]
    foreign_keys = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.foreign_key_constraints
    }
    assert (
        "fk_project_repositories_workspace_project",
        ("workspace_id", "project_id"),
    ) in foreign_keys
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_project_repositories_provider_values",
        "ck_project_repositories_status_values",
        "ck_project_repositories_verification_values",
        "ck_project_repositories_deactivated_consistency",
        "ck_project_repositories_archived_consistency",
    } <= check_names
