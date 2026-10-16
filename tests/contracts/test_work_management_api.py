"""Contract tests for the versioned public Work Management API (Issue #11).

These tests verify the HTTP contract in
``contracts/openapi/work-management.yaml`` and its DTOs in
``contracts/schemas/work_management.yaml``:

- Every operation requires bearer authentication and declares authorization
  roles drawn from the authoritative role vocabulary.
- Every declared error response uses ``application/problem+json`` and resolves
  to a single RFC 9457 problem definition.
- Problem Details core member names/types align with the shared EventFlow error
  model without cross-referencing the Order Processing contracts.
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
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "work_management.yaml"
SHARED_SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "common.yaml"
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "work-management.yaml"
EXAMPLES = REPO_ROOT / "contracts" / "examples" / "work-management"
BOARD_MODEL_PATH = (
    REPO_ROOT
    / "services"
    / "work-management"
    / "src"
    / "eventflow_work_management"
    / "models"
    / "board.py"
)
INITIAL_MIGRATION_PATH = (
    REPO_ROOT
    / "services"
    / "work-management"
    / "src"
    / "eventflow_work_management"
    / "migrations"
    / "versions"
    / "0001_initial_work_management_schema.py"
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATING_METHODS = {"post", "put", "patch"}

ERROR_SCHEMA_REF = "../schemas/work_management.yaml#/$defs/ErrorResponse"

EXPECTED_IDEMPOTENCY_OPERATIONS = {
    "POST /v1/workspaces/{workspace_id}/consultations",
    "POST /v1/workspaces/{workspace_id}/consultations/drafts",
    "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
    "POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
    "PATCH /v1/workspaces/{workspace_id}/consultations/{consultation_id}",
    "POST /v1/workspaces/{workspace_id}/proposals",
    "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
    "POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
    "PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}",
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
    return Draft202012Validator(full_schema, format_checker=FormatChecker())


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
    assert set(schema["$defs"]["Role"]["enum"]) == {
        "owner",
        "admin",
        "triager",
        "approver",
        "contributor",
        "viewer",
    }


def test_operation_ids_are_unique_and_paths_are_versioned(openapi):
    """The public API must have unique operation ids under the approved /v1 prefix."""
    operation_ids = [
        operation.get("operationId") for _, _, operation in iter_operations(openapi)
    ]
    assert all(operation_ids), "every operation must have an operationId"
    assert len(operation_ids) == len(set(operation_ids)), "operationIds must be unique"
    paths = list(openapi["paths"])
    assert paths and all(path.startswith("/v1/") for path in paths)
    assert not any(path.startswith("/api/v1/") for path in paths)


def test_operation_tags_are_declared(openapi):
    """Operations use only the documented OpenAPI tag set."""
    declared = {tag["name"] for tag in openapi["tags"]}
    for path, method, operation in iter_operations(openapi):
        tags = operation.get("tags", [])
        assert tags, f"{method.upper()} {path} has no tag"
        assert set(tags) <= declared, f"{method.upper()} {path} uses undeclared tags"


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
    """All error responses must compose one shared Work Management problem def."""
    wrong = []
    for name, response in openapi["components"]["responses"].items():
        response_schema = response["content"]["application/problem+json"]["schema"]
        if name == "UnexpectedError":
            if response_schema.get("$ref") != ERROR_SCHEMA_REF:
                wrong.append(name)
            continue
        wrapper = openapi["components"]["schemas"][
            response_schema["$ref"].rsplit("/", 1)[-1]
        ]
        if wrapper["allOf"][0].get("$ref") != ERROR_SCHEMA_REF:
            wrong.append(name)
    assert not wrong, f"error responses not using the shared problem def: {wrong}"


def test_every_operation_declares_sanitized_default_error(openapi):
    """Unexpected errors use the shared sanitized Problem Details response."""
    for path, method, operation in iter_operations(openapi):
        assert operation["responses"]["default"]["$ref"] == (
            "#/components/responses/UnexpectedError"
        ), f"{method.upper()} {path} lacks a default error response"


def test_error_schema_is_rfc9457_shaped(schema):
    """The problem definition must carry the RFC 9457 members."""
    error = schema["$defs"]["ErrorResponse"]
    for member in ("type", "title", "status", "detail", "instance"):
        assert member in error["properties"], f"ErrorResponse is missing {member}"
    status = error["properties"]["status"]
    assert status["minimum"] == 400 and status["maximum"] == 599
    assert not set(error["required"]) & {
        "type",
        "title",
        "status",
        "detail",
        "instance",
    }
    assert error["required"] == ["correlation_id"]
    assert "about:blank" in error["properties"]["type"]["description"]


def test_error_schema_matches_the_shared_error_model(schema):
    """Work Management problems must retain the shared core member names and types.

    The Work Management contract cannot reference Order Processing schemas
    (bounded-context isolation), so compatibility is asserted here instead.
    """
    shared = load_yaml(SHARED_SCHEMA_PATH)["$defs"]["Error"]
    wm_error = schema["$defs"]["ErrorResponse"]
    missing_properties = set(shared["properties"]) - set(wm_error["properties"])
    assert not missing_properties, (
        f"Work Management ErrorResponse omits shared fields: {sorted(missing_properties)}"
    )
    assert set(shared["properties"]) <= set(wm_error["properties"])
    for name in (
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "correlation_id",
        "request_id",
    ):
        assert shared["properties"][name].get("type") == wm_error["properties"][
            name
        ].get("type")
    errors_item = wm_error["properties"]["errors"]["items"]
    assert {"field", "message"} <= set(errors_item["required"])


def test_problem_status_when_present_matches_http_response(openapi, schema):
    """Status-specific response schemas preserve RFC 9457's status consistency rule."""
    response_statuses = {
        "BadRequest": 400,
        "Unauthorized": 401,
        "Forbidden": 403,
        "NotFound": 404,
        "Conflict": 409,
        "PreconditionFailed": 412,
        "UnprocessableEntity": 422,
        "ServiceUnavailable": 503,
    }
    for response_name, status in response_statuses.items():
        response = openapi["components"]["responses"][response_name]
        schema_ref = response["content"]["application/problem+json"]["schema"]["$ref"]
        problem_schema = openapi["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
        assert problem_schema["allOf"][0]["$ref"] == ERROR_SCHEMA_REF
        assert problem_schema["allOf"][1]["properties"]["status"]["const"] == status

        base = schema["$defs"]["ErrorResponse"]
        status_bound_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "allOf": [
                {"$ref": "#/$defs/ErrorResponse"},
                {"type": "object", "properties": {"status": {"const": status}}},
            ],
        }
        validator = Draft202012Validator(
            status_bound_schema, format_checker=FormatChecker()
        )
        valid_without_advisory_status = {
            "correlation_id": "a1b2c3d4-0000-0000-0000-000000000001"
        }
        assert validator.is_valid(valid_without_advisory_status)
        assert validator.is_valid({**valid_without_advisory_status, "status": status})
        assert not validator.is_valid({**valid_without_advisory_status, "status": 500})


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


