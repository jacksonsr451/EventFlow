"""End-to-end Authorization Code + PKCE test against the local Keycloak realm."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from uuid import UUID

import httpx
import jwt
import testrunner
from eventflow_work_management.api.app import create_app
from eventflow_work_management.models.authentication import (
    AuthenticationSecurityEvent,
    AuthenticationSession,
    ExternalIdentity,
)
from eventflow_work_management.security.config import AuthSettings
from eventflow_work_management.security.crypto import TokenCipher, digest_token
from eventflow_work_management.security.oidc import OIDCClient, OIDCError
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from support import require_database_url, temporary_database


class _LoginFormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action", ""), "inputs": {}}
        elif tag == "input" and self.current is not None:
            name = attrs.get("name")
            if name:
                self.current["inputs"][name] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def _complete_keycloak_login(authorization_url: str) -> str:
    """Drive Keycloak's real login form over HTTP and return its registered callback."""
    browser = httpx.Client(follow_redirects=False, timeout=30)
    flow = []

    def local_cookie_header() -> str:
        # Modern browsers treat loopback as a trustworthy local context and send
        # Secure cookies there. httpx deliberately applies the stricter network
        # rule, so this test-only adapter mirrors browser behavior for localhost.
        return "; ".join(f"{item.name}={item.value}" for item in browser.cookies.jar)

    try:
        page = browser.get(authorization_url)
        for _ in range(8):
            location = page.headers.get("location")
            if not location:
                break
            page = browser.get(
                urljoin(str(page.url), location),
                headers={"Cookie": local_cookie_header()},
                follow_redirects=False,
            )
        page.raise_for_status()
        parser = _LoginFormParser()
        parser.feed(page.text)
        form = next(
            (
                item
                for item in parser.forms
                if "username" in item["inputs"] and "password" in item["inputs"]
            ),
            None,
        )
        assert form is not None, "Keycloak did not render its standard login form"
        form_action = urljoin(str(page.url), form["action"])
        data = dict(form["inputs"])
        data["username"] = os.environ["EVENTFLOW_TEST_KEYCLOAK_USERNAME"]
        data["password"] = os.environ["EVENTFLOW_TEST_KEYCLOAK_PASSWORD"]
        response = browser.post(
            form_action,
            data=data,
            headers={"Cookie": local_cookie_header()},
            follow_redirects=False,
        )
        flow.append((response.status_code, urlsplit(str(response.url)).path))
        if response.status_code >= 400:
            sent_cookie_names = [
                item.split("=", 1)[0]
                for item in response.request.headers.get("cookie", "").split("; ")
                if item
            ]
            raise AssertionError(
                "Keycloak rejected the local test login; "
                f"status={response.status_code}, cookie_names={sent_cookie_names}, "
                f"stored_cookies={[(item.name, item.domain, item.path, item.secure) for item in browser.cookies.jar]}, "
                f"host={urlsplit(str(response.request.url)).netloc}, "
                f"form_host={urlsplit(form_action).netloc}"
            )
        for _ in range(8):
            location = response.headers.get("location")
            if not location:
                break
            target = urljoin(str(response.url), location)
            parsed = urlsplit(target)
            flow.append((response.status_code, parsed.path))
            if parsed.path == "/v1/auth/oidc/callback":
                params = parse_qs(parsed.query)
                assert params.get("code"), (
                    "Keycloak callback omitted the authorization code"
                )
                assert params.get("state"), "Keycloak callback omitted state"
                return parsed.path + "?" + parsed.query
            response = browser.get(
                target,
                headers={"Cookie": local_cookie_header()},
                follow_redirects=False,
            )
            flow.append((response.status_code, urlsplit(str(response.url)).path))
        raise AssertionError(
            f"Keycloak did not complete the code flow (HTTP {response.status_code}, paths={flow})"
        )
    finally:
        browser.close()


