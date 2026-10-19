"""HTTP integration tests for priority, SLA, dependencies and notifications.

These tests exercise the Issue #30 behavior end to end against a throwaway
migrated database: the centralized priority matrix and reasoned override, SLA
instances backed by a business calendar with pause/breach evaluation,
acyclic work-item dependencies that block transitions to done, and durable
notifications with preferences, deduplication and delivery retry. They skip
themselves when no test database is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.services.notifications import NotificationDispatcher
from support import (
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


def _client(engine) -> TestClient:
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


def _workspace(client: TestClient, subject: str, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        json={"name": name, "slug": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}"},
        headers=_bearer(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["workspace_id"]


def _project(client: TestClient, subject: str, workspace_id: str) -> str:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/projects",
        json={"key": f"P{uuid4().hex[:4].upper()}", "name": "Payments"},
        headers=_bearer(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _invite(client: TestClient, owner: str, workspace_id: str, invitee: str, role: str) -> None:
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


def _board(
    client: TestClient, subject: str, workspace_id: str, project_id: str
) -> str:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/boards",
        json={
            "project_id": project_id,
            "name": "Delivery",
            "columns": [
                {"key": "ready", "name": "Ready", "mapped_status": "ready"},
                {
                    "key": "in_progress",
                    "name": "In Progress",
                    "mapped_status": "in_progress",
                },
                {
                    "key": "in_review",
                    "name": "In Review",
                    "mapped_status": "in_review",
                },
                {"key": "blocked", "name": "Blocked", "mapped_status": "blocked"},
                {"key": "done", "name": "Done", "mapped_status": "done"},
            ],
        },
        headers={**_bearer(subject), "Idempotency-Key": f"board-{uuid4().hex}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["board_id"]


def _triage_payload(**overrides) -> dict:
    payload = {
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
    }
    payload.update(overrides)
    return payload


def _consultation(
    client: TestClient, subject: str, workspace_id: str, project_id: str, *, triage: dict | None = None
) -> tuple[str, dict | None]:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json={
            "project_id": project_id,
            "origin": "web",
            "title": "Add CSV export",
            "description": "Users need CSV export from the dashboard.",
        },
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    consultation_id = created.json()["consultation_id"]
    if triage is None:
        return consultation_id, None
    triaged = client.post(
        f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
        json=triage,
        headers=_bearer(subject),
    )
    return consultation_id, triaged


def _create_work_item(
    client: TestClient,
    engine,
    *,
    owner: str,
    reviewer: str,
    workspace_id: str,
    project_id: str,
    board_id: str,
    triage: dict | None = None,
) -> dict:
    consultation_id, triaged = _consultation(
        client, owner, workspace_id, project_id, triage=triage or _triage_payload()
    )
    assert triaged is not None and triaged.status_code == 200, triaged.text
    created = client.post(
        f"/v1/workspaces/{workspace_id}/proposals",
        json={
            "consultation_id": consultation_id,
            "title": f"Streaming CSV export {uuid4().hex[:6]}",
            "technical_description": "Implement a streaming CSV export endpoint.",
            "scope": "Dashboard export control and backend endpoint.",
            "justification": "Customers requested CSV export.",
            "acceptance_criteria": ["CSV download works for the current filters"],
            "category": "feature",
            "priority": "medium",
        },
        headers=_bearer(owner),
    )
    assert created.status_code == 201, created.text
    proposal_id = created.json()["proposal_id"]
    submitted = client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit",
        headers={**_bearer(owner), "If-Match": created.headers["ETag"]},
    )
    assert submitted.status_code == 200, submitted.text
    version = submitted.json()["version"]
    decided = client.post(
        f"/v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide",
        json={
            "proposal_version": version,
            "decision": "approved",
            "decision_justification": "Meets every acceptance criterion.",
            "target_board_id": board_id,
        },
        headers={
            **_bearer(reviewer),
            "Idempotency-Key": f"decide-{uuid4().hex}",
        },
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    return {
        "work_item_id": body["work_item"]["work_item_id"],
        "card_id": body["board_card"]["card_id"],
        "project_id": project_id,
    }


def _assign(engine, work_item_id: str, user_id: str) -> None:
    with session_scope(engine) as session:
        session.execute(
            text(
                "UPDATE work_items SET assignee_id = :user_id "
                "WHERE id = :work_item_id"
            ),
            {"user_id": user_id, "work_item_id": work_item_id},
        )
        session.commit()


def _move(
    client: TestClient,
    subject: str,
    workspace_id: str,
    board_id: str,
    card_id: str,
    column: str,
):
    card = client.get(
        f"/v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}",
        headers=_bearer(subject),
    )
    assert card.status_code == 200, card.text
    return client.patch(
        f"/v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}",
        json={"target_column_id": column, "target_rank": "a1"},
        headers={
            **_bearer(subject),
            "If-Match": card.headers["ETag"],
            "Idempotency-Key": f"move-{uuid4().hex}",
        },
    )


def _sla_policy(client: TestClient, owner: str, workspace_id: str, **overrides) -> dict:
    payload = {
        "name": "Delivery targets",
        "response_minutes": 60,
        "resolution_minutes": 240,
        "timezone": "UTC",
        "business_hours": {},
        "holidays": [],
        "pause_statuses": ["blocked"],
        "warning_threshold_percent": 75,
        "activate": True,
    }
    payload.update(overrides)
    response = client.post(
        f"/v1/workspaces/{workspace_id}/sla-policies",
        json=payload,
        headers={**_bearer(owner), "Idempotency-Key": f"sla-{uuid4().hex}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_priority_matrix_triage_rules_and_reasoned_override():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "priority-owner"
            workspace_id = _workspace(client, owner, "Priority Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "priority-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)

            _, missing_reason = _consultation(
                client,
                owner,
                workspace_id,
                project_id,
                triage=_triage_payload(
                    priority="critical",
                    business_impact="low",
                    business_urgency="low",
                ),
            )
            assert missing_reason is not None
            assert missing_reason.status_code == 400, missing_reason.text

            _, triaged = _consultation(
                client,
                owner,
                workspace_id,
                project_id,
                triage=_triage_payload(
                    priority="critical",
                    business_impact="low",
                    business_urgency="low",
                    priority_override_reason="Customer contract requires escalation.",
                ),
            )
            assert triaged is not None and triaged.status_code == 200, triaged.text
            with session_scope(engine) as session:
                stored = session.execute(
                    text(
                        "SELECT priority, business_impact, business_urgency, "
                        "priority_override_reason FROM consultations "
                        "ORDER BY created_at DESC LIMIT 1"
                    )
                ).one()
            assert stored == (
                "critical",
                "low",
                "low",
                "Customer contract requires escalation.",
            )

            item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="priority-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            _assign(engine, item["work_item_id"], _principal_id(client, owner))
            path = (
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{item['work_item_id']}/priority"
            )
            overridden = client.patch(
                path,
                json={
                    "priority": "critical",
                    "reason": "Regulatory deadline moved ahead of schedule.",
                },
                headers={
                    **_bearer(owner),
                    "Idempotency-Key": f"priority-{uuid4().hex}",
                },
            )
            assert overridden.status_code == 200, overridden.text
            body = overridden.json()
            assert body["priority"] == "critical"
            assert body["calculated_priority"] == "medium"
            assert body["priority_override_reason"] == (
                "Regulatory deadline moved ahead of schedule."
            )
            assert overridden.headers["ETag"].startswith('"')

            notifications = client.get(
                f"/v1/workspaces/{workspace_id}/notifications",
                headers=_bearer(owner),
            )
            assert notifications.status_code == 200, notifications.text
            assert any(
                entry["event_type"] == "work_item.priority_overridden"
                for entry in notifications.json()["items"]
            )
            with session_scope(engine) as session:
                actions = session.execute(
                    text(
                        "SELECT action FROM audit_records "
                        "WHERE entity_type = 'work_item' AND entity_id = :id"
                    ),
                    {"id": item["work_item_id"]},
                ).scalars().all()
            assert "work_item.priority_overridden" in actions


def test_sla_instance_uses_calendar_pauses_and_is_breach_idempotent():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "sla-owner"
            workspace_id = _workspace(client, owner, "SLA Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "sla-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            _sla_policy(client, owner, workspace_id)
            item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="sla-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            _assign(engine, item["work_item_id"], _principal_id(client, owner))

            path = (
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{item['work_item_id']}/sla"
            )
            started = client.get(path, headers=_bearer(owner))
            assert started.status_code == 200, started.text
            running = started.json()
            assert running["instance"]["status"] == "running"
            assert running["instance"]["response_due_at"] is not None
            assert running["instance"]["policy_version"] == 1
            assert running["instance"]["policy_snapshot"]["response_minutes"] == 60
            original_due = datetime.fromisoformat(
                running["instance"]["resolution_due_at"]
            )

            blocked = _move(
                client, owner, workspace_id, board_id, item["card_id"], "blocked"
            )
            assert blocked.status_code == 200, blocked.text
            paused = client.get(path, headers=_bearer(owner))
            assert paused.status_code == 200, paused.text
            paused_body = paused.json()
            assert paused_body["instance"]["status"] == "paused"
            assert paused_body["instance"]["next_evaluation_at"] is None
            assert paused_body["pauses"][-1]["ended_at"] is None

            resumed = _move(
                client, owner, workspace_id, board_id, item["card_id"], "in_progress"
            )
            assert resumed.status_code == 200, resumed.text
            after_resume = client.get(path, headers=_bearer(owner))
            assert after_resume.status_code == 200, after_resume.text
            resumed_body = after_resume.json()
            assert resumed_body["instance"]["status"] == "running"
            assert resumed_body["pauses"][-1]["ended_at"] is not None
            assert datetime.fromisoformat(
                resumed_body["instance"]["resolution_due_at"]
            ) >= original_due

            with session_scope(engine) as session:
                session.execute(
                    text(
                        "UPDATE sla_instances SET "
                        "response_due_at = :response, resolution_due_at = :resolution, "
                        "warning_resolution_at = NULL, breach_resolution_at = NULL, "
                        "status = 'running' WHERE work_item_id = :id"
                    ),
                    {
                        "response": datetime.now(UTC) + timedelta(hours=1),
                        "resolution": datetime.now(UTC) - timedelta(minutes=1),
                        "id": item["work_item_id"],
                    },
                )
                session.commit()

            breached = client.get(path, headers=_bearer(owner))
            assert breached.status_code == 200, breached.text
            breached_body = breached.json()
            assert breached_body["instance"]["status"] == "breached"
            assert any(
                event["event_type"] == "breach_resolution"
                for event in breached_body["events"]
            )
            event_count = len(breached_body["events"])
            with session_scope(engine) as session:
                notification_count = session.execute(
                    text(
                        "SELECT count(*) FROM notifications "
                        "WHERE event_type = 'sla.breached'"
                    )
                ).scalar_one()

            again = client.get(path, headers=_bearer(owner))
            assert again.status_code == 200, again.text
            assert len(again.json()["events"]) == event_count
            with session_scope(engine) as session:
                assert session.execute(
                    text(
                        "SELECT count(*) FROM notifications "
                        "WHERE event_type = 'sla.breached'"
                    )
                ).scalar_one() == notification_count

            fulfilled_item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="sla-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            _assign(
                engine, fulfilled_item["work_item_id"], _principal_id(client, owner)
            )
            assert (
                _move(
                    client,
                    owner,
                    workspace_id,
                    board_id,
                    fulfilled_item["card_id"],
                    "in_progress",
                ).status_code
                == 200
            )
            assert (
                _move(
                    client,
                    owner,
                    workspace_id,
                    board_id,
                    fulfilled_item["card_id"],
                    "in_review",
                ).status_code
                == 200
            )
            assert (
                _move(
                    client,
                    owner,
                    workspace_id,
                    board_id,
                    fulfilled_item["card_id"],
                    "done",
                ).status_code
                == 200
            )
            with session_scope(engine) as session:
                fulfilled_notifications = session.execute(
                    text(
                        "SELECT count(*) FROM notifications "
                        "WHERE event_type = 'sla.fulfilled' AND entity_id = :id"
                    ),
                    {"id": fulfilled_item["work_item_id"]},
                ).scalar_one()
            assert fulfilled_notifications == 1


def test_dependencies_reject_cycles_dedupe_and_block_done():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "dep-owner"
            workspace_id = _workspace(client, owner, "Dependency Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "dep-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            first = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="dep-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            second = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="dep-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            owner_id = _principal_id(client, owner)
            _assign(engine, first["work_item_id"], owner_id)
            _assign(engine, second["work_item_id"], owner_id)

            path = (
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{first['work_item_id']}/dependencies"
            )
            created = client.post(
                path,
                json={"blocking_work_item_id": second["work_item_id"]},
                headers={**_bearer(owner), "Idempotency-Key": f"dep-{uuid4().hex}"},
            )
            assert created.status_code == 201, created.text
            dependency_id = created.json()["dependency_id"]
            assert created.headers["ETag"].startswith('"')

            duplicate = client.post(
                path,
                json={"blocking_work_item_id": second["work_item_id"]},
                headers={**_bearer(owner), "Idempotency-Key": f"dep-{uuid4().hex}"},
            )
            assert duplicate.status_code == 201, duplicate.text
            assert duplicate.json()["dependency_id"] == dependency_id

            cycle = client.post(
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{second['work_item_id']}/dependencies",
                json={"blocking_work_item_id": first["work_item_id"]},
                headers={**_bearer(owner), "Idempotency-Key": f"dep-{uuid4().hex}"},
            )
            assert cycle.status_code == 409, cycle.text
            assert cycle.json()["code"] == "DEPENDENCY_CYCLE"

            self_edge = client.post(
                path,
                json={"blocking_work_item_id": first["work_item_id"]},
                headers={**_bearer(owner), "Idempotency-Key": f"dep-{uuid4().hex}"},
            )
            assert self_edge.status_code == 400, self_edge.text

            listed = client.get(path, headers=_bearer(owner))
            assert listed.status_code == 200, listed.text
            assert listed.json()["unresolved_blocker_ids"] == [
                second["work_item_id"]
            ]
            assert len(listed.json()["blockers"]) == 1

            started_first = _move(
                client, owner, workspace_id, board_id, first["card_id"], "in_progress"
            )
            assert started_first.status_code == 200, started_first.text
            reviewed_first = _move(
                client, owner, workspace_id, board_id, first["card_id"], "in_review"
            )
            assert reviewed_first.status_code == 200, reviewed_first.text
            blocked_done = _move(
                client, owner, workspace_id, board_id, first["card_id"], "done"
            )
            assert blocked_done.status_code == 409, blocked_done.text
            assert blocked_done.json()["code"] == "DEPENDENCIES_UNRESOLVED"

            assert (
                _move(
                    client, owner, workspace_id, board_id, second["card_id"], "in_progress"
                ).status_code
                == 200
            )
            assert (
                _move(
                    client, owner, workspace_id, board_id, second["card_id"], "in_review"
                ).status_code
                == 200
            )
            assert (
                _move(client, owner, workspace_id, board_id, second["card_id"], "done")
                .status_code
                == 200
            )
            assert (
                _move(client, owner, workspace_id, board_id, first["card_id"], "done")
                .status_code
                == 200
            )

            removed = client.delete(
                f"{path}/{dependency_id}",
                headers={**_bearer(owner), "Idempotency-Key": f"dep-{uuid4().hex}"},
            )
            assert removed.status_code == 204, removed.text
            empty = client.get(path, headers=_bearer(owner))
            assert empty.json()["blockers"] == []


def test_notification_preferences_read_state_and_delivery_retry():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "notify-owner"
            workspace_id = _workspace(client, owner, "Notify Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "notify-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="notify-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            _assign(engine, item["work_item_id"], _principal_id(client, owner))

            preference = client.put(
                f"/v1/workspaces/{workspace_id}/notification-preferences/"
                "work_item.priority_overridden",
                json={"in_app": False, "email": True},
                headers=_bearer(owner),
            )
            assert preference.status_code == 200, preference.text
            assert preference.json()["email"] is True
            assert preference.headers["ETag"].startswith('"')

            overridden = client.patch(
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{item['work_item_id']}/priority",
                json={"priority": "high", "reason": "Customer escalated the issue."},
                headers={
                    **_bearer(owner),
                    "Idempotency-Key": f"notify-{uuid4().hex}",
                },
            )
            assert overridden.status_code == 200, overridden.text

            listed = client.get(
                f"/v1/workspaces/{workspace_id}/notifications",
                headers=_bearer(owner),
            )
            assert listed.status_code == 200, listed.text
            page = listed.json()
            assert page["unread_count"] >= 1
            notification = next(
                entry
                for entry in page["items"]
                if entry["event_type"] == "work_item.priority_overridden"
            )
            assert notification["read_at"] is None

            with session_scope(engine) as session:
                deliveries = session.execute(
                    text(
                        "SELECT channel, status FROM notification_deliveries "
                        "WHERE notification_id = :id ORDER BY channel"
                    ),
                    {"id": notification["notification_id"]},
                ).all()
            assert deliveries == [("email", "pending")]

            marked = client.patch(
                f"/v1/workspaces/{workspace_id}/notifications/"
                f"{notification['notification_id']}",
                json={"read": True},
                headers=_bearer(owner),
            )
            assert marked.status_code == 200, marked.text
            assert marked.json()["read_at"] is not None
            assert marked.headers["ETag"].startswith('"')

            moment = datetime.now(UTC)
            with session_scope(engine) as session:
                dispatcher = NotificationDispatcher(session)
                assert dispatcher.run_once(now=moment) == 1
                for _ in range(4):
                    moment = moment + timedelta(days=1)
                    dispatcher.run_once(now=moment)
                status = session.execute(
                    text(
                        "SELECT status, attempts, last_error "
                        "FROM notification_deliveries WHERE notification_id = :id"
                    ),
                    {"id": notification["notification_id"]},
                ).one()
            assert status[0] == "exhausted"
            assert status[1] == 5
            assert "no email transport" in status[2]
