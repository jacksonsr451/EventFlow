"""Integration tests for the deterministic development seed."""

from __future__ import annotations

from sqlalchemy import text

from eventflow_work_management.models import Workspace
from eventflow_work_management.seeds import run_development_seed
from support import (
    migrated_engine,
    require_database_url,
    session_scope,
)


def test_seed_is_idempotent_and_complete():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        first = run_development_seed(engine)
        second = run_development_seed(engine)

        assert first == second

        with session_scope(engine) as session:
            assert session.get(Workspace, first["workspace_id"]) is not None
            counts = {
                table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in ("workspaces", "projects", "work_items", "approvals", "board_cards")
            }
        assert counts == {
            "workspaces": 1,
            "projects": 1,
            "work_items": 1,
            "approvals": 1,
            "board_cards": 1,
        }
