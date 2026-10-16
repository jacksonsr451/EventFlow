"""Integration tests for concurrent writes under database constraints."""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

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


def test_concurrent_proposals_create_independent_rows():
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
        proposal_ids: list[UUID] = []
        errors: list[Exception] = []

        def worker():
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    proposal = ProposalRepository(session).add(
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
                    session.commit()
                    proposal_ids.append(proposal.id)
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(proposal_ids) == 2, f"expected two proposals: {errors}"
        assert len(set(proposal_ids)) == 2
        with session_scope(engine) as session:
            rows = session.execute(
                text(
                    "SELECT proposal_id, version FROM proposal_revisions "
                    "WHERE workspace_id = :wid"
                ),
                {"wid": workspace_id},
            ).all()
        assert len(rows) == 2
        assert all(version == 1 for _, version in rows)
        assert len({proposal_id for proposal_id, _ in rows}) == 2
