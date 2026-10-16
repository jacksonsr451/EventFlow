"""Verify the checked-in Keycloak realm and fresh bootstrap settings."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REALM_PATH = ROOT / "infra" / "keycloak" / "realm-eventflow-test.json"
ENV_TEMPLATE_PATH = ROOT / ".env.example"
BOOTSTRAP_PATH = ROOT / "scripts" / "prepare_auth_test_environment.py"

spec = importlib.util.spec_from_file_location("eventflow_auth_bootstrap", BOOTSTRAP_PATH)
bootstrap = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bootstrap)


def test_versioned_realm_contains_public_pkce_clients_and_allowlists():
    realm = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    assert realm["realm"] == "eventflow"
    assert realm.get("users", []) == []
    assert realm["accessTokenLifespan"] == 300
    assert realm["ssoSessionIdleTimeout"] == 1800
    assert realm["ssoSessionMaxLifespan"] == 43200
    assert realm["revokeRefreshToken"] is True
    assert realm["refreshTokenMaxReuse"] == 0

    clients = {client["clientId"]: client for client in realm["clients"]}
    assert set(clients) == {
        "eventflow-web-bff",
        "eventflow-desktop",
        "eventflow-vscode",
    }
    expected_redirects = {
        "eventflow-web-bff": ["http://localhost:8000/v1/auth/oidc/callback"],
        "eventflow-desktop": ["eventflow://auth/callback"],
        "eventflow-vscode": ["vscode://jacksonsr451.eventflow/auth-callback"],
    }
    for client_id, client in clients.items():
        assert client["publicClient"] is True
        assert client["standardFlowEnabled"] is True
        assert client["implicitFlowEnabled"] is False
        assert client["directAccessGrantsEnabled"] is False
        assert client["serviceAccountsEnabled"] is False
        assert client["attributes"]["pkce.code.challenge.method"] == "S256"
        assert client["redirectUris"] == expected_redirects[client_id]
        assert "eventflow-api-audience" in client["defaultClientScopes"]
    assert set(clients["eventflow-web-bff"]["webOrigins"]) == {
        "http://localhost:5173",
        "http://localhost:8000",
    }

    audience_scope = next(
        scope for scope in realm["clientScopes"] if scope["name"] == "eventflow-api-audience"
    )
    mapper = audience_scope["protocolMappers"][0]
    assert mapper["protocolMapper"] == "oidc-audience-mapper"
    assert mapper["config"]["included.client.audience"] == "eventflow-api"
    assert mapper["config"]["access.token.claim"] == "true"


def test_new_bootstrap_credentials_are_unique_and_use_only_the_tracked_realm():
    first = bootstrap.build_local_configuration(
        keycloak_port=8182, postgres_port=55432, project_name="eventflow-auth-test"
    )
    second = bootstrap.build_local_configuration(
        keycloak_port=8182, postgres_port=55432, project_name="eventflow-auth-test"
    )
    assert first["KEYCLOAK_REALM_IMPORT_FILE"] == "./infra/keycloak/realm-eventflow-test.json"
    assert first["KEYCLOAK_REALM_IMPORT_FILE"] == second["KEYCLOAK_REALM_IMPORT_FILE"]
    for key in (
        "KEYCLOAK_ADMIN_PASSWORD",
        "EVENTFLOW_TEST_KEYCLOAK_PASSWORD",
        "POSTGRES_PASSWORD",
        "EVENTFLOW_TOKEN_ENCRYPTION_KEYS",
    ):
        assert first[key] != second[key]
    assert first["EVENTFLOW_TEST_KEYCLOAK_USERNAME"] != second[
        "EVENTFLOW_TEST_KEYCLOAK_USERNAME"
    ]
    assert bootstrap.ENVIRONMENT_FILE == ROOT / ".local-data" / "authentication-test.env"
    assert bootstrap.ENVIRONMENT_TEMPLATE == ENV_TEMPLATE_PATH
    template = bootstrap._parse_env(ENV_TEMPLATE_PATH)
    for key in (
        "POSTGRES_PASSWORD",
        "KEYCLOAK_ADMIN_PASSWORD",
        "EVENTFLOW_TOKEN_ENCRYPTION_KEYS",
        "EVENTFLOW_TEST_KEYCLOAK_PASSWORD",
    ):
        assert template[key] == ""
