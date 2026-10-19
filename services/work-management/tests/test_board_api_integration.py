"""HTTP integration tests for configurable Kanban boards (Issue #8).

The app runs against a throwaway migrated database with a deterministic
authentication stub. The tests exercise the public contract end to end: board and
column management, RBAC, optimistic concurrency, deterministic card ordering,
lifecycle transitions, WIP limits, movement history, idempotency, and the
approval-only provenance of cards. They skip themselves when no test database is
configured.
"""

from __future__ import annotations

import threading
from uuid import uuid4

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.repositories.board_repository import BoardRepository
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from sqlalchemy import text
from support import (
    migrated_engine,
    require_database_url,
    session_scope,
)

ISSUER = "https://id.example.test/realms/eventflow"


class FakeOIDC:
    def validate_access_token(self, token: str) -> dict:
        return {"iss": ISSUER, "sub": token}

    def close(self) -> None:  # pragma: no cover - lifecycle no-op
        return None


def _settings() -> AuthSettings:
    return AuthSettings(
        environment="test",
        issuer=ISSUER,
        audience="eventflow-api",
        web_client_id="eventflow-web-bff",
        native_client_ids=("eventflow-desktop", "eventflow-vscode"),
        redirect_uri="https://api.example.test/v1/auth/oidc/callback",
        frontend_redirect_uri="https://web.example.test/auth/complete",
        allowed_origins=("https://web.example.test",),
        token_encryption_keys=(TokenCipher.generate_key(),),
    )


def _client(engine) -> TestClient:
    app = create_app(
        settings=_settings(),
        session_factory_override=session_factory(engine),
        oidc_client=FakeOIDC(),
    )
    return TestClient(app)


def _bearer(subject: str, **extra) -> dict:
    return {"Authorization": f"Bearer {subject}", **extra}


def _principal_id(client: TestClient, subject: str) -> str:
    response = client.get("/v1/auth/principal", headers=_bearer(subject))
    assert response.status_code == 200, response.text
    return response.json()["user_id"]


def _make_workspace(client: TestClient, subject: str, name: str) -> str:
    created = client.post(
        "/v1/workspaces",
        json={"name": name, "slug": name.lower().replace(" ", "-") + f"-{uuid4().hex[:6]}"},
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    return created.json()["workspace_id"]


def _make_project(client: TestClient, subject: str, workspace_id: str) -> str:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/projects",
        json={"key": "PAY", "name": "Payments"},
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    return created.json()["project_id"]


def _invite_and_accept(
    client: TestClient, owner: str, workspace_id: str, invitee: str, role: str
) -> None:
    invitee_id = _principal_id(client, invitee)
    invitation = client.post(
        f"/v1/workspaces/{workspace_id}/invitations",
        json={"invited_user_id": invitee_id, "role": role},
        headers=_bearer(owner),
    )
    assert invitation.status_code == 201, invitation.text
    body = invitation.json()
    accepted = client.post(
        f"/v1/workspaces/{workspace_id}/invitations/"
        f"{body['invitation']['invitation_id']}/accept",
        json={"token": body["token"]},
        headers=_bearer(invitee),
    )
    assert accepted.status_code == 201, accepted.text


def _create_board(
    client: TestClient, subject: str, workspace_id: str, project_id: str, **overrides
) -> dict:
    body = {"project_id": project_id, "name": "Delivery"}
    body.update(overrides)
    created = client.post(
        f"/v1/workspaces/{workspace_id}/boards",
        json=body,
        headers=_bearer(subject, **{"Idempotency-Key": f"board-{uuid4().hex[:12]}"}),
    )
    assert created.status_code == 201, created.text
    return created.json()


def _approved_card(
    client: TestClient,
    owner: str,
    approver: str,
    workspace_id: str,
    project_id: str,
    board_id: str,
    *,
    title: str = "Streaming CSV export",
) -> tuple[dict, dict]:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json={
            "project_id": project_id,
            "origin": "web",
            "title": "Add CSV export",
            "description": "Users need CSV export from the dashboard.",
        },
        headers=_bearer(owner),
    )
    assert created.status_code == 201, created.text
    consultation_id = created.json()["consultation_id"]
    triaged = client.post(
        f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
        json={
            "category": "feature",
            "priority": "high",
            "triage_notes": "Reviewed and reproduced against the current build.",
            "feature_criteria": {
                "problem_statement": "Users cannot export their data.",
                "expected_value": "Self-service data export.",
                "functional_requirements": ["Export the current filter selection."],
                "acceptance_criteria": ["A CSV file downloads."],
                "scope": "Backend endpoint only; no client UI.",
            },
        },
        headers=_bearer(owner),
    )
    assert triaged.status_code == 200, triaged.text
    proposal = client.post(
        f"/v1/workspaces/{workspace_id}/proposals",
        json={
            "consultation_id": consultation_id,
            "title": title,
            "technical_description": "Implement a streaming CSV export endpoint.",
            "scope": "Dashboard export control and backend endpoint.",
            "justification": "Customers requested CSV export.",
            "acceptance_criteria": ["CSV download works for the current filters"],
            "category": "feature",
            "priority": "medium",
        },
        headers=_bearer(owner),
    )
    assert proposal.status_code == 201, proposal.text
    proposal_id = proposal.json()["proposal_id"]
    submitted = client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
        headers=_bearer(owner),
    )
    assert submitted.status_code == 200, submitted.text
    decision = client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
        json={
            "proposal_version": submitted.json()["version"],
            "decision": "approved",
            "decision_justification": "Ready for implementation.",
            "target_board_id": board_id,
        },
        headers=_bearer(
            approver,
            **{"Idempotency-Key": f"decision-{uuid4().hex[:12]}"},
            **{"If-Match": submitted.headers["ETag"]},
        ),
    )
    assert decision.status_code == 200, decision.text
    body = decision.json()
    return body["board_card"], body["work_item"]


