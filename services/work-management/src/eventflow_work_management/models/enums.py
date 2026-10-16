"""Enum value sets mirrored from ``contracts/schemas/work_management.yaml``.

They are stored as ``varchar`` with a ``CHECK`` constraint so the database and
the contracts can never drift silently.
"""

from __future__ import annotations

ORIGIN_VALUES = ("web", "vscode", "desktop", "external")
TRIAGE_CATEGORY_VALUES = ("bug", "feature", "chore", "docs", "security")
PRIORITY_VALUES = ("critical", "high", "medium", "low")
CONSULTATION_STATUS_VALUES = (
    "draft",
    "open",
    "triaging",
    "proposed",
    "duplicate",
    "rejected",
    "closed",
    "reopened",
)
PROPOSAL_STATUS_VALUES = (
    "draft",
    "in_review",
    "approved",
    "rejected",
    "changes_requested",
    "superseded",
)
APPROVAL_DECISION_VALUES = ("approved", "rejected", "changes_requested")
WORK_ITEM_STATUS_VALUES = (
    "ready",
    "in_progress",
    "in_review",
    "blocked",
    "done",
    "cancelled",
)
REMOTE_PROVIDER_VALUES = ("github", "gitlab")
REMOTE_RESOURCE_TYPE_VALUES = ("issue", "pull_request", "merge_request")

# Attachment lifecycle (Issue #4). Fail-closed: an upload starts QUARANTINED and
# only becomes AVAILABLE after an approved malware scanner returns a clean
# verdict. With no scanner configured every upload stays QUARANTINED.
ATTACHMENT_STATUS_VALUES = ("quarantined", "available", "rejected")
ATTACHMENT_SCAN_VERDICT_VALUES = ("clean", "infected", "unknown")
EVIDENCE_KIND_VALUES = ("text", "link", "attachment")

# Work Management authorization vocabulary (Issue #9). The role order is
# intentional: it is roughly ascending privilege, with ``owner`` last so
# assignability and elevation checks can compare positions.
WORKSPACE_ROLE_VALUES = (
    "viewer",
    "contributor",
    "triager",
    "approver",
    "admin",
    "owner",
)
MEMBERSHIP_STATE_VALUES = ("active", "revoked")
INVITATION_STATE_VALUES = ("pending", "accepted", "revoked", "expired")