def test_keycloak_pkce_session_principal_refresh_revocation_and_replay():
    if os.environ.get("EVENTFLOW_AUTH_INTEGRATION") != "1":
        testrunner.skip(
            "set EVENTFLOW_AUTH_INTEGRATION=1 and start the local Keycloak auth profile"
        )
    admin_url = require_database_url()
    settings = AuthSettings.from_env()
    cipher = TokenCipher(settings.token_encryption_keys)

    with temporary_database(admin_url) as (_, engine):
        oidc_client = OIDCClient(settings)
        exchanged_tokens = []
        original_exchange = oidc_client.exchange_code

        def capture_exchange(**kwargs):
            result = original_exchange(**kwargs)
            exchanged_tokens.append(result)
            return result

        oidc_client.exchange_code = capture_exchange
        app = create_app(settings=settings, engine=engine, oidc_client=oidc_client)
        with TestClient(
            app,
            base_url="https://localhost",
            follow_redirects=False,
        ) as client:
            # The configured public client must reject a real authorization code
            # when the verifier does not match the published S256 challenge.
            wrong_pkce_start = client.get("/v1/auth/oidc/login")
            wrong_pkce_callback = _complete_keycloak_login(
                wrong_pkce_start.headers["location"]
            )
            wrong_pkce_params = parse_qs(urlsplit(wrong_pkce_callback).query)
            with testrunner.raises(OIDCError):
                oidc_client.exchange_code(
                    code=wrong_pkce_params["code"][0],
                    verifier="x" * 64,
                )

            start = client.get("/v1/auth/oidc/login")
            assert start.status_code == 302
            authorization_url = start.headers["location"]
            query = parse_qs(urlsplit(authorization_url).query)
            assert query["response_type"] == ["code"]
            assert query["code_challenge_method"] == ["S256"]
            assert "code_verifier" not in query
            state_cookie = client.cookies.get(settings.oidc_state_cookie_name)
            assert state_cookie

            callback = _complete_keycloak_login(authorization_url)
            callback_parts = urlsplit(callback)
            invalid_state_params = parse_qs(callback_parts.query)
            invalid_state_params["state"] = ["invalid-state-from-another-flow"]
            invalid_state = client.get(
                callback_parts.path
                + "?"
                + urlencode(invalid_state_params, doseq=True)
            )
            assert invalid_state.status_code == 400
            completed = client.get(callback)
            if completed.status_code != 303:
                with Session(engine) as db_session:
                    reasons = [
                        event.details.get("reason")
                        for event in db_session.execute(
                            select(AuthenticationSecurityEvent)
                        ).scalars()
                    ]
                token_claim_keys = (
                    sorted(
                        jwt.decode(
                            exchanged_tokens[0].access_token,
                            options={"verify_signature": False},
                        ).keys()
                    )
                    if exchanged_tokens
                    else []
                )
                raise AssertionError(
                    "Keycloak callback failed with sanitized audit reasons "
                    f"{reasons}; unverified access-token claim names={token_claim_keys}; "
                    f"problem={completed.json()}"
                )
            assert completed.status_code == 303
            assert completed.headers["location"] == settings.frontend_redirect_uri
            assert "access_token" not in completed.headers["location"]
            assert "refresh_token" not in completed.headers["location"]
            set_cookies = "\n".join(completed.headers.get_list("set-cookie"))
            assert settings.session_cookie_name in set_cookies
            assert "HttpOnly" in set_cookies
            assert "Secure" in set_cookies
            assert "SameSite=lax" in set_cookies

            current = client.get("/v1/auth/session")
            assert current.status_code == 200
            session_data = current.json()
            session_cookie = client.cookies.get(settings.session_cookie_name)
            assert session_cookie
            assert session_data["user_id"]
            assert session_data["session_id"]
            assert session_data["csrf_token"]
            assert "access_token" not in current.text
            assert "refresh_token" not in current.text

            with Session(engine) as session:
                identities = (
                    session.execute(
                        select(ExternalIdentity).where(
                            ExternalIdentity.issuer == settings.issuer
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(identities) == 1
                stored_session = session.get(
                    AuthenticationSession, UUID(session_data["session_id"])
                )
                assert stored_session is not None
                raw_cookie = client.cookies.get(settings.session_cookie_name)
                assert raw_cookie
                assert stored_session.session_token_digest == digest_token(raw_cookie)
                access_token = cipher.decrypt(stored_session.access_token_ciphertext)
                access_claims = jwt.decode(
                    access_token, options={"verify_signature": False}
                )
                token_audience = access_claims["aud"]
                assert "eventflow-api" in (
                    token_audience
                    if isinstance(token_audience, list)
                    else [token_audience]
                )
                old_refresh = cipher.decrypt(stored_session.refresh_token_ciphertext)

            principal = client.get(
                "/v1/auth/principal",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert principal.status_code == 200
            assert principal.json() == {"user_id": session_data["user_id"]}
            client.cookies.clear()
            impersonation = client.get(
                "/v1/auth/principal",
                headers={"X-User-ID": "00000000-0000-4000-8000-000000000001"},
            )
            assert impersonation.status_code == 401
            session_cookie_header = {
                "Cookie": f"{settings.session_cookie_name}={session_cookie}"
            }

            sessions = client.get("/v1/auth/sessions", headers=session_cookie_header)
            assert sessions.status_code == 200
            assert any(item["current"] for item in sessions.json())

            # Force expiry in the disposable database to exercise Keycloak's
            # real refresh-token rotation without waiting five minutes.
            with Session(engine) as session:
                stored_session = session.get(
                    AuthenticationSession, UUID(session_data["session_id"])
                )
                stored_session.access_expires_at = datetime.now(UTC)
                session.commit()
            missing_csrf = client.post(
                "/v1/auth/refresh",
                headers={**session_cookie_header, "Origin": "https://localhost"},
            )
            assert missing_csrf.status_code == 403
            invalid_csrf = client.post(
                "/v1/auth/refresh",
                headers={
                    **session_cookie_header,
                    "Origin": "https://localhost",
                    "X-CSRF-Token": "incorrect-session-bound-token",
                },
            )
            assert invalid_csrf.status_code == 403
            disallowed_origin = client.post(
                "/v1/auth/refresh",
                headers={
                    **session_cookie_header,
                    "Origin": "https://attacker.example",
                    "X-CSRF-Token": session_data["csrf_token"],
                },
            )
            assert disallowed_origin.status_code == 403
            refreshed = client.post(
                "/v1/auth/refresh",
                headers={
                    **session_cookie_header,
                    "Origin": "https://localhost",
                    "X-CSRF-Token": session_data["csrf_token"],
                },
            )
            assert refreshed.status_code == 200
            with Session(engine) as session:
                stored_session = session.get(
                    AuthenticationSession, UUID(session_data["session_id"])
                )
                assert (
                    cipher.decrypt(stored_session.refresh_token_ciphertext)
                    != old_refresh
                )

            logout = client.post(
                "/v1/auth/logout",
                headers={
                    **session_cookie_header,
                    "Origin": "https://localhost",
                    "X-CSRF-Token": session_data["csrf_token"],
                },
            )
            assert logout.status_code == 204
            assert client.get("/v1/auth/session").status_code == 401

            # Even restoring the browser binding cannot replay a consumed state.
            replay = client.get(
                callback,
                headers={"Cookie": f"{settings.oidc_state_cookie_name}={state_cookie}"},
            )
            assert replay.status_code == 400

        with Session(engine) as session:
            event_types = {
                row[0]
                for row in session.execute(
                    select(AuthenticationSecurityEvent.event_type)
                ).all()
            }
        assert {
            "auth.success",
            "session.created",
            "auth.refresh_success",
            "auth.logout",
            "session.revoked",
            "auth.replay_detected",
        } <= event_types