def _setup(client: TestClient, *extra_roles: tuple[str, str]):
    owner = f"owner-{uuid4().hex[:8]}"
    workspace_id = _make_workspace(client, owner, "Acme Inc")
    project_id = _make_project(client, owner, workspace_id)
    for subject, role in extra_roles:
        _invite_and_accept(client, owner, workspace_id, subject, role)
    return owner, workspace_id, project_id


# ---------------------------------------------------------------------------
# Board and column management
# ---------------------------------------------------------------------------


def test_board_create_get_and_list_with_default_columns():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        board = _create_board(client, owner, workspace_id, project_id)
        assert board["columns"] == ["ready", "in_progress", "in_review", "done"]
        assert board["version"] == 1

        fetched = client.get(
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}",
            headers=_bearer(owner),
        )
        assert fetched.status_code == 200, fetched.text
        assert "ETag" in fetched.headers

        listed = client.get(
            f"/v1/workspaces/{workspace_id}/boards",
            headers=_bearer(owner),
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1

        columns = client.get(
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}/columns",
            headers=_bearer(owner),
        )
        assert columns.status_code == 200, columns.text
        assert [column["key"] for column in columns.json()] == board["columns"]


def test_board_create_is_idempotent_and_replays():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        key = "board-key-0001"
        body = {"project_id": project_id, "name": "Delivery"}
        first = client.post(
            f"/v1/workspaces/{workspace_id}/boards",
            json=body,
            headers=_bearer(owner, **{"Idempotency-Key": key}),
        )
        second = client.post(
            f"/v1/workspaces/{workspace_id}/boards",
            json=body,
            headers=_bearer(owner, **{"Idempotency-Key": key}),
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["board_id"] == second.json()["board_id"]
        conflict = client.post(
            f"/v1/workspaces/{workspace_id}/boards",
            json={**body, "name": "Other"},
            headers=_bearer(owner, **{"Idempotency-Key": key}),
        )
        assert conflict.status_code == 409, conflict.text
        with session_scope(engine) as session:
            count = session.execute(text("SELECT count(*) FROM boards")).scalar_one()
        assert count == 1


def test_only_board_managers_may_create_boards():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        viewer = f"viewer-{uuid4().hex[:8]}"
        owner, workspace_id, project_id = _setup(client, (viewer, "viewer"))
        denied = client.post(
            f"/v1/workspaces/{workspace_id}/boards",
            json={"project_id": project_id, "name": "Delivery"},
            headers=_bearer(viewer),
        )
        assert denied.status_code == 403, denied.text
        board = _create_board(client, owner, workspace_id, project_id)
        allowed = client.get(
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}",
            headers=_bearer(viewer),
        )
        assert allowed.status_code == 200, allowed.text


