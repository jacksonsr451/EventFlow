"""Tests for the security documentation defined in Issue #35.

These tests verify that the security specification is internally coherent:

- The security index lists every security document.
- The threat model covers every required area and records complete scenarios.
- Every control referenced by a threat scenario is defined by a policy document.
- The risk register is complete and every risk traces to a threat.
- The required policy prohibitions are present verbatim.
- The documented security event taxonomy matches the machine-readable schema.
"""

import pathlib
import re

import testrunner
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SECURITY_DOCS = REPO_ROOT / "docs" / "security"
SECURITY_SCHEMA = REPO_ROOT / "contracts" / "schemas" / "security_events.yaml"

THREAT_AREA_MINIMUMS = {
    "OA": 8,
    "SC": 6,
    "WH": 8,
    "AT": 8,
    "MT": 7,
    "DG": 8,
}

CONTROL_PREFIXES = {"OA", "SC", "WH", "AT", "TI", "DG", "SO"}

REQUIRED_THREAT_FIELDS = (
    "**Preconditions:**",
    "**Attack path:**",
    "**Impact:**",
    "**Likelihood:**",
    "**Severity:**",
    "**Preventive controls:**",
    "**Detective controls:**",
    "**Residual risk:**",
    "**Owner:**",
    "**Verification:**",
)

THREAT_HEADING = re.compile(r"^####\s+(TM-[A-Z]{2}-\d{2})\b", re.MULTILINE)
CONTROL_DEF = re.compile(r"^- \*\*([A-Z]{2}-\d{2})\*\*", re.MULTILINE)
CONTROL_REF = re.compile(r"(?<![A-Z-])([A-Z]{2}-\d{2})(?![0-9])")
RISK_ROW = re.compile(r"^\|\s*(R-\d{3})\s*\|", re.MULTILINE)
RISK_REF = re.compile(r"\b(R-\d{3})\b")
EVENT_ROW = re.compile(r"`([a-z_]+\.[a-z_]+)`")


def read(name):
    return (SECURITY_DOCS / name).read_text(encoding="utf-8")


def all_security_text():
    return "\n".join(
        path.read_text(encoding="utf-8") for path in SECURITY_DOCS.glob("*.md")
    )


def threat_blocks():
    text = read("threat-model.md")
    matches = list(THREAT_HEADING.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[start:end]))
    return blocks


def security_event_types():
    schema = yaml.safe_load(SECURITY_SCHEMA.read_text(encoding="utf-8"))
    return schema["$defs"]["SecurityEventType"]["enum"]


# ---------------------------------------------------------------------------
# Index and coverage
# ---------------------------------------------------------------------------


def test_security_index_lists_all_documents():
    """The security README must link to every security document."""
    index = read("README.md")
    documents = sorted(
        path.name for path in SECURITY_DOCS.glob("*.md") if path.name != "README.md"
    )
    missing = [name for name in documents if name not in index]
    assert not missing, f"security index is missing links to: {missing}"


def test_required_threat_areas_covered():
    """Every required threat area must have at least the minimum scenarios."""
    counts = {area: 0 for area in THREAT_AREA_MINIMUMS}
    for threat_id, _ in threat_blocks():
        area = threat_id.split("-")[1]
        counts[area] = counts.get(area, 0) + 1
    deficits = {
        area: counts.get(area, 0)
        for area, minimum in THREAT_AREA_MINIMUMS.items()
        if counts.get(area, 0) < minimum
    }
    assert not deficits, f"threat areas below the minimum scenario count: {deficits}"


# ---------------------------------------------------------------------------
# Threat model completeness
# ---------------------------------------------------------------------------


def test_threat_ids_are_unique():
    """No threat scenario identifier may be reused."""
    threat_ids = [threat_id for threat_id, _ in threat_blocks()]
    assert threat_ids, "no threat scenarios were found"
    duplicates = sorted({tid for tid in threat_ids if threat_ids.count(tid) > 1})
    assert not duplicates, f"duplicate threat identifiers: {duplicates}"


