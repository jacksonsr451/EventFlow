"""HTTP and repository integration tests for proposal decisions (Issue #7).

The app runs against a throwaway migrated database and a deterministic
authentication stub. The tests exercise the public contract end to end:
role-based authorization, approval that atomically creates the WorkItem and its
initial BoardCard, rejection and change requests that create no downstream work,
stale-version and If-Match rejection, self-approval prevention, durable
idempotent replay, renewed approval after a material revision, atomic rollback
on failure, and exactly-once effects under concurrency. They skip themselves
when no test database is configured.
"""

from __future__ import annotations

import threading
from uuid import uuid4

import testrunner
from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.repositories import (
    AlreadyDecided,
    ApprovalRepository,
    BoardRepository,
)
from eventflow_work_management.repositories.approval_repository import (
    BoardPlacement,
)
from eventflow_work_management.repositories.errors import RepositoryError
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from sqlalchemy import text
from support import (
    create_consultation,
    create_project,
    create_proposal,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
    temporary_database,
)

ISSUER = "https://id.example.test/realms/eventflow"


class FakeOIDC:
    """Maps each bearer token to a distinct internal identity."""

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


def _client(engine):
    app = create_app(
        settings=_settings(),
        session_factory_override=session_factory(engine),
        oidc_client=FakeOIDC(),
    )
    return TestClient(app)


def _bearer(subject: str) -> dict:
    return {"Authorization": f"Bearer {subject}"}


def _principal_id(client: TestClient, subject: str) -> str:
    response = client.get("/v1/auth/principal", headers=_bearer(subject))
    assert response.status_code == 200, response.text
    return response.json()["user_id"]


def _make_workspace(client: TestClient, subject: str, name: str) -> str:
    created = client.post(
        "/v1/workspaces",
        json={"name": name, "slug": name.lower().replace(" ", "-")},
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


def _triaged_consultation(
    client: TestClient, owner: str, workspace_id: str, project_id: str
) -> str:
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
    return consultation_id


def _proposal_body(consultation_id: str, **overrides) -> dict:
    body = {
        "consultation_id": consultation_id,
        "title": "Streaming CSV export",
        "technical_description": "Implement a streaming CSV export endpoint.",
        "scope": "Dashboard export control and backend endpoint.",
        "justification": "Customers requested CSV export.",
        "acceptance_criteria": ["CSV download works for the current filters"],
        "category": "feature",
        "priority": "medium",
    }
    body.update(overrides)
    return body


def _submit_in_review_proposal(
    client: TestClient, subject: str, workspace_id: str, consultation_id: str
) -> tuple[str, int, str]:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/proposals",
        json=_proposal_body(consultation_id),
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    proposal_id = created.json()["proposal_id"]
    submitted = client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
        headers={**_bearer(subject), "If-Match": created.headers["ETag"]},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    return proposal_id, body["version"], submitted.headers["ETag"]


def _make_board(engine, workspace_id: str, project_id: str) -> str:
    with session_scope(engine) as session:
        board = BoardRepository(session).create(
            workspace_id=workspace_id,
            project_id=project_id,
            name="Delivery",
            columns=["ready", "done"],
        )
        return str(board.id)


def _decide(
    client: TestClient,
    subject: str,
    workspace_id: str,
    proposal_id: str,
    body: dict,
    key: str,
    **extra_headers,
):
    return client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
        json=body,
        headers={**_bearer(subject), "Idempotency-Key": key, **extra_headers},
    )


def _counts(engine) -> dict[str, int]:
    with session_scope(engine) as session:
        return {
            table: int(
                session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            )
            for table in ("approvals", "work_items", "board_cards")
        }


def test_approval_creates_work_item_and_board_card_atomically():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Approval Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, etag = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            board_id = _make_board(engine, workspace_id, project_id)

            response = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "approved",
                    "decision_justification": "Meets every acceptance criterion.",
                    "target_board_id": board_id,
                },
                "decide-approved-0001",
            )
            assert response.status_code == 200, response.text
            assert response.headers["ETag"].startswith('"')
            body = response.json()
            assert body["approval"]["decision"] == "approved"
            assert body["approval"]["proposal_version"] == version
            assert body["work_item"]["status"] == "ready"
            assert body["work_item"]["origin_proposal_id"] == proposal_id
            assert body["board_card"]["column_id"] == "ready"
            assert body["board_card"]["work_item_id"] == body["work_item"]["work_item_id"]

            stored = client.get(
                f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}",
                headers=_bearer("owner"),
            )
            assert stored.json()["status"] == "approved"

            assert _counts(engine) == {
                "approvals": 1,
                "work_items": 1,
                "board_cards": 1,
            }

            with session_scope(engine) as session:
                actions = list(
                    session.execute(
                        text(
                            "SELECT action FROM audit_records "
                            "WHERE workspace_id = :ws ORDER BY created_at"
                        ),
                        {"ws": workspace_id},
                    ).scalars()
                )
            assert "proposal.approved" in actions
            assert "work_item.created" in actions
            assert "board_card.created" in actions


