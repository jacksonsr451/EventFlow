"""Contract tests for the Issue #10 OIDC/BFF authentication API."""

from __future__ import annotations

import pathlib

import testrunner
import yaml
from openapi_spec_validator import validate

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "authentication.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
FORBIDDEN_RESPONSE_FIELDS = {"access_token", "refresh_token", "id_token", "client_secret"}


def load_openapi():
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def iter_operations(document):
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def test_authentication_openapi_is_valid():
    validate(load_openapi(), base_uri=OPENAPI_PATH.as_uri())


def test_authentication_routes_use_v1_and_have_unique_operation_ids():
    document = load_openapi()
    ids = []
    for path, _, operation in iter_operations(document):
        assert path.startswith("/v1/auth/")
        ids.append(operation.get("operationId"))
    assert ids and all(ids)
    assert len(ids) == len(set(ids))


def test_approved_oidc_and_principal_security_schemes():
    document = load_openapi()
    schemes = document["components"]["securitySchemes"]
    assert schemes["bearerAuth"]["type"] == "http"
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert schemes["sessionCookieAuth"]["type"] == "apiKey"
    assert schemes["sessionCookieAuth"]["in"] == "cookie"
    principal = document["paths"]["/v1/auth/principal"]["get"]
    assert {tuple(requirement) for requirement in principal["security"]} == {
        ("bearerAuth",),
        ("sessionCookieAuth",),
    }


def test_oauth_code_flow_declares_state_nonce_and_pkce():
    document = load_openapi()
    login = document["paths"]["/v1/auth/oidc/login"]["get"]
    description = login["description"].lower()
    for required in ("state", "nonce", "browser", "pkce", "s256", "fixed configuration"):
        assert required in description
    assert login["responses"]["302"]


def test_cookie_mutations_require_csrf():
    document = load_openapi()
    csrf = document["components"]["parameters"]["CsrfToken"]
    assert csrf["required"] is True
    assert csrf["in"] == "header"
    assert csrf["name"] == "X-CSRF-Token"
    for path, method in (
        ("/v1/auth/refresh", "post"),
        ("/v1/auth/logout", "post"),
        ("/v1/auth/sessions/{session_id}", "delete"),
    ):
        refs = [
            parameter.get("$ref")
            for parameter in document["paths"][path][method].get("parameters", [])
        ]
        assert "#/components/parameters/CsrfToken" in refs


def test_public_session_responses_never_contain_provider_tokens():
    schemas = yaml.safe_load(
        (REPO_ROOT / "contracts" / "schemas" / "authentication.yaml").read_text(
            encoding="utf-8"
        )
    )["$defs"]
    for definition in ("AuthenticatedPrincipalResponse", "BffSessionResponse", "AuthenticationSession"):
        fields = set(schemas[definition]["properties"])
        assert not fields.intersection(FORBIDDEN_RESPONSE_FIELDS), definition
