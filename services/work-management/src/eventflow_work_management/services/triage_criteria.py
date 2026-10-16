"""Differentiated triage criteria: the authoritative category model (Issue #5).

Manual triage is only complete when the triager supplies the structured
criteria that belong to the selected category. This module owns that model: the
Pydantic criteria classes are the single source of truth for shape and value
constraints, and :func:`validate_criteria` is the one place the domain accepts or
rejects a criteria payload. The API request union and the published contracts
mirror these classes, so the HTTP surface, the JSON Schema, and the persisted
``triage_criteria`` document can never drift apart.

Triage is always manual: nothing here infers a category from free text and
nothing here creates a Proposal, Approval, WorkItem, or BoardCard. Category
selection and reclassification are explicit, audited operations.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eventflow_work_management.security.errors import ProblemError

_PRIORITY = Literal["critical", "high", "medium", "low"]


class _Criteria(BaseModel):
    """Base class: unknown fields are rejected, matching the contracts."""

    model_config = ConfigDict(extra="forbid")


class BugCriteria(_Criteria):
    expected_behavior: str = Field(min_length=5)
    observed_behavior: str = Field(min_length=5)
    reproduction_steps: list[str] = Field(min_length=1)
    environment: str = Field(min_length=1)
    severity: _PRIORITY
    is_regression: bool
    impact: str = Field(min_length=5)


class FeatureCriteria(_Criteria):
    problem_statement: str = Field(min_length=10)
    expected_value: str = Field(min_length=10)
    functional_requirements: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    scope: str = Field(min_length=5)


class ChoreCriteria(_Criteria):
    maintenance_need: str = Field(min_length=5)
    technical_debt_type: str = Field(min_length=3)
    justification: str = Field(min_length=5)
    risk_of_inaction: str = Field(min_length=5)
    expected_technical_effect: str = Field(min_length=5)


class DocsCriteria(_Criteria):
    affected_document: str = Field(min_length=3)
    inconsistency_summary: str = Field(min_length=5)
    target_audience: str = Field(min_length=3)


class SecurityCriteria(_Criteria):
    vulnerability_type: str = Field(min_length=3)
    severity_rating: _PRIORITY
    confidentiality_level: Literal["confidential", "restricted"]
    access_restricted_to: list[str] = Field(min_length=1)
    safe_evidence_handling: Literal[True]


CRITERIA_MODELS: dict[str, type[_Criteria]] = {
    "bug": BugCriteria,
    "feature": FeatureCriteria,
    "chore": ChoreCriteria,
    "docs": DocsCriteria,
    "security": SecurityCriteria,
}

# Category -> the single request field that carries its criteria. Kept aligned
# with the discriminated union in ``api.consultation_routes`` and the contracts.
CRITERIA_FIELD_FOR_CATEGORY: dict[str, str] = {
    category: f"{category}_criteria" for category in CRITERIA_MODELS
}


def _invalid_criteria() -> ProblemError:
    return ProblemError(
        status_code=422,
        code="VALIDATION_ERROR",
        detail="Triage criteria must match the selected category.",
        title="Unprocessable entity",
    )


def validate_criteria(category: str, payload: dict) -> dict:
    """Validate and normalise one category's criteria payload.

    The category is authoritative: the payload must be a mapping whose fields
    exactly match that category's criteria class. Any mismatch, missing required
    field, or out-of-range value raises a sanitized ``422`` problem.
    """
    model = CRITERIA_MODELS.get(category)
    if model is None:
        raise _invalid_criteria()
    if not isinstance(payload, dict):
        raise _invalid_criteria()
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        raise _invalid_criteria() from exc
    return validated.model_dump()


# Reusable backend metadata for the three differentiated categories. These are
# guidance contracts, not client UIs and not auto-classifiers.
_TEMPLATE_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "bug",
        "Bug report",
        "A defect in existing behaviour that must be reproduced and bounded.",
        "Capture what was expected, what happened, how to reproduce it, the "
        "environment, the severity, whether it is a regression, and the impact.",
    ),
    (
        "feature",
        "Feature request",
        "Net-new behaviour or capability that does not exist yet.",
        "Capture the problem, the expected value, functional requirements, "
        "acceptance criteria, and the scope boundary.",
    ),
    (
        "chore",
        "Chore",
        "Internal maintenance or technical-debt work with no user-visible change.",
        "Capture the maintenance need, the technical-debt type, the "
        "justification, the risk of inaction, and the expected technical effect.",
    ),
)


def _required_fields(category: str) -> list[str]:
    return list(CRITERIA_MODELS[category].model_fields)


def triage_templates() -> list[dict]:
    """Return the reusable triage templates for the differentiated categories."""
    return [
        {
            "category": category,
            "title": title,
            "description": description,
            "guidance": guidance,
            "required_fields": _required_fields(category),
        }
        for category, title, description, guidance in _TEMPLATE_DEFINITIONS
    ]
