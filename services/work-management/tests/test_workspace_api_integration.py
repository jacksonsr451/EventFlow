"""HTTP integration tests for the workspace administration API (Issue #9).

The app is built against a throwaway migrated database and a deterministic
authentication stub that maps an opaque bearer token to an internal identity.
The tests exercise the public contract behaviour: ETag/If-Match, non-disclosive
404s for non-members, role-gated writes, and identity-bound invitation
acceptance. They skip themselves when no test database is configured.
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


def test_workspace_isolation_and_etag_enforcement():
    with temporary_database(require_database_url()) as (_, engine):
        settings = _settings()
        app = create_app(
            settings=settings,
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            created = client.post(
                "/v1/workspaces",
                json={"name": "Acme Inc", "slug": "acme-api"},
                headers=_bearer("alice"),
            )
            assert created.status_code == 201, created.text
            workspace_id = created.json()["workspace_id"]
            etag = created.headers["ETag"]

            assert client.get(f"/v1/workspaces/{workspace_id}").status_code == 401

            listed = client.get("/v1/workspaces", headers=_bearer("alice"))
            assert [row["workspace_id"] for row in listed.json()] == [workspace_id]

            # A non-member must not be able to distinguish "exists" from "foreign".
            assert (
                client.get(
                    f"/v1/workspaces/{workspace_id}", headers=_bearer("bob")
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/v1/workspaces/{workspace_id}/projects",
                    json={"key": "DEMO", "name": "Demo Project"},
                    headers=_bearer("bob"),
                ).status_code
                == 404
            )

            # A stale If-Match validator yields 412.
            stale = client.patch(
                f"/v1/workspaces/{workspace_id}",
                json={"name": "Acme Renamed"},
                headers={**_bearer("alice"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412

            ok = client.patch(
                f"/v1/workspaces/{workspace_id}",
                json={"name": "Acme Renamed"},
                headers={**_bearer("alice"), "If-Match": etag},
            )
            assert ok.status_code == 200
            assert ok.headers["ETag"] != etag


def test_role_gating_and_invitation_acceptance_over_http():
    with temporary_database(require_database_url()) as (_, engine):
        settings = _settings()
        app = create_app(
            settings=settings,
            session_factory_override=session_factory(engine),
            oidc_client=FakeOIDC(),
        )
        with TestClient(app) as client:
            workspace_id = client.post(
                "/v1/workspaces",
                json={"name": "Beta Co", "slug": "beta-api"},
                headers=_bearer("owner"),
            ).json()["workspace_id"]
            bob_id = _principal_id(client, "bob")

            invitation = client.post(
                f"/v1/workspaces/{workspace_id}/invitations",
                json={"invited_user_id": bob_id, "role": "contributor"},
                headers=_bearer("owner"),
            )
            assert invitation.status_code == 201, invitation.text
            body = invitation.json()
            token = body["token"]
            invitation_id = body["invitation"]["invitation_id"]

            # The wrong identity cannot accept the invitation.
            assert (
                client.post(
                    f"/v1/workspaces/{workspace_id}/invitations/{invitation_id}/accept",
                    json={"token": token},
                    headers=_bearer("carol"),
                ).status_code
                == 404
            )

            accepted = client.post(
                f"/v1/workspaces/{workspace_id}/invitations/{invitation_id}/accept",
                json={"token": token},
                headers=_bearer("bob"),
            )
            assert accepted.status_code == 201, accepted.text
            assert accepted.json()["role"] == "contributor"

            # A contributor may read but not invite.
            assert (
                client.get(
                    f"/v1/workspaces/{workspace_id}", headers=_bearer("bob")
                ).status_code
                == 200
            )
            forbidden = client.post(
                f"/v1/workspaces/{workspace_id}/invitations",
                json={"invited_user_id": bob_id, "role": "viewer"},
                headers=_bearer("bob"),
            )
            assert forbidden.status_code == 403
            assert forbidden.headers["content-type"] == "application/problem+json"
