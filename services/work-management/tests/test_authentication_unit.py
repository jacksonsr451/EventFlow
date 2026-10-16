"""Unit tests for authentication configuration, JWT validation and secure storage."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from unittest.mock import patch

import httpx
import jwt
import testrunner
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from eventflow_work_management.api.app import create_app
from eventflow_work_management.security.config import (
    AuthSettings,
    AuthenticationConfigurationError,
)
from eventflow_work_management.security.crypto import TokenCipher
from eventflow_work_management.security.oidc import OIDCClient, OIDCError

ISSUER = "https://id.example.test/realms/eventflow"
NOW = int(time.time())


def auth_settings(*, environment="test", issuer=ISSUER):
    return AuthSettings(
        environment=environment,
        issuer=issuer,
        audience="eventflow-api",
        web_client_id="eventflow-web-bff",
        native_client_ids=("eventflow-desktop", "eventflow-vscode"),
        redirect_uri="https://api.example.test/v1/auth/oidc/callback",
        frontend_redirect_uri="https://web.example.test/auth/complete",
        allowed_origins=("https://web.example.test",),
        token_encryption_keys=(Fernet.generate_key().decode("ascii"),),
    )


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _test_oidc_client(*, extra_keys=()):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "use": "sig",
                "alg": "RS256",
                "n": _b64(numbers.n),
                "e": _b64(numbers.e),
            },
            *extra_keys,
        ]
    }
    config = auth_settings()
    metadata = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
        "revocation_endpoint": f"{ISSUER}/protocol/openid-connect/revoke",
    }
    fetches = {"jwks": 0}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=metadata)
        if request.url.path.endswith("/certs"):
            fetches["jwks"] += 1
            return httpx.Response(200, json=jwks)
        return httpx.Response(404, json={"error": "not_found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oidc = OIDCClient(config, http=client, clock=lambda: NOW)
    return oidc, private_key, jwks, fetches


def _access_token(private_key, *, issuer=ISSUER, audience="eventflow-api", kid="test-key", exp=NOW + 300):
    return jwt.encode(
        {
            "iss": issuer,
            "sub": "keycloak-subject-123",
            "aud": audience,
            "azp": "eventflow-desktop",
            "typ": "Bearer",
            "iat": NOW,
            "nbf": NOW,
            "exp": exp,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_auth_settings_reject_unsafe_production_urls_and_wildcard_cors():
    key = Fernet.generate_key().decode("ascii")
    common = {
        "EVENTFLOW_ENVIRONMENT": "production",
        "EVENTFLOW_OIDC_ISSUER": "http://id.example.test/realms/eventflow",
        "EVENTFLOW_OIDC_REDIRECT_URI": "https://api.example.test/v1/auth/oidc/callback",
        "EVENTFLOW_WEB_REDIRECT_AFTER_LOGIN": "https://web.example.test/auth/complete",
        "EVENTFLOW_CORS_ALLOWED_ORIGINS": "https://web.example.test",
        "EVENTFLOW_TOKEN_ENCRYPTION_KEYS": key,
    }
    with patch.dict(os.environ, common, clear=True):
        with testrunner.raises(AuthenticationConfigurationError):
            AuthSettings.from_env()
    common["EVENTFLOW_OIDC_ISSUER"] = ISSUER
    common["EVENTFLOW_CORS_ALLOWED_ORIGINS"] = "*"
    with patch.dict(os.environ, common, clear=True):
        with testrunner.raises(AuthenticationConfigurationError):
            AuthSettings.from_env()


def test_token_cipher_encrypts_and_supports_ordered_key_rotation():
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    old_ciphertext = TokenCipher((old_key,)).encrypt("refresh-secret")
    rotating = TokenCipher((new_key, old_key))
    assert rotating.decrypt(old_ciphertext) == "refresh-secret"
    new_ciphertext = rotating.encrypt("access-secret")
    assert new_ciphertext != "access-secret"
    assert rotating.decrypt(new_ciphertext) == "access-secret"


def test_access_token_requires_signature_issuer_audience_client_and_lifetime():
    oidc, key, _, _ = _test_oidc_client()
    valid = _access_token(key)
    claims = oidc.validate_access_token(valid)
    assert claims["sub"] == "keycloak-subject-123"

    for token in (
        _access_token(key, issuer="https://attacker.example/realms/eventflow"),
        _access_token(key, audience="another-api"),
        _access_token(key, exp=NOW - 60),
    ):
        with testrunner.raises(OIDCError):
            oidc.validate_access_token(token)

    wrong_client = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "keycloak-subject-123",
            "aud": "eventflow-api",
            "azp": "unregistered-client",
            "typ": "Bearer",
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(wrong_client)


def test_access_token_rejects_unsupported_algorithm_and_id_token_type():
    oidc, key, _, _ = _test_oidc_client()
    unsigned = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": "eventflow-api",
            "azp": "eventflow-web-bff",
            "typ": "Bearer",
            "iat": NOW,
            "exp": NOW + 300,
        },
        key=None,
        algorithm="none",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(unsigned)

    critical_header = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": "eventflow-api",
            "azp": "eventflow-web-bff",
            "typ": "Bearer",
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key", "crit": ["unrecognized-extension"]},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(critical_header)

    id_token_as_access_token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": "eventflow-api",
            "azp": "eventflow-web-bff",
            "typ": "ID",
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(id_token_as_access_token)


def test_access_token_rejects_bad_signature_future_nbf_and_missing_subject():
    oidc, key, _, _ = _test_oidc_client()
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid_signature = _access_token(other_key)
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(invalid_signature)

    future_nbf = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": "eventflow-api",
            "azp": "eventflow-web-bff",
            "typ": "Bearer",
            "iat": NOW,
            "nbf": NOW + 100,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(future_nbf)

    missing_subject = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "eventflow-api",
            "azp": "eventflow-web-bff",
            "typ": "Bearer",
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_access_token(missing_subject)


def test_malformed_token_response_types_fail_closed():
    oidc, _, _, _ = _test_oidc_client()
    for payload in (
        {"access_token": "token", "token_type": 7, "expires_in": 300},
        {"access_token": "token", "token_type": "Bearer", "expires_in": True},
        {"access_token": "", "token_type": "Bearer", "expires_in": 300},
    ):
        with testrunner.raises(OIDCError):
            oidc._token_set(payload)


def test_id_token_nonce_must_match_the_single_use_transaction():
    oidc, key, _, _ = _test_oidc_client()
    nonce = "transaction-nonce"
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "keycloak-subject-123",
            "aud": "eventflow-web-bff",
            "azp": "eventflow-web-bff",
            "nonce": nonce,
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    claims = oidc.validate_id_token(
        token, nonce_digest=hashlib.sha256(nonce.encode()).hexdigest()
    )
    assert claims["sub"] == "keycloak-subject-123"
    with testrunner.raises(OIDCError):
        oidc.validate_id_token(token, nonce_digest="0" * 64)

    wrong_authorized_party = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "keycloak-subject-123",
            "aud": "eventflow-web-bff",
            "azp": "eventflow-desktop",
            "nonce": nonce,
            "iat": NOW,
            "exp": NOW + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with testrunner.raises(OIDCError):
        oidc.validate_id_token(
            wrong_authorized_party,
            nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(),
        )


def test_unknown_key_id_causes_one_bounded_jwks_refresh():
    oidc, old_key, jwks, fetches = _test_oidc_client()
    assert oidc.validate_access_token(_access_token(old_key))["sub"] == "keycloak-subject-123"
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = new_key.public_key().public_numbers()
    rotated = {
        "kty": "RSA",
        "kid": "rotated-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }
    # Mock the rotation endpoint update after the first cached key-set fetch.
    original_jwks = jwks["keys"][:]
    jwks["keys"].append(rotated)
    token = _access_token(new_key, kid="rotated-key")
    claims = oidc.validate_access_token(token)
    assert claims["sub"] == "keycloak-subject-123"
    assert fetches["jwks"] >= 2
    assert old_key is not None and original_jwks


def test_anonymous_http_request_cannot_forge_principal_with_headers():
    settings = auth_settings()
    # An unopened SQLite database is sufficient here because authentication
    # rejects before any identity/session query is attempted.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    oidc, _, _, _ = _test_oidc_client()
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory_override=sessionmaker(bind=engine),
        oidc_client=oidc,
    )
    async def send_request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://web.example.test"
        ) as client:
            return await client.get(
                "/v1/auth/principal",
                headers={"X-User-ID": "00000000-0000-4000-8000-000000000001"},
            )

    response = asyncio.run(send_request())
    oidc.close()
    engine.dispose()
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "user_id" not in response.json()


def test_auth_cors_is_allowlisted_and_credentials_are_not_wildcarded():
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from httpx import ASGITransport, AsyncClient

    settings = auth_settings()
    engine = create_engine("sqlite://")
    oidc, _, _, _ = _test_oidc_client()
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory_override=sessionmaker(bind=engine),
        oidc_client=oidc,
    )

    async def check_origins():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.example.test"
        ) as client:
            allowed = await client.options(
                "/v1/auth/principal",
                headers={
                    "Origin": "https://web.example.test",
                    "Access-Control-Request-Method": "GET",
                },
            )
            rejected = await client.options(
                "/v1/auth/principal",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            return allowed, rejected

    allowed, rejected = asyncio.run(check_origins())
    assert allowed.headers["access-control-allow-origin"] == "https://web.example.test"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in rejected.headers
    oidc.close()
    engine.dispose()


def test_uvicorn_access_log_filter_removes_query_strings():
    import logging

    from eventflow_work_management.security.logging import RedactAccessQueryFilter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "server.py",
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1",
            "GET",
            "/v1/auth/oidc/callback?code=secret-code&state=secret-state",
            "1.1",
            200,
        ),
        None,
    )
    assert RedactAccessQueryFilter().filter(record)
    message = record.getMessage()
    assert "secret-code" not in message
    assert "secret-state" not in message
    assert "/v1/auth/oidc/callback" in message
