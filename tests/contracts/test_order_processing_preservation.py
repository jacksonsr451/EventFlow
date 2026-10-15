"""Regression tests that preserve the Order Processing contracts.

This suite protects the Order Saga bounded context from accidental change while
Work Management evolves independently. It verifies:

- The Order Processing contract files exist and are structurally valid.
- The machine-readable contracts match a reviewed compatibility baseline, so a
  removal, rename, retype or enum change fails until the baseline is updated on
  purpose (see ``docs/architecture/order-processing/regression-strategy.md``).
- Every workflow event maps to a schema and to the shared event-type enum.
- OpenAPI operations keep their security and RFC 9457 problem+json errors.
- Order Processing and Work Management contracts do not cross-reference.
- The Order Processing documentation covers every event and schema definition.
"""

import functools
import json
import pathlib

import testrunner
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas"
OPENAPI = CONTRACTS / "openapi"
ASYNCAPI = CONTRACTS / "asyncapi"
DOCS = REPO_ROOT / "docs" / "architecture" / "order-processing"
BASELINE_PATH = pathlib.Path(__file__).resolve().parent / "order_processing_baseline.json"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ORDER_SCHEMAS = ("common.yaml", "http.yaml", "events.yaml", "envelope.yaml")
ORDER_CONTRACT_FILES = (
    OPENAPI / "orders.yaml",
    ASYNCAPI / "workflow.yaml",
    SCHEMAS / "common.yaml",
    SCHEMAS / "http.yaml",
    SCHEMAS / "events.yaml",
    SCHEMAS / "envelope.yaml",
)
ORDER_STATUS = (
    "PENDING",
    "STOCK_RESERVED",
    "PAYMENT_PROCESSING",
    "CONFIRMED",
    "CANCELLING",
    "CANCELLED",
)


def load_yaml(path):
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def read_text(path):
    return path.read_text(encoding="utf-8")


def walk(node, path, required, enum):
    if isinstance(node, dict):
        if isinstance(node.get("required"), list):
            required[path] = sorted(node["required"])
        if isinstance(node.get("enum"), list):
            enum[path] = list(node["enum"])
        for key, value in node.items():
            walk(value, f"{path}/{key}", required, enum)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, f"{path}/{index}", required, enum)


@functools.lru_cache(maxsize=1)
def contract_snapshot():
    snapshot = {
        "schemas": {},
        "events": {},
        "event_type_enum": [],
        "error_code_enum": [],
        "openapi_paths": [],
        "openapi_operations": [],
        "asyncapi_channels": [],
        "asyncapi_operations": [],
        "asyncapi_messages": [],
    }
    for name in ORDER_SCHEMAS:
        document = load_yaml(SCHEMAS / name)
        required = {}
        enum = {}
        walk(document, name, required, enum)
        snapshot["schemas"][name] = {"required": required, "enum": enum}

    common = load_yaml(SCHEMAS / "common.yaml")
    snapshot["event_type_enum"] = list(common["$defs"]["EventType"]["enum"])
    snapshot["error_code_enum"] = list(
        common["$defs"]["Error"]["properties"]["code"]["enum"]
    )

    events = load_yaml(SCHEMAS / "events.yaml")
    for definition, schema in events["$defs"].items():
        for branch in schema.get("allOf", []):
            properties = branch.get("properties", {})
            if "event_type" in properties:
                snapshot["events"][properties["event_type"]["const"]] = definition

    openapi = load_yaml(OPENAPI / "orders.yaml")
    snapshot["openapi_paths"] = sorted(openapi["paths"])
    operations = []
    for item in openapi["paths"].values():
        for method, operation in item.items():
            if method in HTTP_METHODS and "operationId" in operation:
                operations.append(operation["operationId"])
    snapshot["openapi_operations"] = sorted(operations)

    asyncapi = load_yaml(ASYNCAPI / "workflow.yaml")
    snapshot["asyncapi_channels"] = sorted(asyncapi["channels"])
    snapshot["asyncapi_operations"] = sorted(asyncapi["operations"])
    snapshot["asyncapi_messages"] = sorted(
        message["name"] for message in asyncapi["components"]["messages"].values()
    )
    return snapshot


