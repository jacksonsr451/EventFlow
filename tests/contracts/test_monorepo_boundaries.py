"""Tests for the monorepo contract boundaries defined in ADR-007.

These tests verify that:
- The monorepo directory structure is coherent with ADR-007.
- The contracts directory contains the expected contract files.
- Work Management and Order Processing schemas remain isolated.
- ADR-007 is present and registered in the ADR index.
- No bounded-context entity definitions leak across schema files.
- All $ref paths in OpenAPI specs resolve to existing local files.
"""

import pathlib

import testrunner
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas"
OPENAPI = CONTRACTS / "openapi"
ADR_DIR = REPO_ROOT / "docs" / "adr"


def load_yaml(path: pathlib.Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Contract structure tests
# ---------------------------------------------------------------------------


def test_work_management_openapi_exists():
    """Work Management OpenAPI contract must be present."""
    assert (OPENAPI / "work-management.yaml").is_file(), (
        "contracts/openapi/work-management.yaml is missing"
    )


def test_orders_openapi_exists():
    """Order Processing OpenAPI contract must be present."""
    assert (OPENAPI / "orders.yaml").is_file(), (
        "contracts/openapi/orders.yaml is missing"
    )


def test_work_management_schema_exists():
    """Work Management JSON Schema must be present."""
    assert (SCHEMAS / "work_management.yaml").is_file(), (
        "contracts/schemas/work_management.yaml is missing"
    )


def test_common_schema_exists():
    """Shared common schema must be present."""
    assert (SCHEMAS / "common.yaml").is_file(), (
        "contracts/schemas/common.yaml is missing"
    )


# ---------------------------------------------------------------------------
# Bounded context isolation tests
# ---------------------------------------------------------------------------


def test_work_management_schema_does_not_reference_orders_openapi():
    """Work Management schema must not reference the Orders OpenAPI contract.

    This enforces bounded context isolation at the contract level.
    """
    wm_schema_text = (SCHEMAS / "work_management.yaml").read_text(encoding="utf-8")
    assert "orders.yaml" not in wm_schema_text, (
        "work_management.yaml must not reference orders.yaml "
        "(bounded context isolation violation)"
    )


def test_orders_openapi_does_not_reference_work_management_schema():
    """Orders OpenAPI must not reference Work Management schemas.

    This enforces bounded context isolation at the contract level.
    """
    orders_text = (OPENAPI / "orders.yaml").read_text(encoding="utf-8")
    assert "work_management.yaml" not in orders_text, (
        "contracts/openapi/orders.yaml must not reference work_management.yaml "
        "(bounded context isolation violation)"
    )


# ---------------------------------------------------------------------------
# ADR-007 registration tests
# ---------------------------------------------------------------------------


def test_adr_007_file_exists():
    """ADR-007 document must exist."""
    adr_007 = ADR_DIR / "ADR-007-multi-client-monorepo-layout-and-contracts.md"
    assert adr_007.is_file(), "ADR-007 file is missing from docs/adr/"


def test_adr_007_registered_in_index():
    """ADR-007 must be listed in the ADR README index."""
    adr_readme = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    assert "ADR-007" in adr_readme, (
        "ADR-007 is not registered in docs/adr/README.md"
    )


def test_adr_007_status_is_accepted():
    """ADR-007 must have status 'Accepted'."""
    adr_007 = ADR_DIR / "ADR-007-multi-client-monorepo-layout-and-contracts.md"
    content = adr_007.read_text(encoding="utf-8")
    assert "## Status" in content, "ADR-007 is missing a Status section"
    # The word 'Accepted' must appear after the Status header
    status_section = content.split("## Status")[1].split("##")[0]
    assert "Accepted" in status_section, (
        "ADR-007 status is not 'Accepted'"
    )


# ---------------------------------------------------------------------------
# $ref resolution tests for Work Management OpenAPI
# ---------------------------------------------------------------------------


def _collect_refs(obj, refs=None):
    """Recursively collect all $ref values from a parsed YAML/JSON object."""
    if refs is None:
        refs = []
    if isinstance(obj, dict):
        if "$ref" in obj:
            refs.append(obj["$ref"])
        for value in obj.values():
            _collect_refs(value, refs)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, refs)
    return refs


def test_work_management_openapi_local_refs_resolve():
    """All local $ref paths in work-management.yaml must resolve to existing files.

    Refs starting with '#' are internal and are not checked here.
    External HTTP refs are skipped (they point to planned infrastructure).
    Only relative file refs are validated.
    """
    openapi_path = OPENAPI / "work-management.yaml"
    spec = load_yaml(openapi_path)
    refs = _collect_refs(spec)

    unresolved = []
    for ref in refs:
        if ref.startswith("#") or ref.startswith("http"):
            # Internal refs and external URLs are not checked here
            continue
        # Strip fragment
        file_part = ref.split("#")[0]
        if not file_part:
            continue
        target = (openapi_path.parent / file_part).resolve()
        if not target.is_file():
            unresolved.append(ref)

    assert not unresolved, (
        f"Unresolved $ref paths in work-management.yaml: {unresolved}"
    )


# ---------------------------------------------------------------------------
# Bounded-context entity isolation (no cross-domain schema definitions)
# ---------------------------------------------------------------------------

ORDER_DOMAIN_ENTITIES = {
    "Order",
    "OrderStatus",
    "CartItem",
    "AcceptedOrderItem",
    "Reservation",
    "ReservationItem",
    "ReservationStatus",
    "Payment",
    "PaymentState",
    "PriceQuote",
    "NotificationOperation",
    "IdentifierEnvelope",
}

WORK_MANAGEMENT_ENTITIES = {
    "Consultation",
    "Proposal",
    "Approval",
    "WorkItem",
    "BoardCard",
    "EditorContext",
}


def _defined_names(path: pathlib.Path) -> set[str]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        return set()
    return set(document.get("$defs", {}))


def test_work_management_schema_defines_no_order_domain_entities():
    """Work Management schema must not define Order Processing entities."""
    leaked = _defined_names(SCHEMAS / "work_management.yaml") & ORDER_DOMAIN_ENTITIES
    assert not leaked, (
        "work_management.yaml defines Order-domain definitions: "
        f"{sorted(leaked)} (bounded context isolation violation)"
    )


def test_order_schemas_define_no_work_management_entities():
    """Order Processing schemas must not define Work Management entities."""
    for name in ("common.yaml", "http.yaml", "events.yaml", "envelope.yaml"):
        path = SCHEMAS / name
        if not path.is_file():
            continue
        leaked = _defined_names(path) & WORK_MANAGEMENT_ENTITIES
        assert not leaked, (
            f"{name} defines Work Management definitions: "
            f"{sorted(leaked)} (bounded context isolation violation)"
        )
