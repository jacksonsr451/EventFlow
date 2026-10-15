"""Deterministic development seed data.

The seed uses fixed identifiers so it is safe to run repeatedly: if the demo
workspace already exists the function is a no-op. It never contains real
credentials or user data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import (
    Approval,
    AuditRecord,
    Board,
    BoardCard,
    Consultation,
    IdempotencyRecord,
    Project,
    Proposal,
    WorkItem,
    Workspace,
)

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")
BOARD_ID = UUID("00000000-0000-4000-8000-000000000003")
CONSULTATION_ID = UUID("00000000-0000-4000-8000-000000000004")
AUTHOR_ID = UUID("00000000-0000-4000-8000-000000000005")
PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000006")
APPROVAL_ID = UUID("00000000-0000-4000-8000-000000000007")
WORK_ITEM_ID = UUID("00000000-0000-4000-8000-000000000008")
DECIDER_ID = UUID("00000000-0000-4000-8000-000000000009")
CARD_ID = UUID("00000000-0000-4000-8000-000000000010")
IDEMPOTENCY_ID = UUID("00000000-0000-4000-8000-000000000011")

SEED_OCCURRED_AT = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
IDEMPOTENCY_KEY = "seed-idempotency-key-0001"

ACCEPTANCE_CRITERIA = [
    "Seeded records are created exactly once",
    "Re-running the seed changes nothing",
]


def _seed_proposal_snapshot() -> dict:
    return {
        "proposal_id": str(PROPOSAL_ID),
        "version": 1,
        "status": "approved",
        "title": "Seed proposal",
        "category": "feature",
        "priority": "medium",
        "acceptance_criteria": ACCEPTANCE_CRITERIA,
    }


def seed(session: Session) -> dict[str, UUID]:
    """Insert the demo dataset if absent and return the created identifiers."""
    if session.get(Workspace, WORKSPACE_ID) is not None:
        return {
            "workspace_id": WORKSPACE_ID,
            "project_id": PROJECT_ID,
            "board_id": BOARD_ID,
            "consultation_id": CONSULTATION_ID,
            "proposal_id": PROPOSAL_ID,
            "approval_id": APPROVAL_ID,
            "work_item_id": WORK_ITEM_ID,
        }

    session.add(Workspace(id=WORKSPACE_ID, name="EventFlow Demo", slug="eventflow-demo"))
    session.flush()

    session.add(
        Project(
            id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            key="DEMO",
            name="Demo Project",
            description="Local development project.",
        )
    )
    session.flush()

    session.add(
        Consultation(
            id=CONSULTATION_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            author_id=AUTHOR_ID,
            origin="web",
            title="Seed consultation",
            description="Seeded consultation used for local development.",
            category="feature",
            priority="medium",
            status="proposed",
            external_references=[],
        )
    )
    session.flush()

    session.add(
        Proposal(
            id=PROPOSAL_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            consultation_id=CONSULTATION_ID,
            version=1,
            title="Seed proposal",
            technical_description="Seeded proposal used for local development.",
            scope="Local development only.",
            justification="Provides representative data for manual testing.",
            acceptance_criteria=ACCEPTANCE_CRITERIA,
            category="feature",
            priority="medium",
            status="approved",
            proposer_id=AUTHOR_ID,
        )
    )
    session.flush()

    snapshot = _seed_proposal_snapshot()
    session.add(
        Approval(
            id=APPROVAL_ID,
            proposal_id=PROPOSAL_ID,
            proposal_version=1,
            workspace_id=WORKSPACE_ID,
            decider_id=DECIDER_ID,
            decision="approved",
            decision_justification="Seeded approval for local development.",
            idempotency_key=IDEMPOTENCY_KEY,
            decided_at=SEED_OCCURRED_AT,
            audit_snapshot_hash=fingerprint(snapshot),
        )
    )
    session.add(
        IdempotencyRecord(
            id=IDEMPOTENCY_ID,
            workspace_id=WORKSPACE_ID,
            operation="proposal.decide",
            idempotency_key=IDEMPOTENCY_KEY,
            request_fingerprint=fingerprint(snapshot),
            response_status=200,
            response_body={"approval_id": str(APPROVAL_ID), "decision": "approved"},
        )
    )
    session.flush()

    session.add(
        WorkItem(
            id=WORK_ITEM_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            origin_proposal_id=PROPOSAL_ID,
            origin_proposal_version=1,
            origin_approval_id=APPROVAL_ID,
            title="Seed work item",
            description="Seeded work item derived from an approved proposal.",
            acceptance_criteria=ACCEPTANCE_CRITERIA,
            category="feature",
            priority="medium",
            status="ready",
            external_issue_links=[],
        )
    )
    session.add(
        Board(
            id=BOARD_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            name="Demo Board",
            columns=["ready", "in_progress", "review", "done"],
        )
    )
    session.flush()

    session.add(
        BoardCard(
            id=CARD_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            board_id=BOARD_ID,
            column_id="ready",
            work_item_id=WORK_ITEM_ID,
            rank="a0",
            title="Seed work item",
            priority="medium",
            category="feature",
        )
    )
    session.add(
        AuditRecord(
            id=UUID("00000000-0000-4000-8000-000000000012"),
            workspace_id=WORKSPACE_ID,
            actor_id=DECIDER_ID,
            action="proposal.decided",
            entity_type="proposal",
            entity_id=PROPOSAL_ID,
            occurred_at=SEED_OCCURRED_AT,
            snapshot={"decision": "approved", "approval_id": str(APPROVAL_ID)},
            snapshot_hash=fingerprint(
                {"decision": "approved", "approval_id": str(APPROVAL_ID)}
            ),
        )
    )
    session.commit()

    return {
        "workspace_id": WORKSPACE_ID,
        "project_id": PROJECT_ID,
        "board_id": BOARD_ID,
        "consultation_id": CONSULTATION_ID,
        "proposal_id": PROPOSAL_ID,
        "approval_id": APPROVAL_ID,
        "work_item_id": WORK_ITEM_ID,
    }


def run_development_seed(engine: Engine) -> dict[str, UUID]:
    """Open a session against ``engine`` and seed it."""
    with Session(engine) as session:
        return seed(session)
