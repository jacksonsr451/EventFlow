"""Centralized business priority model (Issue #30).

There is exactly one priority system. It maps a documented business impact and
urgency pair onto the existing four-value priority vocabulary
(``critical`` > ``high`` > ``medium`` > ``low``). Nothing else in the code base
may compute a priority: triage, work-item overrides, and downstream consumers
all call :func:`calculate_priority`.

Bug severity (``BugCriteria.severity``) and security severity
(``SecurityCriteria.severity_rating``) are independent triage criteria. They do
not feed this matrix: a severe bug can still be low business priority and a
cosmetic bug can be a critical business priority.
"""

from __future__ import annotations

from eventflow_work_management.models.enums import (
    BUSINESS_IMPACT_VALUES,
    BUSINESS_URGENCY_VALUES,
    PRIORITY_VALUES,
)
from eventflow_work_management.security.errors import ProblemError

PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# impact x urgency -> priority. Documented, exhaustive, and the only place the
# mapping exists.
_MATRIX: dict[tuple[str, str], str] = {
    ("critical", "immediate"): "critical",
    ("critical", "elevated"): "critical",
    ("critical", "normal"): "high",
    ("critical", "low"): "medium",
    ("high", "immediate"): "critical",
    ("high", "elevated"): "high",
    ("high", "normal"): "high",
    ("high", "low"): "medium",
    ("moderate", "immediate"): "high",
    ("moderate", "elevated"): "medium",
    ("moderate", "normal"): "medium",
    ("moderate", "low"): "low",
    ("low", "immediate"): "medium",
    ("low", "elevated"): "low",
    ("low", "normal"): "low",
    ("low", "low"): "low",
}


def _invalid(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def calculate_priority(business_impact: str, business_urgency: str) -> str:
    """Return the deterministic priority for one impact/urgency pair."""
    if business_impact not in BUSINESS_IMPACT_VALUES:
        raise _invalid("Unknown business impact value.")
    if business_urgency not in BUSINESS_URGENCY_VALUES:
        raise _invalid("Unknown business urgency value.")
    return _MATRIX[(business_impact, business_urgency)]


def is_valid_priority(value: str) -> bool:
    return value in PRIORITY_VALUES


def priority_rank(value: str) -> int:
    """Lower rank means higher priority; unknown values sort last."""
    return PRIORITY_ORDER.get(value, len(PRIORITY_ORDER))


def higher_priority(left: str, right: str) -> str:
    """Return the more urgent of two priorities (stable on equal rank)."""
    return left if priority_rank(left) <= priority_rank(right) else right
