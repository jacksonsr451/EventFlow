"""Integration tests for concurrent writes under database constraints."""

from __future__ import annotations

import threading
from uuid import uuid4

from eventflow_work_management.repositories import ProposalRepository
from sqlalchemy import text
from support import (
    create_consultation,
    create_project,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def test_concurrent_proposals_never_duplicate_versions():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        with session_scope(engine) as setup_session:
            workspace = create_workspace(setup_session)
            project = create_project(setup_session, workspace)
            consultation = create_consultation(setup_session, workspace, project)
            workspace_id, project_id, consultation_id = (
                workspace.id,
                project.id,
                consultation.id,
            )

        barrier = threading.Barrier(2)
        successes: list[int] = []
        errors: list[Exception] = []

        def worker():
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    proposal = ProposalRepository(session).create(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        consultation_id=consultation_id,
                        proposer_id=uuid4(),
                        title="Concurrent proposal",
                        technical_description="Concurrent proposal description.",
                        scope="Scope.",
                        justification="Justification.",
                        acceptance_criteria=["criteria"],
                        category="feature",
                        priority="medium",
                    )
                    successes.append(proposal.version)
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert successes, f"no proposal was persisted: {errors}"
        with session_scope(engine) as session:
            versions = list(
                session.execute(
                    text("SELECT version FROM proposals WHERE consultation_id = :cid"),
                    {"cid": consultation_id},
                ).scalars()
            )
        assert len(versions) == len(set(versions)), (
            "duplicate proposal versions persisted"
        )
        assert set(versions) == set(successes)
