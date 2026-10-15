"""Contract tests for the versioned public Work Management API (Issue #11).

These tests verify the HTTP contract in
``contracts/openapi/work-management.yaml`` and its DTOs in
``contracts/schemas/work_management.yaml``:

- Every operation requires bearer authentication and declares authorization
  roles drawn from the authoritative role vocabulary.
- Every declared error response uses ``application/problem+json`` and resolves
  to a single RFC 9457 problem definition.
- The problem definition is structurally compatible with the shared EventFlow
  error model without cross-referencing the Order Processing contracts.
- Retryable mutating operations declare ``Idempotency-Key`` (Amendment A-02)
  and optimistic-concurrency operations declare ``If-Match`` with ``412``.
- List operations declare cursor pagination, filtering and sorting and return a
  page envelope.
- Request bodies use the extracted request DTOs.
- Per-flow example payloads validate against their schema definitions.
"""

from __future__ import annotations

import json
import pathlib

import testrunner
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "work_management.yaml"
SHARED_SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "common.yaml"
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "work-management.yaml"
EXAMPLES = REPO_ROOT / "contracts" / "examples" / "work-management"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATING_METHODS = {"post", "put", "patch"}

ERROR_SCHEMA_REF = "../schemas/work_management.yaml#/$defs/ErrorResponse"

EXPECTED_IDEMPOTENCY_OPERATIONS = {
    "POST /v1/workspaces/{workspace_id}/consultations",
    "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
    "POST /v1/workspaces/{workspace_id}/proposals",
    "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
    "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
    "PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards",
}

LIST_OPERATIONS = {
    "listConsultations": "ConsultationPage",
    "listWorkItems": "WorkItemPage",
    "listBoardCards": "BoardCardPage",
}

EXAMPLE_DEFINITIONS = {
    "create-consultation.request.json": "CreateConsultationRequest",
    "triage-consultation.request.json": "TriageConsultationRequest",
    "create-proposal.request.json": "CreateProposalRequest",
    "decide-proposal.request.json": "DecideProposalRequest",
    "decide-proposal.response.json": "DecideProposalResponse",
    "move-board-card.request.json": "MoveBoardCardRequest",
    "consultations.page.json": "ConsultationPage",
    "problem.json": "ErrorResponse",
}

# Required by RFC 9457 and by the shared EventFlow error model.
SHARED_ERROR_REQUIRED = {"type", "title", "status", "detail", "correlation_id"}


