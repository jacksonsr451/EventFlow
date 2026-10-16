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
    "approvals",
    "work_items",
    "boards",
    "board_cards",
    "audit_records",
    "idempotency_records",
    "remote_integration_references",
}

TENANT_TABLES = EXPECTED_TABLES - {"workspaces"}


def test_expected_tables_are_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


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
