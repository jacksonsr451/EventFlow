"""HTTP integration tests for consultation intake, read, and triage (Issue #4).

The app runs against a throwaway migrated database and a deterministic
authentication stub. The tests exercise the public contract behaviour:
workspace-scoped intake from multiple origins, optional initial category,
ETag/Location, optional idempotent replay, cursor pagination and filters,
non-disclosive 404s for non-members, role-gated triage, and optimistic
concurrency. They skip themselves when no test database is configured.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from support import require_database_url, temporary_database

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
        f"/v1/workspaces/{workspace_id}/invitations/{body['invitation']['invitation_id']}/accept",
        json={"token": body["token"]},
        headers=_bearer(invitee),
    )
    assert accepted.status_code == 201, accepted.text


def _submit(client: TestClient, subject: str, workspace_id: str, project_id: str, **extra):
    payload = {
        "project_id": project_id,
        "origin": "vscode",
        "title": "Null pointer on empty cart",
        "description": "Submitting an empty cart returns 500 instead of 400.",
    }
    payload.update(extra)
    return client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json=payload,
        headers=_bearer(subject),
    )


def test_intake_read_list_and_isolation():
    with temporary_database(require_database_url()) as (_, engine):
        app = create_app(
            settings=_settings(),
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = _make_workspace(client, "alice", "Acme Intake")
            project_id = _make_project(client, "alice", workspace_id)

            created = _submit(
                client, "alice", workspace_id, project_id, origin="web", category="bug"
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["status"] == "open"
            assert body["priority"] == "medium"
            assert body["category"] == "bug"
            assert body["author_id"]
            assert created.headers["ETag"].startswith('"')
            assert created.headers["Location"].endswith(body["consultation_id"])

            detail = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{body['consultation_id']}",
                headers=_bearer("alice"),
            )
            assert detail.status_code == 200
            assert detail.headers["ETag"] == created.headers["ETag"]

            # A non-member must not distinguish "exists" from "foreign".
            assert (
                client.get(
                    f"/v1/workspaces/{workspace_id}/consultations/{body['consultation_id']}",
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )
            assert _submit(client, "mallory", workspace_id, project_id).status_code == 404
            assert (
                client.get(
                    f"/v1/workspaces/{workspace_id}/consultations",
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )

            # Every declared client origin is accepted.
            for origin in ("web", "vscode", "desktop", "external"):
                assert (
                    _submit(
                        client, "alice", workspace_id, project_id, origin=origin
                    ).status_code
                    == 201
                )


def test_intake_requires_consent_for_editor_context():
    with temporary_database(require_database_url()) as (_, engine):
        app = create_app(
            settings=_settings(),
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = _make_workspace(client, "alice", "Consent Co")
            project_id = _make_project(client, "alice", workspace_id)

            denied = _submit(
                client,
                "alice",
                workspace_id,
                project_id,
                editor_context={
                    "repository": "github.com/x/y",
                    "branch": "main",
                    "commit_sha": "1670d90",
                    "file_path": "src/a.py",
                    "line_start": 1,
                    "line_end": 2,
                    "consent_granted": False,
                },
            )
            assert denied.status_code == 422

            granted = _submit(
                client,
                "alice",
                workspace_id,
                project_id,
                editor_context={
                    "repository": "github.com/x/y",
                    "branch": "main",
                    "commit_sha": "1670d90",
                    "file_path": "src/a.py",
                    "line_start": 1,
                    "line_end": 2,
                    "consent_granted": True,
                },
            )
            assert granted.status_code == 201, granted.text


def test_idempotent_intake_replays_and_conflicts():
    with temporary_database(require_database_url()) as (_, engine):
        app = create_app(
            settings=_settings(),
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = _make_workspace(client, "alice", "Idem Co")
            project_id = _make_project(client, "alice", workspace_id)

            headers = {**_bearer("alice"), "Idempotency-Key": "intake-key-0001"}
            payload = {
                "project_id": project_id,
                "origin": "desktop",
                "title": "Offline submission",
                "description": "Submitted from the desktop offline queue.",
            }
            first = client.post(
                f"/v1/workspaces/{workspace_id}/consultations",
                json=payload,
                headers=headers,
            )
            assert first.status_code == 201, first.text
            replay = client.post(
                f"/v1/workspaces/{workspace_id}/consultations",
                json=payload,
                headers=headers,
            )
            assert replay.status_code == 201
            assert (
                replay.json()["consultation_id"] == first.json()["consultation_id"]
            )

            conflict = client.post(
                f"/v1/workspaces/{workspace_id}/consultations",
                json={**payload, "title": "Different payload"},
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.headers["content-type"] == "application/problem+json"

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations", headers=_bearer("alice")
            )
            assert listed.json()["page_info"]["has_more"] is False
            assert len(listed.json()["items"]) == 1


def test_list_pagination_and_filters():
    with temporary_database(require_database_url()) as (_, engine):
        app = create_app(
            settings=_settings(),
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = _make_workspace(client, "alice", "Paging Co")
            project_id = _make_project(client, "alice", workspace_id)
            for index in range(3):
                assert (
                    _submit(
                        client,
                        "alice",
                        workspace_id,
                        project_id,
                        title=f"Consultation number {index}",
                        category="bug" if index == 0 else None,
                    ).status_code
                    == 201
                )

            first = client.get(
                f"/v1/workspaces/{workspace_id}/consultations?limit=2",
                headers=_bearer("alice"),
            )
            assert first.status_code == 200
            body = first.json()
            assert len(body["items"]) == 2
            assert body["page_info"]["has_more"] is True
            cursor = body["page_info"]["next_cursor"]
            assert cursor

            second = client.get(
                f"/v1/workspaces/{workspace_id}/consultations?limit=2&cursor={cursor}",
                headers=_bearer("alice"),
            )
            assert second.status_code == 200
            assert len(second.json()["items"]) == 1
            assert second.json()["page_info"]["has_more"] is False

            filtered = client.get(
                f"/v1/workspaces/{workspace_id}/consultations?category=bug",
                headers=_bearer("alice"),
            )
            assert len(filtered.json()["items"]) == 1

            invalid = client.get(
                f"/v1/workspaces/{workspace_id}/consultations?sort=secret",
                headers=_bearer("alice"),
            )
            assert invalid.status_code == 400


def test_triage_is_role_gated_and_optimistic():
    with temporary_database(require_database_url()) as (_, engine):
        app = create_app(
            settings=_settings(),
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = _make_workspace(client, "owner", "Triage Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "contrib", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            created = _submit(client, "contrib", workspace_id, project_id)
            assert created.status_code == 201, created.text
            consultation_id = created.json()["consultation_id"]
            etag = created.headers["ETag"]

            triage_body = {
                "category": "bug",
                "priority": "high",
                "triage_notes": "Reproduced locally against the current build.",
                "bug_criteria": {
                    "expected_behavior": "Returns 400 with a problem document.",
                    "observed_behavior": "Raises an unhandled 500 error.",
                    "reproduction_steps": ["Submit an empty cart payload."],
                    "environment": "Python 3.11",
                    "severity": "high",
                    "is_regression": False,
                },
            }

            # A contributor cannot triage.
            assert (
                client.post(
                    f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                    json=triage_body,
                    headers=_bearer("contrib"),
                ).status_code
                == 403
            )

            # Criteria must match the selected category.
            mismatch = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json={**triage_body, "feature_criteria": {}},
                headers=_bearer("tina"),
            )
            assert mismatch.status_code == 422

            # A stale If-Match validator yields 412.
            stale = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=triage_body,
                headers={**_bearer("tina"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412

            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=triage_body,
                headers={**_bearer("tina"), "If-Match": etag},
            )
            assert triaged.status_code == 200, triaged.text
            assert triaged.json()["status"] == "triaging"
            assert triaged.json()["priority"] == "high"
            assert triaged.headers["ETag"] != etag

            # A consultation already in triage cannot be triaged again.
            again = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=triage_body,
                headers=_bearer("tina"),
            )
            assert again.status_code == 409
            assert again.json()["code"] == "INVALID_STATE"
