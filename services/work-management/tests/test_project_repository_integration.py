"""HTTP integration tests for project repository configuration (Issue #44).

The tests cover remote-identity deduplication (independent of URL form),
provider-instance isolation, canonicalization, lifecycle and terminal archive,
optimistic concurrency, idempotency replay/conflict, tenant isolation, RBAC,
audit evidence, database uniqueness, and concurrent duplicate creation. They
skip themselves when no test database is configured.
"""

from __future__ import annotations

import threading
import uuid
from uuid import uuid4

import testrunner
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from eventflow_work_management.api.app import create_app
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.models import WorkspaceMembership
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.project_repository_management import (
    ProjectRepositoryService,
)
from support import (
    create_project,
    create_workspace,
    require_database_url,
    session_scope,
    temporary_database,
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


def _bearer(subject: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {subject}", **extra}


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


def _workspace(client: TestClient, subject: str, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        json={
            "name": name,
            "slug": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}",
        },
        headers=_bearer(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["workspace_id"]


def _project(client: TestClient, subject: str, workspace_id: str) -> str:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/projects",
        json={"key": "PAY", "name": "Payments"},
        headers=_bearer(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _invite(
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


def _repo_path(workspace_id: str, project_id: str) -> str:
    return (
        f"/v1/workspaces/{workspace_id}/projects/{project_id}/repositories"
    )


def _payload(**overrides) -> dict:
    payload = {
        "provider": "github",
        "provider_instance_id": "github.com",
        "remote_repository_id": "123456",
        "repository_url": "https://github.com/acme/payments.git",
    }
    payload.update(overrides)
    return payload


def test_remote_identity_dedup_is_url_and_instance_aware():
    database_url = require_database_url()
    with temporary_database(database_url) as (_, engine):
        client = _client(engine)
        owner = "repo-owner"
        workspace_id = _workspace(client, owner, "Repo Dedup")
        project_id = _project(client, owner, workspace_id)
        path = _repo_path(workspace_id, project_id)

        created = client.post(path, json=_payload(), headers=_bearer(owner))
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["repository_url"] == "https://github.com/acme/payments"
        assert first["repository_full_path"] == "acme/payments"
        assert first["display_name"] == "payments"
        assert first["status"] == "active"
        assert first["verification_status"] == "configured"
        assert created.headers["etag"].startswith('"')

        duplicate = client.post(
            path,
            json=_payload(repository_url="git@github.com:acme/payments.git"),
            headers=_bearer(owner),
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "REPOSITORY_ALREADY_LINKED"

        other_instance = client.post(
            path,
            json=_payload(
                provider_instance_id="github.example.com",
                repository_url="https://github.example.com/acme/payments.git",
            ),
            headers=_bearer(owner),
        )
        assert other_instance.status_code == 201, other_instance.text

        wrong_host = client.post(
            path,
            json=_payload(
                remote_repository_id="999",
                provider_instance_id="gitlab.com",
                repository_url="https://github.com/acme/other.git",
            ),
            headers=_bearer(owner),
        )
        assert wrong_host.status_code == 400
        credentials = client.post(
            path,
            json=_payload(
                remote_repository_id="888",
                repository_url="https://user:secret@github.com/acme/credentials.git",
            ),
            headers=_bearer(owner),
        )
        assert credentials.status_code == 400

        listed = client.get(path, headers=_bearer(owner))
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["items"]) == 2
        assert listed.headers["etag"].startswith('"')

        with session_scope(engine) as session:
            actions = session.execute(
                text(
                    "SELECT action FROM audit_records "
                    "WHERE entity_type = 'project_repository' "
                    "AND entity_id = :entity_id"
                ),
                {"entity_id": first["repository_id"]},
            ).scalars().all()
            assert actions == ["project_repository.linked"]

            with testrunner.raises(IntegrityError):
                session.execute(
                    text(
                        "INSERT INTO project_repositories ("
                        "id, workspace_id, project_id, provider, "
                        "provider_instance_id, remote_repository_id, "
                        "repository_full_path, canonical_repository_url, "
                        "display_name, status, verification_status, version, "
                        "created_by) VALUES ("
                        ":id, :workspace_id, :project_id, 'github', "
                        "'github.com', '123456', 'acme/payments', "
                        "'https://github.com/acme/payments', 'payments', "
                        "'active', 'configured', 1, :created_by)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "created_by": uuid.uuid4(),
                    },
                )
                session.commit()
            session.rollback()


def test_lifecycle_idempotency_tenant_isolation_rbac_and_audit():
    database_url = require_database_url()
    with temporary_database(database_url) as (_, engine):
        client = _client(engine)
        owner = "lifecycle-owner"
        workspace_id = _workspace(client, owner, "Repo Lifecycle")
        project_id = _project(client, owner, workspace_id)
        path = _repo_path(workspace_id, project_id)

        created = client.post(path, json=_payload(), headers=_bearer(owner))
        assert created.status_code == 201, created.text
        repository = created.json()
        repository_id = repository["repository_id"]
        item_path = f"{path}/{repository_id}"

        updated = client.patch(
            item_path,
            json={"display_name": "Payments service"},
            headers={
                **_bearer(owner),
                "If-Match": created.headers["etag"],
                "Idempotency-Key": "repo-update-0001",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["display_name"] == "Payments service"
        assert updated.json()["version"] == 2
        updated_etag = updated.headers["etag"]

        replayed = client.patch(
            item_path,
            json={"display_name": "Payments service"},
            headers={
                **_bearer(owner),
                "If-Match": created.headers["etag"],
                "Idempotency-Key": "repo-update-0001",
            },
        )
        assert replayed.status_code == 200
        assert replayed.json()["repository_id"] == repository_id

        stale = client.patch(
            item_path,
            json={"display_name": "Stale"},
            headers={**_bearer(owner), "If-Match": created.headers["etag"]},
        )
        assert stale.status_code == 412

        deactivated = client.patch(
            item_path,
            json={"status": "inactive"},
            headers={**_bearer(owner), "If-Match": updated_etag},
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["status"] == "inactive"
        assert deactivated.json()["deactivated_at"] is not None
        deactivated_etag = deactivated.headers["etag"]

        archived_via_patch = client.patch(
            item_path,
            json={"status": "archived"},
            headers={**_bearer(owner), "If-Match": deactivated_etag},
        )
        assert archived_via_patch.status_code == 400

        unlinked = client.delete(
            item_path,
            headers={**_bearer(owner), "If-Match": deactivated_etag},
        )
        assert unlinked.status_code == 204, unlinked.text

        fetched = client.get(item_path, headers=_bearer(owner))
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "archived"
        assert fetched.json()["archived_at"] is not None
        assert fetched.json()["deactivated_at"] is None

        repeated_delete = client.delete(item_path, headers=_bearer(owner))
        assert repeated_delete.status_code == 204

        archived_conflict = client.post(
            path, json=_payload(), headers=_bearer(owner)
        )
        assert archived_conflict.status_code == 409
        assert archived_conflict.json()["code"] == "REPOSITORY_ARCHIVED"

        idempotent = client.post(
            path,
            json=_payload(
                remote_repository_id="654321",
                repository_url="https://github.com/acme/reports.git",
            ),
            headers={**_bearer(owner), "Idempotency-Key": "repo-create-0001"},
        )
        assert idempotent.status_code == 201, idempotent.text
        second_id = idempotent.json()["repository_id"]
        replay = client.post(
            path,
            json=_payload(
                remote_repository_id="654321",
                repository_url="https://github.com/acme/reports.git",
            ),
            headers={**_bearer(owner), "Idempotency-Key": "repo-create-0001"},
        )
        assert replay.status_code == 201
        assert replay.json()["repository_id"] == second_id
        conflict = client.post(
            path,
            json=_payload(
                remote_repository_id="777777",
                repository_url="https://github.com/acme/different.git",
            ),
            headers={**_bearer(owner), "Idempotency-Key": "repo-create-0001"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

        _invite(client, owner, workspace_id, "repo-contributor", "contributor")
        _invite(client, owner, workspace_id, "repo-viewer", "viewer")
        contributor_create = client.post(
            path,
            json=_payload(
                remote_repository_id="555555",
                repository_url="https://github.com/acme/denied.git",
            ),
            headers=_bearer("repo-contributor"),
        )
        assert contributor_create.status_code == 403
        assert client.get(item_path, headers=_bearer("repo-viewer")).status_code == 200
        assert (
            client.patch(
                item_path,
                json={"display_name": "Denied"},
                headers=_bearer("repo-viewer"),
            ).status_code
            == 403
        )

        other_workspace = _workspace(client, owner, "Repo Other Tenant")
        other_project = _project(client, owner, other_workspace)
        hidden = client.get(
            f"{_repo_path(other_workspace, other_project)}/{repository_id}",
            headers=_bearer(owner),
        )
        assert hidden.status_code == 404

        with session_scope(engine) as session:
            actions = session.execute(
                text(
                    "SELECT action FROM audit_records "
                    "WHERE entity_type = 'project_repository' "
                    "AND entity_id = :entity_id ORDER BY occurred_at"
                ),
                {"entity_id": repository_id},
            ).scalars().all()
            assert actions == [
                "project_repository.linked",
                "project_repository.updated",
                "project_repository.deactivated",
                "project_repository.unlinked",
            ]
            count = session.execute(
                text(
                    "SELECT count(*) FROM project_repositories "
                    "WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            ).scalar_one()
            assert count == 2


def _service_context(workspace, user_id, role: str = "admin") -> AuthorizationContext:
    membership = WorkspaceMembership(
        workspace_id=workspace.id, user_id=user_id, role=role
    )
    principal = AuthenticatedPrincipal(
        user_id=user_id, issuer=ISSUER, subject=str(user_id)
    )
    return AuthorizationContext(
        principal=principal, workspace=workspace, membership=membership
    )


def test_concurrent_duplicate_create_converges_on_one_row():
    database_url = require_database_url()
    with temporary_database(database_url) as (_, engine):
        with session_scope(engine) as setup_session:
            workspace = create_workspace(setup_session)
            project = create_project(setup_session, workspace)
            actor_id = uuid4()
            context = _service_context(workspace, actor_id)
            workspace_id = workspace.id
            project_id = project.id

        barrier = threading.Barrier(2)
        outcomes: list = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                with session_scope(engine) as session:
                    barrier.wait(timeout=10)
                    outcome = ProjectRepositoryService(session).create(
                        context,
                        project_id,
                        provider="github",
                        provider_instance_id="github.com",
                        remote_repository_id="777777",
                        repository_url="https://github.com/acme/concurrent.git",
                        idempotency_key="repo-concurrent-0001",
                    )
                    outcomes.append(outcome.link.id)
            except Exception as error:  # noqa: BLE001 - asserted below
                errors.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        assert len(outcomes) == 2
        assert len(set(outcomes)) == 1
        with session_scope(engine) as session:
            count = session.execute(
                text(
                    "SELECT count(*) FROM project_repositories "
                    "WHERE workspace_id = :workspace_id AND project_id = :project_id"
                ),
                {"workspace_id": workspace_id, "project_id": project_id},
            ).scalar_one()
            assert count == 1
