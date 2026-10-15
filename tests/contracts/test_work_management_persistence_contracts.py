"""Tests for the additive Work Management persistence definitions (ADR-008).

These definitions (Workspace, Project, Board, AuditRecord and
RemoteIntegrationReference) back the Work Management persistence layer without
altering the existing entity contracts.
"""

from __future__ import annotations

import pathlib

import testrunner
import yaml
from jsonschema import Draft202012Validator, ValidationError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "work_management.yaml"

PERSISTENCE_DEFS = (
    "Workspace",
    "Project",
    "Board",
    "AuditRecord",
    "RemoteIntegrationReference",
)

HASH = "a" * 64


def load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def validator_for(schema: dict, definition: str) -> Draft202012Validator:
    full_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        **schema["$defs"][definition],
    }
    Draft202012Validator.check_schema(full_schema)
    return Draft202012Validator(full_schema)


def test_persistence_definitions_are_present_and_valid():
    schema = load_schema()
    for definition in PERSISTENCE_DEFS:
        assert definition in schema["$defs"], f"{definition} is not defined"
        Draft202012Validator.check_schema(schema["$defs"][definition])


def test_workspace_example_validates():
    workspace = {
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "name": "Acme Inc",
        "slug": "acme-inc",
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    validator_for(load_schema(), "Workspace").validate(workspace)


def test_project_example_validates():
    project = {
        "project_id": "e345a678-9012-3456-7890-12cdef345678",
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "key": "DEMO",
        "name": "Demo Project",
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    validator_for(load_schema(), "Project").validate(project)


def test_audit_record_example_validates():
    record = {
        "audit_id": "f456b789-0123-4567-8901-23def4567890",
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "action": "proposal.decided",
        "entity_type": "proposal",
        "entity_id": "a123e456-7890-1234-5678-90abcdef1234",
        "occurred_at": "2023-01-01T12:00:00Z",
        "snapshot_hash": HASH,
    }
    validator_for(load_schema(), "AuditRecord").validate(record)


def test_remote_reference_invalid_provider_fails():
    reference = {
        "reference_id": "b123e456-7890-1234-5678-90abcdef1234",
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "provider": "bitbucket",
        "installation_id": "1",
        "remote_resource_type": "issue",
        "remote_resource_id": "42",
        "entity_type": "consultation",
        "entity_id": "c123e456-7890-1234-5678-90abcdef1234",
        "created_at": "2023-01-01T12:00:00Z",
    }
    with testrunner.raises(ValidationError):
        validator_for(load_schema(), "RemoteIntegrationReference").validate(reference)
