"""Integration tests for the persisted Work Management workflow."""

from __future__ import annotations

from uuid import uuid4

import testrunner
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from eventflow_work_management.repositories import (
    ApprovalRepository,
    AuditRepository,
    BoardCardRepository,
    BoardRepository,
    ConsultationRepository,
    ProposalRepository,
    WorkItemRepository,
)
from support import (
    create_consultation,
    create_project,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def _approve(session, workspace, consultation, *, decision="approved", key="decision-key-0001"):
    proposal = ProposalRepository(session).create(
        workspace_id=workspace.id,
        project_id=consultation.project_id,
        consultation_id=consultation.id,
        proposer_id=uuid4(),
        title="Export proposals",
        technical_description="Streaming CSV export endpoint.",
        scope="Dashboard export control.",
        justification="Customer request.",
        acceptance_criteria=["CSV export works"],
        category="feature",
        priority="medium",
    )
    result = ApprovalRepository(session).decide(
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        decider_id=uuid4(),
        decision=decision,
        justification="Reviewed against acceptance criteria.",
        idempotency_key=key,
    )
    return proposal, result


def test_full_workflow_persists_end_to_end():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = ConsultationRepository(session).create(
            workspace_id=workspace.id,
            project_id=project.id,
            author_id=uuid4(),
            origin="web",
            title="Add CSV export",
            description="Users need CSV export from the dashboard.",
            priority="medium",
        )

        proposal, decision = _approve(session, workspace, consultation)
        assert decision.replayed is False
        assert decision.approval.decision == "approved"
        assert proposal.status == "approved"

        work_item = WorkItemRepository(session).create_from_approved_proposal(
            workspace_id=workspace.id,
            project_id=project.id,
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            approval_id=decision.approval.id,
            title="Implement CSV export",
            description="Build the streaming CSV export endpoint.",
            acceptance_criteria=["CSV export works"],
            category="feature",
            priority="medium",
        )
        assert work_item.status == "ready"

        board = BoardRepository(session).create(
            workspace_id=workspace.id,
            project_id=project.id,
            name="Delivery",
            columns=["ready", "done"],
        )
        card = BoardCardRepository(session).add_card(
            workspace_id=workspace.id,
            board_id=board.id,
            work_item_id=work_item.id,
            column_id="ready",
            rank="a0",
            title="Implement CSV export",
            priority="medium",
            category="feature",
        )
        assert card.work_item_id == work_item.id

        trail = AuditRepository(session).list_for_entity(
            workspace.id, "proposal", proposal.id
        )
        assert [record.action for record in trail] == ["proposal.decided"]
        assert len(trail[0].snapshot_hash) == 64

        idempotency_count = session.execute(
            text("SELECT count(*) FROM idempotency_records")
        ).scalar_one()
        assert idempotency_count == 1


def test_work_item_requires_approved_proposal():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        proposal, decision = _approve(session, workspace, consultation, decision="changes_requested")

        with testrunner.raises(IntegrityError):
            WorkItemRepository(session).create_from_approved_proposal(
                workspace_id=workspace.id,
                project_id=project.id,
                proposal_id=proposal.id,
                proposal_version=proposal.version,
                approval_id=decision.approval.id,
                title="Should not be created",
                description="Origin approval is not approved.",
                acceptance_criteria=["never"],
                category="feature",
                priority="medium",
            )
        session.rollback()


def test_work_item_rejects_mismatched_proposal_version():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        proposal, decision = _approve(session, workspace, consultation)

        with testrunner.raises(IntegrityError):
            WorkItemRepository(session).create_from_approved_proposal(
                workspace_id=workspace.id,
                project_id=project.id,
                proposal_id=proposal.id,
                proposal_version=proposal.version + 1,
                approval_id=decision.approval.id,
                title="Wrong version",
                description="Origin version does not match the approval.",
                acceptance_criteria=["never"],
                category="feature",
                priority="medium",
            )
        session.rollback()


def test_audit_records_are_append_only():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        AuditRepository(session).append(
            workspace_id=workspace.id,
            action="workspace.created",
            entity_type="workspace",
            entity_id=workspace.id,
            snapshot={"slug": workspace.slug},
        )
        session.commit()

        with testrunner.raises(Exception):
            session.execute(text("UPDATE audit_records SET action = 'tampered'"))
            session.commit()
        session.rollback()

        with testrunner.raises(Exception):
            session.execute(text("DELETE FROM audit_records"))
            session.commit()
        session.rollback()

        remaining = session.execute(text("SELECT count(*) FROM audit_records")).scalar_one()
        assert remaining == 1


def test_audit_records_cannot_be_truncated():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        AuditRepository(session).append(
            workspace_id=workspace.id,
            action="workspace.created",
            entity_type="workspace",
            entity_id=workspace.id,
            snapshot={"slug": workspace.slug},
        )
        session.commit()

        with testrunner.raises(Exception):
            session.execute(text("TRUNCATE audit_records"))
            session.commit()
        session.rollback()

        remaining = session.execute(text("SELECT count(*) FROM audit_records")).scalar_one()
        assert remaining == 1


def test_work_item_origin_cannot_be_updated_to_invalid_version():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        proposal, decision = _approve(session, workspace, consultation)
        work_item = WorkItemRepository(session).create_from_approved_proposal(
            workspace_id=workspace.id,
            project_id=project.id,
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            approval_id=decision.approval.id,
            title="Guarded work item",
            description="Origin must stay bound to the approved version.",
            acceptance_criteria=["origin remains valid"],
            category="feature",
            priority="medium",
        )

        with testrunner.raises(Exception):
            session.execute(
                text("UPDATE work_items SET origin_proposal_version = :v WHERE id = :id"),
                {"v": proposal.version + 1, "id": work_item.id},
            )
            session.commit()
        session.rollback()

        stored = session.execute(
            text("SELECT origin_proposal_version FROM work_items WHERE id = :id"),
            {"id": work_item.id},
        ).scalar_one()
        assert stored == proposal.version
