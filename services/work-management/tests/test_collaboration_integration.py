"""HTTP integration tests for entity collaboration (Issue #29).

Comments, generic attachments, and history are exercised through the public
routes for consultations, proposals, work items, and board cards. The tests
cover author derivation, tombstones, idempotency, fail-closed malware scanning,
tenant/role boundaries, append-only history, and database-level comment
immutability. They skip themselves when no test database is configured.
"""

from __future__ import annotations

import base64
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.models import Project, Workspace
from eventflow_work_management.security.attachment_scanner import (
    CLEAN,
    INFECTED,
    StaticMalwareScanner,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from support import (
    create_consultation,
    create_proposal,
    require_database_url,
    session_scope,
    temporary_database,
)

ISSUER = "https://id.example.test/realms/eventflow"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


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


def _bearer(subject: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {subject}", **extra}


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


def _create_board(
    client: TestClient, subject: str, workspace_id: str, project_id: str
) -> str:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/boards",
        json={"project_id": project_id, "name": "Delivery"},
        headers=_bearer(subject, **{"Idempotency-Key": f"board-{uuid4().hex[:12]}"}),
    )
    assert created.status_code == 201, created.text
    return created.json()["board_id"]


def _approved_card(
    client: TestClient,
    owner: str,
    approver: str,
    workspace_id: str,
    project_id: str,
    board_id: str,
) -> dict:
    consultation_id = _create_consultation(client, owner, workspace_id, project_id)
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
            "title": "Streaming CSV export",
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
    return decision.json()["board_card"]


def _comments_url(workspace_id: str, collection: str, entity_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/{collection}/{entity_id}/comments"


def _attachments_url(workspace_id: str, collection: str, entity_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/{collection}/{entity_id}/attachments"


def _history_url(workspace_id: str, collection: str, entity_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/{collection}/{entity_id}/history"


def _post_comment(
    client: TestClient,
    subject: str,
    workspace_id: str,
    collection: str,
    entity_id: str,
    body: str,
    *,
    key: str | None = None,
):
    headers = _bearer(subject)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        _comments_url(workspace_id, collection, entity_id),
        json={"body": body},
        headers=headers,
    )


def _upload(
    client: TestClient,
    subject: str,
    workspace_id: str,
    collection: str,
    entity_id: str,
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
        _attachments_url(workspace_id, collection, entity_id),
        json={
            "file_name": file_name,
            "content_type": content_type,
            "content_base64": base64.b64encode(data).decode("ascii"),
        },
        headers=headers,
    )


def _actions(client: TestClient, subject: str, url: str) -> list[str]:
    response = client.get(url, headers=_bearer(subject))
    assert response.status_code == 200, response.text
    return [item["action"] for item in response.json()["items"]]


def _seed_proposal(engine, workspace_id: str, project_id: str) -> str:
    with session_scope(engine) as session:
        workspace = session.get(Workspace, UUID(workspace_id))
        project = session.get(Project, UUID(project_id))
        assert workspace is not None and project is not None
        consultation = create_consultation(session, workspace, project)
        proposal = create_proposal(session, workspace, project, consultation)
        return str(proposal.id)


def test_comment_lifecycle_tombstone_and_history():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Comment Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )
            owner_id = _principal_id(client, "owner")
            url = _comments_url(workspace_id, "consultations", consultation_id)

            created = _post_comment(
                client,
                "owner",
                workspace_id,
                "consultations",
                consultation_id,
                "  Please include the staging trace.  ",
            )
            assert created.status_code == 201, created.text
            body = created.json()
            comment_id = body["comment_id"]
            assert body["body"] == "Please include the staging trace."
            assert body["author_id"] == owner_id
            assert body["entity_type"] == "consultation"
            assert body["entity_id"] == consultation_id
            assert body["deleted"] is False
            assert created.headers["ETag"].startswith('"')
            assert created.headers["Location"].endswith(f"/comments/{comment_id}")

            fetched = client.get(
                f"{url}/{comment_id}", headers=_bearer("owner")
            )
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["comment_id"] == comment_id

            listed = client.get(url, headers=_bearer("owner"))
            assert listed.status_code == 200, listed.text
            assert [item["comment_id"] for item in listed.json()["items"]] == [
                comment_id
            ]
            assert listed.headers["ETag"].startswith('"')

            assert "comment.created" in _actions(
                client, "owner", _history_url(workspace_id, "consultations", consultation_id)
            )

            deleted = client.delete(
                f"{url}/{comment_id}", headers=_bearer("owner")
            )
            assert deleted.status_code == 204, deleted.text
            again = client.delete(f"{url}/{comment_id}", headers=_bearer("owner"))
            assert again.status_code == 204

            tombstone = client.get(f"{url}/{comment_id}", headers=_bearer("owner"))
            assert tombstone.status_code == 200
            assert tombstone.json()["body"] is None
            assert tombstone.json()["deleted"] is True
            assert tombstone.json()["deleted_at"] is not None
            assert "comment.deleted" in _actions(
                client, "owner", _history_url(workspace_id, "consultations", consultation_id)
            )

            blank = _post_comment(
                client, "owner", workspace_id, "consultations", consultation_id, "   "
            )
            assert blank.status_code == 400, blank.text
            too_long = _post_comment(
                client, "owner", workspace_id, "consultations", consultation_id, "x" * 4001
            )
            assert too_long.status_code == 400
            assert (
                client.get(
                    url, params={"sort": "author_id"}, headers=_bearer("owner")
                ).status_code
                == 400
            )
            assert (
                client.get(
                    url, params={"cursor": "!!not-a-cursor!!"}, headers=_bearer("owner")
                ).status_code
                == 400
            )


def test_comment_idempotency_and_pagination():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Idem Comment Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )

            first = _post_comment(
                client,
                "owner",
                workspace_id,
                "consultations",
                consultation_id,
                "First.",
                key="comment-key-0001",
            )
            assert first.status_code == 201, first.text
            comment_id = first.json()["comment_id"]
            replay = _post_comment(
                client,
                "owner",
                workspace_id,
                "consultations",
                consultation_id,
                "First.",
                key="comment-key-0001",
            )
            assert replay.status_code == 201
            assert replay.json()["comment_id"] == comment_id
            conflict = _post_comment(
                client,
                "owner",
                workspace_id,
                "consultations",
                consultation_id,
                "Different.",
                key="comment-key-0001",
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

            for index in range(2, 4):
                created = _post_comment(
                    client,
                    "owner",
                    workspace_id,
                    "consultations",
                    consultation_id,
                    f"Note {index}.",
                )
                assert created.status_code == 201, created.text

            url = _comments_url(workspace_id, "consultations", consultation_id)
            first_page = client.get(url, params={"limit": 2}, headers=_bearer("owner"))
            assert first_page.status_code == 200, first_page.text
            page = first_page.json()
            assert len(page["items"]) == 2
            assert page["page_info"]["has_more"] is True
            cursor = page["page_info"]["next_cursor"]
            collected = list(page["items"])
            while cursor:
                next_page = client.get(
                    url,
                    params={"limit": 2, "cursor": cursor},
                    headers=_bearer("owner"),
                )
                assert next_page.status_code == 200, next_page.text
                collected.extend(next_page.json()["items"])
                cursor = next_page.json()["page_info"]["next_cursor"]
            assert len(collected) == 3

            newest_first = client.get(
                url, params={"sort": "-created_at"}, headers=_bearer("owner")
            )
            assert newest_first.status_code == 200
            assert newest_first.json()["items"][0]["body"] == "Note 3."


def test_comment_rbac_and_tenant_isolation():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Authz Comment Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "author", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "peer", "contributor")
            _invite_and_accept(client, "owner", workspace_id, "root", "admin")
            _invite_and_accept(client, "owner", workspace_id, "watch", "viewer")
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )
            url = _comments_url(workspace_id, "consultations", consultation_id)

            assert (
                _post_comment(
                    client, "watch", workspace_id, "consultations", consultation_id, "Hi"
                ).status_code
                == 403
            )
            created = _post_comment(
                client, "author", workspace_id, "consultations", consultation_id, "Mine."
            )
            assert created.status_code == 201, created.text
            comment_id = created.json()["comment_id"]
            assert client.get(url, headers=_bearer("watch")).status_code == 200

            assert (
                client.delete(f"{url}/{comment_id}", headers=_bearer("peer")).status_code
                == 403
            )
            assert (
                client.delete(f"{url}/{comment_id}", headers=_bearer("root")).status_code
                == 204
            )

            second = _post_comment(
                client, "author", workspace_id, "consultations", consultation_id, "Mine again."
            )
            assert (
                client.delete(
                    f"{url}/{second.json()['comment_id']}", headers=_bearer("author")
                ).status_code
                == 204
            )

            assert (
                _post_comment(
                    client, "mallory", workspace_id, "consultations", consultation_id, "Hi"
                ).status_code
                == 404
            )
            assert client.get(url, headers=_bearer("mallory")).status_code == 404

            other_workspace = _make_workspace(client, "alice", "Other Comment Co")
            assert (
                client.get(
                    _comments_url(other_workspace, "consultations", consultation_id),
                    headers=_bearer("alice"),
                ).status_code
                == 404
            )
            assert (
                client.get(
                    _comments_url(workspace_id, "widgets", consultation_id),
                    headers=_bearer("owner"),
                ).status_code
                == 404
            )


