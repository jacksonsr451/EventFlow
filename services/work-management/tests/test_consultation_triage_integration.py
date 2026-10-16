"""HTTP integration tests for differentiated triage and reclassification (Issue #5).

The app runs against a throwaway migrated database and a deterministic
authentication stub. The tests exercise the public contract behaviour: the
category-discriminated triage union, the manual reclassification lifecycle and
its append-only audit trail, RBAC and tenant isolation, optimistic concurrency,
idempotent replay, and the reusable triage templates. They skip themselves when
no test database is configured.
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
        f"/v1/workspaces/{workspace_id}/invitations/{body['invitation']['invitation_id']}/accept",
        json={"token": body["token"]},
        headers=_bearer(invitee),
    )
    assert accepted.status_code == 201, accepted.text


def _submit(client: TestClient, subject: str, workspace_id: str, project_id: str, **extra):
    payload = {
        "project_id": project_id,
        "origin": "web",
        "title": "Null pointer on empty cart",
        "description": "Submitting an empty cart returns 500 instead of 400.",
    }
    payload.update(extra)
    return client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json=payload,
        headers=_bearer(subject),
    )


VALID_CRITERIA = {
    "bug": {
        "expected_behavior": "Returns 400 with a problem document.",
        "observed_behavior": "Raises an unhandled 500 error.",
        "reproduction_steps": ["Submit an empty cart payload."],
        "environment": "Python 3.11",
        "severity": "high",
        "is_regression": False,
        "impact": "All empty-cart checkouts fail for every user.",
    },
    "feature": {
        "problem_statement": "Triagers cannot record structured feature intent.",
        "expected_value": "Consistent, queryable feature triage records.",
        "functional_requirements": ["Record functional requirements."],
        "acceptance_criteria": ["Feature triage is verifiable."],
        "scope": "Backend triage contract only; no client UI.",
    },
    "chore": {
        "maintenance_need": "Upgrade the pinned database driver.",
        "technical_debt_type": "dependency",
        "justification": "The current driver is out of support.",
        "risk_of_inaction": "Unpatched security issues accumulate.",
        "expected_technical_effect": "A supported, patched driver is pinned.",
    },
    "docs": {
        "affected_document": "docs/architecture/work-management-api.md",
        "inconsistency_summary": "The triage payload is described incorrectly.",
        "target_audience": "Backend engineers",
    },
    "security": {
        "vulnerability_type": "broken access control",
        "severity_rating": "critical",
        "confidentiality_level": "restricted",
        "access_restricted_to": ["security-team"],
        "safe_evidence_handling": True,
    },
}


def _triage_body(category: str) -> dict:
    return {
        "category": category,
        "priority": "high",
        "triage_notes": "Reviewed and reproduced against the current build.",
        f"{category}_criteria": VALID_CRITERIA[category],
    }


def _reclassify_body(category: str, **overrides) -> dict:
    body = {
        "justification": "Initial triage conflated two distinct defects.",
        "triage": _triage_body(category),
    }
    body.update(overrides)
    return body


def test_each_category_requires_its_own_criteria():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Category Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            for category in VALID_CRITERIA:
                created = _submit(client, "owner", workspace_id, project_id)
                consultation_id = created.json()["consultation_id"]
                triaged = client.post(
                    f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                    json=_triage_body(category),
                    headers=_bearer("tina"),
                )
                assert triaged.status_code == 200, (category, triaged.text)
                assert triaged.json()["category"] == category
                assert triaged.json()["status"] == "triaging"

            created = _submit(client, "owner", workspace_id, project_id)
            consultation_id = created.json()["consultation_id"]
            url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage"
            )

            # Missing the required criteria object: no variant matches.
            missing = client.post(
                url,
                json={
                    "category": "bug",
                    "priority": "high",
                    "triage_notes": "Reviewed against the current build.",
                },
                headers=_bearer("tina"),
            )
            assert missing.status_code == 400

            # Supplying a second category's criteria: no variant matches.
            mixed = _triage_body("bug")
            mixed["feature_criteria"] = VALID_CRITERIA["feature"]
            assert (
                client.post(url, json=mixed, headers=_bearer("tina")).status_code == 400
            )

            # An unknown field inside the criteria object is rejected.
            bad_field = _triage_body("bug")
            bad_field["bug_criteria"] = {
                **VALID_CRITERIA["bug"],
                "unexpected": "value",
            }
            assert (
                client.post(url, json=bad_field, headers=_bearer("tina")).status_code
                == 400
            )


def test_triage_and_reclassify_are_role_gated():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Roles Co")
            project_id = _make_project(client, "owner", workspace_id)
            for subject, role in (
                ("contrib", "contributor"),
                ("ap", "approver"),
                ("view", "viewer"),
                ("tina", "triager"),
            ):
                _invite_and_accept(client, "owner", workspace_id, subject, role)

            created = _submit(client, "owner", workspace_id, project_id)
            consultation_id = created.json()["consultation_id"]
            triage_url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage"
            )
            reclassify_url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/reclassify"
            )

            for subject in ("contrib", "ap", "view"):
                assert (
                    client.post(
                        triage_url, json=_triage_body("bug"), headers=_bearer(subject)
                    ).status_code
                    == 403
                )

            triaged = client.post(
                triage_url, json=_triage_body("bug"), headers=_bearer("tina")
            )
            assert triaged.status_code == 200, triaged.text

            for subject in ("contrib", "ap", "view"):
                assert (
                    client.post(
                        reclassify_url,
                        json=_reclassify_body("feature"),
                        headers=_bearer(subject),
                    ).status_code
                    == 403
                )


def test_reclassification_requires_completed_triage_and_audits():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Reclass Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            created = _submit(client, "owner", workspace_id, project_id)
            consultation_id = created.json()["consultation_id"]
            reclassify_url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/reclassify"
            )

            # Raw OPEN intake that has not been triaged cannot be reclassified.
            premature = client.post(
                reclassify_url,
                json=_reclassify_body("feature"),
                headers=_bearer("tina"),
            )
            assert premature.status_code == 409
            assert premature.json()["code"] == "INVALID_STATE"

            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=_triage_body("bug"),
                headers=_bearer("tina"),
            )
            assert triaged.status_code == 200, triaged.text

            reclassified = client.post(
                reclassify_url,
                json=_reclassify_body("feature"),
                headers=_bearer("tina"),
            )
            assert reclassified.status_code == 200, reclassified.text
            assert reclassified.json()["category"] == "feature"

            history = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/history",
                headers=_bearer("owner"),
            )
            assert history.status_code == 200, history.text
            reclassifications = [
                item
                for item in history.json()["items"]
                if item["action"] == "consultation.reclassified"
            ]
            assert len(reclassifications) == 1
            snapshot = reclassifications[0]["snapshot"]
            assert snapshot["previous_category"] == "bug"
            assert snapshot["category"] == "feature"
            assert snapshot["justification"]


def test_reclassification_is_tenant_isolated_and_concurrency_safe():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Isolation Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            created = _submit(client, "owner", workspace_id, project_id)
            consultation_id = created.json()["consultation_id"]
            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=_triage_body("bug"),
                headers=_bearer("tina"),
            )
            etag = triaged.headers["ETag"]
            reclassify_url = (
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/reclassify"
            )

            # A non-member cannot see the consultation at all.
            assert (
                client.post(
                    reclassify_url,
                    json=_reclassify_body("feature"),
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )

            # A stale validator yields 412 and leaves the row unchanged.
            stale = client.post(
                reclassify_url,
                json=_reclassify_body("feature"),
                headers={**_bearer("tina"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412

            # An idempotent reclassification replays without a second audit row.
            headers = {**_bearer("tina"), "If-Match": etag, "Idempotency-Key": "reclassify-key-01"}
            first = client.post(
                reclassify_url, json=_reclassify_body("feature"), headers=headers
            )
            assert first.status_code == 200, first.text
            replay = client.post(
                reclassify_url, json=_reclassify_body("feature"), headers=headers
            )
            assert replay.status_code == 200
            assert replay.json()["consultation_id"] == consultation_id

            conflict = client.post(
                reclassify_url,
                json=_reclassify_body("chore"),
                headers=headers,
            )
            assert conflict.status_code == 409

            history = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/history",
                headers=_bearer("owner"),
            )
            assert (
                len(
                    [
                        item
                        for item in history.json()["items"]
                        if item["action"] == "consultation.reclassified"
                    ]
                )
                == 1
            )


def test_triage_templates_are_role_gated_and_structured():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Templates Co")
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")
            _invite_and_accept(client, "owner", workspace_id, "view", "viewer")

            url = f"/v1/workspaces/{workspace_id}/consultations/triage-templates"
            assert client.get(url, headers=_bearer("view")).status_code == 403
            assert client.get(url, headers=_bearer("mallory")).status_code == 404

            listed = client.get(url, headers=_bearer("tina"))
            assert listed.status_code == 200, listed.text
            templates = {item["category"]: item for item in listed.json()["templates"]}
            assert set(templates) == {"bug", "feature", "chore"}
            assert "impact" in templates["bug"]["required_fields"]
            assert "scope" in templates["feature"]["required_fields"]
            assert (
                "expected_technical_effect"
                in templates["chore"]["required_fields"]
            )
            assert listed.headers["ETag"].startswith('"')