@functools.lru_cache(maxsize=1)
def baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Contract presence and compatibility baseline
# ---------------------------------------------------------------------------


def test_order_processing_contract_files_exist():
    """All Order Processing contract files must remain present."""
    missing = [str(path) for path in ORDER_CONTRACT_FILES if not path.is_file()]
    assert not missing, f"Order Processing contracts are missing: {missing}"
    assert (CONTRACTS / "examples" / "order-workflow.json").is_file(), (
        "contracts/examples/order-workflow.json is missing"
    )


def test_contracts_match_the_compatibility_baseline():
    """Contracts must match the reviewed baseline without silent change.

    Any intentional contract change must update
    ``tests/contracts/order_processing_baseline.json`` in the same reviewed
    change. This detects removed or renamed required fields, changed enum
    values, retyped definitions and dropped operations or events.
    """
    current = contract_snapshot()
    expected = baseline()
    differences = {
        key: {"baseline": expected.get(key), "current": current.get(key)}
        for key in expected
        if expected.get(key) != current.get(key)
    }
    assert not differences, (
        "Order Processing contracts diverged from the reviewed compatibility "
        f"baseline: {sorted(differences)}"
    )


def test_event_taxonomy_is_consistent():
    """The event schema, event enum and AsyncAPI messages must agree."""
    snapshot = contract_snapshot()
    event_types = set(snapshot["events"])
    assert event_types == set(snapshot["event_type_enum"]), (
        "event schemas and the shared EventType enum diverged: "
        f"{sorted(event_types ^ set(snapshot['event_type_enum']))}"
    )
    assert event_types == set(snapshot["asyncapi_messages"]), (
        "event schemas and AsyncAPI messages diverged: "
        f"{sorted(event_types ^ set(snapshot['asyncapi_messages']))}"
    )


def test_every_event_uses_the_common_envelope():
    """Every event schema must reuse the envelope and pin schema_version."""
    events = load_yaml(SCHEMAS / "events.yaml")["$defs"]
    problems = []
    base_event = events.get("BaseEvent", {})
    if base_event.get("$ref") != "envelope.yaml":
        problems.append("BaseEvent does not reference envelope.yaml")
    for definition, schema in events.items():
        branches = schema.get("allOf", [])
        if not branches:
            continue
        head = branches[0]
        if head.get("$ref") != "#/$defs/BaseEvent":
            problems.append(f"{definition} does not reuse BaseEvent")
        tail = branches[-1].get("properties", {})
        if tail.get("schema_version", {}).get("const") != 1:
            problems.append(f"{definition} does not pin schema_version to 1")
        if "event_type" not in tail:
            problems.append(f"{definition} does not constrain event_type")
    assert not problems, f"event schemas not using the common envelope: {problems}"


def test_asyncapi_messages_map_to_their_event_schema():
    """Each AsyncAPI message must reference the matching event schema."""
    events = contract_snapshot()["events"]
    messages = load_yaml(ASYNCAPI / "workflow.yaml")["components"]["messages"]
    problems = []
    for message in messages.values():
        event_type = message["name"]
        expected = f"../schemas/events.yaml#/$defs/{events.get(event_type)}"
        if message["payload"]["$ref"] != expected:
            problems.append(event_type)
    assert not problems, f"AsyncAPI messages not mapped to their schema: {problems}"


# ---------------------------------------------------------------------------
# HTTP contract preservation
# ---------------------------------------------------------------------------


def test_order_operations_require_bearer_auth():
    """Every Order Processing operation must declare bearer authentication."""
    openapi = load_yaml(OPENAPI / "orders.yaml")
    missing = []
    for path, item in openapi["paths"].items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            schemes = [entry for entry in operation.get("security", []) if entry]
            if "bearerAuth" not in {name for entry in schemes for name in entry}:
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"Order Processing operations without bearerAuth: {missing}"