def test_missing_required_idempotency_key_is_rejected_by_contract(openapi):
    """The decision operation requires the header; other A-02 headers are optional."""
    decide = openapi["components"]["parameters"]["IdempotencyKey"]
    optional = openapi["components"]["parameters"]["IdempotencyKeyOptional"]
    assert decide["required"] is True
    assert optional["required"] is False


def test_decide_idempotency_key_is_required(openapi):
    """The approval decision must require the Idempotency-Key header."""
    parameters = openapi["components"]["parameters"]
    assert parameters["IdempotencyKey"]["required"] is True
    assert parameters["IdempotencyKeyOptional"]["required"] is False


def test_idempotency_key_contract_scope_format_and_replay_semantics(openapi, schema):
    """A-02 defines key grammar, namespace, conflict, and concurrent replay behavior."""
    parameters = openapi["components"]["parameters"]
    for name in ("IdempotencyKey", "IdempotencyKeyOptional"):
        parameter = parameters[name]
        assert parameter["x-idempotency-scope"] == ["workspace_id", "operationId"]
        key_schema = parameter["schema"]
        validator = Draft202012Validator(key_schema)
        assert validator.is_valid("decision-key_01")
        assert not validator.is_valid("bad key")
        assert not validator.is_valid("x" * 129)
        assert "different request fingerprint returns 409" in parameter["description"]
        assert "concurrent duplicates" in parameter["description"]
        assert "another workspace" in parameter["description"]
    assert (
        schema["$defs"]["Approval"]["properties"]["idempotency_key"]["pattern"]
        == parameters["IdempotencyKey"]["schema"]["pattern"]
    )


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


