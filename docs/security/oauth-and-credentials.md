# OAuth and Credentials

This document defines how EventFlow authenticates users across the Webapp,
Desktop, and VS Code clients, and how it stores, rotates, and revokes
credentials. It is subordinate to
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) section
3.5 and constrains [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10).

Status: Specified (Phase 0). The concrete identity provider and token format are
open decisions ([OD-01](open-decisions.md)); the control requirements below apply
regardless of the provider chosen.

## Authorization Flow

All clients use the OAuth 2.0 Authorization Code flow with PKCE. An implicit flow
or a client-side password grant is not permitted.

1. The client creates a high-entropy `code_verifier` and its `code_challenge`
   (`S256`).
2. The client redirects to the authorization endpoint with the challenge, a
   `state` value, and a least-privilege `scope`.
3. The authorization server redirects back to an exact, pre-registered redirect
   URI.
4. The client verifies `state`, then exchanges the `code` plus `code_verifier`
   for tokens at the token endpoint.
5. The client stores tokens using the platform-appropriate mechanism and attaches
   the access token as a `Bearer` credential on API calls.

## Controls

- **OA-01** — Authorization Code flow with PKCE (`S256`) is mandatory for every
  public client (Web, Desktop, VS Code).
- **OA-02** — Every authorization request carries an unpredictable `state`
  parameter that is validated on return to prevent cross-site request forgery.
- **OA-03** — Redirect URIs are matched exactly against a pre-registered
  allowlist. Wildcards and open redirects are rejected.
- **OA-04** — The authorization code is exchanged server-side or by the client
  with its `code_verifier`; tokens are never placed in a URL fragment or query.
- **OA-05** — Clients request the minimum scopes required for their feature, and
  elevated scopes require an explicit, separate consent step.
- **OA-06** — Refresh tokens are rotated on every use; reuse of a rotated refresh
  token invalidates the token family and raises a security event.
- **OA-07** — Tokens are stored per platform: `HttpOnly` cookies for the Webapp,
  the OS keychain or secure store for Desktop, and the VS Code `SecretStorage`
  API for the extension.
- **OA-08** — Credentials are encrypted in transit (TLS) and at rest, and are
  never written to a plaintext file, URL, or client bundle.
- **OA-09** — Credentials are revocable: global logout, per-device revocation,
  and deprovisioning invalidate access and refresh tokens promptly.
- **OA-10** — Credentials, authorization codes, and secrets never appear in logs,
  traces, metrics, telemetry, crash reports, or error messages.

## Token Storage by Platform

| Client | Storage | Prohibited |
|---|---|---|
| Webapp | `HttpOnly`, `Secure`, `SameSite` cookie | Script-readable storage |
| Desktop | OS keychain / secure store | Plain JSON or config file |
| VS Code | `SecretStorage` API | `workspaceState`, `globalState`, settings |

Access and refresh tokens must never be stored in `localStorage`, in
`sessionStorage`, or in any script-readable persistent store in the browser. The
Webapp keeps the access token out of JavaScript reach so that a cross-site
scripting flaw cannot read it.

## Sessions and Lifetime

- Access tokens are short-lived; refresh tokens are longer-lived but rotated
  (`OA-06`).
- A silent refresh happens before showing a login prompt; a failed refresh
  clears the local session.
- Sessions are bound to the workspace membership they were issued for. A token
  must not grant access to a workspace the principal is not a member of
  ([tenant-isolation.md](tenant-isolation.md)).
- On logout or revocation, tokens are removed from the platform store and the
  server-side session is invalidated.

## Secrets Handling

- Client secrets, when a confidential client exists, are stored server-side and
  never shipped to a client.
- The service identity uses least privilege and a short-lived credential when the
  provider supports it.
- Secret material is sourced from the deployment secret store, not from the
  repository or environment files committed to version control.

## Verification

- Implementation tests (Issue #10) must assert PKCE usage, `state` validation,
  redirect-URI allowlisting, refresh rotation, and revocation.
- A secret-scanning check must confirm that examples and fixtures contain no real
  credentials.

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-OA-01` to `TM-OA-08`.
- [Tenant isolation](tenant-isolation.md)
- [Open decisions](open-decisions.md)
