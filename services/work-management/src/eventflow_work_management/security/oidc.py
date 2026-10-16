"""Keycloak-compatible OIDC discovery, code exchange and strict JWT validation."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from jwt import InvalidTokenError
from jwt.exceptions import MissingRequiredClaimError

from eventflow_work_management.security.config import AuthSettings


class OIDCError(RuntimeError):
    """An OIDC operation failed without exposing provider response details."""


class OIDCProviderUnavailable(OIDCError):
    """The configured identity provider could not be reached safely."""


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    access_expires_at: int
    refresh_expires_at: int | None
    id_token: str | None = None


class OIDCClient:
    """OIDC client that trusts only the configured issuer and its JWKS endpoint."""

    def __init__(
        self,
        settings: AuthSettings,
        *,
        http: httpx.Client | None = None,
        clock=time.time,
    ) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0))
        self._owns_http = http is None
        self._clock = clock
        self._lock = threading.RLock()
        self._metadata: dict[str, Any] | None = None
        self._metadata_expires = 0.0
        self._jwks: dict[str, dict[str, Any]] = {}
        self._jwks_expires = 0.0
        self._last_jwks_refresh_attempt = 0.0

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def _same_origin(self, url: str) -> bool:
        issuer = urlparse(self.settings.issuer)
        target = urlparse(url)
        try:
            origins_match = (target.scheme, target.hostname, target.port) == (
                issuer.scheme,
                issuer.hostname,
                issuer.port,
            )
        except ValueError:
            return False
        return (
            not target.username
            and not target.password
            and not target.query
            and not target.fragment
            and origins_match
        )

    def discovery(self, *, force: bool = False) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            if (
                self._metadata is not None
                and self._metadata_expires > now
                and not force
            ):
                return self._metadata
            url = f"{self.settings.issuer}/.well-known/openid-configuration"
            try:
                response = self.http.get(url)
                response.raise_for_status()
                metadata = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OIDCProviderUnavailable("OIDC discovery is unavailable") from exc
            if not isinstance(metadata, dict):
                raise OIDCError("OIDC discovery document is invalid")
            discovered_issuer = metadata.get("issuer")
            if (
                not isinstance(discovered_issuer, str)
                or discovered_issuer.rstrip("/") != self.settings.issuer
            ):
                raise OIDCError(
                    "OIDC discovery issuer does not match configured issuer"
                )
            required = (
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
                "revocation_endpoint",
            )
            if any(not isinstance(metadata.get(key), str) for key in required):
                raise OIDCError("OIDC discovery document is incomplete")
            for key in required:
                if not self._same_origin(metadata[key]):
                    raise OIDCError(
                        f"OIDC discovery {key} must use the configured issuer origin"
                    )
            self._metadata = metadata
            self._metadata_expires = now + 300
            return metadata

    def _load_jwks(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        now = self._clock()
        with self._lock:
            if self._jwks and self._jwks_expires > now and not force:
                return self._jwks
            if force and self._jwks and now - self._last_jwks_refresh_attempt < 30:
                return self._jwks
            jwks_uri = self.discovery(force=force)["jwks_uri"]
            if force:
                self._last_jwks_refresh_attempt = now
            try:
                response = self.http.get(jwks_uri)
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OIDCProviderUnavailable(
                    "OIDC signing keys are unavailable"
                ) from exc
            if not isinstance(document, dict):
                raise OIDCError("OIDC JWKS document is invalid")
            keys = document.get("keys")
            if not isinstance(keys, list):
                raise OIDCError("OIDC JWKS document is invalid")
            parsed: dict[str, dict[str, Any]] = {}
            for item in keys:
                if not isinstance(item, dict):
                    continue
                kid = item.get("kid")
                if (
                    isinstance(kid, str)
                    and item.get("kty") == "RSA"
                    and item.get("use", "sig") == "sig"
                    and item.get("alg", "RS256") == "RS256"
                ):
                    parsed[kid] = item
            if not parsed:
                raise OIDCError("OIDC JWKS contains no approved RSA signing keys")
            self._jwks = parsed
            self._jwks_expires = now + self.settings.jwks_cache_seconds
            return parsed

    def _key_for(self, token: str) -> Any:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise OIDCError("token header is invalid") from exc
        if header.get("alg") != "RS256":
            raise OIDCError("token signing algorithm is not allowed")
        if header.get("crit"):
            raise OIDCError("token uses an unsupported critical JOSE header")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise OIDCError("token has no signing key identifier")
        keys = self._load_jwks()
        if kid not in keys:
            # A rotated signing key may be published before the cache expires.
            keys = self._load_jwks(force=True)
        jwk = keys.get(kid)
        if jwk is None:
            raise OIDCError("token signing key is not trusted")
        try:
            return jwt.PyJWK.from_dict(jwk, algorithm="RS256").key
        except (InvalidTokenError, ValueError, TypeError) as exc:
            raise OIDCError("token signing key is invalid") from exc

    def validate_access_token(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise OIDCError("access token is invalid")
        key = self._key_for(token)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.audience,
                leeway=self.settings.access_token_leeway_seconds,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except InvalidTokenError as exc:
            reason = type(exc).__name__
            if isinstance(exc, MissingRequiredClaimError):
                reason = f"{reason}:{exc.claim}"
            raise OIDCError(f"access token validation failed:{reason}") from exc
        if claims.get("typ") not in (None, "Bearer"):
            raise OIDCError("ID tokens cannot be used as API access tokens")
        registered_clients = {
            self.settings.web_client_id,
            *self.settings.native_client_ids,
        }
        if claims.get("azp") not in registered_clients:
            raise OIDCError(
                "access token was issued to an unregistered EventFlow client"
            )
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OIDCError("access token subject is invalid")
        return claims

    def validate_id_token(self, token: str, *, nonce_digest: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise OIDCError("ID token is invalid")
        key = self._key_for(token)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=self.settings.web_client_id,
                leeway=self.settings.access_token_leeway_seconds,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
        except InvalidTokenError as exc:
            reason = type(exc).__name__
            if isinstance(exc, MissingRequiredClaimError):
                reason = f"{reason}:{exc.claim}"
            raise OIDCError(f"ID token validation failed:{reason}") from exc
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(
            hashlib.sha256(nonce.encode("utf-8")).hexdigest(), nonce_digest
        ):
            raise OIDCError("ID token nonce does not match the login transaction")
        authorized_party = claims.get("azp")
        if authorized_party is not None and authorized_party != self.settings.web_client_id:
            raise OIDCError("ID token authorized party does not match the web client")
        if isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1:
            if authorized_party != self.settings.web_client_id:
                raise OIDCError("ID token is missing the expected authorized party")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OIDCError("ID token subject is invalid")
        return claims

    def authorization_url(self, *, state: str, nonce: str, challenge: str) -> str:
        metadata = self.discovery()
        return str(
            httpx.URL(metadata["authorization_endpoint"]).copy_merge_params(
                {
                    "client_id": self.settings.web_client_id,
                    "response_type": "code",
                    "scope": "openid eventflow-api-audience",
                    "redirect_uri": self.settings.redirect_uri,
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    def exchange_code(self, *, code: str, verifier: str) -> TokenSet:
        metadata = self.discovery()
        try:
            response = self.http.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.web_client_id,
                    "code": code,
                    "redirect_uri": self.settings.redirect_uri,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise OIDCProviderUnavailable("OIDC token endpoint failed") from exc
            raise OIDCError("authorization code exchange failed") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCProviderUnavailable("OIDC token endpoint is unavailable") from exc
        return self._token_set(payload)

    def refresh(self, refresh_token: str) -> TokenSet:
        metadata = self.discovery()
        try:
            response = self.http.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.settings.web_client_id,
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise OIDCProviderUnavailable("OIDC token endpoint failed") from exc
            raise OIDCError("refresh token exchange failed") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCProviderUnavailable("OIDC token endpoint is unavailable") from exc
        return self._token_set(payload)

    def revoke(self, refresh_token: str) -> None:
        metadata = self.discovery()
        try:
            response = self.http.post(
                metadata["revocation_endpoint"],
                data={
                    "client_id": self.settings.web_client_id,
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OIDCProviderUnavailable("provider token revocation failed") from exc

    def _token_set(self, payload: Any) -> TokenSet:
        if not isinstance(payload, dict):
            raise OIDCError("OIDC token response is invalid")
        access_token = payload.get("access_token")
        token_type = payload.get("token_type", "")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise OIDCError(
                "OIDC token response is missing required bearer credentials"
            )
        refresh_token = payload.get("refresh_token")
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise OIDCError("OIDC refresh token is invalid")
        refresh_expires_in = payload.get("refresh_expires_in")
        refresh_expires_at = (
            int(self._clock()) + refresh_expires_in
            if isinstance(refresh_expires_in, int)
            and not isinstance(refresh_expires_in, bool)
            and refresh_expires_in > 0
            else None
        )
        return TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=int(self._clock()) + expires_in,
            refresh_expires_at=refresh_expires_at,
            id_token=payload.get("id_token")
            if isinstance(payload.get("id_token"), str)
            else None,
        )
