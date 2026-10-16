"""HTTP integration tests for consultation attachments, evidence, history (Issue #4).

These tests exercise the public contract of the multisource intake evidence
pipeline: hostile uploads fail closed, the content-type allowlist and size limit
are enforced on decoded bytes, quarantined bytes can never be downloaded or cited
as evidence, tenant/role boundaries hold, and the append-only audit trail is
projected back as a paginated consultation history. They skip themselves when no
test database is configured.
"""

from __future__ import annotations

import base64
from uuid import uuid4

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.security.attachment_scanner import (
    CLEAN,
    INFECTED,
    StaticMalwareScanner,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from support import require_database_url, temporary_database

ISSUER = "https://id.example.test/realms/eventflow"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TEXT_BYTES = b"hello world"


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


def _client(engine, scanner=None) -> TestClient:
    app = create_app(
        settings=_settings(),
        session_factory_override=session_factory(engine),
        oidc_client=FakeOIDC(),
        malware_scanner=scanner,
    )
    return TestClient(app)


def _principal_id(client: TestClient, subject: str) -> str:
    response = client.get("/v1/auth/principal", headers=_bearer(subject))
    assert response.status_code == 200, response.text
    return response.json()["user_id"]


def _make_workspace(client: TestClient, subject: str, name: str) -> str:
    created = client.post(
        "/v1/workspaces",
        json={"name": name, "slug": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}"},
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


def _create_consultation(
    client: TestClient, subject: str, workspace_id: str, project_id: str
) -> str:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json={
            "project_id": project_id,
            "origin": "web",
            "title": "Export button crashes the dashboard",
            "description": "Clicking export raises an unhandled 500 error.",
        },
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    return created.json()["consultation_id"]


def _attachments_url(workspace_id: str, consultation_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/attachments"


def _upload(
    client: TestClient,
    subject: str,
    workspace_id: str,
    consultation_id: str,
    *,
    file_name: str = "diagram.png",
    content_type: str = "image/png",
    data: bytes = PNG_BYTES,
    key: str | None = None,
):
    headers = _bearer(subject)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        _attachments_url(workspace_id, consultation_id),
        json={
            "file_name": file_name,
            "content_type": content_type,
            "content_base64": base64.b64encode(data).decode("ascii"),
        },
        headers=headers,
    )


def _evidence_url(workspace_id: str, consultation_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/evidence"


def test_attachment_clean_upload_download_and_delete():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "alice", "Attach Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            uploaded = _upload(client, "alice", workspace_id, consultation_id)
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            attachment_id = body["attachment_id"]
            assert body["status"] == "available"
            assert body["scan_verdict"] == "clean"
            assert body["rejection_reason"] is None
            assert body["content_type"] == "image/png"
            assert body["size_bytes"] == len(PNG_BYTES)
            assert uploaded.headers["ETag"].startswith('"')
            assert uploaded.headers["Location"].endswith(f"/attachments/{attachment_id}")

            listed = client.get(
                _attachments_url(workspace_id, consultation_id), headers=_bearer("alice")
            )
            assert listed.status_code == 200, listed.text
            assert [item["attachment_id"] for item in listed.json()["items"]] == [
                attachment_id
            ]
            assert listed.headers["ETag"].startswith('"')

            fetched = client.get(
                f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}",
                headers=_bearer("alice"),
            )
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["status"] == "available"

            downloaded = client.get(
                f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}/content",
                headers=_bearer("alice"),
            )
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.content == PNG_BYTES
            assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
            assert downloaded.headers["Content-Disposition"].startswith("attachment;")

            deleted = client.delete(
                f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}",
                headers=_bearer("alice"),
            )
            assert deleted.status_code == 204, deleted.text

            gone = client.get(
                f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}",
                headers=_bearer("alice"),
            )
            assert gone.status_code == 404
            assert (
                client.get(
                    f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}/content",
                    headers=_bearer("alice"),
                ).status_code
                == 404
            )


def test_attachment_fails_closed_without_a_scanner():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "alice", "Quarantine Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            uploaded = _upload(client, "alice", workspace_id, consultation_id)
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            assert body["status"] == "quarantined"
            assert body["scan_verdict"] == "unknown"

            blocked = client.get(
                f"{_attachments_url(workspace_id, consultation_id)}"
                f"/{body['attachment_id']}/content",
                headers=_bearer("alice"),
            )
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "ATTACHMENT_QUARANTINED"


