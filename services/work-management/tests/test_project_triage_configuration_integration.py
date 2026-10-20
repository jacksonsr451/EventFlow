"""HTTP integration tests for project triage rules and versioned templates (#41).

The app runs against a throwaway migrated database and a deterministic
authentication stub. The tests cover additive configuration, immutable template
versions, activation, custom-field validation, historical snapshots, proposal
gating, RBAC, optimistic concurrency, idempotent replay and tenant isolation.
They skip themselves when no test database is configured.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from eventflow_work_management.api.app import create_app
from eventflow_work_management.db.engine import session_factory
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher
from support import require_database_url, temporary_database

ISSUER = "https://id.example.test/realms/eventflow"

VALID_BUG_CRITERIA = {
    "expected_behavior": "Returns 400 with a problem document.",
    "observed_behavior": "Raises an unhandled 500 error.",
    "reproduction_steps": ["Submit an empty cart payload."],
    "environment": "Python 3.11",
    "severity": "high",
    "is_regression": False,
    "impact": "All empty-cart checkouts fail for every user.",
}


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
        json={"name": name, "slug": f"{name.lower().replace(' ', '-')}-co"},
        headers=_bearer(subject),
    )
    assert created.status_code == 201, created.text
    return created.json()["workspace_id"]


def _make_project(
    client: TestClient, subject: str, workspace_id: str, *, key: str = "PAY"
) -> str:
    created = client.post(
        f"/v1/workspaces/{workspace_id}/projects",
        json={"key": key, "name": "Payments"},
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


def _config_url(workspace_id: str, project_id: str) -> str:
    return (
        f"/v1/workspaces/{workspace_id}/projects/{project_id}/triage-configuration"
    )


def _templates_url(workspace_id: str, project_id: str) -> str:
    return f"/v1/workspaces/{workspace_id}/projects/{project_id}/triage-templates"


def _template_url(workspace_id: str, project_id: str, template_id: str) -> str:
    return f"{_templates_url(workspace_id, project_id)}/{template_id}"


def _custom_field_config() -> dict:
    return {
        "enabled": True,
        "required_fields": {"bug": ["customer_tier"]},
        "custom_fields": [
            {
                "key": "customer_tier",
                "label": "Customer tier",
                "type": "enum",
                "allowed_values": ["free", "pro", "enterprise"],
                "categories": ["bug"],
            }
        ],
        "workflow_rules": {},
    }


def _template_definition() -> dict:
    return {
        "fields": [
            {
                "key": "repro_url",
                "label": "Reproduction URL",
                "type": "string",
                "required": True,
                "categories": ["bug"],
                "max_length": 500,
            }
        ],
        "required_fields": ["repro_url"],
        "workflow": {"require_template_for_new_triage": True},
    }


def _submit(client: TestClient, subject: str, workspace_id: str, project_id: str):
    response = client.post(
        f"/v1/workspaces/{workspace_id}/consultations",
        json={
            "project_id": project_id,
            "origin": "web",
            "title": "Null pointer on empty cart",
            "description": "Submitting an empty cart returns 500 instead of 400.",
        },
        headers=_bearer(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()["consultation_id"]


def _triage_body(**overrides) -> dict:
    body = {
        "category": "bug",
        "priority": "high",
        "triage_notes": "Reviewed and reproduced against the current build.",
        "bug_criteria": VALID_BUG_CRITERIA,
    }
    body.update(overrides)
    return body


def _create_template(client, workspace_id, project_id, subject="owner", **overrides):
    body = {
        "category": "bug",
        "key": "bug-default",
        "name": "Default bug template",
        "description": "Bounded reproduction fields for defect triage.",
        "definition": _template_definition(),
    }
    body.update(overrides)
    return client.post(
        _templates_url(workspace_id, project_id),
        json=body,
        headers=_bearer(subject),
    )


def _create_publish_activate(client, workspace_id, project_id, template_id):
    detail = client.get(
        _template_url(workspace_id, project_id, template_id), headers=_bearer("owner")
    )
    assert detail.status_code == 200, detail.text
    version_id = detail.json()["versions"][0]["template_version_id"]
    published = client.post(
        f"{_template_url(workspace_id, project_id, template_id)}/versions/"
        f"{version_id}/publish",
        headers=_bearer("owner"),
    )
    assert published.status_code == 200, published.text
    activated = client.post(
        f"{_template_url(workspace_id, project_id, template_id)}/versions/"
        f"{version_id}/activate",
        headers=_bearer("owner"),
    )
    assert activated.status_code == 200, activated.text
    return version_id


def test_configuration_defaults_rbac_and_optimistic_concurrency():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Config Co")
            project_id = _make_project(client, "owner", workspace_id)
            for subject, role in (("view", "viewer"), ("tina", "triager")):
                _invite_and_accept(client, "owner", workspace_id, subject, role)

            missing = client.get(
                _config_url(workspace_id, project_id), headers=_bearer("view")
            )
            assert missing.status_code == 200, missing.text
            assert missing.json() == {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "enabled": False,
                "required_fields": {},
                "custom_fields": [],
                "workflow_rules": {},
                "version": 0,
                "updated_at": None,
            }
            assert missing.headers["ETag"].startswith('"')
            assert (
                client.get(
                    _config_url(workspace_id, project_id),
                    headers=_bearer("mallory"),
                ).status_code
                == 404
            )

            for subject in ("view", "tina"):
                denied = client.put(
                    _config_url(workspace_id, project_id),
                    json=_custom_field_config(),
                    headers=_bearer(subject),
                )
                assert denied.status_code == 403, denied.text

            updated = client.put(
                _config_url(workspace_id, project_id),
                json=_custom_field_config(),
                headers=_bearer("owner"),
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["enabled"] is True
            assert updated.json()["version"] == 1
            etag = updated.headers["ETag"]

            stale = client.put(
                _config_url(workspace_id, project_id),
                json={**_custom_field_config(), "enabled": False},
                headers={**_bearer("owner"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412, stale.text

            headers = {
                **_bearer("owner"),
                "If-Match": etag,
                "Idempotency-Key": "config-key-01",
            }
            first = client.put(
                _config_url(workspace_id, project_id),
                json={**_custom_field_config(), "enabled": False},
                headers=headers,
            )
            assert first.status_code == 200, first.text
            replay = client.put(
                _config_url(workspace_id, project_id),
                json={**_custom_field_config(), "enabled": False},
                headers=headers,
            )
            assert replay.status_code == 200, replay.text
            first_version = first.json()["version"]
            replay_version = replay.json()["version"]
            assert replay_version == first_version == 2

            conflict = client.put(
                _config_url(workspace_id, project_id),
                json={**_custom_field_config(), "enabled": True},
                headers=headers,
            )
            assert conflict.status_code == 409, conflict.text
            assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_template_lifecycle_publish_activate_archive_and_deprecate():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Lifecycle Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "view", "viewer")

            created = _create_template(client, workspace_id, project_id)
            assert created.status_code == 201, created.text
            body = created.json()
            template_id = body["template_id"]
            assert body["status"] == "active"
            assert created.headers["ETag"].startswith('"')
            assert body["template_id"] in created.headers["Location"]

            duplicate = _create_template(client, workspace_id, project_id)
            assert duplicate.status_code == 409, duplicate.text

            detail = client.get(
                _template_url(workspace_id, project_id, template_id),
                headers=_bearer("view"),
            )
            assert detail.status_code == 200, detail.text
            versions = detail.json()["versions"]
            assert len(versions) == 1
            assert versions[0]["status"] == "draft"
            assert versions[0]["version"] == 1
            assert versions[0]["definition"]["required_fields"] == ["repro_url"]
            version_one = versions[0]["template_version_id"]

            draft_activate = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_one}/activate",
                headers=_bearer("owner"),
            )
            assert draft_activate.status_code == 409, draft_activate.text
            assert draft_activate.json()["code"] == "TEMPLATE_NOT_PUBLISHED"

            published = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_one}/publish",
                headers=_bearer("owner"),
            )
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "published"

            activated = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_one}/activate",
                headers=_bearer("owner"),
            )
            assert activated.status_code == 200, activated.text
            activation = activated.json()["activation"]
            assert activation["category"] == "bug"
            assert activation["template_version_id"] == version_one
            etag = activated.headers["ETag"]
            assert etag.startswith('"')

            stale = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_one}/activate",
                headers={**_bearer("owner"), "If-Match": '"deadbeef"'},
            )
            assert stale.status_code == 412, stale.text

            second = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions",
                json={"definition": _template_definition()},
                headers=_bearer("owner"),
            )
            assert second.status_code == 201, second.text
            assert second.json()["version"] == 2
            assert second.json()["status"] == "draft"
            version_two = second.json()["template_version_id"]

            latest = client.get(
                _template_url(workspace_id, project_id, template_id),
                headers=_bearer("owner"),
            )
            assert [item["status"] for item in latest.json()["versions"]] == [
                "published",
                "draft",
            ]

            archived = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/archive",
                headers={**_bearer("owner"), "If-Match": latest.headers["ETag"]},
            )
            assert archived.status_code == 200, archived.text
            assert archived.json()["status"] == "archived"

            after_archive = client.get(
                _template_url(workspace_id, project_id, template_id),
                headers=_bearer("owner"),
            )
            assert after_archive.status_code == 200, after_archive.text
            assert after_archive.json()["activation"] is None

            archived_activate = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_two}/publish",
                headers=_bearer("owner"),
            )
            assert archived_activate.status_code == 200, archived_activate.text
            cannot_activate = client.post(
                f"{_template_url(workspace_id, project_id, template_id)}/versions/"
                f"{version_two}/activate",
                headers=_bearer("owner"),
            )
            assert cannot_activate.status_code == 409, cannot_activate.text
            assert cannot_activate.json()["code"] == "TEMPLATE_NOT_PUBLISHED"

            replacement = _create_template(
                client,
                workspace_id,
                project_id,
                key="bug-replacement",
                name="Replacement bug template",
            )
            assert replacement.status_code == 201, replacement.text
            replacement_id = replacement.json()["template_id"]
            _create_publish_activate(client, workspace_id, project_id, replacement_id)

            deprecated = client.post(
                f"{_template_url(workspace_id, project_id, replacement_id)}/deprecate",
                headers=_bearer("owner"),
            )
            assert deprecated.status_code == 200, deprecated.text
            assert deprecated.json()["status"] == "deprecated"


def test_custom_fields_validate_and_pin_the_effective_template():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Fields Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            configured = client.put(
                _config_url(workspace_id, project_id),
                json=_custom_field_config(),
                headers=_bearer("owner"),
            )
            assert configured.status_code == 200, configured.text

            first = _submit(client, "owner", workspace_id, project_id)
            missing = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{first}/triage",
                json=_triage_body(),
                headers=_bearer("tina"),
            )
            assert missing.status_code == 422, missing.text
            assert missing.json()["code"] == "TRIAGE_REQUIRED_FIELD_MISSING"
            assert {
                item["field"] for item in missing.json()["errors"]
            } == {"customer_tier"}

            invalid = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{first}/triage",
                json=_triage_body(custom_fields={"customer_tier": "platinum"}),
                headers=_bearer("tina"),
            )
            assert invalid.status_code == 422, invalid.text
            assert invalid.json()["code"] == "TRIAGE_FIELD_INVALID"

            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{first}/triage",
                json=_triage_body(custom_fields={"customer_tier": "pro"}),
                headers=_bearer("tina"),
            )
            assert triaged.status_code == 200, triaged.text
            triaged_body = triaged.json()
            assert triaged_body["triage_custom_fields"] == {"customer_tier": "pro"}
            assert triaged_body["triage_template_id"] is None
            assert (
                triaged_body["triage_template_snapshot"]["source"]
                == "project_configuration"
            )

            fetched = client.get(
                f"/v1/workspaces/{workspace_id}/consultations/{first}",
                headers=_bearer("owner"),
            )
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["triage_custom_fields"] == {"customer_tier": "pro"}

            template = _create_template(client, workspace_id, project_id)
            assert template.status_code == 201, template.text
            template_id = template.json()["template_id"]
            version_id = _create_publish_activate(
                client, workspace_id, project_id, template_id
            )

            second = _submit(client, "owner", workspace_id, project_id)
            missing_template = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{second}/triage",
                json=_triage_body(custom_fields={"customer_tier": "free"}),
                headers=_bearer("tina"),
            )
            assert missing_template.status_code == 422, missing_template.text
            assert missing_template.json()["code"] == "TRIAGE_REQUIRED_FIELD_MISSING"

            pinned = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{second}/triage",
                json=_triage_body(
                    custom_fields={
                        "customer_tier": "enterprise",
                        "repro_url": "https://reports.example.test/issue/42",
                    }
                ),
                headers=_bearer("tina"),
            )
            assert pinned.status_code == 200, pinned.text
            pinned_body = pinned.json()
            assert pinned_body["triage_template_id"] == template_id
            assert pinned_body["triage_template_version"] == 1
            assert pinned_body["triage_template_schema_version"] == 1
            assert (
                pinned_body["triage_template_snapshot"]["source"]
                == "project_template"
            )
            assert pinned_body["triage_custom_fields"] == {
                "customer_tier": "enterprise",
                "repro_url": "https://reports.example.test/issue/42",
            }


def test_preview_is_deterministic_and_does_not_triage():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Preview Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            client.put(
                _config_url(workspace_id, project_id),
                json=_custom_field_config(),
                headers=_bearer("owner"),
            )
            preview_url = (
                f"/v1/workspaces/{workspace_id}/projects/{project_id}/"
                "triage-validation/preview"
            )
            base = {"project_id": project_id, "category": "bug"}

            invalid = client.post(
                preview_url, json=base, headers=_bearer("tina")
            )
            assert invalid.status_code == 200, invalid.text
            assert invalid.json()["valid"] is False
            assert invalid.json()["code"] == "TRIAGE_REQUIRED_FIELD_MISSING"
            assert invalid.json()["effective_template"] is None

            valid = client.post(
                preview_url,
                json={**base, "custom_fields": {"customer_tier": "pro"}},
                headers=_bearer("tina"),
            )
            assert valid.status_code == 200, valid.text
            assert valid.json()["valid"] is True
            assert valid.json()["normalized_custom_fields"] == {"customer_tier": "pro"}
            assert valid.headers["ETag"].startswith('"')

            other_project = _make_project(
                client, "owner", workspace_id, key="OPS"
            )
            mismatch = client.post(
                preview_url,
                json={**base, "project_id": other_project},
                headers=_bearer("tina"),
            )
            assert mismatch.status_code == 400, mismatch.text
            assert mismatch.json()["code"] == "VALIDATION_ERROR"


def test_proposal_gating_only_applies_while_configuration_is_enabled():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Proposal Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "tina", "triager")

            consultation_id = _submit(client, "owner", workspace_id, project_id)
            triaged = client.post(
                f"/v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage",
                json=_triage_body(),
                headers=_bearer("tina"),
            )
            assert triaged.status_code == 200, triaged.text

            proposal = {
                "consultation_id": consultation_id,
                "title": "Streaming CSV export",
                "technical_description": "Implement a streaming CSV export endpoint.",
                "scope": "Dashboard export control and backend endpoint.",
                "justification": "Customers requested CSV export.",
                "acceptance_criteria": ["CSV download works for the current filters"],
                "category": "bug",
                "priority": "medium",
            }
            preview_url = f"/v1/workspaces/{workspace_id}/proposals/preview"

            baseline = client.post(
                preview_url, json=proposal, headers=_bearer("owner")
            )
            assert baseline.status_code == 200, baseline.text

            for enabled in (False, True):
                configured = client.put(
                    _config_url(workspace_id, project_id),
                    json={
                        "enabled": enabled,
                        "workflow_rules": {
                            "require_evidence_for_categories": ["bug"]
                        },
                    },
                    headers=_bearer("owner"),
                )
                assert configured.status_code == 200, configured.text

                result = client.post(
                    preview_url, json=proposal, headers=_bearer("owner")
                )
                if enabled:
                    assert result.status_code == 422, result.text
                    assert result.json()["code"] == "TRIAGE_WORKFLOW_VIOLATION"
                else:
                    assert result.status_code == 200, result.text

            missing = client.post(
                f"/v1/workspaces/{workspace_id}/proposals",
                json=proposal,
                headers=_bearer("owner"),
            )
            assert missing.status_code == 422, missing.text
            assert missing.json()["code"] == "TRIAGE_WORKFLOW_VIOLATION"


def test_templates_and_configuration_are_tenant_isolated():
    with temporary_database(require_database_url()) as (_, engine):
        with _client(engine) as client:
            workspace_id = _make_workspace(client, "owner", "Alpha Co")
            project_id = _make_project(client, "owner", workspace_id)
            _invite_and_accept(client, "owner", workspace_id, "view", "viewer")
            template = _create_template(client, workspace_id, project_id)
            assert template.status_code == 201, template.text
            template_id = template.json()["template_id"]

            other_workspace = _make_workspace(client, "other", "Beta Co")
            other_project = _make_project(client, "other", other_workspace, key="BET")

            hidden = client.get(
                _template_url(other_workspace, other_project, template_id),
                headers=_bearer("other"),
            )
            assert hidden.status_code == 404, hidden.text

            defaults = client.get(
                _config_url(other_workspace, other_project), headers=_bearer("other")
            )
            assert defaults.status_code == 200, defaults.text
            assert defaults.json()["version"] == 0

            listing = client.get(
                _templates_url(other_workspace, other_project),
                headers=_bearer("other"),
            )
            assert listing.status_code == 200, listing.text
            assert listing.json()["items"] == []
            assert listing.json()["page_info"] == {
                "has_more": False,
                "next_cursor": None,
            }

            isolated = client.get(
                _template_url(workspace_id, project_id, template_id),
                headers=_bearer("other"),
            )
            assert isolated.status_code == 404, isolated.text

            readable = client.get(
                _template_url(workspace_id, project_id, template_id),
                headers=_bearer("view"),
            )
            assert readable.status_code == 200, readable.text
