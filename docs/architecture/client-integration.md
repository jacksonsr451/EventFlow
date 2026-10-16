# Client Integration Architecture

This document describes how the three EventFlow client platforms (Webapp,
Desktop, VS Code extension) integrate with the backend API. It complements
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) with
interaction diagrams and platform-specific patterns.

## Overview

All clients are **thin consumers** of the backend API. Business logic
(consultation routing, triage rules, proposal approval, Kanban ordering) lives
exclusively in the backend services. Clients render state and transmit user
intent.

```
┌────────────────────────────────────────────────────────────┐
│                      Backend (Python/FastAPI)               │
│  ┌──────────────────┐          ┌──────────────────────┐    │
│  │  Order Processing│          │   Work Management    │    │
│  │    (bounded ctx) │          │    (bounded ctx)     │    │
│  └──────────────────┘          └──────────────────────┘    │
└────────────────┬───────────────────────┬───────────────────┘
                 │  OpenAPI 3.1 (HTTP)   │  AsyncAPI 3.0 (Kafka)
      ┌──────────┼──────────────┬────────┘
      │          │              │
┌─────▼──┐  ┌───▼────┐  ┌──────▼──────┐
│ Webapp │  │Desktop │  │ VS Code Ext │
│ (React)│  │(Tauri) │  │  (Node.js) │
└────────┘  └────────┘  └─────────────┘
      │          │              │
      └──────────┴──────────────┘
             packages/
          ├── domain/
          ├── api-client/
          ├── auth/
          └── ui/
```

## Authentication Flow

EventFlow uses Keycloak through OIDC Authorization Code with PKCE S256. The Web
client uses the backend-for-frontend session; Desktop and VS Code are public
clients and use the system browser. Token storage follows ADR-009 and ADR-007
section 3.5.

```text
Web browser          EventFlow FastAPI BFF            Keycloak
    |                         |                            |
    |-- GET /v1/auth/oidc/login --------------------------->|
    |<-- 302 authorization URL + HttpOnly state cookie -----|
    |---------------- system/browser navigation ---------->|
    |<---------------- authorization code + state ---------|
    |-- GET /v1/auth/oidc/callback?code&state ------------->|
    |                         |-- exchange code + PKCE ---->|
    |                         |<-- signed ID/access tokens --|
    |                         | validate issuer/audience/JWKS|
    |                         | map (issuer, subject) -> UUID|
    |<-- 303 + opaque HttpOnly BFF session cookie ----------|
    |-- API request with cookie + CSRF header -------------->|
```

The BFF stores access/refresh tokens encrypted server-side. Browser JavaScript
never receives them. `GET /v1/auth/session` returns a session-bound CSRF token;
unsafe cookie-authenticated requests send it in `X-CSRF-Token` and require an
allowlisted `Origin`. A bearer access token used by Desktop/VS Code is validated
server-side and resolves the same stable internal principal. Neither client
receives workspace roles from OIDC claims.

Desktop and VS Code adapters persist native-client refresh tokens only through
the OS keychain and `vscode.SecretStorage` interfaces respectively. Their
application runtimes do not yet exist in this repository; the reusable PKCE and
secure-store package is the integration boundary, not a claim of full client
integration.

For the Web BFF, a refresh request is server-side and requires the session cookie
and CSRF proof. For native clients, refresh uses Keycloak's token endpoint from
the client adapter with refresh-token rotation. A failed refresh clears the
affected local/session credentials; it does not silently restore a revoked
session.

## Error Handling in Clients