def test_infected_attachment_is_rejected_and_never_stored():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(INFECTED)) as client:
            workspace_id = _make_workspace(client, "alice", "Malware Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            uploaded = _upload(client, "alice", workspace_id, consultation_id)
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            assert body["status"] == "rejected"
            assert body["scan_verdict"] == "infected"
            assert body["rejection_reason"] == "malware_detected"

            blocked = client.get(
                f"{_attachments_url(workspace_id, consultation_id)}"
                f"/{body['attachment_id']}/content",
                headers=_bearer("alice"),
            )
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "ATTACHMENT_QUARANTINED"


def test_attachment_validation_rejects_bad_input():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "alice", "Validate Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )
            url = _attachments_url(workspace_id, consultation_id)

            def post(payload):
                return client.post(url, json=payload, headers=_bearer("alice"))

            bad_base64 = post(
                {
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "content_base64": "not valid base64!!",
                }
            )
            assert bad_base64.status_code == 400, bad_base64.text
            assert bad_base64.headers["content-type"] == "application/problem+json"

            unsupported = post(
                {
                    "file_name": "archive.zip",
                    "content_type": "application/zip",
                    "content_base64": base64.b64encode(b"PK\x03\x04").decode("ascii"),
                }
            )
            assert unsupported.status_code == 422

            svg = post(
                {
                    "file_name": "evil.svg",
                    "content_type": "image/svg+xml",
                    "content_base64": base64.b64encode(b"<svg/>").decode("ascii"),
                }
            )
            assert svg.status_code == 422

            mismatch = post(
                {
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(TEXT_BYTES).decode("ascii"),
                }
            )
            assert mismatch.status_code == 422

            traversal = post(
                {
                    "file_name": "../etc/passwd",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
                }
            )
            assert traversal.status_code == 422

            empty = post(
                {
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "content_base64": "",
                }
            )
            assert empty.status_code == 400

            oversize = post(
                {
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(
                        b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1)
                    ).decode("ascii"),
                }
            )
            assert oversize.status_code == 422

            listed = client.get(url, headers=_bearer("alice"))
            assert listed.json()["items"] == []


def test_attachment_quota_is_enforced():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "alice", "Quota Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            for index in range(25):
                response = _upload(
                    client,
                    "alice",
                    workspace_id,
                    consultation_id,
                    file_name=f"file-{index}.png",
                )
                assert response.status_code == 201, response.text

            overflow = _upload(
                client, "alice", workspace_id, consultation_id, file_name="one-too-many.png"
            )
            assert overflow.status_code == 409
            assert overflow.json()["code"] == "ATTACHMENT_LIMIT_REACHED"


def test_evidence_kinds_and_attachment_reference():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "alice", "Evidence Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )
            url = _evidence_url(workspace_id, consultation_id)

            text = client.post(
                url,
                json={"kind": "text", "content": "Reproduced on the staging build."},
                headers=_bearer("alice"),
            )
            assert text.status_code == 201, text.text
            assert text.json()["kind"] == "text"

            link = client.post(
                url,
                json={
                    "kind": "link",
                    "content": "https://logs.example.test/trace/12345",
                    "description": "Server trace",
                },
                headers=_bearer("alice"),
            )
            assert link.status_code == 201, link.text
            assert link.json()["kind"] == "link"

            attachment_id = _upload(
                client, "alice", workspace_id, consultation_id
            ).json()["attachment_id"]
            attached = client.post(
                url,
                json={"kind": "attachment", "attachment_id": attachment_id},
                headers=_bearer("alice"),
            )
            assert attached.status_code == 201, attached.text
            assert attached.json()["attachment_id"] == attachment_id

            listed = client.get(url, headers=_bearer("alice"))
            assert listed.status_code == 200
            assert [item["kind"] for item in listed.json()["items"]] == [
                "text",
                "link",
                "attachment",
            ]

            missing = client.post(
                url,
                json={"kind": "attachment", "attachment_id": str(uuid4())},
                headers=_bearer("alice"),
            )
            assert missing.status_code == 404

            assert (
                client.post(
                    url, json={"kind": "text"}, headers=_bearer("alice")
                ).status_code
                == 422
            )
            assert (
                client.post(
                    url, json={"kind": "attachment"}, headers=_bearer("alice")
                ).status_code
                == 422
            )
            assert (
                client.post(
                    url,
                    json={
                        "kind": "text",
                        "content": "x",
                        "attachment_id": attachment_id,
                    },
                    headers=_bearer("alice"),
                ).status_code
                == 422
            )


def test_evidence_cannot_cite_quarantined_attachment():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "alice", "Cite Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            attachment_id = _upload(
                client, "alice", workspace_id, consultation_id
            ).json()["attachment_id"]
            cited = client.post(
                _evidence_url(workspace_id, consultation_id),
                json={"kind": "attachment", "attachment_id": attachment_id},
                headers=_bearer("alice"),
            )
            assert cited.status_code == 409
            assert cited.json()["code"] == "INVALID_STATE"


