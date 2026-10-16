#!/usr/bin/env python3
"""Create, start and verify an isolated local Keycloak/PostgreSQL test stack."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
REALM_SOURCE = ROOT / "infra" / "keycloak" / "realm-eventflow-test.json"
LOCAL_ROOT = ROOT / ".local-data"
ENVIRONMENT_FILE = LOCAL_ROOT / "authentication-test.env"
ENVIRONMENT_TEMPLATE = ROOT / ".env.example"
DEFAULT_PROJECT = "eventflow-auth-dev"
DEFAULT_KEYCLOAK_PORT = 8082
DEFAULT_POSTGRES_PORT = 5432


class BootstrapError(RuntimeError):
    """A safe-to-display bootstrap failure (never includes generated secrets)."""


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BootstrapError(
            "The local authentication environment file could not be read."
        ) from exc
    for line in lines:
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise BootstrapError(
                "The local authentication environment file is malformed."
            )
        values[name] = value
    return values


def _write_secret_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise BootstrapError(
            "The shared local authentication file already exists; it was not overwritten."
        ) from exc
    try:
        path.chmod(0o600)
    except OSError:
        # On Windows the new file inherits the current user's local-directory ACL.
        pass


def _make_values(
    *,
    username: str,
    test_password: str,
    admin_password: str,
    database_password: str,
    keycloak_port: int,
    postgres_port: int,
    project_name: str,
) -> dict[str, str]:
    database_url = (
        f"postgresql+psycopg://eventflow:{database_password}"
        f"@localhost:{postgres_port}/eventflow"
    )
    test_database_url = (
        f"postgresql+psycopg://eventflow:{database_password}"
        f"@localhost:{postgres_port}/postgres"
    )
    values = _parse_env(ENVIRONMENT_TEMPLATE)
    values.update(
        {
            "POSTGRES_USER": "eventflow",
            "POSTGRES_PASSWORD": database_password,
            "POSTGRES_DB": "eventflow",
            "POSTGRES_PORT": str(postgres_port),
            "KEYCLOAK_ADMIN_USERNAME": "eventflow-admin",
            "KEYCLOAK_ADMIN_PASSWORD": admin_password,
            "KEYCLOAK_PORT": str(keycloak_port),
            "KEYCLOAK_REALM_IMPORT_FILE": f"./{REALM_SOURCE.relative_to(ROOT).as_posix()}",
            "EVENTFLOW_AUTH_COMPOSE_PROJECT": project_name,
            "EVENTFLOW_DATABASE_URL": database_url,
            "EVENTFLOW_TEST_DATABASE_URL": test_database_url,
            "EVENTFLOW_ENVIRONMENT": "test",
            "EVENTFLOW_OIDC_ISSUER": f"http://localhost:{keycloak_port}/realms/eventflow",
            "EVENTFLOW_TOKEN_ENCRYPTION_KEYS": Fernet.generate_key().decode("ascii"),
            "EVENTFLOW_TEST_KEYCLOAK_USERNAME": username,
            "EVENTFLOW_TEST_KEYCLOAK_PASSWORD": test_password,
        }
    )
    return values


def build_local_configuration(
    *,
    keycloak_port: int | None = None,
    postgres_port: int | None = None,
    project_name: str | None = None,
) -> dict[str, str]:
    """Build fresh local settings in memory without reading or writing runtime files."""
    keycloak_port = (
        DEFAULT_KEYCLOAK_PORT if keycloak_port is None else keycloak_port
    )
    postgres_port = DEFAULT_POSTGRES_PORT if postgres_port is None else postgres_port
    project_name = project_name or DEFAULT_PROJECT
    if not 1 <= keycloak_port <= 65535 or not 1 <= postgres_port <= 65535:
        raise BootstrapError("Service ports must be in the range 1–65535.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,50}", project_name):
        raise BootstrapError(
            "Compose project name must use lowercase letters, digits, '_' or '-'."
        )
    return _make_values(
        username=f"eventflow-test-{secrets.token_hex(6)}",
        test_password=secrets.token_urlsafe(36),
        admin_password=secrets.token_urlsafe(36),
        database_password=secrets.token_urlsafe(36),
        keycloak_port=keycloak_port,
        postgres_port=postgres_port,
        project_name=project_name,
    )


def ensure_local_configuration(
    *,
    keycloak_port: int | None = None,
    postgres_port: int | None = None,
    project_name: str | None = None,
) -> tuple[Path, dict[str, str], bool]:
    """Create the shared env file only if absent; preserve existing bytes/credentials."""
    env_path = ENVIRONMENT_FILE
    if not REALM_SOURCE.is_file():
        raise BootstrapError(
            "The version-controlled development realm file is missing."
        )
    if not ENVIRONMENT_TEMPLATE.is_file():
        raise BootstrapError(
            "The version-controlled authentication env template is missing."
        )
    if env_path.exists():
        existing_values = _parse_env(env_path)
        requested_settings = {
            "KEYCLOAK_PORT": keycloak_port,
            "POSTGRES_PORT": postgres_port,
            "EVENTFLOW_AUTH_COMPOSE_PROJECT": project_name,
        }
        for name, requested_value in requested_settings.items():
            if (
                requested_value is not None
                and existing_values.get(name)
                and existing_values[name] != str(requested_value)
            ):
                raise BootstrapError(
                    f"{name} conflicts with the existing shared environment; "
                    "the file was not changed."
                )
        values = _parse_env(ENVIRONMENT_TEMPLATE)
        values.update(existing_values)
        expected_realm = f"./{REALM_SOURCE.relative_to(ROOT).as_posix()}"
        values["KEYCLOAK_REALM_IMPORT_FILE"] = expected_realm
        values["KEYCLOAK_PORT"] = str(
            keycloak_port
            if keycloak_port is not None
            else values.get("KEYCLOAK_PORT", DEFAULT_KEYCLOAK_PORT)
        )
        values["POSTGRES_PORT"] = str(
            postgres_port
            if postgres_port is not None
            else values.get("POSTGRES_PORT", DEFAULT_POSTGRES_PORT)
        )
        values["EVENTFLOW_AUTH_COMPOSE_PROJECT"] = (
            project_name
            or existing_values.get("EVENTFLOW_AUTH_COMPOSE_PROJECT")
            or "eventflow"
        )
        if not values.get("POSTGRES_USER"):
            values["POSTGRES_USER"] = "eventflow"
        if not values.get("POSTGRES_PASSWORD"):
            values["POSTGRES_PASSWORD"] = "compose-parse-only-unused"
        if not values.get("POSTGRES_DB"):
            values["POSTGRES_DB"] = "eventflow"
        values.setdefault("EVENTFLOW_AUTH_INTEGRATION", "1")
        _validate_saved_configuration(values)
        start_postgres = all(
            existing_values.get(name)
            for name in (
                "POSTGRES_PASSWORD",
                "EVENTFLOW_DATABASE_URL",
                "EVENTFLOW_TEST_DATABASE_URL",
                "EVENTFLOW_AUTH_COMPOSE_PROJECT",
            )
        )
        return env_path, values, start_postgres

    values = build_local_configuration(
        keycloak_port=keycloak_port,
        postgres_port=postgres_port,
        project_name=project_name,
    )
    _write_secret_file(
        env_path,
        "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
    )
    return env_path, values, True


def _validate_saved_configuration(values: dict[str, str]) -> None:
    required = {
        "KEYCLOAK_ADMIN_USERNAME",
        "KEYCLOAK_ADMIN_PASSWORD",
        "KEYCLOAK_PORT",
        "KEYCLOAK_REALM_IMPORT_FILE",
        "EVENTFLOW_AUTH_COMPOSE_PROJECT",
        "EVENTFLOW_OIDC_ISSUER",
        "EVENTFLOW_TEST_KEYCLOAK_USERNAME",
        "EVENTFLOW_TEST_KEYCLOAK_PASSWORD",
        "EVENTFLOW_TOKEN_ENCRYPTION_KEYS",
        "EVENTFLOW_OIDC_WEB_CLIENT_ID",
        "EVENTFLOW_OIDC_API_AUDIENCE",
        "EVENTFLOW_OIDC_REDIRECT_URI",
    }
    if not required.issubset(values) or any(not values.get(name) for name in required):
        raise BootstrapError("The saved local auth configuration is incomplete.")
    if not REALM_SOURCE.is_file():
        raise BootstrapError(
            "The version-controlled development realm file is missing."
        )


def _request_json(
    url: str,
    *,
    data: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    token: str | None = None,
    method: str | None = None,
) -> Any:
    if data is not None and json_body is not None:
        raise ValueError("provide either form data or JSON body")
    body = (
        urlencode(data).encode("ascii")
        if data is not None
        else json.dumps(json_body).encode("utf-8")
        if json_body is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        raise BootstrapError(
            "Keycloak's local admin API could not be verified."
        ) from exc


def verify_keycloak(values: dict[str, str]) -> None:
    issuer = values["EVENTFLOW_OIDC_ISSUER"].rstrip("/")
    token_response = _request_json(
        f"{issuer.split('/realms/', 1)[0]}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": values["KEYCLOAK_ADMIN_USERNAME"],
            "password": values["KEYCLOAK_ADMIN_PASSWORD"],
        },
    )
    admin_token = token_response.get("access_token")
    if not isinstance(admin_token, str) or not admin_token:
        raise BootstrapError("Keycloak did not issue a local admin verification token.")
    server_root = issuer.split("/realms/", 1)[0]
    admin_root = f"{server_root}/admin/realms/eventflow"
    realm = _request_json(admin_root, token=admin_token)
    expected_realm = {
        "enabled": True,
        "accessTokenLifespan": 300,
        "ssoSessionIdleTimeout": 1800,
        "ssoSessionMaxLifespan": 43200,
        "revokeRefreshToken": True,
        "refreshTokenMaxReuse": 0,
    }
    for name, expected in expected_realm.items():
        if realm.get(name) != expected:
            raise BootstrapError(f"Keycloak realm policy mismatch: {name}.")

    client_ids = (
        "eventflow-web-bff",
        "eventflow-desktop",
        "eventflow-vscode",
    )
    expected_redirects = {
        "eventflow-web-bff": {"http://localhost:8000/v1/auth/oidc/callback"},
        "eventflow-desktop": {"eventflow://auth/callback"},
        "eventflow-vscode": {"vscode://jacksonsr451.eventflow/auth-callback"},
    }
    audience_scope_id: str | None = None
    scopes = _request_json(f"{admin_root}/client-scopes", token=admin_token)
    audience_scope = next(
        (scope for scope in scopes if scope.get("name") == "eventflow-api-audience"),
        None,
    )
    if audience_scope is None:
        raise BootstrapError("The eventflow-api-audience client scope is missing.")
    audience_scope_id = audience_scope.get("id")
    mappers = _request_json(
        f"{admin_root}/client-scopes/{audience_scope_id}/protocol-mappers/models",
        token=admin_token,
    )
    audience_mapper = next(
        (
            mapper
            for mapper in mappers
            if mapper.get("protocolMapper") == "oidc-audience-mapper"
            and mapper.get("config", {}).get("included.client.audience")
            == "eventflow-api"
            and mapper.get("config", {}).get("access.token.claim") == "true"
        ),
        None,
    )
    if audience_mapper is None:
        raise BootstrapError(
            "The access-token eventflow-api audience mapper is missing."
        )

    for client_id in client_ids:
        response = _request_json(
            f"{admin_root}/clients?{urlencode({'clientId': client_id})}",
            token=admin_token,
        )
        client = next(
            (item for item in response if item.get("clientId") == client_id), None
        )
        if client is None:
            raise BootstrapError(f"Required Keycloak client is missing: {client_id}.")
        if (
            client.get("enabled") is not True
            or client.get("protocol") != "openid-connect"
            or client.get("publicClient") is not True
            or client.get("standardFlowEnabled") is not True
            or client.get("implicitFlowEnabled") is not False
            or client.get("directAccessGrantsEnabled") is not False
            or client.get("serviceAccountsEnabled") is not False
            or client.get("attributes", {}).get("pkce.code.challenge.method") != "S256"
            or set(client.get("redirectUris", [])) != expected_redirects[client_id]
        ):
            raise BootstrapError(
                f"Keycloak client security configuration mismatch: {client_id}."
            )
        if client_id == "eventflow-web-bff" and set(client.get("webOrigins", [])) != {
            "http://localhost:5173",
            "http://localhost:8000",
        }:
            raise BootstrapError(
                "The web BFF Keycloak origins do not match the local allowlist."
            )
        default_scopes = _request_json(
            f"{admin_root}/clients/{client['id']}/default-client-scopes",
            token=admin_token,
        )
        if not any(
            scope.get("name") == "eventflow-api-audience" for scope in default_scopes
        ):
            raise BootstrapError(
                f"The API audience scope is not assigned to {client_id}."
            )

    username = values["EVENTFLOW_TEST_KEYCLOAK_USERNAME"]
    users_url = (
        f"{admin_root}/users?{urlencode({'username': username, 'exact': 'true'})}"
    )
    users = _request_json(users_url, token=admin_token)
    user = next((item for item in users if item.get("username") == username), None)
    if user is None:
        _request_json(
            f"{admin_root}/users",
            json_body={
                "username": username,
                "email": "eventflow-test@example.invalid",
                "firstName": "EventFlow",
                "lastName": "Integration Test",
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
                "credentials": [
                    {
                        "type": "password",
                        "value": values["EVENTFLOW_TEST_KEYCLOAK_PASSWORD"],
                        "temporary": False,
                    }
                ],
            },
            token=admin_token,
            method="POST",
        )
        users = _request_json(users_url, token=admin_token)
        user = next((item for item in users if item.get("username") == username), None)
    if user is None or user.get("enabled") is not True:
        raise BootstrapError(
            "The generated Keycloak test identity is missing or disabled."
        )


def _compose(
    values: dict[str, str], env_path: Path, *command: str
) -> subprocess.CompletedProcess[str]:
    compose = [
        "docker",
        "compose",
        "--project-name",
        values["EVENTFLOW_AUTH_COMPOSE_PROJECT"],
        "--env-file",
        str(env_path.relative_to(ROOT)).replace("\\", "/"),
        "--profile",
        "auth",
    ]
    result = subprocess.run(
        [*compose, *command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, **values},
        check=False,
    )
    if result.returncode:
        raise BootstrapError(
            "Docker Compose failed (exit "
            f"{result.returncode}). Check Docker availability and configured ports; "
            "diagnostic output was suppressed to protect local credentials."
        )
    return result


def _append_github_environment(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise BootstrapError(f"Invalid newline in environment setting {name}.")
            stream.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keycloak-port", type=int)
    parser.add_argument("--postgres-port", type=int)
    parser.add_argument("--project-name")
    parser.add_argument("--github-env", help=argparse.SUPPRESS)
    parser.add_argument(
        "--stop", action="store_true", help="stop this project's containers"
    )
    parser.add_argument(
        "--volumes",
        action="store_true",
        help="also remove project database volumes with --stop",
    )
    args = parser.parse_args()
    if args.volumes and not args.stop:
        parser.error("--volumes is valid only with --stop")
    try:
        if args.stop and not ENVIRONMENT_FILE.exists():
            print("No generated authentication environment exists; nothing to stop.")
            return 0
        env_path, values, start_postgres = ensure_local_configuration(
            keycloak_port=args.keycloak_port,
            postgres_port=args.postgres_port,
            project_name=args.project_name,
        )
        if args.github_env:
            _append_github_environment(Path(args.github_env), values)
        if args.stop:
            if args.volumes and not start_postgres:
                raise BootstrapError(
                    "Refusing to remove database volumes for a pre-existing shared environment."
                )
            if start_postgres:
                volume_args = ["--volumes"] if args.volumes else []
                _compose(
                    values,
                    env_path,
                    "down",
                    *volume_args,
                )
            else:
                _compose(values, env_path, "stop", "keycloak")
            print("Stopped the local EventFlow authentication stack.")
            return 0
        services = ("postgres", "keycloak") if start_postgres else ("keycloak",)
        _compose(values, env_path, "up", "-d", "--wait", *services)
        verify_keycloak(values)
        if start_postgres and args.github_env:
            print(
                "Local Keycloak and PostgreSQL are ready; generated values were not displayed."
            )
        elif start_postgres:
            print(
                "Local Keycloak and PostgreSQL are ready. Shared credentials are stored in "
                f"{env_path.relative_to(ROOT)}; generated values were not displayed."
            )
        else:
            print(
                "Local Keycloak is ready. The existing shared environment file was preserved; "
                "PostgreSQL was not restarted."
            )
        return 0
    except BootstrapError as exc:
        print(f"Authentication environment setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
