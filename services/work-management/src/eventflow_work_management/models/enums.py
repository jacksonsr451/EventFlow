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

# Business priority inputs (Issue #30). Business impact and urgency are the
# authoritative inputs of the priority matrix; the resulting priority uses the
# existing four-value ``PRIORITY_VALUES`` vocabulary so no parallel priority
# system is introduced. Bug severity and security severity remain independent
# triage criteria and never feed this matrix implicitly.
BUSINESS_IMPACT_VALUES = ("critical", "high", "moderate", "low")
BUSINESS_URGENCY_VALUES = ("immediate", "elevated", "normal", "low")

# SLA policy lifecycle. A policy is versioned; exactly one version per scope
# (workspace default or project) may be active at a time.
SLA_POLICY_STATUS_VALUES = ("draft", "active", "retired")

# SLA instance lifecycle. ``paused`` is driven by explicit pause intervals
# (for example when the WorkItem is blocked); ``breached`` records that at least
# one target was missed and is terminal for evaluation purposes.
SLA_INSTANCE_STATUS_VALUES = (
    "pending",
    "running",
    "paused",
    "fulfilled",
    "breached",
    "cancelled",
)
SLA_EVENT_TYPE_VALUES = (
    "started",
    "paused",
    "resumed",
    "warning_response",
    "warning_resolution",
    "breach_response",
    "breach_resolution",
    "fulfilled",
    "cancelled",
)

# Project-scoped triage configuration and versioned templates (Issue #41).
# A template groups versions for one category; only a published version may be
# activated. Published versions are immutable and are never physically deleted
# so historical consultations keep a resolvable snapshot reference.
TRIAGE_TEMPLATE_STATUS_VALUES = ("active", "deprecated", "archived")
TRIAGE_TEMPLATE_VERSION_STATUS_VALUES = (
    "draft",
    "published",
    "deprecated",
    "archived",
)
TRIAGE_FIELD_TYPE_VALUES = (
    "string",
    "multiline_text",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "enum",
    "multi_select",
    "reference",
)
TRIAGE_FIELD_STATUS_VALUES = ("active", "deprecated")

# Durable notifications (Issue #30). Delivery state is separate from read
# state; ``unavailable`` means no configured provider could accept the message
# and the transport is deliberately not claimed as delivered.
NOTIFICATION_EVENT_VALUES = (
    "dependency.created",
    "dependency.removed",
    "sla.warning",
    "sla.breached",
    "sla.fulfilled",
    "work_item.priority_overridden",
    "work_item.blocked",
)
NOTIFICATION_CHANNEL_VALUES = ("in_app", "email")
NOTIFICATION_DELIVERY_STATUS_VALUES = (
    "pending",
    "delivered",
    "failed",
    "unavailable",
    "exhausted",
)