def test_threat_scenarios_have_required_fields():
    """Every threat scenario must record all required fields."""
    incomplete = []
    for threat_id, block in threat_blocks():
        missing = [field for field in REQUIRED_THREAT_FIELDS if field not in block]
        if missing:
            incomplete.append((threat_id, missing))
    assert not incomplete, f"threat scenarios with missing fields: {incomplete}"


def test_every_referenced_control_is_defined():
    """Every control referenced by a threat scenario must be defined."""
    defined = set(CONTROL_DEF.findall(all_security_text()))
    referenced = set()
    for _, block in threat_blocks():
        referenced.update(CONTROL_REF.findall(block))
    referenced = {control for control in referenced if control[:2] in CONTROL_PREFIXES}
    undefined = sorted(referenced - defined)
    assert not undefined, f"threat scenarios reference undefined controls: {undefined}"


# ---------------------------------------------------------------------------
# Risk register
# ---------------------------------------------------------------------------


def test_risk_register_rows_are_complete():
    """Every risk register row must have all columns populated."""
    text = read("risk-register.md")
    incomplete = []
    for line in text.splitlines():
        if not re.match(r"^\|\s*R-\d{3}\s*\|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 10 or not all(cells):
            incomplete.append(line.strip())
    assert not incomplete, f"incomplete risk register rows: {incomplete}"


def test_all_risks_reference_a_threat():
    """Every risk must reference an existing threat scenario."""
    threat_ids = {threat_id for threat_id, _ in threat_blocks()}
    text = read("risk-register.md")
    unmapped = []
    for line in text.splitlines():
        if not re.match(r"^\|\s*R-\d{3}\s*\|", line):
            continue
        threat = re.search(r"\bTM-[A-Z]{2}-\d{2}\b", line)
        if not threat or threat.group(0) not in threat_ids:
            unmapped.append(line.strip())
    assert not unmapped, f"risks referencing an unknown threat: {unmapped}"


def test_risk_references_are_consistent():
    """Risks cited by threats and risks registered must be the same set."""
    referenced = set()
    for _, block in threat_blocks():
        referenced.update(RISK_REF.findall(block))
    registered = set(RISK_ROW.findall(read("risk-register.md")))
    assert referenced == registered, (
        "threat-referenced risks and registered risks differ "
        f"(only referenced: {sorted(referenced - registered)}, "
        f"only registered: {sorted(registered - referenced)})"
    )


# ---------------------------------------------------------------------------
# Policy prohibitions
# ---------------------------------------------------------------------------


def test_policy_prohibitions_are_present():
    """The specification must state its non-negotiable prohibitions verbatim."""
    assertions = {
        "oauth-and-credentials.md": "must never be stored in `localStorage`",
        "untrusted-content.md": "Untrusted content is data, never instructions.",
        "tenant-isolation.md": "A client-supplied `workspace_id` never grants access.",
        "security-observability.md": (
            "Logs, traces, and metrics must never contain tokens, secrets, "
            "or full payloads."
        ),
    }
    missing = {
        name: phrase for name, phrase in assertions.items() if phrase not in read(name)
    }
    assert not missing, f"missing policy prohibitions: {missing}"


# ---------------------------------------------------------------------------
# Security event taxonomy
# ---------------------------------------------------------------------------


def test_security_event_types_are_documented_and_in_schema():
    """Documented event types and the schema enum must match exactly."""
    documented = []
    for line in read("security-observability.md").splitlines():
        if line.startswith("| SE-"):
            match = EVENT_ROW.search(line)
            if match:
                documented.append(match.group(1))
    assert documented, "no documented security event types were found"
    assert len(documented) == len(set(documented)), "duplicate event types documented"
    assert set(documented) == set(security_event_types()), (
        "documented event types do not match the schema enum: "
        f"{sorted(set(documented) ^ set(security_event_types()))}"
    )