def test_entity_attachment_scan_lifecycle_on_proposal():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            workspace_id = _make_workspace(client, "owner", "Generic Attach Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "watch", "viewer")
            proposal_id = _seed_proposal(engine, workspace_id, project_id)
            url = _attachments_url(workspace_id, "proposals", proposal_id)

            commented = _post_comment(
                client,
                "owner",
                workspace_id,
                "proposals",
                proposal_id,
                "Check the rollout plan.",
            )
            assert commented.status_code == 201, commented.text
            assert commented.json()["entity_type"] == "proposal"
            assert "comment.created" in _actions(
                client, "owner", _history_url(workspace_id, "proposals", proposal_id)
            )

            assert (
                _upload(
                    client, "watch", workspace_id, "proposals", proposal_id
                ).status_code
                == 403
            )

            uploaded = _upload(
                client,
                "owner",
                workspace_id,
                "proposals",
                proposal_id,
                key="attachment-key-0001",
            )
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            attachment_id = body["attachment_id"]
            assert body["entity_type"] == "proposal"
            assert body["entity_id"] == proposal_id
            assert body["status"] == "available"
            assert body["scan_verdict"] == "clean"
            assert body["size_bytes"] == len(PNG_BYTES)
            assert uploaded.headers["ETag"].startswith('"')

            replay = _upload(
                client,
                "owner",
                workspace_id,
                "proposals",
                proposal_id,
                key="attachment-key-0001",
            )
            assert replay.status_code == 201
            assert replay.json()["attachment_id"] == attachment_id
            conflict = _upload(
                client,
                "owner",
                workspace_id,
                "proposals",
                proposal_id,
                file_name="other.png",
                key="attachment-key-0001",
            )
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

            listed = client.get(url, headers=_bearer("owner"))
            assert listed.status_code == 200, listed.text
            assert [item["attachment_id"] for item in listed.json()["items"]] == [
                attachment_id
            ]

            downloaded = client.get(
                f"{url}/{attachment_id}/content", headers=_bearer("owner")
            )
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.content == PNG_BYTES
            assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
            assert "attachment.uploaded" in _actions(
                client, "owner", _history_url(workspace_id, "proposals", proposal_id)
            )

            bad_base64 = client.post(
                url,
                json={
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "content_base64": "not valid base64!!",
                },
                headers=_bearer("owner"),
            )
            assert bad_base64.status_code == 400, bad_base64.text
            unsupported = client.post(
                url,
                json={
                    "file_name": "archive.zip",
                    "content_type": "application/zip",
                    "content_base64": base64.b64encode(b"PK\x03\x04").decode("ascii"),
                },
                headers=_bearer("owner"),
            )
            assert unsupported.status_code == 422

            deleted = client.delete(
                f"{url}/{attachment_id}", headers=_bearer("owner")
            )
            assert deleted.status_code == 204, deleted.text
            assert (
                client.get(f"{url}/{attachment_id}", headers=_bearer("owner")).status_code
                == 404
            )
            assert "attachment.deleted" in _actions(
                client, "owner", _history_url(workspace_id, "proposals", proposal_id)
            )

            assert (
                client.get(
                    _attachments_url(workspace_id, "proposals", proposal_id),
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )

        with _client(engine, StaticMalwareScanner(INFECTED)) as client:
            rejected = _upload(
                client, "owner", workspace_id, "proposals", proposal_id
            )
            assert rejected.status_code == 201, rejected.text
            assert rejected.json()["status"] == "rejected"
            assert rejected.json()["scan_verdict"] == "infected"
            assert "attachment.rejected" in _actions(
                client, "owner", _history_url(workspace_id, "proposals", proposal_id)
            )

        with _client(engine) as client:
            quarantined = _upload(
                client, "owner", workspace_id, "proposals", proposal_id
            )
            assert quarantined.status_code == 201, quarantined.text
            assert quarantined.json()["status"] == "quarantined"
            blocked = client.get(
                f"{_attachments_url(workspace_id, 'proposals', proposal_id)}"
                f"/{quarantined.json()['attachment_id']}/content",
                headers=_bearer("owner"),
            )
            assert blocked.status_code == 409
            assert blocked.json()["code"] == "ATTACHMENT_QUARANTINED"


def test_comments_and_attachments_on_work_items_and_board_cards():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine, StaticMalwareScanner(CLEAN)) as client:
            owner = f"owner-{uuid4().hex[:8]}"
            approver = f"approver-{uuid4().hex[:8]}"
            workspace_id = _make_workspace(client, owner, "Card Collab Co")
            project_id = _make_project(client, owner, workspace_id)
            _invite_and_accept(client, owner, workspace_id, approver, "approver")
            board_id = _create_board(client, owner, workspace_id, project_id)
            card = _approved_card(
                client, owner, approver, workspace_id, project_id, board_id
            )

            card_comment = _post_comment(
                client,
                owner,
                workspace_id,
                "board-cards",
                card["card_id"],
                "Needs a QA pass before release.",
            )
            assert card_comment.status_code == 201, card_comment.text
            assert card_comment.json()["entity_type"] == "board_card"

            item_comment = _post_comment(
                client,
                owner,
                workspace_id,
                "work-items",
                card["work_item_id"],
                "Implementation started.",
            )
            assert item_comment.status_code == 201, item_comment.text
            assert item_comment.json()["entity_type"] == "work_item"

            uploaded = _upload(
                client, owner, workspace_id, "work-items", card["work_item_id"]
            )
            assert uploaded.status_code == 201, uploaded.text

            listed = client.get(
                _comments_url(workspace_id, "board-cards", card["card_id"]),
                headers=_bearer(owner),
            )
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["items"]) == 1

            history_actions = _actions(
                client,
                owner,
                _history_url(workspace_id, "work-items", card["work_item_id"]),
            )
            assert "comment.created" in history_actions
            assert "attachment.uploaded" in history_actions

            other_workspace = _make_workspace(client, "alice", "Other Card Co")
            assert (
                client.get(
                    _comments_url(other_workspace, "board-cards", card["card_id"]),
                    headers=_bearer("alice"),
                ).status_code
                == 404
            )


def test_comment_body_is_immutable_at_the_database_level():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Immutable Co")
            project_id = _make_project(client, "owner", workspace_id)
            consultation_id = _create_consultation(
                client, "owner", workspace_id, project_id
            )
            created = _post_comment(
                client, "owner", workspace_id, "consultations", consultation_id, "Original."
            )
            assert created.status_code == 201, created.text
            comment_id = created.json()["comment_id"]

        def fails(statement: str) -> bool:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text(statement), {"id": comment_id})
                except DBAPIError:
                    return True
                finally:
                    transaction.rollback()
            return False

        assert fails("UPDATE entity_comments SET body = 'tampered' WHERE id = :id")
        assert fails(
            "UPDATE entity_comments SET author_id = gen_random_uuid() WHERE id = :id"
        )
        assert fails("DELETE FROM entity_comments WHERE id = :id")

        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("TRUNCATE entity_comments"))
                truncated = False
            except DBAPIError:
                truncated = True
            finally:
                transaction.rollback()
        assert truncated

        with session_scope(engine) as session:
            body = session.execute(
                text("SELECT body FROM entity_comments WHERE id = :id"),
                {"id": comment_id},
            ).scalar_one()
        assert body == "Original."
