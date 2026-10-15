"""Integration tests: one WorkItem per approved Proposal (F-11).

The workflow specification (`docs/architecture/work-management-workflow.md`,
step 7) requires a unique constraint on `origin_proposal_id`. These tests prove
the database rejects a second WorkItem from the same Proposal, including under
concurrent writers and direct SQL.
"""

from __future__ import annotations

import threading
from uuid import uuid4

import testrunner
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from eventflow_work_management.repositories import (
    ApprovalRepository,
    WorkItemRepository,
)
from support import (
    create_consultation,
    create_project,
    create_proposal,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def _approved_proposal(session, workspace, project):
    consultation = create_consultation(session, workspace, project)
    proposal = create_proposal(session, workspace, project, consultation)
    decision = ApprovalRepository(session).decide(
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        decider_id=uuid4(),
        decision="approved",
        justification="Approved for cardinality tests.",
        idempotency_key=f"cardinality-{uuid4().hex[:12]}",
    )
    return proposal, decision


def _create_work_item(
    session,
    *,
    workspace_id,
    project_id,
    proposal_id,
    proposal_version,
    approval_id,
    title,
):
    return WorkItemRepository(session).create_from_approved_proposal(
        workspace_id=workspace_id,
        project_id=project_id,
        proposal_id=proposal_id,
        proposal_version=proposal_version,
        approval_id=approval_id,
        title=title,
        description="Work item created for a cardinality test.",
        acceptance_criteria=["only one per proposal"],
        category="feature",
        priority="medium",
    )


def test_second_work_item_from_same_proposal_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        proposal, decision = _approved_proposal(session, workspace, project)
        ids = {
            "workspace_id": workspace.id,
            "project_id": project.id,
            "proposal_id": proposal.id,
            "proposal_version": proposal.version,
            "approval_id": decision.approval.id,
        }

        _create_work_item(session, **ids, title="First item")

        with testrunner.raises(IntegrityError):
            _create_work_item(session, **ids, title="Second item")
        session.rollback()

        count = session.execute(
            text("SELECT count(*) FROM work_items WHERE origin_proposal_id = :pid"),
            {"pid": proposal.id},
        ).scalar_one()
        assert count == 1


def test_duplicate_work_item_via_direct_sql_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        proposal, decision = _approved_proposal(session, workspace, project)

        _create_work_item(
            session,
            workspace_id=workspace.id,
            project_id=project.id,
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            approval_id=decision.approval.id,
            title="First item",
        )

        with testrunner.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO work_items "
                    "(workspace_id, project_id, origin_proposal_id, "
                    " origin_proposal_version, origin_approval_id, title, description, "
                    " acceptance_criteria, category, priority) "
                    "VALUES (:ws, :project, :proposal, :version, :approval, "
                    " 'Direct SQL duplicate', 'Inserted without the repository.', "
                    " '[\"x\"]'::jsonb, 'feature', 'medium')"
                ),
                {
                    "ws": workspace.id,
                    "project": project.id,
                    "proposal": proposal.id,
                    "version": proposal.version,
                    "approval": decision.approval.id,
                },
            )
            session.commit()
        session.rollback()

        count = session.execute(
            text("SELECT count(*) FROM work_items WHERE origin_proposal_id = :pid"),
            {"pid": proposal.id},
        ).scalar_one()
        assert count == 1


def test_concurrent_work_items_from_same_proposal_has_exactly_one_effect():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        with session_scope(engine) as setup:
            workspace = create_workspace(setup)
            project = create_project(setup, workspace)
            proposal, decision = _approved_proposal(setup, workspace, project)
            ids = {
                "workspace_id": workspace.id,
                "project_id": project.id,
                "proposal_id": proposal.id,
                "proposal_version": proposal.version,
                "approval_id": decision.approval.id,
            }

        barrier = threading.Barrier(2)
        successes: list[int] = []
        errors: list[Exception] = []

        def worker():
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    _create_work_item(session, **ids, title="Concurrent item")
                    successes.append(1)
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert successes, f"no work item was persisted: {errors}"
        with session_scope(engine) as session:
            count = session.execute(
                text("SELECT count(*) FROM work_items WHERE origin_proposal_id = :pid"),
                {"pid": ids["proposal_id"]},
            ).scalar_one()
        assert count == 1, "more than one WorkItem was persisted for a single proposal"
