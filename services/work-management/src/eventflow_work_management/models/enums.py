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

# Project repository associations (Issue #44). A repository is identified by
# the provider's stable repository id scoped to one provider instance, never by
# its URL. ``configured`` is the only verification state this issue can reach:
# no GitHub/GitLab adapter verifies or authenticates the association yet.
PROJECT_REPOSITORY_STATUS_VALUES = ("active", "inactive", "archived")
PROJECT_REPOSITORY_VERIFICATION_VALUES = ("configured", "verified")

# Attachment lifecycle (Issue #4). Fail-closed: an upload starts QUARANTINED and
# only becomes AVAILABLE after an approved malware scanner returns a clean
# verdict. With no scanner configured every upload stays QUARANTINED.
ATTACHMENT_STATUS_VALUES = ("quarantined", "available", "rejected")
ATTACHMENT_SCAN_VERDICT_VALUES = ("clean", "infected", "unknown")
EVIDENCE_KIND_VALUES = ("text", "link", "attachment")

# Entity collaboration (Issue #29). One canonical singular vocabulary is shared
# by comments and generic attachments; the public ``entity_collection`` path
# segment maps onto it in ``services.entity_access``.
ENTITY_TYPE_VALUES = ("consultation", "proposal", "work_item", "board_card")

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