def test_idempotent_decision_replays_without_duplicating_work():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Replay Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            board_id = _make_board(engine, workspace_id, project_id)
            request_body = {
                "proposal_version": version,
                "decision": "approved",
                "decision_justification": "Meets every acceptance criterion.",
                "target_board_id": board_id,
            }

            first = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                request_body,
                "decide-replay-0001",
            )
            second = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                request_body,
                "decide-replay-0001",
            )
            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            assert (
                second.json()["approval"]["approval_id"]
                == first.json()["approval"]["approval_id"]
            )
            assert (
                second.json()["work_item"]["work_item_id"]
                == first.json()["work_item"]["work_item_id"]
            )
            assert (
                second.json()["board_card"]["card_id"]
                == first.json()["board_card"]["card_id"]
            )
            assert _counts(engine) == {
                "approvals": 1,
                "work_items": 1,
                "board_cards": 1,
            }

            conflict = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "rejected",
                    "decision_justification": "A different request body.",
                },
                "decide-replay-0001",
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_stale_version_and_if_match_are_rejected():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Stale Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, etag = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            board_id = _make_board(engine, workspace_id, project_id)

            stale_version = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version + 7,
                    "decision": "approved",
                    "decision_justification": "Stale revision.",
                    "target_board_id": board_id,
                },
                "decide-stale-version",
            )
            assert stale_version.status_code == 409
            assert stale_version.json()["code"] == "STALE_VERSION"

            stale_match = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "approved",
                    "decision_justification": "Stale validator.",
                    "target_board_id": board_id,
                },
                "decide-stale-match",
                **{"If-Match": '"deadbeef"'},
            )
            assert stale_match.status_code == 412
            assert _counts(engine) == {
                "approvals": 0,
                "work_items": 0,
                "board_cards": 0,
            }


def test_self_approval_is_disallowed():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Self Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            board_id = _make_board(engine, workspace_id, project_id)

            response = _decide(
                client,
                "owner",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "approved",
                    "decision_justification": "Approving my own proposal.",
                    "target_board_id": board_id,
                },
                "decide-self-0001",
            )
            assert response.status_code == 403
            assert response.json()["code"] == "SELF_APPROVAL_DISALLOWED"
            assert _counts(engine) == {
                "approvals": 0,
                "work_items": 0,
                "board_cards": 0,
            }


def test_rejection_and_change_request_record_only_a_decision():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Review Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )

            rejected_id, rejected_version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            rejected = _decide(
                client,
                "reviewer",
                workspace_id,
                rejected_id,
                {
                    "proposal_version": rejected_version,
                    "decision": "rejected",
                    "decision_justification": "Out of scope for this quarter.",
                },
                "decide-rejected-0001",
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["approval"]["decision"] == "rejected"
            assert "work_item" not in rejected.json()

            changes_id, changes_version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            changes = _decide(
                client,
                "reviewer",
                workspace_id,
                changes_id,
                {
                    "proposal_version": changes_version,
                    "decision": "changes_requested",
                    "decision_justification": "Clarify the export format.",
                },
                "decide-changes-0001",
            )
            assert changes.status_code == 200, changes.text
            assert changes.json()["approval"]["decision"] == "changes_requested"

            assert _counts(engine) == {
                "approvals": 2,
                "work_items": 0,
                "board_cards": 0,
            }
            for proposal_id in (rejected_id, changes_id):
                stored = client.get(
                    f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}",
                    headers=_bearer("owner"),
                )
            assert stored.json()["status"] == "changes_requested"


def test_decision_requires_approver_role():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Rbac Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "worker", "contributor")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            created = client.post(
                f"/v1/workspaces/{workspace_id}/proposals",
                json=_proposal_body(consultation_id),
                headers=_bearer("worker"),
            )
            proposal_id = created.json()["proposal_id"]
            client.post(
                f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
                headers={**_bearer("worker"), "If-Match": created.headers["ETag"]},
            )
            board_id = _make_board(engine, workspace_id, project_id)

            denied = _decide(
                client,
                "worker",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": 1,
                    "decision": "approved",
                    "decision_justification": "Trying to approve.",
                    "target_board_id": board_id,
                },
                "decide-rbac-0001",
            )
            assert denied.status_code == 403
            assert _counts(engine) == {
                "approvals": 0,
                "work_items": 0,
                "board_cards": 0,
            }