def test_attachment_and_evidence_idempotency():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "alice", "Idem Co")
            project_id = _make_project(client, "alice", workspace_id)
            consultation_id = _create_consultation(
                client, "alice", workspace_id, project_id
            )

            first = _upload(
                client, "alice", workspace_id, consultation_id, key="upload-key-0001"
            )
            assert first.status_code == 201, first.text
            attachment_id = first.json()["attachment_id"]

            replay = _upload(
                client, "alice", workspace_id, consultation_id, key="upload-key-0001"
            )
            assert replay.status_code == 201
            assert replay.json()["attachment_id"] == attachment_id

            conflict = _upload(
                client,
                "alice",
                workspace_id,
                consultation_id,
                file_name="different.png",
                key="upload-key-0001",
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

            evidence_url = _evidence_url(workspace_id, consultation_id)
            evidence_headers = {**_bearer("alice"), "Idempotency-Key": "evidence-key-0001"}
            created = client.post(
                evidence_url,
                json={"kind": "text", "content": "First and only."},
                headers=evidence_headers,
            )
            assert created.status_code == 201, created.text
            evidence_id = created.json()["evidence_id"]
            evidence_replay = client.post(
                evidence_url,
                json={"kind": "text", "content": "First and only."},
                headers=evidence_headers,
            )
            assert evidence_replay.status_code == 201
            assert evidence_replay.json()["evidence_id"] == evidence_id

            assert len(client.get(evidence_url, headers=_bearer("alice")).json()["items"]) == 1


def test_attachment_rbac_and_tenant_isolation():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "owner", "Authz Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "author", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "peer", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "root", "admin")
            _invite_and_accept(client, "owner", workspace_id, "watch", "viewer")
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )

            assert (
                _upload(client, "watch", workspace_id, consultation_id).status_code == 403
            )

            uploaded = _upload(client, "author", workspace_id, consultation_id)
            assert uploaded.status_code == 201, uploaded.text
            attachment_id = uploaded.json()["attachment_id"]

            assert (
                client.get(
                    _attachments_url(workspace_id, consultation_id),
                    headers=_bearer("watch"),
                ).status_code
                == 200
            )

            assert (
                client.get(
                    _attachments_url(workspace_id, consultation_id),
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )
            assert (
                _upload(client, "mallory", workspace_id, consultation_id).status_code
                == 404
            )

            url = f"{_attachments_url(workspace_id, consultation_id)}/{attachment_id}"
            assert client.delete(url, headers=_bearer("peer")).status_code == 403
            assert client.delete(url, headers=_bearer("author")).status_code == 204

            second = _upload(client, "author", workspace_id, consultation_id)
            second_id = second.json()["attachment_id"]
            second_url = (
                f"{_attachments_url(workspace_id, consultation_id)}/{second_id}"
            )
            assert client.delete(second_url, headers=_bearer("root")).status_code == 204

            other_workspace = _make_workspace(client, "alice", "Other Co")
            assert (
                client.get(
                    _attachments_url(other_workspace, consultation_id),
                    headers=_bearer("alice"),
                ).status_code
                == 404
            )


def test_consultation_history_is_paginated_and_audited():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "owner", "History Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )

            for index in range(3):
                _upload(
                    client,
                    "owner",
                    workspace_id,
                    consultation_id,
                    file_name=f"shot-{index}.png",
                )
            client.post(
                _evidence_url(workspace_id, consultation_id),
                json={"kind": "text", "content": "Noted."},
                headers=_bearer("owner"),
            )

            history_url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/history"
            )
            first_page = client.get(
                history_url, params={"limit": 2}, headers=_bearer("owner")
            )
            assert first_page.status_code == 200, first_page.text
            body = first_page.json()
            assert len(body["items"]) == 2
            assert body["page_info"]["has_more"] is True
            cursor = body["page_info"]["next_cursor"]
            assert cursor

            collected = list(body["items"])
            while cursor:
                page = client.get(
                    history_url,
                    params={"limit": 2, "cursor": cursor},
                    headers=_bearer("owner"),
                )
                assert page.status_code == 200, page.text
                collected.extend(page.json()["items"])
                cursor = page.json()["page_info"]["next_cursor"]

            actions = [item["action"] for item in collected]
            assert actions.count("attachment.uploaded") == 3
            assert "evidence.added" in actions

            invalid = client.get(
                history_url, params={"cursor": "!!not-a-cursor!!"}, headers=_bearer("owner")
            )
            assert invalid.status_code == 400

            assert (
                client.get(history_url, headers=_bearer("mallory")).status_code == 404
            )


def test_rejected_upload_is_recorded_in_history():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(INFECTED)) as client:
            workspace_id = _make_workspace(client, "owner", "Reject Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )

            _upload(client, "owner", workspace_id, consultation_id)
            history = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/history",
                headers=_bearer("owner"),
            )
            assert history.status_code == 200, history.text
            actions = [item["action"] for item in history.json()["items"]]
            assert "attachment.rejected" in actions
