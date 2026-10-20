"""Contract tests for the security event schema and tenant boundaries.

These tests verify that:

- `contracts/schemas/security_events.yaml` is a valid Draft 2020-12 schema.
- Valid security events pass and invalid ones fail validation.
- The schema defines no secret-bearing properties.
- The schema does not define bounded-context entities.
- Work Management tenant boundaries hold: workspace path parameters are
  required, mutating request bodies do not declare a tenant, idempotency is
  declared only where the contract allows it, errors use problem+json, and
  editor context requires consent.
"""

import pathlib

import testrunner
import yaml
from jsonschema import Draft202012Validator, ValidationError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "contracts" / "schemas"
SECURITY_SCHEMA_PATH = SCHEMAS / "security_events.yaml"
WM_SCHEMA_PATH = SCHEMAS / "work_management.yaml"
WM_OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "work-management.yaml"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATING_METHODS = {"post", "put", "patch"}

SECRET_PROPERTY_NAMES = {
    "token",
    "tokens",
    "access_token",
    "refresh_token",
    "secret",
    "secrets",
    "client_secret",
    "password",
    "passwords",
    "authorization",
    "credential",
    "credentials",
    "signature",
    "payload",
}

FORBIDDEN_DEFS = {
    "Consultation",
    "Proposal",
    "Approval",
    "WorkItem",
    "BoardCard",
    "EditorContext",
    "Order",
    "Payment",
    "Reservation",
    "PriceQuote",
}

WORKSPACE = "a1b2c3d4-0000-0000-0000-000000000001"


def load_yaml(path):
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


@testrunner.fixture(scope="session")
def security_schema():
    return load_yaml(SECURITY_SCHEMA_PATH)


@testrunner.fixture(scope="session")
def security_event_validator(security_schema):
    full_schema = {
        "$schema": security_schema["$schema"],
        "$defs": security_schema["$defs"],
        **security_schema["$defs"]["SecurityEvent"],
    }
    Draft202012Validator.check_schema(full_schema)
    return Draft202012Validator(full_schema)


@testrunner.fixture(scope="session")
def wm_openapi():
    return load_yaml(WM_OPENAPI_PATH)


@testrunner.fixture(scope="session")
def wm_schema():
    return load_yaml(WM_SCHEMA_PATH)


def _property_names(node, names=None):
    if names is None:
        names = set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in node.values():
            _property_names(value, names)
    elif isinstance(node, list):
        for item in node:
            _property_names(item, names)
    return names


def _parameter_name(spec, parameter):
    reference = parameter.get("$ref")
    if reference:
        name = reference.rsplit("/", 1)[-1]
        return spec["components"]["parameters"][name].get("name")
    return parameter.get("name")


def _valid_event():
    return {
        "event_id": "c123e456-7890-1234-5678-90abcdef1234",
        "schema_version": 1,
        "event_type": "auth.failure",
        "severity": "medium",
        "outcome": "failure",
        "occurred_at": "2023-01-01T12:00:00Z",
        "actor": {
            "actor_type": "user",
            "actor_id": "user-123",
            "workspace_id": WORKSPACE,
        },
        "workspace_id": WORKSPACE,
        "source": "web",
        "details": {"reason": "invalid_password"},
    }


# ---------------------------------------------------------------------------
# Security event schema
# ---------------------------------------------------------------------------


def test_security_events_schema_is_valid_draft_2020_12(security_schema):
    """The security event schema must be a valid Draft 2020-12 document."""
    Draft202012Validator.check_schema(security_schema)


def test_security_events_schema_defines_event_taxonomy(security_schema):
    """The schema must define the documented security event taxonomy."""
    types = security_schema["$defs"]["SecurityEventType"]["enum"]
    assert len(types) == len(set(types)), "security event types must be unique"
    for required in (
        "tenant.cross_access_attempt",
        "webhook.verification_failure",
        "data.export",
        "data.deletion",
    ):
        assert required in types, f"{required} is missing from the event taxonomy"


def test_valid_security_event_payload(security_event_validator):
    """A minimal valid security event must pass validation."""
    security_event_validator.validate(_valid_event())


def test_invalid_security_event_missing_required(security_event_validator):
    """Omitting a required field must raise a ValidationError."""
    payload = _valid_event()
    del payload["event_type"]
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_bad_enum(security_event_validator):
    """An unknown event type must raise a ValidationError."""
    payload = _valid_event()
    payload["event_type"] = "auth.unrecognized"
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_missing_schema_version(security_event_validator):
    """Omitting schema_version must raise a ValidationError."""
    payload = _valid_event()
    del payload["schema_version"]
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_wrong_schema_version(security_event_validator):
    """A schema_version other than the pinned const must raise a ValidationError."""
    payload = _valid_event()
    payload["schema_version"] = 2
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_unknown_root_property(security_event_validator):
    """An undeclared root property must raise a ValidationError."""
    payload = _valid_event()
    payload["access_token"] = "secret-value"
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_details_forbid_additional_properties(
    security_event_validator,
):
    """An undeclared details key must raise a ValidationError."""
    payload = _valid_event()
    payload["details"]["token"] = "secret-value"
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_invalid_security_event_actor_id_is_length_bounded(
    security_event_validator,
):
    """An oversized actor_id must raise a ValidationError."""
    payload = _valid_event()
    payload["actor"]["actor_id"] = "a" * 129
    with testrunner.raises(ValidationError):
        security_event_validator.validate(payload)


