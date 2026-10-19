"""Server-authoritative WorkItem status transitions (Issue #8).

Moving a board card between columns whose mapped statuses differ is a domain
transition of the backing ``WorkItem``. The allowed edges are defined here so the
API never accepts an arbitrary status change and visual columns cannot bypass the
WorkItem lifecycle.
"""

from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "ready": frozenset({"in_progress", "blocked", "cancelled"}),
    "in_progress": frozenset({"ready", "in_review", "blocked", "cancelled"}),
    "in_review": frozenset({"in_progress", "done", "cancelled"}),
    "blocked": frozenset({"in_progress", "cancelled"}),
    "done": frozenset(),
    "cancelled": frozenset(),
}

TERMINAL_STATUSES: frozenset[str] = frozenset(
    status for status, targets in ALLOWED_TRANSITIONS.items() if not targets
)


def is_valid_transition(source: str, target: str) -> bool:
    """Whether a WorkItem may move from ``source`` to ``target``.

    A no-op transition (same status) is always valid so a card can be reordered
    within or between columns that map to the same canonical status.
    """
    if source not in ALLOWED_TRANSITIONS or target not in ALLOWED_TRANSITIONS:
        return False
    if source == target:
        return True
    return target in ALLOWED_TRANSITIONS[source]