def load_yaml(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_json(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


@testrunner.fixture(scope="session")
def schema() -> dict:
    return load_yaml(SCHEMA_PATH)


@testrunner.fixture(scope="session")
def openapi() -> dict:
    return load_yaml(OPENAPI_PATH)


def validator_for(schema: dict, definition: str) -> Draft202012Validator:
    full_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        **schema["$defs"][definition],
    }
    Draft202012Validator.check_schema(full_schema)
    return Draft202012Validator(full_schema)


def iter_operations(openapi: dict):
    for path, item in openapi["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def parameter_name(openapi: dict, parameter: dict) -> str | None:
    reference = parameter.get("$ref")
    if reference:
        name = reference.rsplit("/", 1)[-1]
        return openapi["components"]["parameters"][name].get("name")
    return parameter.get("name")


def parameter_names(openapi: dict, operation: dict) -> list[str]:
    return [
        parameter_name(openapi, parameter)
        for parameter in operation.get("parameters", [])
    ]


# ---------------------------------------------------------------------------
# Authentication and authorization
# ---------------------------------------------------------------------------


def test_every_operation_requires_bearer_auth(openapi):
    """Every operation must declare the bearer authentication scheme."""
    missing = []
    for path, method, operation in iter_operations(openapi):
        schemes = {name for entry in operation.get("security", []) for name in entry}
        if "bearerAuth" not in schemes:
            missing.append(f"{method.upper()} {path}")
    assert not missing, f"operations without bearerAuth: {missing}"


def test_bearer_auth_scheme_is_declared(openapi):
    """The bearerAuth security scheme must be defined as HTTP bearer JWT."""
    scheme = openapi["components"]["securitySchemes"]["bearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


def test_every_operation_declares_authorization_roles(openapi, schema):
    """Every operation must declare x-required-roles from the role vocabulary."""
    roles = set(schema["$defs"]["Role"]["enum"])
    problems = []
    for path, method, operation in iter_operations(openapi):
        required = operation.get("x-required-roles")
        if not required:
            problems.append(f"{method.upper()} {path}: missing x-required-roles")
            continue
        unknown = set(required) - roles
        if unknown:
            problems.append(f"{method.upper()} {path}: unknown roles {sorted(unknown)}")
    assert not problems, f"authorization declaration problems: {problems}"


def test_decide_requires_approver_or_higher(openapi):
    """Approval decisions must require an approver, admin, or owner."""
    decide = openapi["paths"][
        "/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide"
    ]["post"]
    assert set(decide["x-required-roles"]) == {"approver", "admin", "owner"}


# ---------------------------------------------------------------------------
# Error contract (Amendment A-01)
# ---------------------------------------------------------------------------


def test_error_responses_use_problem_json(openapi):
    """Every declared error response must use application/problem+json."""
    missing = [
        name
        for name, response in openapi["components"]["responses"].items()
        if "application/problem+json" not in response.get("content", {})
    ]
    assert not missing, f"error responses without problem+json: {missing}"


def test_error_responses_reference_a_single_definition(openapi):
    """All error responses must reference one shared Work Management problem def."""
    wrong = [
        name
        for name, response in openapi["components"]["responses"].items()
        if response["content"]["application/problem+json"].get("schema", {}).get("$ref")
        != ERROR_SCHEMA_REF
    ]
    assert not wrong, f"error responses not using the shared problem def: {wrong}"


def test_error_schema_is_rfc9457_shaped(schema):
    """The problem definition must carry the RFC 9457 members."""
    error = schema["$defs"]["ErrorResponse"]
    for member in ("type", "title", "status", "detail", "instance"):
        assert member in error["properties"], f"ErrorResponse is missing {member}"
    status = error["properties"]["status"]
    assert status["minimum"] == 400 and status["maximum"] == 599
    assert set(error["required"]) >= {"type", "title", "status", "detail"}


def test_error_schema_matches_the_shared_error_model(schema):
    """Work Management problems must be structurally compatible with the shared model.

    The Work Management contract cannot reference Order Processing schemas
    (bounded-context isolation), so compatibility is asserted here instead.
    """
    shared = load_yaml(SHARED_SCHEMA_PATH)["$defs"]["Error"]
    wm_error = schema["$defs"]["ErrorResponse"]
    missing_properties = set(shared["properties"]) - set(wm_error["properties"])
    assert not missing_properties, (
        f"Work Management ErrorResponse omits shared fields: {sorted(missing_properties)}"
    )
    assert set(shared["required"]) <= set(wm_error["required"]), (
        "Work Management ErrorResponse must require every shared required field"
    )
    errors_item = wm_error["properties"]["errors"]["items"]
    assert {"field", "message"} <= set(errors_item["required"])


def test_problem_example_validates(schema):
    """The example problem document must validate against ErrorResponse."""
    validator_for(schema, "ErrorResponse").validate(
        load_json(EXAMPLES / "problem.json")
    )


# ---------------------------------------------------------------------------
# Idempotency (Amendment A-02) and optimistic concurrency
# ---------------------------------------------------------------------------


def test_idempotency_key_declared_on_retryable_operations(openapi):
    """Idempotency-Key must be declared on exactly the retryable operations."""
    operations = {
        f"{method.upper()} {path}"
        for path, method, operation in iter_operations(openapi)
        if "Idempotency-Key" in parameter_names(openapi, operation)
    }
    assert operations == EXPECTED_IDEMPOTENCY_OPERATIONS, (
        f"unexpected Idempotency-Key declarations: {sorted(operations)}"
    )


def test_decide_idempotency_key_is_required(openapi):
    """The approval decision must require the Idempotency-Key header."""
    parameters = openapi["components"]["parameters"]
    assert parameters["IdempotencyKey"]["required"] is True
    assert parameters["IdempotencyKeyOptional"]["required"] is False


def test_optimistic_concurrency_declares_if_match_and_412(openapi):
    """Operations accepting If-Match must document the 412 response."""
    problems = []
    for path, method, operation in iter_operations(openapi):
        if "If-Match" not in parameter_names(openapi, operation):
            continue
        if "412" not in operation.get("responses", {}):
            problems.append(f"{method.upper()} {path}: If-Match without 412")
    assert not problems, f"If-Match operations missing 412: {problems}"
    decide = openapi["paths"][
        "/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide"
    ]["post"]
    assert "If-Match" in parameter_names(openapi, decide)
    assert "412" in decide["responses"]


# ---------------------------------------------------------------------------
# Pagination, filtering and sorting
# ---------------------------------------------------------------------------


def test_list_operations_paginate(openapi):
    """List operations must declare pagination and return a page envelope."""
    problems = []
    for path, method, operation in iter_operations(openapi):
        operation_id = operation.get("operationId")
        if operation_id not in LIST_OPERATIONS:
            continue
        names = parameter_names(openapi, operation)
        for expected in ("limit", "cursor", "sort"):
            if expected not in names:
                problems.append(f"{operation_id}: missing {expected}")
        if not operation.get("x-allowed-sort-fields"):
            problems.append(f"{operation_id}: missing x-allowed-sort-fields")
        schema_ref = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        if not schema_ref.endswith(LIST_OPERATIONS[operation_id]):
            problems.append(
                f"{operation_id}: response is not {LIST_OPERATIONS[operation_id]}"
            )
    assert not problems, f"pagination problems: {problems}"


def test_page_envelopes_are_defined(schema):
    """The page envelope definitions must be present and valid."""
    for definition in ("PageInfo", "ConsultationPage", "WorkItemPage", "BoardCardPage"):
        assert definition in schema["$defs"], f"{definition} is not defined"
        Draft202012Validator.check_schema(schema["$defs"][definition])


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


def test_mutating_bodies_reference_dtos(openapi):
    """Mutating request bodies must reference extracted request DTOs."""
    problems = []
    for path, method, operation in iter_operations(openapi):
        if method not in MUTATING_METHODS:
            continue
        body = operation.get("requestBody")
        if not body:
            continue
        schema = body["content"]["application/json"]["schema"]
        reference = schema.get("$ref", "")
        if not reference.startswith("../schemas/work_management.yaml#/$defs/"):
            problems.append(f"{method.upper()} {path}: body is not a DTO reference")
    assert not problems, f"request bodies not using DTOs: {problems}"


def test_all_dtos_are_valid(schema):
    """Every request/response DTO must be a valid Draft 2020-12 definition."""
    for definition in EXAMPLE_DEFINITIONS.values():
        Draft202012Validator.check_schema(schema["$defs"][definition])


# ---------------------------------------------------------------------------
# Per-flow examples
# ---------------------------------------------------------------------------


def test_per_flow_examples_validate(schema):
    """Every example payload must validate against its schema definition."""
    failures = []
    for filename, definition in EXAMPLE_DEFINITIONS.items():
        try:
            validator_for(schema, definition).validate(load_json(EXAMPLES / filename))
        except Exception as error:  # noqa: BLE001 - surface the failing example
            failures.append(f"{filename} ({definition}): {error}")
    assert not failures, f"invalid examples: {failures}"
