"""Integration tests for database-enforced constraints and tenant isolation."""

from __future__ import annotations

from uuid import uuid4

import testrunner
from eventflow_work_management.models import (
    Consultation,
    Proposal,
    ProposalRevision,
    WorkItem,
    Workspace,
)
from eventflow_work_management.repositories import (
    ApprovalRepository,
    BoardCardRepository,
    BoardRepository,
    ProposalRepository,
)
from sqlalchemy.exc import IntegrityError
from support import (
    create_consultation,
    create_project,
    create_proposal,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
    unique_slug,
)


def test_duplicate_workspace_slug_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        slug = unique_slug()
        create_workspace(session, slug=slug)
        with testrunner.raises(IntegrityError):
            session.add(Workspace(id=uuid4(), name="Other", slug=slug))
            session.commit()
        session.rollback()


def test_invalid_slug_format_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        with testrunner.raises(IntegrityError):
            session.add(Workspace(id=uuid4(), name="Bad Slug", slug="Not A Slug"))
            session.commit()
        session.rollback()


def test_invalid_consultation_origin_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        with testrunner.raises(IntegrityError):
            session.add(
                Consultation(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    project_id=project.id,
                    author_id=uuid4(),
                    origin="carrier-pigeon",
                    title="Invalid origin",
                    description="The origin value is not in the contract enum.",
                    priority="medium",
                )
            )
            session.commit()
        session.rollback()


def test_cross_workspace_reference_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace_a = create_workspace(session, name="Tenant A")
        workspace_b = create_workspace(session, name="Tenant B")
        project_a = create_project(session, workspace_a)

        with testrunner.raises(IntegrityError):
            session.add(
                Consultation(
                    id=uuid4(),
                    workspace_id=workspace_b.id,
                    project_id=project_a.id,
                    author_id=uuid4(),
                    origin="web",
                    title="Cross tenant",
                    description="A consultation cannot point at another tenant's project.",
                    priority="medium",
                )
            )
            session.commit()
        session.rollback()


def test_independent_proposals_share_consultation():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        repository = ProposalRepository(session)

        def create(title):
            return repository.add(
                workspace_id=workspace.id,
                project_id=project.id,
                consultation_id=consultation.id,
                proposer_id=uuid4(),
                title=title,
                technical_description="Independent proposal description.",
                scope="Scope.",
                justification="Justification.",
                acceptance_criteria=["criteria"],
                category="feature",
                priority="medium",
            )

        first = create("First proposal")
        second = create("Second proposal")

        assert first.id != second.id
        assert first.version == 1
        assert second.version == 1
        assert (
            repository.count_for_consultation(
                workspace_id=workspace.id, consultation_id=consultation.id
            )
            == 2
        )


def test_duplicate_proposal_revision_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        proposal = ProposalRepository(session).add(
            workspace_id=workspace.id,
            project_id=project.id,
            consultation_id=consultation.id,
            proposer_id=uuid4(),
            title="Revisioned proposal",
            technical_description="Revisioned proposal description.",
            scope="Scope.",
            justification="Justification.",
            acceptance_criteria=["criteria"],
            category="feature",
            priority="medium",
        )
        session.commit()

        with testrunner.raises(IntegrityError):
            session.add(
                ProposalRevision(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    proposal_id=proposal.id,
                    version=proposal.version,
                    author_id=uuid4(),
                    summary="Duplicate revision",
                    snapshot={"title": "Duplicate"},
                )
            )
            session.commit()
        session.rollback()


def test_duplicate_board_card_rank_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        board = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project.id, name="Board"
        )
        work_item_a = session.get(
            WorkItem, _persist_work_item(session, workspace, project)
        )
        work_item_b = session.get(
            WorkItem, _persist_work_item(session, workspace, project)
        )

        cards = BoardCardRepository(session)
        cards.add_card(
            workspace_id=workspace.id,
            board_id=board.id,
            work_item_id=work_item_a.id,
            column_id="ready",
            rank="a0",
            title="Card A",
            priority="medium",
            category="feature",
        )
        with testrunner.raises(IntegrityError):
            cards.add_card(
                workspace_id=workspace.id,
                board_id=board.id,
                work_item_id=work_item_b.id,
                column_id="ready",
                rank="a0",
                title="Card B",
                priority="medium",
                category="feature",
            )
        session.rollback()


def test_proposal_project_must_match_consultation_project():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        consultation = create_consultation(session, workspace, project_a)

        with testrunner.raises(IntegrityError):
            session.add(
                Proposal(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    project_id=project_b.id,
                    consultation_id=consultation.id,
                    version=1,
                    title="Cross-project proposal",
                    technical_description="Project must match the consultation.",
                    scope="Scope.",
                    justification="Justification.",
                    acceptance_criteria=["criteria"],
                    category="feature",
                    priority="medium",
                    proposer_id=uuid4(),
                )
            )
            session.commit()
        session.rollback()


def test_work_item_project_must_match_origin_proposal_project():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        consultation = create_consultation(session, workspace, project_a)
        proposal = create_proposal(session, workspace, project_a, consultation)
        decision = ApprovalRepository(session).decide(
            workspace_id=workspace.id,
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            decider_id=uuid4(),
            decision="approved",
            justification="Approved for cross-project test.",
            idempotency_key=f"cross-project-{uuid4().hex[:12]}",
        )

        with testrunner.raises(IntegrityError):
            session.add(
                WorkItem(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    project_id=project_b.id,
                    origin_proposal_id=proposal.id,
                    origin_proposal_version=proposal.version,
                    origin_approval_id=decision.approval.id,
                    title="Cross-project work item",
                    description="Project must match the origin proposal.",
                    acceptance_criteria=["criteria"],
                    category="feature",
                    priority="medium",
                )
            )
            session.commit()
        session.rollback()


def _persist_work_item(session, workspace, project):
    """Create a minimal approved-proposal-backed WorkItem for card tests."""
    from uuid import uuid4 as _uuid4

    consultation = create_consultation(session, workspace, project)
    proposal = create_proposal(session, workspace, project, consultation)
    decision = ApprovalRepository(session).decide(
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        decider_id=_uuid4(),
        decision="approved",
        justification="Approved for card tests.",
        idempotency_key=f"card-key-{_uuid4().hex[:12]}",
    )
    item = WorkItem(
        id=_uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        origin_proposal_id=proposal.id,
        origin_proposal_version=proposal.version,
        origin_approval_id=decision.approval.id,
        title="Card work item",
        description="Work item backing a board card.",
        acceptance_criteria=["card exists"],
        category="feature",
        priority="medium",
    )
    session.add(item)
    session.commit()
    return item.id
