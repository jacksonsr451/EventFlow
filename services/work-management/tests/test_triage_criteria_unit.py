"""Unit tests for the differentiated triage criteria model (Issue #5).

No database is required. These tests pin the authoritative per-category
validation used by the service and cross-check the reusable templates against
the criteria models so the guidance metadata cannot drift from enforcement.
"""

from __future__ import annotations

import testrunner
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.triage_criteria import (
    CRITERIA_FIELD_FOR_CATEGORY,
    CRITERIA_MODELS,
    triage_templates,
    validate_criteria,
)

VALID_CRITERIA = {
    "bug": {
        "expected_behavior": "Returns 400 with a problem document.",
        "observed_behavior": "Raises an unhandled 500 error.",
        "reproduction_steps": ["Submit an empty cart payload."],
        "environment": "Python 3.11",
        "severity": "high",
        "is_regression": False,
        "impact": "All empty-cart checkouts fail for every user.",
    },
    "feature": {
        "problem_statement": "Triagers cannot record structured feature intent.",
        "expected_value": "Consistent, queryable feature triage records.",
        "functional_requirements": ["Record functional requirements."],
        "acceptance_criteria": ["Feature triage is verifiable."],
        "scope": "Backend triage contract only; no client UI.",
    },
    "chore": {
        "maintenance_need": "Upgrade the pinned database driver.",
        "technical_debt_type": "dependency",
        "justification": "The current driver is out of support.",
        "risk_of_inaction": "Unpatched security issues accumulate.",
        "expected_technical_effect": "A supported, patched driver is pinned.",
    },
    "docs": {
        "affected_document": "docs/architecture/work-management-api.md",
        "inconsistency_summary": "The triage payload is described incorrectly.",
        "target_audience": "Backend engineers",
    },
    "security": {
        "vulnerability_type": "broken access control",
        "severity_rating": "critical",
        "confidentiality_level": "restricted",
        "access_restricted_to": ["security-team"],
        "safe_evidence_handling": True,
    },
}


def _assert_rejected(category: str, payload: dict) -> None:
    with testrunner.raises(ProblemError) as caught:
        validate_criteria(category, payload)
    assert caught.value.status_code == 422
    assert caught.value.code == "VALIDATION_ERROR"


def test_every_category_accepts_its_criteria():
    for category, criteria in VALID_CRITERIA.items():
        normalised = validate_criteria(category, criteria)
        assert normalised == criteria


def test_criteria_field_mapping_matches_models():
    assert set(CRITERIA_FIELD_FOR_CATEGORY) == set(CRITERIA_MODELS)
    for category in CRITERIA_MODELS:
        assert CRITERIA_FIELD_FOR_CATEGORY[category] == f"{category}_criteria"


def test_unknown_category_is_rejected():
    _assert_rejected("spike", VALID_CRITERIA["bug"])


def test_missing_required_field_is_rejected():
    bug = {k: v for k, v in VALID_CRITERIA["bug"].items() if k != "impact"}
    _assert_rejected("bug", bug)
    feature = {k: v for k, v in VALID_CRITERIA["feature"].items() if k != "scope"}
    _assert_rejected("feature", feature)
    chore = {
        k: v
        for k, v in VALID_CRITERIA["chore"].items()
        if k != "expected_technical_effect"
    }
    _assert_rejected("chore", chore)


def test_unknown_field_is_rejected():
    _assert_rejected("bug", {**VALID_CRITERIA["bug"], "extra": "value"})


def test_out_of_range_values_are_rejected():
    _assert_rejected("bug", {**VALID_CRITERIA["bug"], "severity": "urgent"})
    _assert_rejected("bug", {**VALID_CRITERIA["bug"], "reproduction_steps": []})
    _assert_rejected(
        "security",
        {**VALID_CRITERIA["security"], "safe_evidence_handling": False},
    )
    _assert_rejected(
        "security",
        {**VALID_CRITERIA["security"], "confidentiality_level": "public"},
    )


def test_templates_cover_differentiated_categories():
    templates = triage_templates()
    assert [template["category"] for template in templates] == [
        "bug",
        "feature",
        "chore",
    ]
    for template in templates:
        assert template["required_fields"] == list(
            CRITERIA_MODELS[template["category"]].model_fields
        )
        assert template["title"]
        assert template["description"]
        assert template["guidance"]
