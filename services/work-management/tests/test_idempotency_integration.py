"""Integration tests for idempotent approval decisions."""

from __future__ import annotations

import threading
from uuid import uuid4

import testrunner
from sqlalchemy import text

from eventflow_work_management.repositories import (
    AlreadyDecided,
    ApprovalRepository,
    IdempotencyConflict,
    ProposalRepository,
)
from support import (
    create_consultation,
    create_project,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def _setup(session):
    workspace = create_workspace(session)
    project = create_project(session, workspace)
    consultation = create_consultation(session, workspace, project)
    proposal = ProposalRepository(session).create(
        workspace_id=workspace.id,
        project_id=project.id,
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
    return workspace, proposal


def _decide_kwargs(workspace, proposal):
    return {
        "workspace_id": workspace.id,
        "proposal_id": proposal.id,
        "proposal_version": proposal.version,
        "decider_id": uuid4(),
        "decision": "approved",
        "justification": "Reviewed against acceptance criteria.",
    }


def test_same_key_replays_without_new_effects():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace, proposal = _setup(session)
        repository = ApprovalRepository(session)

        first = repository.decide(idempotency_key="decision-key-0001", **_decide_kwargs(workspace, proposal))
        second = repository.decide(idempotency_key="decision-key-0001", **_decide_kwargs(workspace, proposal))

        assert first.replayed is False
        assert second.replayed is True
        assert first.approval.id == second.approval.id
        approval_count = session.execute(text("SELECT count(*) FROM approvals")).scalar_one()
        idempotency_count = session.execute(
            text("SELECT count(*) FROM idempotency_records")
        ).scalar_one()
        assert approval_count == 1
        assert idempotency_count == 1


def test_same_key_different_request_conflicts():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace, proposal = _setup(session)
        repository = ApprovalRepository(session)

        repository.decide(idempotency_key="decision-key-0001", **_decide_kwargs(workspace, proposal))

        with testrunner.raises(IdempotencyConflict):
            repository.decide(
                idempotency_key="decision-key-0001",
                **{**_decide_kwargs(workspace, proposal), "decision": "rejected"},
            )
        session.rollback()


def test_new_key_for_decided_version_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace, proposal = _setup(session)
        repository = ApprovalRepository(session)

        repository.decide(idempotency_key="decision-key-0001", **_decide_kwargs(workspace, proposal))

        with testrunner.raises(AlreadyDecided):
            repository.decide(idempotency_key="decision-key-0002", **_decide_kwargs(workspace, proposal))
        session.rollback()


def test_concurrent_same_key_has_exactly_one_effect():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        with session_scope(engine) as setup_session:
            workspace, proposal = _setup(setup_session)
            kwargs = _decide_kwargs(workspace, proposal)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker():
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    outcome = ApprovalRepository(session).decide(
                        idempotency_key="decision-key-0001", **kwargs
                    )
                    results.append(outcome)
            except Exception as error:  # noqa: BLE001 - surfaced by assertion below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == []
        assert len(results) == 2
        assert {result.replayed for result in results} == {True, False}
        assert len({result.approval.id for result in results}) == 1

        with session_scope(engine) as session:
            assert session.execute(text("SELECT count(*) FROM approvals")).scalar_one() == 1
            assert (
                session.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one()
                == 1
            )