def test_free_text_fields_declare_a_max_length(security_schema):
    """Free-text security fields must be length bounded."""
    defs = security_schema["$defs"]
    expectations = {
        "SecurityActor": "actor_id",
        "SecurityDetails": "reason",
        "SecurityDetails": "resource_type",
        "SecurityEvent": "subject",
    }
    unbounded = []
    for definition, field in expectations.items():
        prop = defs[definition]["properties"].get(field, {})
        if not isinstance(prop.get("maxLength"), int):
            unbounded.append(f"{definition}.{field}")
    assert not unbounded, f"free-text fields without maxLength: {unbounded}"


def test_schema_defines_no_secret_properties(security_schema):
    """The security event schema must not define secret-bearing properties."""
    leaked = _property_names(security_schema) & SECRET_PROPERTY_NAMES
    assert not leaked, f"security schema defines secret properties: {sorted(leaked)}"


def test_schema_defines_no_bounded_context_entities(security_schema):
    """The security schema must not define domain entity types."""
    leaked = set(security_schema["$defs"]) & FORBIDDEN_DEFS
    assert not leaked, f"security schema defines domain entities: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Work Management tenant and error boundaries
# ---------------------------------------------------------------------------


def test_workspace_paths_require_workspace_id_parameter(wm_openapi):
    """Every workspace-scoped operation must require the workspace_id path."""
    missing = []
    for path, item in wm_openapi["paths"].items():
        if "{workspace_id}" not in path:
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            names = [
                _parameter_name(wm_openapi, parameter)
                for parameter in operation.get("parameters", [])
            ]
            if "workspace_id" not in names:
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"workspace operations missing workspace_id: {missing}"


def test_mutating_request_bodies_do_not_declare_tenant(wm_openapi):
    """Request bodies must not declare workspace_id or tenant_id."""
    violations = []
    for path, item in wm_openapi["paths"].items():
        for method, operation in item.items():
            if method not in MUTATING_METHODS:
                continue
            body = operation.get("requestBody")
            if not body:
                continue
            schema = body["content"]["application/json"]["schema"]
            properties = schema.get("properties", {})
            if "workspace_id" in properties or "tenant_id" in properties:
                violations.append(f"{method.upper()} {path}")
    assert not violations, f"request bodies declaring a tenant: {violations}"


def test_idempotency_key_declared_on_retryable_operations(wm_openapi):
    """Idempotency-Key must be declared on the retryable mutating operations.

    Amendment A-02 (owned by Issue #11) extends the header beyond the approval
    decision to every unsafe operation a client may replay.
    """
    operations = []
    for path, item in wm_openapi["paths"].items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            names = [
                _parameter_name(wm_openapi, parameter)
                for parameter in operation.get("parameters", [])
            ]
            if "Idempotency-Key" in names:
                operations.append(f"{method.upper()} {path}")
    assert operations == [
        "POST /v1/workspaces/{workspace_id}/consultations",
        "POST /v1/workspaces/{workspace_id}/consultations/drafts",
        "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
        "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/reclassify",
        "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
        "PATCH /v1/workspaces/{workspace_id}/consultations/{consultation_id}",
        "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/attachments",
        "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/evidence",
        "POST /v1/workspaces/{workspace_id}/proposals",
        "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
        "PATCH /v1/workspaces/{workspace_id}/proposals/{proposal_id}",
        "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/duplicate",
        "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
        "POST /v1/workspaces/{workspace_id}/boards",
        "PATCH /v1/workspaces/{workspace_id}/boards/{board_id}",
        "POST /v1/workspaces/{workspace_id}/boards/{board_id}/columns",
        "PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/columns/{column_id}",
        "DELETE /v1/workspaces/{workspace_id}/boards/{board_id}/columns/{column_id}",
        "PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}",
        "POST /v1/workspaces/{workspace_id}/projects/{project_id}/repositories",
        "PATCH /v1/workspaces/{workspace_id}/projects/{project_id}/repositories/{repository_id}",
        "DELETE /v1/workspaces/{workspace_id}/projects/{project_id}/repositories/{repository_id}",
        "POST /v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}/comments",
        "POST /v1/workspaces/{workspace_id}/{entity_collection}/{entity_id}/attachments",
        "POST /v1/workspaces/{workspace_id}/sla-policies",
        "POST /v1/workspaces/{workspace_id}/sla-policies/{policy_id}/versions",
        "POST /v1/workspaces/{workspace_id}/sla-policies/{policy_id}/activate",
        "PATCH /v1/workspaces/{workspace_id}/work-items/{work_item_id}/priority",
        "POST /v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies",
        "DELETE /v1/workspaces/{workspace_id}/work-items/{work_item_id}/dependencies/{dependency_id}",
    ], f"unexpected Idempotency-Key declarations: {operations}"


def test_error_responses_use_problem_json(wm_openapi):
    """Every declared error response must use application/problem+json."""
    missing = [
        name
        for name, response in wm_openapi["components"]["responses"].items()
        if "application/problem+json" not in response.get("content", {})
    ]
    assert not missing, f"error responses without problem+json: {missing}"


def test_editor_context_requires_consent(wm_schema):
    """Editor context must require consent_granted to be true."""
    editor_context = wm_schema["$defs"]["EditorContext"]
    assert "consent_granted" in editor_context["required"], (
        "EditorContext must require consent_granted"
    )
    assert editor_context["properties"]["consent_granted"].get("const") is True, (
        "consent_granted must be constrained to true"
    )