def test_if_match_and_etag_use_strong_quoted_validators(openapi):
    """ETag response values and If-Match values share the strong quoted form."""
    expected_pattern = '^"[^"]+"$'
    assert (
        openapi["components"]["headers"]["ETag"]["schema"]["pattern"]
        == expected_pattern
    )
    assert (
        openapi["components"]["parameters"]["IfMatch"]["schema"]["pattern"]
        == expected_pattern
    )


def test_successful_resource_and_collection_responses_return_etag(openapi):
    """Every successful read or mutation returns an ETag for its representation."""
    missing = []
    for path, method, operation in iter_operations(openapi):
        for status, response in operation["responses"].items():
            if status not in {"200", "201"}:
                continue
            if "ETag" not in response.get("headers", {}):
                missing.append(f"{method.upper()} {path} {status}")
    assert not missing, f"successful responses without ETag: {missing}"


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


def test_list_operations_bind_workspace_and_validate_sort_allowlist(openapi):
    """Each collection list has scoped pagination, sort fields and a problem response for invalid cursors."""
    for _, _, operation in iter_operations(openapi):
        if operation.get("operationId") not in LIST_OPERATIONS:
            continue
        names = parameter_names(openapi, operation)
        assert "workspace_id" in names
        assert operation["x-allowed-sort-fields"]
        assert operation["x-default-sort-fields"]
        assert "400" in operation["responses"]
        sort = openapi["components"]["parameters"]["Sort"]
        assert sort["x-ordering"] == "stable_keyset_with_resource_id_tiebreaker"
        assert sort["x-snapshot-isolation"] is False


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


def test_triage_criteria_match_the_selected_category(schema):
    """A triage payload requires exactly the category-specific criteria object."""
    validator = validator_for(schema, "TriageConsultationRequest")
    valid = load_json(EXAMPLES / "triage-consultation.request.json")
    assert validator.is_valid(valid)
    missing_criteria = {
        key: value for key, value in valid.items() if key != "bug_criteria"
    }
    assert not validator.is_valid(missing_criteria)
    mismatched_criteria = {
        **valid,
        "feature_criteria": {
            "problem_statement": "A sufficiently long problem statement.",
            "expected_value": "A sufficiently long expected value.",
            "functional_requirements": ["Must behave as specified."],
            "acceptance_criteria": ["The feature is verified."],
        },
    }
    assert not validator.is_valid(mismatched_criteria)


def test_approved_decisions_require_target_board_and_generated_resources(schema):
    """An approval cannot be accepted without the board needed for card creation."""
    request_validator = validator_for(schema, "DecideProposalRequest")
    request = {
        "proposal_version": 1,
        "decision": "approved",
        "decision_justification": "The proposal is ready for implementation.",
    }
    assert not request_validator.is_valid(request)
    assert request_validator.is_valid(
        {**request, "target_board_id": "a1b2c3d4-0000-0000-0000-000000000005"}
    )
    response_validator = validator_for(schema, "DecideProposalResponse")
    example = load_json(EXAMPLES / "decide-proposal.response.json")
    assert response_validator.is_valid(example)
    assert not response_validator.is_valid(
        {"approval": example["approval"], "work_item": example["work_item"]}
    )


def test_page_info_cursor_presence_matches_has_more(schema):
    """PageInfo cannot claim more pages without a cursor or a final page with one."""
    validator = validator_for(schema, "PageInfo")
    assert validator.is_valid({"has_more": False, "next_cursor": None})
    assert validator.is_valid({"has_more": True, "next_cursor": "opaque-token"})
    assert not validator.is_valid({"has_more": True, "next_cursor": None})
    assert not validator.is_valid({"has_more": False, "next_cursor": "opaque-token"})


