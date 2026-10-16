"""HTTP integration tests for consultation task proposals (Issue #6).

The app runs against a throwaway migrated database and a deterministic
authentication stub. The tests exercise the public contract: one triaged
consultation yielding many independent proposals, preview, edit with an
immutable revision history, submit, controlled duplication, RBAC and tenant
isolation, optimistic concurrency, idempotent replay, and the append-only audit
trail. They skip themselves when no test database is configured.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from sqlalchemy import text
from support import (
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


def _create_proposal(
    client: TestClient, subject: str, workspace_id: str, consultation_id: str, **extra
):
    return client.post(
        f"/v1/workspaces/{workspace_id}/proposals",
        json=_proposal_body(consultation_id, **extra),
        headers=_bearer(subject),
    )


def test_one_consultation_yields_multiple_independent_proposals():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Independence Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )

            first = _create_proposal(client, "owner", workspace_id, consultation_id)
            second = _create_proposal(
                client, "owner", workspace_id, consultation_id, title="Bulk CSV export"
            )
            assert first.status_code == 201, first.text
            assert second.status_code == 201, second.text

            first_body = first.json()
            second_body = second.json()
            assert first_body["proposal_id"] != second_body["proposal_id"]
            assert first_body["consultation_id"] == consultation_id
            assert first_body["version"] == 1
            assert second_body["version"] == 1
            assert first_body["status"] == "draft"
            assert first.headers["ETag"].startswith('"')
            assert first.headers["Location"].endswith(
                f"/proposals/{first_body['proposal_id']}"
            )

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
                "/proposals",
                headers=_bearer("owner"),
            )
            assert listed.status_code == 200, listed.text
            ids = {item["proposal_id"] for item in listed.json()["items"]}
            assert ids == {first_body["proposal_id"], second_body["proposal_id"]}

            # Creating proposals never produces downstream work.
            with session_scope(engine) as session:
                for table in ("approvals", "work_items", "board_cards"):
                    assert (
                        session.execute(
                            text(f"SELECT count(*) FROM {table}")
                        ).scalar_one()
                        == 0
                    )


def test_proposal_requires_completed_triage():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Eligibility Co")
            project_id = _make_project(client, "owner", workspace_id)
            created = client.post(
                f"/v1/workspaces/{workspace_id}/consultations",
                json={
                    "project_id": project_id,
                    "origin": "web",
                    "title": "Raw intake",
                    "description": "This consultation has not been triaged yet.",
                },
                headers=_bearer("owner"),
            )
            consultation_id = created.json()["consultation_id"]

            response = _create_proposal(
                client, "owner", workspace_id, consultation_id
            )
            assert response.status_code == 409
            assert response.json()["code"] == "INVALID_STATE"

            preview = client.post(
                f"/v1/workspaces/{workspace_id}/proposals/preview",
                json=_proposal_body(consultation_id),
                headers=_bearer("owner"),
            )
            assert preview.status_code == 409
            assert preview.json()["code"] == "INVALID_STATE"


def test_preview_validates_without_persisting():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Preview Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )

            preview = client.post(
                f"/v1/workspaces/{workspace_id}/proposals/preview",
                json=_proposal_body(
                    consultation_id,
                    checklist=[{"text": "Add streaming writer"}],
                ),
                headers=_bearer("owner"),
            )
            assert preview.status_code == 200, preview.text
            body = preview.json()
            assert body["status"] == "draft"
            assert body["version"] == 1
            assert body["consultation_id"] == consultation_id
            assert body["checklist"][0]["text"] == "Add streaming writer"
            assert body["checklist"][0]["item_id"]
            assert preview.headers["ETag"].startswith('"')

            invalid = client.post(
                f"/v1/workspaces/{workspace_id}/proposals/preview",
                json=_proposal_body(consultation_id, category="unknown"),
                headers=_bearer("owner"),
            )
            assert invalid.status_code == 400
            assert invalid.json()["code"] == "VALIDATION_ERROR"

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
                "/proposals",
                headers=_bearer("owner"),
            )
            assert listed.json()["items"] == []


def test_edit_appends_revision_and_enforces_concurrency():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Revision Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            created = _create_proposal(
                client, "owner", workspace_id, consultation_id
            )
            proposal_id = created.json()["proposal_id"]
            etag = created.headers["ETag"]
            url = f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}"

            stale = client.patch(
                url,
                json={"title": "Streaming CSV export v2"},
                headers={**_bearer("owner"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412

            updated = client.patch(
                url,
                json={"title": "Streaming CSV export v2"},
                headers={**_bearer("owner"), "If-Match": etag},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["version"] == 2
            assert updated.json()["title"] == "Streaming CSV export v2"

            revisions = client.get(f"{url}/revisions", headers=_bearer("owner"))
            assert revisions.status_code == 200, revisions.text
            versions = [item["version"] for item in revisions.json()["items"]]
            assert versions == [1, 2]

            # An immutable revision keeps the original title.
            assert revisions.json()["items"][0]["snapshot"]["title"] == (
                "Streaming CSV export"
            )

            submitted = client.post(
                f"{url}/submit",
                headers={**_bearer("owner"), "If-Match": updated.headers["ETag"]},
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "in_review"

            frozen = client.patch(
                url,
                json={"title": "Too late to edit"},
                headers=_bearer("owner"),
            )
            assert frozen.status_code == 409
            assert frozen.json()["code"] == "INVALID_STATE"

            resubmit = client.post(f"{url}/submit", headers=_bearer("owner"))
            assert resubmit.status_code == 409


def test_duplicate_creates_independent_copy_and_can_supersede():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Duplicate Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )
            created = _create_proposal(
                client, "owner", workspace_id, consultation_id
            )
            source_id = created.json()["proposal_id"]
            url = f"/v1/workspaces/{workspace_id}/proposals/{source_id}"

            duplicate = client.post(
                f"{url}/duplicate",
                json={"title": "Streaming CSV export (experiment)"},
                headers=_bearer("owner"),
            )
            assert duplicate.status_code == 201, duplicate.text
            copy = duplicate.json()
            assert copy["proposal_id"] != source_id
            assert copy["duplicated_from_proposal_id"] == source_id
            assert copy["version"] == 1
            assert copy["status"] == "draft"

            superseding = client.post(
                f"{url}/duplicate",
                json={"supersede_source": True},
                headers=_bearer("owner"),
            )
            assert superseding.status_code == 201, superseding.text

            source = client.get(url, headers=_bearer("owner"))
            assert source.json()["status"] == "superseded"
            assert (
                source.json()["superseded_by_proposal_id"]
                == superseding.json()["proposal_id"]
            )

            with session_scope(engine) as session:
                for table in ("approvals", "work_items", "board_cards"):
                    assert (
                        session.execute(
                            text(f"SELECT count(*) FROM {table}")
                        ).scalar_one()
                        == 0
                    )


def test_proposal_rbac_and_tenant_isolation():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Roles Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "contrib", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "other", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "view", "viewer")
            _invite_and_accept(client, "owner", workspace_id, "boss", "admin")
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )

            # A viewer may read but not create.
            assert (
                _create_proposal(client, "view", workspace_id, consultation_id).status_code
                == 403
            )
            # A non-member cannot even see the workspace.
            assert (
                _create_proposal(
                    client, "mallory", workspace_id, consultation_id
                ).status_code
                == 404
            )

            created = _create_proposal(
                client, "contrib", workspace_id, consultation_id
            )
            assert created.status_code == 201, created.text
            proposal_id = created.json()["proposal_id"]
            url = f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}"

            # Only the proposer or an administrator may edit or submit.
            assert (
                client.patch(
                    url, json={"title": "Hijacked title"}, headers=_bearer("other")
                ).status_code
                == 403
            )
            assert (
                client.post(f"{url}/submit", headers=_bearer("other")).status_code == 403
            )

            # An administrator can act on any proposal.
            assert (
                client.patch(
                    url, json={"title": "Admin adjusted title"}, headers=_bearer("boss")
                ).status_code
                == 200
            )

            # Read access is still tenant-scoped.
            assert (
                client.get(url, headers=_bearer("mallory")).status_code == 404
            )


def test_proposal_idempotency_and_audit():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Idempotency Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _triaged_consultation(
                client, "owner", workspace_id, project_id
            )

            evidence = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
                "/evidence",
                json={"kind": "text", "content": "Reproduced on the staging build."},
                headers=_bearer("owner"),
            )
            assert evidence.status_code == 201, evidence.text
            evidence_id = evidence.json()["evidence_id"]

            headers = {**_bearer("owner"), "Idempotency-Key": "proposal-key-0001"}
            first = client.post(
                f"/v1/workspaces/{workspace_id}/proposals",
                json=_proposal_body(consultation_id, evidence_ids=[evidence_id]),
                headers=headers,
            )
            assert first.status_code == 201, first.text
            replay = client.post(
                f"/v1/workspaces/{workspace_id}/proposals",
                json=_proposal_body(consultation_id, evidence_ids=[evidence_id]),
                headers=headers,
            )
            assert replay.status_code == 201, replay.text
            assert replay.json()["proposal_id"] == first.json()["proposal_id"]
            assert replay.json()["evidence"] == [evidence_id]

            conflict = client.post(
                f"/v1/workspaces/{workspace_id}/proposals",
                json=_proposal_body(consultation_id, title="Different request body"),
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}"
                "/proposals",
                headers=_bearer("owner"),
            )
            assert len(listed.json()["items"]) == 1

            with session_scope(engine) as session:
                actions = list(
                    session.execute(
                        text(
                            "SELECT action FROM audit_records "
                            "WHERE entity_id = :pid ORDER BY created_at"
                        ),
                        {"pid": first.json()["proposal_id"]},
                    ).scalars()
                )
            assert actions == ["proposal.created"]