def test_approval_requires_target_board():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Placement Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )

            missing_board = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "approved",
                    "decision_justification": "No board supplied.",
                },
                "decide-no-board",
            )
            assert missing_board.status_code == 400
            assert missing_board.json()["code"] == "VALIDATION_ERROR"

            response = client.post(
                f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
                json={
                    "proposal_version": version,
                    "decision": "approved",
                    "decision_justification": "Missing the idempotency key.",
                },
                headers=_bearer("reviewer"),
            )
            assert response.status_code == 400
            assert response.json()["code"] == "VALIDATION_ERROR"


def test_approval_is_renewed_after_a_material_revision():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Revision Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "reviewer", "approver")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            proposal_id, version, _ = _submit_in_review_proposal(
                client, "owner", workspace_id, consultation_id
            )
            board_id = _make_board(engine, workspace_id, project_id)

            changes = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": version,
                    "decision": "changes_requested",
                    "decision_justification": "Please clarify the export format.",
                },
                "decide-revise-0001",
            )
            assert changes.status_code == 200, changes.text

            url = f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}"
            edited = client.patch(
                url,
                json={"technical_description": "Streaming CSV and JSON export."},
                headers=_bearer("owner"),
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["version"] == version + 1

            resubmitted = client.post(
                f"{url}/submit",
                headers={**_bearer("owner"), "If-Match": edited.headers["ETag"]},
            )
            assert resubmitted.status_code == 200, resubmitted.text

            approved = _decide(
                client,
                "reviewer",
                workspace_id,
                proposal_id,
                {
                    "proposal_version": resubmitted.json()["version"],
                    "decision": "approved",
                    "decision_justification": "Now meets every criterion.",
                    "target_board_id": board_id,
                },
                "decide-revise-0002",
            )
            assert approved.status_code == 200, approved.text
            assert (
                approved.json()["approval"]["proposal_version"]
                == resubmitted.json()["version"]
            )
            assert _counts(engine) == {
                "approvals": 2,
                "work_items": 1,
                "board_cards": 1,
            }


def test_approval_rolls_back_every_row_on_failure():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        other_project = create_project(session, workspace, name="Other")
        consultation = create_consultation(session, workspace, project)
        proposal = create_proposal(session, workspace, project, consultation)
        other_board = BoardRepository(session).create(
            workspace_id=workspace.id,
            project_id=other_project.id,
            name="Wrong board",
        )

        with testrunner.raises(RepositoryError):
            ApprovalRepository(session).decide(
                workspace_id=workspace.id,
                proposal_id=proposal.id,
                proposal_version=proposal.version,
                decider_id=uuid4(),
                decision="approved",
                justification="Placement points at the wrong project.",
                idempotency_key="decide-atomicity-0001",
                placement=BoardPlacement(
                    board_id=other_board.id,
                    column_id="ready",
                    rank=uuid4().hex,
                ),
            )
        session.rollback()

        for table in ("approvals", "work_items", "board_cards", "idempotency_records"):
            assert (
                session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
            )


def test_concurrent_decisions_have_exactly_one_effect():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        with session_scope(engine) as setup:
            workspace = create_workspace(setup)
            project = create_project(setup, workspace)
            consultation = create_consultation(setup, workspace, project)
            proposal = create_proposal(setup, workspace, project, consultation)
            board = BoardRepository(setup).create(
                workspace_id=workspace.id, project_id=project.id, name="Delivery"
            )
            ids = {
                "workspace_id": workspace.id,
                "project_id": project.id,
                "proposal_id": proposal.id,
                "proposal_version": proposal.version,
                "board_id": board.id,
            }

        barrier = threading.Barrier(2)
        results: list = []
        errors: list[Exception] = []

        def worker(key: str):
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    outcome = ApprovalRepository(session).decide(
                        workspace_id=ids["workspace_id"],
                        proposal_id=ids["proposal_id"],
                        proposal_version=ids["proposal_version"],
                        decider_id=uuid4(),
                        decision="approved",
                        justification="Concurrent approval attempt.",
                        idempotency_key=key,
                        placement=BoardPlacement(
                            board_id=ids["board_id"],
                            column_id="ready",
                            rank=uuid4().hex,
                        ),
                    )
                    results.append(outcome)
            except AlreadyDecided:
                pass
            except Exception as error:  # noqa: BLE001 - surfaced by assertion below
                errors.append(error)

        threads = [
            threading.Thread(target=worker, args=(f"decide-concurrent-{index}",))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == [], f"unexpected errors: {errors}"
        assert len(results) == 1, "more than one decision was persisted"

        with session_scope(engine) as session:
            assert session.execute(text("SELECT count(*) FROM approvals")).scalar_one() == 1
            assert session.execute(text("SELECT count(*) FROM work_items")).scalar_one() == 1
            assert session.execute(text("SELECT count(*) FROM board_cards")).scalar_one() == 1
