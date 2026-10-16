# ADR-009: OIDC Authentication and Secure Sessions

## Status

Accepted — implementation for Issue #10.

## Context

Work Management needs a verified user principal before Issue #9 can evaluate
workspace membership and action permissions. Issue #11 defines bearer-authenticated
API operations, but its contract does not validate credentials or establish a
principal. Issue #12 supplies PostgreSQL, SQLAlchemy and Alembic persistence; it
intentionally stores user references as UUIDs without an identity foreign key.

The system serves a Web BFF, a Tauri 2 desktop client and a VS Code extension.
Authentication must be shared through OIDC while each client stores credentials
according to its platform boundary. The repository previously left the identity
provider (OD-01) and access/session lifetimes (OD-02) unresolved.

## Decision

### Identity provider and protocol

- **Keycloak** is the selected OIDC identity provider. EventFlow consumes the
  standard OIDC discovery document and remains configurable for a compatible
  issuer.
- Authorization uses OAuth 2.0 Authorization Code Flow with **PKCE S256** for
  every public client. Implicit and Resource Owner Password grants are not used.
- Keycloak access tokens are JWTs. The backend validates RS256 signatures using
  issuer-bound JWKS, issuer, API audience, expiration, not-before, subject and
  registered client (`azp`) before establishing a principal.
- The Web BFF uses the public `eventflow-web-bff` client with PKCE; no client
  secret is distributed or required by this client registration.
- Public client IDs are `eventflow-desktop` and `eventflow-vscode`. Their
  platform-specific redirect URIs are exact allowlist entries and their
  adapters use PKCE S256.
- The requested scopes are the minimum `openid eventflow-api-audience`; profile
  and email claims are not needed for the internal `(issuer, subject)` mapping.

### Internal identity and principal

- The internal identity is a UUID, independent of email and display name.
- An external identity is uniquely mapped by `(issuer, subject)`.
- The backend creates the immutable `AuthenticatedPrincipal` only after token
  or session validation and identity resolution. A principal contains the
  internal user UUID, issuer, subject and, for BFF sessions, a session UUID.
- Client-supplied identity, workspace role and membership values are never
  trusted. Workspace authorization remains Issue #9.

### FastAPI boundary

- The existing `services/work-management` package is the Work Management HTTP
  boundary and uses FastAPI; it reuses the existing SQLAlchemy engine, Base and
  Alembic tree.
- Authentication routes live under `/v1/auth/`. Work Management routes can
  depend on the same principal dependency and accept a verified bearer token or
  an active BFF cookie session.
- This does not add a second Gateway or an authentication bypass.

### Web BFF sessions

- Web authentication terminates at the backend callback. OAuth tokens are
  encrypted at rest and never returned to browser JavaScript.
- The browser receives only a random opaque, HttpOnly session cookie; production
  uses Secure, SameSite=Lax and the `__Host-` prefix. Local loopback development
  may use HTTP and a non-prefixed cookie.
- Session rows store a digest of the cookie token, encrypted access/refresh
  tokens, CSRF token digest/encrypted value, identity, creation/idle/absolute
  expiry and revocation metadata.
- Initial limits are 5-minute access tokens, 30-minute idle timeout and 12-hour
  absolute EventFlow BFF sessions. These values are configurable within bounded
  ranges. Keycloak is configured with the matching development token/session
  limits; production realm settings must match.
- State and nonce are random, single-use, short-lived and bound to a random
  browser transaction cookie. The PKCE verifier is encrypted in PostgreSQL.
- Cookie-authenticated unsafe requests require exact allowlisted Origin and a
  session-bound `X-CSRF-Token`. CORS is an explicit allowlist and is not treated
  as CSRF protection.

### Desktop and VS Code

- Both use the system browser and Authorization Code + PKCE S256.
- Desktop credential storage is provided through a secure keychain adapter
  interface. A concrete Tauri plugin integration waits for the Tauri app.
- VS Code credential storage uses the SecretStorage-compatible adapter
  interface. A concrete ExtensionHost integration waits for the extension.
- Refresh tokens are never stored in workspace/settings files or WebViews. The
  adapters provide single-flight refresh and always clear local credentials on
  logout, even if provider revocation fails.

### Refresh and revocation

- Keycloak is configured for refresh-token rotation and zero reuse in the
  development realm.
- BFF refresh is serialized by a PostgreSQL row lock. A rotated refresh token
  and replacement access token are encrypted and committed together. Invalid
  refresh credentials revoke the local session; provider outages do not revoke a
  still-valid local session.
- Logout invalidates the local session first and attempts upstream refresh-token
  revocation best-effort. Local logout is not represented as global Keycloak
  logout.

### Persistence, audit and secrets

- Identity mappings, one-use OIDC transactions, server sessions and global
  authentication security events use an incremental Alembic migration.
- Authentication audit events are separate from workspace-scoped `audit_records`
  and are append-only in PostgreSQL.
- Access/refresh tokens and PKCE verifiers are encrypted using an externally
  supplied Fernet key ring (`EVENTFLOW_TOKEN_ENCRYPTION_KEYS`). The first key
  encrypts; later keys allow decrypting during rotation. Production key delivery
  must use the deployment secret manager. Selecting the KMS/rotation operator
  workflow remains under OD-03 / Issue #12.
- OAuth codes, tokens, state, PKCE verifiers and client credentials are not
  logged. Uvicorn access logging is redacted for query strings.

### Development and provider configuration

- Docker Compose offers Keycloak 26.3.3 behind the `auth` profile with a
  development-only imported `eventflow` realm. It binds to loopback, allows
  HTTP only for this local realm, and uses Keycloak's development database. The
  EventFlow BFF cookie remains Secure in test/production, and the EventFlow
  application uses the existing PostgreSQL 17 database for identities, sessions
  and audit events.
- Production Keycloak must use PostgreSQL, TLS, externally managed admin
  credentials, exact redirect URIs and the documented realm settings; the
  development realm and credentials must not be promoted to production.

## Consequences

### Positive

- Every authenticated API request can resolve a stable, verified internal user
  UUID suitable for Issue #9.
- Browser refresh tokens stay server-side; native clients have explicit secure
  storage adapters without inventing full client applications.
- OIDC issuer/subject identity is independent of mutable personal data.
- Session, refresh and identity races have PostgreSQL uniqueness and locking
  boundaries.

### Negative and remaining integration work

- The repository has no Web, Tauri or VS Code application. The backend BFF and
  reusable adapters are implemented, but those application integrations cannot
  be claimed complete.
- The development Keycloak realm uses local-only settings; production realm,
  TLS, Keycloak PostgreSQL and secret-manager deployment still require platform
  configuration.
- KMS selection remains OD-03; deployments must supply and rotate the
  encryption-key ring safely.
- OAuth callback codes necessarily arrive in the callback query; the backend
  strips query strings from Uvicorn access logs and the reverse proxy must apply
  the same redaction.

## Alternatives Considered

- **Custom authentication/password database:** rejected; increases credential
  and protocol risk and duplicates the selected OIDC provider.
- **Vendor-specific client SDKs:** rejected as the required protocol; clients
  use standard OIDC endpoints and PKCE so a compatible issuer can be configured.
- **Browser-stored refresh token:** rejected; the Web BFF holds provider tokens
  server-side and the browser receives an opaque session cookie.
- **Trusting JWT claims without signature verification:** rejected; all accepted
  access tokens are cryptographically verified against configured issuer JWKS.

## Notes

- [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10) implements
  authentication and session security.
- [Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9) consumes the
  principal for workspace membership and action-level authorization.
- [Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11) remains the
  source of the `/v1/`, Problem Details and API authorization contract.
