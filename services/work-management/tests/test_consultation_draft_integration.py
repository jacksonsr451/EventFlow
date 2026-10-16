"""HTTP and concurrency integration tests for consultation drafts (Issue #4).

Drafts add a DRAFT consultation status and dedicated create/edit/submit
endpoints on top of the direct-submission intake. The tests exercise the public
contract behaviour: draft creation, author/admin-only editing, the DRAFT->OPEN
submission transition, repeated submission rejection, optimistic concurrency
(If-Match), idempotent replay, and authorization/tenant isolation. A service
level concurrency test proves the row lock lets only one concurrent submit win.
They skip themselves when no test database is configured.
"""

from __future__ import annotations

import threading
from uuid import uuid4

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.models import WorkspaceMembership
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.consultation import ConsultationService
from support import (
    create_project,
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


def _bearer(subject: str) -> dict:
    return {"Authorization": f"Bearer {subject}"}


def _client(engine) -> TestClient:
    app = create_app(
        settings=_settings(),
        session_factory_override=session_factory(engine),
        oidc_client=FakeOIDC(),
    )
    return TestClient(app)


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


def _create_draft(client: TestClient, subject: str, workspace_id: str, project_id: str, **extra):
    payload = {
        "project_id": project_id,
        "origin": "vscode",
        "title": "Draft null pointer on empty cart",
        "description": "Submitting an empty cart returns 500 instead of 400.",
    }
    payload.update(extra)
    return client.post(
        f"/v1/workspaces/{workspace_id}/consultations/drafts",
        json=payload,
        headers=_bearer(subject),
    )


def _triage_body():
    return {
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


def test_draft_is_not_triageable_until_submitted():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "alice", "Draft Co")
            project_id = _make_project(client, "alice", workspace_id)

            created = _create_draft(
                client, "alice", workspace_id, project_id, origin="web", category="bug"
            )
            assert created.status_code == 201, created.text
            body = created.json()
            consultation_id = body["consultation_id"]
            assert body["status"] == "draft"
            assert body["priority"] == "medium"
            assert body["category"] == "bug"
            assert created.headers["ETag"].startswith('"')
            assert created.headers["Location"].endswith(consultation_id)

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations", headers=_bearer("alice")
            )
            assert listed.status_code == 200
            assert [item["status"] for item in listed.json()["items"]] == ["draft"]

            triage_blocked = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=_triage_body(),
                headers=_bearer("alice"),
            )
            assert triage_blocked.status_code == 409
            assert triage_blocked.json()["code"] == "INVALID_STATE"

            submitted = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=_bearer("alice"),
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "open"
            assert submitted.headers["ETag"] != created.headers["ETag"]

            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=_triage_body(),
                headers={**_bearer("alice"), "If-Match": submitted.headers["ETag"]},
            )
            assert triaged.status_code == 200, triaged.text
            assert triaged.json()["status"] == "triaging"

            # A submitted consultation is no longer a draft.
            repeated = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=_bearer("alice"),
            )
            assert repeated.status_code == 409
            assert repeated.json()["code"] == "INVALID_STATE"


def test_update_draft_partial_clear_and_optimistic_lock():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "alice", "Edit Co")
            project_id = _make_project(client, "alice", workspace_id)

            created = _create_draft(
                client, "alice", workspace_id, project_id, category="bug"
            )
            assert created.status_code == 201, created.text
            consultation_id = created.json()["consultation_id"]
            etag = created.headers["ETag"]

            updated = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"title": "Edited draft title", "description": "Edited description body."},
                headers={**_bearer("alice"), "If-Match": etag},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["title"] == "Edited draft title"
            assert updated.headers["ETag"] != etag
            new_etag = updated.headers["ETag"]

            stale = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"title": "Stale write"},
                headers={**_bearer("alice"), "If-Match": etag},
            )
            assert stale.status_code == 412

            cleared = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"category": None},
                headers={**_bearer("alice"), "If-Match": new_etag},
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["category"] is None

            empty = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={},
                headers=_bearer("alice"),
            )
            assert empty.status_code == 400

            client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=_bearer("alice"),
            )
            after_submit = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"title": "Too late to edit"},
                headers=_bearer("alice"),
            )
            assert after_submit.status_code == 409
            assert after_submit.json()["code"] == "INVALID_STATE"