def test_column_create_update_reorder_and_delete():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        board = _create_board(client, owner, workspace_id, project_id)
        base = f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}/columns"

        created = client.post(
            base,
            json={
                "key": "blocked",
                "name": "Blocked",
                "mapped_status": "blocked",
                "wip_limit": 2,
                "position": 1,
            },
            headers=_bearer(owner),
        )
        assert created.status_code == 201, created.text
        column = created.json()
        assert column["position"] == 1
        assert column["wip_limit"] == 2

        reordered = client.get(
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}",
            headers=_bearer(owner),
        )
        assert reordered.json()["columns"][1] == "blocked"

        updated = client.patch(
            f"{base}/{column['column_id']}",
            json={"position": 0, "name": "Waiting"},
            headers=_bearer(owner, **{"If-Match": created.headers["ETag"]}),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["position"] == 0

        stale = client.patch(
            f"{base}/{column['column_id']}",
            json={"name": "Stale"},
            headers=_bearer(owner, **{"If-Match": created.headers["ETag"]}),
        )
        assert stale.status_code == 412, stale.text

        removed = client.delete(
            f"{base}/{column['column_id']}",
            headers=_bearer(owner, **{"If-Match": updated.headers["ETag"]}),
        )
        assert removed.status_code == 204, removed.text


def test_last_column_cannot_be_deleted():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        board = _create_board(
            client,
            owner,
            workspace_id,
            project_id,
            columns=[
                {"key": "ready", "name": "Ready", "mapped_status": "ready"}
            ],
        )
        base = f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}/columns"
        columns = client.get(base, headers=_bearer(owner)).json()
        denied = client.delete(
            f"{base}/{columns[0]['column_id']}", headers=_bearer(owner)
        )
        assert denied.status_code == 409, denied.text


# ---------------------------------------------------------------------------
# Card moves, transitions, WIP, history and provenance
# ---------------------------------------------------------------------------


def test_card_move_updates_work_item_and_records_history():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        approver = f"approver-{uuid4().hex[:8]}"
        owner, workspace_id, project_id = _setup(client, (approver, "approver"))
        board = _create_board(client, owner, workspace_id, project_id)
        card, work_item = _approved_card(
            client, owner, approver, workspace_id, project_id, board["board_id"]
        )
        assert card["column_id"] == "ready"
        assert work_item["status"] == "ready"

        cards_base = (
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}"
            f"/cards/{card['card_id']}"
        )
        moved = client.patch(
            cards_base,
            json={"target_column_id": "in_progress", "target_rank": "U"},
            headers=_bearer(
                owner, **{"Idempotency-Key": f"move-{uuid4().hex[:12]}"}
            ),
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["column_id"] == "in_progress"

        work_item_after = client.get(
            f"/v1/workspaces/{workspace_id}/work-items/{card['work_item_id']}",
            headers=_bearer(owner),
        )
        assert work_item_after.json()["status"] == "in_progress"

        history = client.get(
            f"{cards_base}/movements", headers=_bearer(owner)
        )
        assert history.status_code == 200, history.text
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["from_column_id"] == "ready"
        assert items[0]["to_column_id"] == "in_progress"
        assert items[0]["from_status"] == "ready"
        assert items[0]["to_status"] == "in_progress"


def test_card_move_rejects_invalid_transition_and_unknown_column():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        approver = f"approver-{uuid4().hex[:8]}"
        owner, workspace_id, project_id = _setup(client, (approver, "approver"))
        board = _create_board(client, owner, workspace_id, project_id)
        card, _ = _approved_card(
            client, owner, approver, workspace_id, project_id, board["board_id"]
        )
        base = (
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}"
            f"/cards/{card['card_id']}"
        )
        invalid = client.patch(
            base,
            json={"target_column_id": "done", "target_rank": "U"},
            headers=_bearer(owner),
        )
        assert invalid.status_code == 409, invalid.text
        unknown = client.patch(
            base,
            json={"target_column_id": "nonexistent", "target_rank": "U"},
            headers=_bearer(owner),
        )
        assert unknown.status_code == 409, unknown.text