def test_order_error_responses_use_problem_json():
    """Every Order Processing error response must use problem+json and ErrorResponse."""
    openapi = load_yaml(OPENAPI / "orders.yaml")
    bad_media_type = []
    bad_schema = []
    for name, response in openapi["components"]["responses"].items():
        media = response.get("content", {})
        if "application/problem+json" not in media:
            bad_media_type.append(name)
            continue
        schema = media["application/problem+json"].get("schema", {})
        if schema.get("$ref") != "../schemas/http.yaml#/$defs/ErrorResponse":
            bad_schema.append(name)
    assert not bad_media_type, f"responses not using problem+json: {bad_media_type}"
    assert not bad_schema, f"responses not using the shared ErrorResponse: {bad_schema}"


# ---------------------------------------------------------------------------
# Bounded-context separation
# ---------------------------------------------------------------------------


def test_order_contracts_do_not_reference_work_management():
    """Order Processing contracts must not reference Work Management."""
    violations = []
    for path in ORDER_CONTRACT_FILES:
        text = read_text(path)
        for forbidden in ("work_management", "work-management", "work_events"):
            if forbidden in text:
                violations.append(f"{path.name}: {forbidden}")
    assert not violations, (
        f"Order Processing contracts reference Work Management: {violations}"
    )


def test_work_management_contracts_do_not_reference_order_processing():
    """Work Management contracts must not reference Order Processing contracts."""
    targets = (
        OPENAPI / "work-management.yaml",
        SCHEMAS / "work_management.yaml",
    )
    forbidden_names = (
        "orders.yaml",
        "workflow.yaml",
        "common.yaml",
        "http.yaml",
        "events.yaml",
        "envelope.yaml",
        "order-workflow.json",
    )
    violations = []
    for path in targets:
        text = read_text(path)
        for forbidden in forbidden_names:
            if forbidden in text:
                violations.append(f"{path.name}: {forbidden}")
    assert not violations, (
        f"Work Management contracts reference Order Processing: {violations}"
    )


# ---------------------------------------------------------------------------
# Documentation coverage
# ---------------------------------------------------------------------------


def test_order_processing_documents_exist_and_are_indexed():
    """The Order Processing sub-index must list every document and be linked."""
    index = read_text(DOCS / "README.md")
    documents = sorted(
        path.name for path in DOCS.glob("*.md") if path.name != "README.md"
    )
    missing = [name for name in documents if name not in index]
    assert not missing, f"order-processing index is missing links to: {missing}"
    assert "architecture/order-processing/README.md" in read_text(
        REPO_ROOT / "docs" / "README.md"
    ), "docs/README.md must link to the Order Processing index"


def test_contract_inventory_covers_every_schema_definition_and_event():
    """The inventory must name every Order Processing schema definition and event."""
    inventory = read_text(DOCS / "contract-inventory.md")
    missing = []
    for name in ORDER_SCHEMAS:
        document = load_yaml(SCHEMAS / name)
        for definition in document.get("$defs", {}):
            if f"`{definition}`" not in inventory:
                missing.append(f"{name}#/$defs/{definition}")
    for event_type in contract_snapshot()["asyncapi_messages"]:
        if f"`{event_type}`" not in inventory:
            missing.append(event_type)
    assert not missing, f"contract inventory is missing coverage: {missing}"


def test_workflow_document_lists_every_order_state():
    """The transition matrix must reference every documented Order status."""
    workflow = read_text(DOCS / "workflow.md")
    missing = [state for state in ORDER_STATUS if f"`{state}`" not in workflow]
    assert not missing, f"workflow document omits order states: {missing}"


def test_domain_separation_document_names_both_bounded_contexts():
    """The separation document must enumerate both domains' owned entities."""
    document = read_text(DOCS / "domain-separation.md")
    entities = (
        "Order",
        "Cart",
        "PriceQuote",
        "Reservation",
        "Payment",
        "NotificationOperation",
        "Workspace",
        "Consultation",
        "Proposal",
        "Approval",
        "WorkItem",
        "BoardCard",
    )
    missing = [entity for entity in entities if f"`{entity}`" not in document]
    assert not missing, f"domain separation document omits entities: {missing}"


def test_execution_plan_references_the_order_processing_issues():
    """The roadmap must keep the Order Saga implementation issues explicit."""
    plan = read_text(DOCS / "execution-plan.md")
    required = ("#49", "#50", "#51", "#52", "#53", "#54")
    missing = [issue for issue in required if issue not in plan]
    assert not missing, f"execution plan omits issue references: {missing}"
