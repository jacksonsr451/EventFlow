"""Integration tests: a BoardCard must join a Board and WorkItem in one project (F-05)."""

from __future__ import annotations

from uuid import uuid4

import testrunner
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from eventflow_work_management.repositories import (
    ApprovalRepository,
    BoardCardRepository,
    BoardRepository,
    WorkItemRepository,
)
from eventflow_work_management.repositories.errors import EntityNotFound
from support import (
    create_consultation,
    create_project,
    create_proposal,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def _approved_work_item(session, workspace, project, *, title="Card work item"):
    consultation = create_consultation(session, workspace, project)
    proposal = create_proposal(session, workspace, project, consultation)
    decision = ApprovalRepository(session).decide(
        workspace_id=workspace.id,
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        decider_id=uuid4(),
        decision="approved",
        justification="Approved for board integrity tests.",
        idempotency_key=f"board-integrity-{uuid4().hex[:12]}",
    )
    return WorkItemRepository(session).create_from_approved_proposal(
        workspace_id=workspace.id,
        project_id=project.id,
        proposal_id=proposal.id,
        proposal_version=proposal.version,
        approval_id=decision.approval.id,
        title=title,
        description="Work item backing a board card integrity test.",
        acceptance_criteria=["card integrity"],
        category="feature",
        priority="medium",
    )


def _add_card(session, workspace, board, work_item, *, rank="a0", title="Card"):
    return BoardCardRepository(session).add_card(
        workspace_id=workspace.id,
        board_id=board.id,
        work_item_id=work_item.id,
        column_id="ready",
        rank=rank,
        title=title,
        priority="medium",
        category="feature",
    )


def test_board_card_in_same_project_is_allowed():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        board = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project.id, name="Board"
        )
        work_item = _approved_work_item(session, workspace, project)

        card = _add_card(session, workspace, board, work_item)

        assert card.project_id == project.id
        assert card.work_item_id == work_item.id


def test_board_card_cross_project_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        board_a = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project_a.id, name="Board A"
        )
        work_item_b = _approved_work_item(session, workspace, project_b)

        with testrunner.raises(IntegrityError):
            _add_card(session, workspace, board_a, work_item_b)
        session.rollback()

        remaining = session.execute(text("SELECT count(*) FROM board_cards")).scalar_one()
        assert remaining == 0


def test_board_card_cross_project_direct_sql_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        board_a = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project_a.id, name="Board A"
        )
        work_item_b = _approved_work_item(session, workspace, project_b)

        with testrunner.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO board_cards "
                    "(workspace_id, project_id, board_id, column_id, work_item_id, "
                    " rank, title, priority, category) "
                    "VALUES (:ws, :project, :board, 'ready', :work_item, "
                    " 'a0', 'Direct SQL card', 'medium', 'feature')"
                ),
                {
                    "ws": workspace.id,
                    "project": project_a.id,
                    "board": board_a.id,
                    "work_item": work_item_b.id,
                },
            )
            session.commit()
        session.rollback()


def test_board_card_cross_workspace_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace_a = create_workspace(session, name="Tenant A")
        workspace_b = create_workspace(session, name="Tenant B")
        project_a = create_project(session, workspace_a, name="Project A")
        project_b = create_project(session, workspace_b, name="Project B")
        board_a = BoardRepository(session).create(
            workspace_id=workspace_a.id, project_id=project_a.id, name="Board A"
        )
        work_item_b = _approved_work_item(session, workspace_b, project_b)

        with testrunner.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO board_cards "
                    "(workspace_id, project_id, board_id, column_id, work_item_id, "
                    " rank, title, priority, category) "
                    "VALUES (:ws, :project, :board, 'ready', :work_item, "
                    " 'a0', 'Cross tenant card', 'medium', 'feature')"
                ),
                {
                    "ws": workspace_a.id,
                    "project": project_a.id,
                    "board": board_a.id,
                    "work_item": work_item_b.id,
                },
            )
            session.commit()
        session.rollback()


def test_board_card_update_to_cross_project_work_item_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        board_a = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project_a.id, name="Board A"
        )
        work_item_a = _approved_work_item(session, workspace, project_a, title="Item A")
        work_item_b = _approved_work_item(session, workspace, project_b, title="Item B")
        card = _add_card(session, workspace, board_a, work_item_a)

        with testrunner.raises(IntegrityError):
            session.execute(
                text("UPDATE board_cards SET work_item_id = :wi WHERE id = :id"),
                {"wi": work_item_b.id, "id": card.id},
            )
            session.commit()
        session.rollback()

        stored = session.execute(
            text("SELECT work_item_id FROM board_cards WHERE id = :id"),
            {"id": card.id},
        ).scalar_one()
        assert stored == work_item_a.id


def test_changing_work_item_project_cannot_invalidate_existing_card():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project_a = create_project(session, workspace, name="Project A")
        project_b = create_project(session, workspace, name="Project B")
        board_a = BoardRepository(session).create(
            workspace_id=workspace.id, project_id=project_a.id, name="Board A"
        )
        work_item_a = _approved_work_item(session, workspace, project_a)
        _add_card(session, workspace, board_a, work_item_a)

        with testrunner.raises(IntegrityError):
            session.execute(
                text("UPDATE work_items SET project_id = :p WHERE id = :id"),
                {"p": project_b.id, "id": work_item_a.id},
            )
            session.commit()
        session.rollback()

        stored = session.execute(
            text("SELECT project_id FROM work_items WHERE id = :id"),
            {"id": work_item_a.id},
        ).scalar_one()
        assert stored == project_a.id


def test_missing_board_is_rejected_without_partial_write():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        work_item = _approved_work_item(session, workspace, project)

        with testrunner.raises(EntityNotFound):
            BoardCardRepository(session).add_card(
                workspace_id=workspace.id,
                board_id=uuid4(),
                work_item_id=work_item.id,
                column_id="ready",
                rank="a0",
                title="Orphan card",
                priority="medium",
                category="feature",
            )
        session.rollback()

        remaining = session.execute(text("SELECT count(*) FROM board_cards")).scalar_one()
        assert remaining == 0