def test_card_move_enforces_wip_limit():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        approver = f"approver-{uuid4().hex[:8]}"
        owner, workspace_id, project_id = _setup(client, (approver, "approver"))
        board = _create_board(
            client,
            owner,
            workspace_id,
            project_id,
            columns=[
                {"key": "ready", "name": "Ready", "mapped_status": "ready"},
                {
                    "key": "in_progress",
                    "name": "In Progress",
                    "mapped_status": "in_progress",
                    "wip_limit": 1,
                },
            ],
        )
        first, _ = _approved_card(
            client, owner, approver, workspace_id, project_id, board["board_id"]
        )
        second, _ = _approved_card(
            client,
            owner,
            approver,
            workspace_id,
            project_id,
            board["board_id"],
            title="Follow-up export work",
        )

        def move(card, column):
            return client.patch(
                f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}"
                f"/cards/{card['card_id']}",
                json={"target_column_id": column, "target_rank": "U"},
                headers=_bearer(owner),
            )

        assert move(first, "in_progress").status_code == 200
        blocked = move(second, "in_progress")
        assert blocked.status_code == 409, blocked.text


def test_concurrent_moves_respect_single_wip_slot():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        approver = f"approver-{uuid4().hex[:8]}"
        owner, workspace_id, project_id = _setup(client, (approver, "approver"))
        board = _create_board(
            client,
            owner,
            workspace_id,
            project_id,
            columns=[
                {"key": "ready", "name": "Ready", "mapped_status": "ready"},
                {
                    "key": "in_progress",
                    "name": "In Progress",
                    "mapped_status": "in_progress",
                    "wip_limit": 1,
                },
            ],
        )
        first, _ = _approved_card(
            client, owner, approver, workspace_id, project_id, board["board_id"]
        )
        second, _ = _approved_card(
            client,
            owner,
            approver,
            workspace_id,
            project_id,
            board["board_id"],
            title="Second work item",
        )
        barrier = threading.Barrier(2)
        statuses: list[int] = []
        errors: list[Exception] = []

        def move(card: dict) -> None:
            try:
                barrier.wait(timeout=10)
                response = client.patch(
                    f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}"
                    f"/cards/{card['card_id']}",
                    json={"target_column_id": "in_progress", "target_rank": "U"},
                    headers=_bearer(owner),
                )
                statuses.append(response.status_code)
            except Exception as error:  # noqa: BLE001 - surfaced by assertion below
                errors.append(error)

        threads = [
            threading.Thread(target=move, args=(card,))
            for card in (first, second)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == [], f"unexpected errors: {errors}"
        assert sorted(statuses) == [200, 409], statuses
        with session_scope(engine) as session:
            occupied = session.execute(
                text(
                    "SELECT count(*) FROM board_cards WHERE column_id = 'in_progress'"
                )
            ).scalar_one()
        assert occupied == 1


def test_cards_cannot_be_created_directly():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        board = _create_board(client, owner, workspace_id, project_id)
        denied = client.post(
            f"/v1/workspaces/{workspace_id}/boards/{board['board_id']}/cards",
            json={"title": "Nope"},
            headers=_bearer(owner),
        )
        assert denied.status_code == 405, denied.text


def test_legacy_board_without_columns_can_still_be_read():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        client = _client(engine)
        owner, workspace_id, project_id = _setup(client)
        with session_scope(engine) as session:
            board = BoardRepository(session).create(
                workspace_id=workspace_id,
                project_id=project_id,
                name="Legacy",
                columns=["ready"],
            )
            board_id = str(board.id)
        fetched = client.get(
            f"/v1/workspaces/{workspace_id}/boards/{board_id}",
            headers=_bearer(owner),
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["columns"] == ["ready"]