Every client implements **one** error handler against the target model described
in [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.4: RFC 9457 problem details (`type`, `title`, `status`, `detail`,
`instance`) plus `correlation_id`, `request_id`, and optional `errors[]`.

| Status | Client Behaviour |
|---|---|
| `400` | Show field-level validation errors from `errors[]` |
| `401` | Silent token refresh, then login prompt on failure |
| `403` | Show a role-insufficient message; do not retry |
| `404` | Show "not found"; drop the local reference |
| `409` | Conflict (optimistic locking or idempotency); reload and re-confirm |
| `412` | Stale `If-Match` validator; reload the target representation before retrying |
| `5xx` | Transient error; offer retry with exponential backoff |

Work Management uses the same RFC 9457 problem shape, applied by Amendment A-01
([Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11)). All clients
therefore share one error handler with no per-domain mapping. See
[work-management-api.md](work-management-api.md) for the problem definition and
error codes.

## Consultation Submission Flow

### Webapp and Desktop

```
User                Webapp / Desktop            Backend
 │                        │                       │
 │── Fill form ──────────>│                       │
 │                        │── POST /v1/workspaces/{id}/consultations ──>│
 │                        │   {project_id, origin, title, description}  │
 │                        │<──────────── 201 {consultation_id, status}  │
 │<── Show confirmation ──│                       │
```

### VS Code Extension

The VS Code extension captures editor context only with explicit user consent:

```
Developer              VS Code Ext             Backend
   │                       │                     │
   │── Invoke command ─────>│                     │
   │                        │── Check consent ────┤
   │                        │   (workspaceState)  │
   │   [if no consent]      │                     │
   │<── Show consent dialog─│                     │
   │── Grant / Deny ────────>│                     │
   │                        │── Store consent ────┤
   │                        │                     │
   │<── Show submission form│                     │
   │── Fill title + desc ──>│                     │
   │                        │   Attach EditorContext (if consented):    │
   │                        │   {repository, branch, commit_sha,       │
   │                        │    file_path, line_start, line_end}       │
   │                        │── POST /v1/workspaces/{id}/consultations─>│
   │<── Confirmation ────────│<────────── 201 {consultation_id} ────────│
```

## Proposal Approval Flow (with Idempotency)

```
Approver              Client                  Backend
   │                    │                        │
   │── Review proposal ─>│                        │
   │                     │── Generate UUID key ───┤ (stored locally)
   │── Submit decision──>│                        │
   │                     │── POST /v1/workspaces/{id}/proposals/{id}/decide
   │                     │   Headers: Idempotency-Key: <uuid>
   │                     │   Body: {proposal_version, decision, justification}
   │                     │                        │
   │   [network failure] │                        │
   │                     │── Retry (same key) ───>│
   │                     │<─── 200 (idempotent) ──│
   │<── Result shown ────│                        │
```

On `409 Conflict` (stale `proposal_version`):
1. Client discards the pending key.
2. Client fetches the latest proposal state.
3. Client presents the updated state to the user.
4. User confirms or abandons the decision.
5. A new `Idempotency-Key` is generated for the fresh attempt.

## Offline Queue (Desktop and VS Code)

```
Client (offline)                     Backend
      │                                  │
      │  [network unavailable]           │
      │── Enqueue {operation, key, body} │
      │   in local persistent store      │
      │                                  │
      │  [network restored]              │
      │── Dequeue first operation        │
      │── POST ... Idempotency-Key: <k> ─┤
      │<──── 201/200 (or 4xx) ───────────│
      │── Remove from queue (on 2xx/4xx) │
      │── Retry later (on 5xx/network)   │
      │── Process next operation         │
```

5xx responses and network errors are retried with exponential backoff
(1 s, 2 s, 4 s, …, max 60 s). 4xx responses are removed from the queue
and surfaced to the user as errors.

Every unsafe operation now accepts `Idempotency-Key` as an API contract
(Amendment A-02, applied by
[Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11)). A queued write
may be auto-replayed only when it carries the key generated when it was
enqueued. This is a client/API contract requirement; HTTP replay handlers are
not implemented yet. The approval decision still requires the header.

| Operation | `Idempotency-Key` | Auto-replay |
|---|---|---|
| Approval decision (`.../decide`) | Required | Contract permits replay; HTTP handler pending |
| Consultation create | Optional (send when queued) | Contract permits replay with stored key; handler pending |
| Triage | Optional (send when queued) | Contract permits replay with stored key; handler pending |
| Proposal create / submit | Optional (send when queued) | Contract permits replay with stored key; handler pending |
| Board card move | Optional (send when queued) | Contract permits replay with stored key; handler pending |

Conflict handling uses **optimistic locking**: approval decisions submit
`proposal_version`. On `409`, the client reloads the entity and asks the user to
re-confirm instead of overwriting silently.

## Editor Context and Consent Model (VS Code)

The editor context captures the developer's current code position for use in
consultation submissions. It is **never captured without explicit consent**.

| Field | Source | Consent Required |
|---|---|---|
| `repository` | `vscode.workspace.rootUri` | Yes |
| `branch` | `vscode.workspace.getConfiguration` / git extension | Yes |
| `commit_sha` | git extension | Yes |
| `file_path` | `vscode.window.activeTextEditor.document.uri` | Yes |
| `line_start` | `editor.selection.start.line` | Yes |
| `line_end` | `editor.selection.end.line` | Yes |
| `consent_granted` | stored in `workspaceState` | — (the field itself) |

The consent dialog is shown once per workspace. The developer can revoke consent
at any time via the extension's settings panel. If consent is revoked, the
`editor_context` field is omitted from all future submissions.

## Bounded Context Isolation in Client Code

Client code must enforce the same bounded context isolation as the backend.
Practical rules:

1. `packages/domain/work-management` types must not be used in any Order
   Processing UI flow, and vice versa.
2. The generated Work Management and Order Processing clients are separate
   entry modules of `packages/api-client` with no cross-imports.
3. If a future UI screen must display both order and work-management data
   (e.g., a unified dashboard), it composes data at the presentation layer
   only — never by merging domain types.

A build-time lint rule (`no-restricted-imports`) enforces these boundaries
before any violation can reach a pull request.

## Compatibility Matrix

| Contract | Version | Breaking Change Policy |
|---|---|---|
| `contracts/openapi/work-management.yaml` | `1.0.0` | New version prefix (`/v2/`) for breaking changes |
| `contracts/schemas/work_management.yaml` | Draft 2020-12 | Additive optional fields: compatible. Any removal or required addition: new `$id` |
| `packages/domain/work-management` | `0.1.0` (planned) | semver; breaking TypeScript changes → major bump |
| `packages/api-client/work-management` | `0.1.0` (planned) | Follows OpenAPI version |

## Pending Implementation (Future Issues)

The following integration behaviours are architecturally specified here but
not yet implemented. They are the responsibility of dedicated issues:

| Behaviour | Issue |
|---|---|
| Token-based authentication service | [#10](https://github.com/jacksonsr451/EventFlow/issues/10) |
| Workspace and RBAC enforcement | [#9](https://github.com/jacksonsr451/EventFlow/issues/9) |
| TypeScript code generation tooling | [#33](https://github.com/jacksonsr451/EventFlow/issues/33) |
| Webapp implementation | [#13](https://github.com/jacksonsr451/EventFlow/issues/13) |
| VS Code extension implementation | [#23](https://github.com/jacksonsr451/EventFlow/issues/23) |
| Desktop (Tauri) implementation | [#25](https://github.com/jacksonsr451/EventFlow/issues/25) |
| Offline sync and conflict resolution | [#26](https://github.com/jacksonsr451/EventFlow/issues/26), [#42](https://github.com/jacksonsr451/EventFlow/issues/42) |
| GitHub/GitLab webhook integration | [#27](https://github.com/jacksonsr451/EventFlow/issues/27), [#29](https://github.com/jacksonsr451/EventFlow/issues/29) |
| Realtime Kanban via WebSocket/SSE | [#46](https://github.com/jacksonsr451/EventFlow/issues/46) |
| pnpm workspace and TypeScript configuration | [#33](https://github.com/jacksonsr451/EventFlow/issues/33) |
