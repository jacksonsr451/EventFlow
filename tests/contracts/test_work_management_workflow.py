"""Tests for the work-management contracts defined in ADR-006.

These tests ensure that:
- The JSON Schema (`work_management.yaml`) is a valid Draft 2020-12 schema.
- Example payloads for the core entities validate against the schema.
- The OpenAPI specification (`work-management.yaml`) is syntactically correct.
- Invalid payloads raise `jsonschema.exceptions.ValidationError`.
"""

import pathlib
from urllib.request import pathname2url

import testrunner
import yaml
from jsonschema import Draft202012Validator, ValidationError
from openapi_spec_validator import validate

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "work_management.yaml"
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "work-management.yaml"


def load_yaml(path: pathlib.Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@testrunner.fixture(scope="session")
def schema():
    """Load and return the full JSON Schema document."""
    return load_yaml(SCHEMA_PATH)


@testrunner.fixture(scope="session")
def consultation_validator(schema):
    """Create a Draft202012Validator scoped to the Consultation definition."""
    consultation_schema = schema["$defs"]["Consultation"]
    # Build a self-contained schema referencing $defs from parent
    full_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        **consultation_schema,
    }
    Draft202012Validator.check_schema(full_schema)
    return Draft202012Validator(full_schema)


def test_openapi_spec_is_valid():
    """The OpenAPI contract must be a valid OpenAPI 3.1 document.

    Uses a file:// URI as the spec_url so that relative $ref paths
    (../schemas/work_management.yaml) are resolved correctly.
    """
    spec = load_yaml(OPENAPI_PATH)
    # Build a portable file URI — works on Windows and POSIX.
    spec_url = OPENAPI_PATH.as_uri()
    validate(spec, base_uri=spec_url)


def test_valid_consultation_payload(consultation_validator):
    """A minimal valid Consultation payload should pass validation."""
    valid_payload = {
        "consultation_id": "c123e456-7890-1234-5678-90abcdef1234",
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "project_id": "e345a678-9012-3456-7890-12cdef345678",
        "author_id": "f456b789-0123-4567-8901-23def4567890",
        "origin": "web",
        "title": "How to reset password?",
        "description": "Users cannot reset their passwords via the webapp.",
        "status": "open",
        "priority": "medium",
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    consultation_validator.validate(valid_payload)


def test_invalid_consultation_missing_required(consultation_validator):
    """Missing a required field (workspace_id) must raise a ValidationError."""
    invalid_payload = {
        "consultation_id": "c123e456-7890-1234-5678-90abcdef1234",
        # 'workspace_id' is omitted (required)
        "project_id": "e345a678-9012-3456-7890-12cdef345678",
        "author_id": "f456b789-0123-4567-8901-23def4567890",
        "origin": "web",
        "title": "How to reset password?",
        "description": "Users cannot reset their passwords via the webapp.",
        "status": "open",
        "priority": "medium",
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    with testrunner.raises(ValidationError):
        consultation_validator.validate(invalid_payload)


def test_invalid_consultation_bad_enum(consultation_validator):
    """Providing an enum value outside the allowed set must fail."""
    invalid_payload = {
        "consultation_id": "c123e456-7890-1234-5678-90abcdef1234",
        "workspace_id": "d234f567-8901-2345-6789-01bcde234567",
        "project_id": "e345a678-9012-3456-7890-12cdef345678",
        "author_id": "f456b789-0123-4567-8901-23def4567890",
        "origin": "web",
        "title": "How to reset password?",
        "description": "Users cannot reset their passwords via the webapp.",
        "status": "open",
        "priority": "ultra-high",  # not defined in the Priority enum
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    with testrunner.raises(ValidationError):
        consultation_validator.validate(invalid_payload)