def test_draft_editing_is_author_or_admin_only_and_tenant_isolated():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Draft Authz")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "author", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "peer", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "root", "admin")
            _invite_and_accept(client, "owner", workspace_id, "watch", "viewer")

            created = _create_draft(client, "author", workspace_id, project_id)
            assert created.status_code == 201, created.text
            consultation_id = created.json()["consultation_id"]

            # A different contributor in the same workspace may not edit the draft.
            peer_edit = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"title": "Peer tampering"},
                headers=_bearer("peer"),
            )
            assert peer_edit.status_code == 403
            peer_submit = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=_bearer("peer"),
            )
            assert peer_submit.status_code == 403

            # A viewer cannot create a draft at all.
            assert _create_draft(client, "watch", workspace_id, project_id).status_code == 403

            # A non-member cannot see or mutate the draft.
            assert (
                client.patch(
                    f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                    json={"title": "Intruder"},
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )

            # A workspace admin may edit and submit the draft.
            admin_edit = client.patch(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}",
                json={"title": "Admin edit"},
                headers=_bearer("root"),
            )
            assert admin_edit.status_code == 200, admin_edit.text
            admin_submit = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=_bearer("root"),
            )
            assert admin_submit.status_code == 200, admin_submit.text
            assert admin_submit.json()["status"] == "open"


def test_draft_idempotent_replay_and_conflict():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "alice", "Draft Idem")
            project_id = _make_project(client, "alice", workspace_id)

            headers = {**_bearer("alice"), "Idempotency-Key": "draft-key-0001"}
            payload = {
                "project_id": project_id,
                "origin": "desktop",
                "title": "Offline draft",
                "description": "Persisted from the desktop offline queue.",
            }
            first = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/drafts",
                json=payload,
                headers=headers,
            )
            assert first.status_code == 201, first.text
            consultation_id = first.json()["consultation_id"]

            replay = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/drafts",
                json=payload,
                headers=headers,
            )
            assert replay.status_code == 201
            assert replay.json()["consultation_id"] == consultation_id

            conflict = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/drafts",
                json={**payload, "title": "Different payload"},
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.headers["content-type"] == "application/problem+json"

            submit_headers = {**_bearer("alice"), "Idempotency-Key": "draft-key-0002"}
            submitted = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=submit_headers,
            )
            assert submitted.status_code == 200, submitted.text
            submit_replay = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/submit",
                headers=submit_headers,
            )
            assert submit_replay.status_code == 200
            assert submit_replay.json()["status"] == "open"

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/consultations", headers=_bearer("alice")
            )
            assert len(listed.json()["items"]) == 1


def _service_context(workspace, author_id):
    membership = WorkspaceMembership(
        workspace_id=workspace.id, user_id=author_id, role="contributor"
    )
    principal = AuthenticatedPrincipal(
        user_id=author_id, issuer=ISSUER, subject="author"
    )
    return AuthorizationContext(
        principal=principal, workspace=workspace, membership=membership
    )


def test_concurrent_submit_allows_exactly_one_transition():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine:
        with session_scope(engine) as setup_session:
            workspace = create_workspace(setup_session)
            project = create_project(setup_session, workspace)
            author_id = uuid4()
            context = _service_context(workspace, author_id)
            draft = ConsultationService(setup_session).create_draft(
                context,
                project_id=project.id,
                origin="web",
                title="Concurrent draft",
                description="A draft submitted from two clients at once.",
            ).consultation
            draft_id = draft.id

        barrier = threading.Barrier(2)
        successes: list = []
        errors: list[Exception] = []

        def worker():
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    result = ConsultationService(session).submit_draft(
                        context, draft_id
                    )
                    successes.append(result)
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(successes) == 1, f"expected one winner, got {len(successes)}: {errors}"
        assert len(errors) == 1
        assert isinstance(errors[0], ProblemError)
        assert errors[0].code == "INVALID_STATE"

        with session_scope(engine) as session:
            persisted = ConsultationService(session).get(context, draft_id)
            assert persisted.status == "open"
