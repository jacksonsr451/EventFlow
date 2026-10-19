"""HTTP integration tests for priority, SLA, dependencies and notifications.

These tests exercise the Issue #30 behavior end to end against a throwaway
migrated database: the centralized priority matrix and reasoned override, SLA
instances backed by a business calendar with pause/breach evaluation,
acyclic work-item dependencies that block transitions to done, and durable
notifications with preferences, deduplication and delivery retry. They skip
themselves when no test database is configured.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.repositories.notification_repository import (
    NotificationRepository,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.dependencies import DependencyService
from eventflow_work_management.services.notifications import (
    SECURITY_NOTIFICATION_BODY,
    SECURITY_NOTIFICATION_TITLE,
    NotificationDispatcher,
    NotificationService,
)
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
    proposal_title: str | None = None,
    category: str = "feature",
    priority: str = "medium",
) -> dict:
    consultation_id, triaged = _consultation(
        client, owner, workspace_id, project_id, triage=triage or _triage_payload()
    )
    assert triaged is not None and triaged.status_code == 200, triaged.text
    created = client.post(
        f"/v1/workspaces/{workspace_id}/proposals",
        json={
            "consultation_id": consultation_id,
            "title": proposal_title or f"Streaming CSV export {uuid4().hex[:6]}",
            "technical_description": "Implement a streaming CSV export endpoint.",
            "scope": "Dashboard export control and backend endpoint.",
            "justification": "Customers requested CSV export.",
            "acceptance_criteria": ["CSV download works for the current filters"],
            "category": category,
            "priority": priority,
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


def _run_threads(targets) -> None:
    for thread in targets:
        thread.start()
    for thread in targets:
        thread.join(timeout=30)
        assert not thread.is_alive(), "concurrency test thread did not finish"


def test_notification_emission_concurrent_dedup_converges():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "notify-race-owner"
            workspace_id = _workspace(client, owner, "Notify Race Co")
            recipient_id = _principal_id(client, owner)
            dedup_key = f"concurrent:{uuid4().hex}"
            barrier = threading.Barrier(2)
            local = threading.local()
            original = NotificationRepository.get_by_dedup

            def gated_get_by_dedup(self, *, workspace_id, dedup_key):
                existing = original(
                    self, workspace_id=workspace_id, dedup_key=dedup_key
                )
                if not getattr(local, "waited", False):
                    local.waited = True
                    barrier.wait(timeout=10)
                return existing

            results: list[tuple[str, str]] = []

            def emit_once() -> None:
                try:
                    with session_scope(engine) as session:
                        notification = NotificationService(session).emit(
                            workspace_id=UUID(workspace_id),
                            recipient_id=UUID(recipient_id),
                            event_type="work_item.priority_overridden",
                            entity_type="work_item",
                            entity_id=uuid4(),
                            title="Concurrent notification",
                            body="Two writers must converge to one record.",
                            payload={"work_item_id": str(uuid4())},
                            dedup_key=dedup_key,
                        )
                        session.commit()
                        results.append(("ok", str(notification.id)))
                except Exception as exc:  # pragma: no cover - assertion reports it
                    results.append(("error", repr(exc)))

            NotificationRepository.get_by_dedup = gated_get_by_dedup
            try:
                _run_threads(
                    [threading.Thread(target=emit_once) for _ in range(2)]
                )
            finally:
                NotificationRepository.get_by_dedup = original

            assert [item[0] for item in results] == ["ok", "ok"], results
            assert len({item[1] for item in results}) == 1, results
            with session_scope(engine) as session:
                count = session.execute(
                    text(
                        "SELECT count(*) FROM notifications "
                        "WHERE workspace_id = :workspace_id AND dedup_key = :dedup"
                    ),
                    {"workspace_id": workspace_id, "dedup": dedup_key},
                ).scalar_one()
                deliveries = session.execute(
                    text(
                        "SELECT count(*) FROM notification_deliveries d "
                        "JOIN notifications n ON n.id = d.notification_id "
                        "WHERE n.workspace_id = :workspace_id AND n.dedup_key = :dedup"
                    ),
                    {"workspace_id": workspace_id, "dedup": dedup_key},
                ).scalar_one()
            assert count == 1
            assert deliveries == 1


def test_security_work_item_notifications_are_redacted():
    marker = f"CONFIDENTIAL-{uuid4().hex}"
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "security-notify-owner"
            workspace_id = _workspace(client, owner, "Security Notify Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "security-notify-reviewer", "approver")
            _invite(client, owner, workspace_id, "security-notify-viewer", "viewer")
            board_id = _board(client, owner, workspace_id, project_id)
            security_triage = {
                "category": "security",
                "priority": "high",
                "triage_notes": f"{marker} restricted triage notes.",
                "security_criteria": {
                    "vulnerability_type": f"{marker} SQL injection",
                    "severity_rating": "critical",
                    "confidentiality_level": "restricted",
                    "access_restricted_to": [marker],
                    "safe_evidence_handling": True,
                },
            }
            item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="security-notify-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
                triage=security_triage,
                proposal_title=f"{marker} vulnerability details",
                category="security",
                priority="high",
            )
            viewer_id = _principal_id(client, "security-notify-viewer")
            _assign(engine, item["work_item_id"], viewer_id)

            overridden = client.patch(
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{item['work_item_id']}/priority",
                json={"priority": "critical", "reason": "Security coordination."},
                headers={**_bearer(owner), "Idempotency-Key": f"sec-{uuid4().hex}"},
            )
            assert overridden.status_code == 200, overridden.text

            with session_scope(engine) as session:
                row = session.execute(
                    text(
                        "SELECT title, body, payload::text FROM notifications "
                        "WHERE entity_id = :entity_id "
                        "AND event_type = 'work_item.priority_overridden'"
                    ),
                    {"entity_id": item["work_item_id"]},
                ).one()
            title, body, payload = row
            assert title == SECURITY_NOTIFICATION_TITLE
            assert body == SECURITY_NOTIFICATION_BODY
            assert marker not in title
            assert marker not in body
            assert marker not in payload
            assert '"redacted": true' in payload
            assert item["work_item_id"] in payload

            feature_item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="security-notify-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
                proposal_title=f"{marker} feature title",
            )
            owner_id = _principal_id(client, owner)
            _assign(engine, feature_item["work_item_id"], owner_id)
            feature_override = client.patch(
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{feature_item['work_item_id']}/priority",
                json={"priority": "high", "reason": "Feature escalation."},
                headers={**_bearer(owner), "Idempotency-Key": f"feature-{uuid4().hex}"},
            )
            assert feature_override.status_code == 200, feature_override.text
            with session_scope(engine) as session:
                feature_row = session.execute(
                    text(
                        "SELECT title, body, payload::text FROM notifications "
                        "WHERE entity_id = :entity_id "
                        "AND event_type = 'work_item.priority_overridden'"
                    ),
                    {"entity_id": feature_item["work_item_id"]},
                ).one()
            assert marker in feature_row[0]
            assert marker not in feature_row[1]


def test_concurrent_direct_dependency_writers_reject_cycle():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "dep-race-owner"
            workspace_id = _workspace(client, owner, "Dependency Race Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "dep-race-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            first = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="dep-race-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            second = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="dep-race-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            context = SimpleNamespace(
                workspace_id=UUID(workspace_id),
                actor_id=UUID(_principal_id(client, owner)),
            )
            barrier = threading.Barrier(2)
            results: list[str] = []

            def add_edge(blocking_id: str, blocked_id: str) -> None:
                try:
                    barrier.wait(timeout=10)
                    with session_scope(engine) as session:
                        DependencyService(session).create(
                            context,
                            UUID(blocked_id),
                            blocking_work_item_id=UUID(blocking_id),
                        )
                    results.append("ok")
                except ProblemError as exc:
                    results.append(exc.code)
                except Exception as exc:  # pragma: no cover - assertion reports it
                    results.append(repr(exc))

            _run_threads(
                [
                    threading.Thread(
                        target=add_edge,
                        args=(first["work_item_id"], second["work_item_id"]),
                    ),
                    threading.Thread(
                        target=add_edge,
                        args=(second["work_item_id"], first["work_item_id"]),
                    ),
                ]
            )
            assert sorted(results) == ["DEPENDENCY_CYCLE", "ok"], results
            with session_scope(engine) as session:
                count = session.execute(
                    text(
                        "SELECT count(*) FROM work_item_dependencies "
                        "WHERE workspace_id = :workspace_id"
                    ),
                    {"workspace_id": workspace_id},
                ).scalar_one()
            assert count == 1


def test_concurrent_transitive_dependency_writers_reject_cycle():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "dep-transitive-owner"
            workspace_id = _workspace(client, owner, "Dependency Transitive Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "dep-transitive-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            items = [
                _create_work_item(
                    client,
                    engine,
                    owner=owner,
                    reviewer="dep-transitive-reviewer",
                    workspace_id=workspace_id,
                    project_id=project_id,
                    board_id=board_id,
                )
                for _ in range(3)
            ]
            context = SimpleNamespace(
                workspace_id=UUID(workspace_id),
                actor_id=UUID(_principal_id(client, owner)),
            )
            with session_scope(engine) as session:
                DependencyService(session).create(
                    context,
                    UUID(items[1]["work_item_id"]),
                    blocking_work_item_id=UUID(items[0]["work_item_id"]),
                )

            barrier = threading.Barrier(2)
            results: list[str] = []

            def add_edge(blocking_id: str, blocked_id: str) -> None:
                try:
                    barrier.wait(timeout=10)
                    with session_scope(engine) as session:
                        DependencyService(session).create(
                            context,
                            UUID(blocked_id),
                            blocking_work_item_id=UUID(blocking_id),
                        )
                    results.append("ok")
                except ProblemError as exc:
                    results.append(exc.code)
                except Exception as exc:  # pragma: no cover - assertion reports it
                    results.append(repr(exc))

            _run_threads(
                [
                    threading.Thread(
                        target=add_edge,
                        args=(items[1]["work_item_id"], items[2]["work_item_id"]),
                    ),
                    threading.Thread(
                        target=add_edge,
                        args=(items[2]["work_item_id"], items[0]["work_item_id"]),
                    ),
                ]
            )
            assert sorted(results) == ["DEPENDENCY_CYCLE", "ok"], results
            with session_scope(engine) as session:
                count = session.execute(
                    text(
                        "SELECT count(*) FROM work_item_dependencies "
                        "WHERE workspace_id = :workspace_id"
                    ),
                    {"workspace_id": workspace_id},
                ).scalar_one()
            assert count == 2


def test_sla_policy_authorization_and_project_visibility():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "sla-rbac-owner"
            workspace_id = _workspace(client, owner, "SLA RBAC Co")
            project_id = _project(client, owner, workspace_id)
            for subject, role in (
                ("sla-rbac-admin", "admin"),
                ("sla-rbac-triager", "triager"),
                ("sla-rbac-approver", "approver"),
                ("sla-rbac-contributor", "contributor"),
                ("sla-rbac-viewer", "viewer"),
            ):
                _invite(client, owner, workspace_id, subject, role)

            admin_policy = _sla_policy(
                client, "sla-rbac-admin", workspace_id, name="Admin owned", activate=False
            )
            assert admin_policy["status"] == "draft"
            for subject in (
                "sla-rbac-triager",
                "sla-rbac-approver",
                "sla-rbac-contributor",
                "sla-rbac-viewer",
            ):
                forbidden = client.post(
                    f"/v1/workspaces/{workspace_id}/sla-policies",
                    json={
                        "name": f"Forbidden {subject}",
                        "response_minutes": 60,
                        "resolution_minutes": 120,
                        "timezone": "UTC",
                        "activate": False,
                    },
                    headers={
                        **_bearer(subject),
                        "Idempotency-Key": f"sla-forbidden-{uuid4().hex}",
                    },
                )
                assert forbidden.status_code == 403, forbidden.text

            lifecycle = _sla_policy(
                client, owner, workspace_id, name="Lifecycle", activate=False
            )
            policy_id = lifecycle["policy_id"]
            for subject in (
                "sla-rbac-triager",
                "sla-rbac-approver",
                "sla-rbac-contributor",
                "sla-rbac-viewer",
            ):
                forbidden_version = client.post(
                    f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/versions",
                    json={"response_minutes": 90},
                    headers={
                        **_bearer(subject),
                        "Idempotency-Key": f"sla-version-{uuid4().hex}",
                    },
                )
                assert forbidden_version.status_code == 403, forbidden_version.text
                forbidden_activate = client.post(
                    f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/activate",
                    headers={
                        **_bearer(subject),
                        "Idempotency-Key": f"sla-activate-{uuid4().hex}",
                    },
                )
                assert forbidden_activate.status_code == 403, forbidden_activate.text

            version = client.post(
                f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/versions",
                json={"response_minutes": 90},
                headers={
                    **_bearer("sla-rbac-admin"),
                    "Idempotency-Key": f"sla-version-{uuid4().hex}",
                },
            )
            assert version.status_code == 201, version.text
            activated = client.post(
                f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/activate",
                headers={
                    **_bearer("sla-rbac-admin"),
                    "Idempotency-Key": f"sla-activate-{uuid4().hex}",
                },
            )
            assert activated.status_code == 200, activated.text
            assert activated.json()["status"] == "active"

            other_owner = "sla-rbac-other-owner"
            other_workspace = _workspace(client, other_owner, "SLA Other Co")
            foreign_get = client.get(
                f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}",
                headers=_bearer(other_owner),
            )
            assert foreign_get.status_code == 404, foreign_get.text
            foreign_version = client.post(
                f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/versions",
                json={"response_minutes": 60},
                headers={
                    **_bearer(other_owner),
                    "Idempotency-Key": f"sla-foreign-version-{uuid4().hex}",
                },
            )
            assert foreign_version.status_code == 404, foreign_version.text
            foreign_activate = client.post(
                f"/v1/workspaces/{workspace_id}/sla-policies/{policy_id}/activate",
                headers={
                    **_bearer(other_owner),
                    "Idempotency-Key": f"sla-foreign-activate-{uuid4().hex}",
                },
            )
            assert foreign_activate.status_code == 404, foreign_activate.text

            foreign_project = client.post(
                f"/v1/workspaces/{other_workspace}/sla-policies",
                json={
                    "name": "Foreign project",
                    "project_id": project_id,
                    "response_minutes": 60,
                    "timezone": "UTC",
                },
                headers={
                    **_bearer(other_owner),
                    "Idempotency-Key": f"sla-foreign-project-{uuid4().hex}",
                },
            )
            assert foreign_project.status_code == 404, foreign_project.text
            foreign_list = client.get(
                f"/v1/workspaces/{other_workspace}/sla-policies",
                params={"project_id": project_id},
                headers=_bearer(other_owner),
            )
            assert foreign_list.status_code == 200, foreign_list.text
            assert foreign_list.json()["items"] == []

            scoped = _sla_policy(
                client,
                owner,
                workspace_id,
                name="Project scoped",
                project_id=project_id,
                activate=False,
            )
            assert scoped["project_id"] == project_id
            visible = client.get(
                f"/v1/workspaces/{workspace_id}/sla-policies/{scoped['policy_id']}",
                headers=_bearer("sla-rbac-viewer"),
            )
            assert visible.status_code == 200, visible.text


def test_notification_mark_and_preference_are_naturally_idempotent():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            owner = "idempotent-notify-owner"
            workspace_id = _workspace(client, owner, "Idempotent Notify Co")
            project_id = _project(client, owner, workspace_id)
            _invite(client, owner, workspace_id, "idempotent-notify-reviewer", "approver")
            board_id = _board(client, owner, workspace_id, project_id)
            item = _create_work_item(
                client,
                engine,
                owner=owner,
                reviewer="idempotent-notify-reviewer",
                workspace_id=workspace_id,
                project_id=project_id,
                board_id=board_id,
            )
            owner_id = _principal_id(client, owner)
            _assign(engine, item["work_item_id"], owner_id)
            overridden = client.patch(
                f"/v1/workspaces/{workspace_id}/work-items/"
                f"{item['work_item_id']}/priority",
                json={"priority": "high", "reason": "Idempotency coverage."},
                headers={**_bearer(owner), "Idempotency-Key": f"idem-{uuid4().hex}"},
            )
            assert overridden.status_code == 200, overridden.text
            notifications = client.get(
                f"/v1/workspaces/{workspace_id}/notifications",
                headers=_bearer(owner),
            )
            notification = next(
                entry
                for entry in notifications.json()["items"]
                if entry["event_type"] == "work_item.priority_overridden"
            )
            notification_id = notification["notification_id"]
            first_mark = client.patch(
                f"/v1/workspaces/{workspace_id}/notifications/{notification_id}",
                json={"read": True},
                headers=_bearer(owner),
            )
            second_mark = client.patch(
                f"/v1/workspaces/{workspace_id}/notifications/{notification_id}",
                json={"read": True},
                headers=_bearer(owner),
            )
            assert first_mark.status_code == second_mark.status_code == 200
            assert first_mark.json()["read_at"] == second_mark.json()["read_at"]
            assert first_mark.headers["ETag"] == second_mark.headers["ETag"]

            event_type = "work_item.priority_overridden"
            first_preference = client.put(
                f"/v1/workspaces/{workspace_id}/notification-preferences/{event_type}",
                json={"in_app": True, "email": False},
                headers=_bearer(owner),
            )
            second_preference = client.put(
                f"/v1/workspaces/{workspace_id}/notification-preferences/{event_type}",
                json={"in_app": True, "email": False},
                headers=_bearer(owner),
            )
            assert first_preference.status_code == second_preference.status_code == 200
            assert first_preference.json()["version"] == second_preference.json()["version"]
            assert first_preference.headers["ETag"] == second_preference.headers["ETag"]