def test_board_rank_matches_persistence_constraints(schema):
    """Board rank contract matches the existing SQLAlchemy and migration pattern."""
    pattern = schema["$defs"]["BoardCard"]["properties"]["rank"]["pattern"]
    assert pattern == "^[0-9a-zA-Z_-]+$"
    assert schema["$defs"]["BoardCard"]["properties"]["rank"]["maxLength"] == 64
    model_source = BOARD_MODEL_PATH.read_text(encoding="utf-8")
    migration_source = INITIAL_MIGRATION_PATH.read_text(encoding="utf-8")
    assert f'RANK_PATTERN = "{pattern}"' in model_source
    assert f"rank ~ '{pattern}'" in migration_source
    validator = validator_for(schema, "BoardCard")
    card = {
        "card_id": "a1b2c3d4-0000-0000-0000-000000000001",
        "workspace_id": "a1b2c3d4-0000-0000-0000-000000000002",
        "board_id": "a1b2c3d4-0000-0000-0000-000000000003",
        "column_id": "ready",
        "work_item_id": "a1b2c3d4-0000-0000-0000-000000000004",
        "rank": "0hzzzzz",
        "title": "Valid task title",
        "priority": "medium",
        "category": "bug",
        "created_at": "2023-01-01T12:00:00Z",
        "updated_at": "2023-01-01T12:00:00Z",
    }
    assert validator.is_valid(card)
    assert not validator.is_valid({**card, "rank": "0|hzzzzz:"})
    move_schema = validator_for(schema, "MoveBoardCardRequest")
    assert move_schema.is_valid(
        {
            "target_column_id": "ready",
            "target_rank": "0hzzzzz",
        }
    )
    assert not move_schema.is_valid(
        {
            "target_column_id": "ready",
            "target_rank": "0|hzzzzz:",
        }
    )


def test_nullable_response_fields_match_persistence_models(schema):
    """Nullable ORM columns can be represented as null in response DTOs."""
    for definition, fields in {
        "Consultation": (
            "assignee_id",
            "category",
            "editor_context",
            "active_proposal_id",
        ),
        "Proposal": ("reviewer_id", "estimated_hours"),
        "WorkItem": ("assignee_id",),
        "BoardCard": ("assignee_id",),
        "Project": ("description",),
    }.items():
        for field in fields:
            branches = schema["$defs"][definition]["properties"][field].get("anyOf", [])
            assert any(branch.get("type") == "null" for branch in branches), (
                f"{definition}.{field} must accept null when persisted as NULL"
            )


def test_consultation_proposal_workitem_and_board_have_detail_reads(openapi):
    """Workflow resources have workspace-scoped detail reads with ETags."""
    expected = {
        "getConsultation": "Consultation",
        "getProposal": "Proposal",
        "getWorkItem": "WorkItem",
        "getBoard": "Board",
        "getBoardCard": "BoardCard",
    }
    actual = {
        operation["operationId"]: operation
        for _, _, operation in iter_operations(openapi)
        if operation.get("operationId") in expected
    }
    assert set(actual) == set(expected)
    for operation_id, definition in expected.items():
        operation = actual[operation_id]
        assert "404" in operation["responses"]
        assert "ETag" in operation["responses"]["200"].get("headers", {})
        schema_ref = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        assert schema_ref.endswith(f"#/$defs/{definition}")


def test_workitem_cannot_be_created_directly_and_invalid_transitions_are_conflicts(
    openapi,
):
    """The API cannot bypass approval and declares explicit lifecycle conflicts."""
    assert "post" not in openapi["paths"]["/v1/workspaces/{workspace_id}/work-items"]
    expected_conflicts = {
        "createProposal",
        "triageConsultation",
        "submitProposalForReview",
        "decideProposal",
        "moveBoardCard",
    }
    for _, _, operation in iter_operations(openapi):
        if operation.get("operationId") in expected_conflicts:
            assert "409" in operation["responses"], operation["operationId"]


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
