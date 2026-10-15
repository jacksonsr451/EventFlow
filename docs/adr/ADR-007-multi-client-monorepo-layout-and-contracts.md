# ADR-007: Multi-Client Monorepo Layout and Shared Contracts

## Status

Accepted

## Context

ADR-006 established two bounded contexts (Order Processing and Work Management)
in a single repository, and mandated an API-first integration model for three
client platforms: a React web application, a Tauri desktop application, and a
VS Code extension. As implementation begins, the repository requires explicit
decisions about:

1. Where client code lives in the monorepo and how directories are organized.
2. How TypeScript models and business-logic primitives are shared across clients
   without duplicating backend domain rules.
3. How contracts (OpenAPI, AsyncAPI, JSON Schema) evolve without breaking client
   compatibility.
4. How each client handles authentication, offline behaviour, editor context
   capture, and synchronization.
5. What tooling enforces boundaries between bounded contexts and between clients
   and shared packages.

The three clients have overlapping needs (same API, same auth, same entity
models) but fundamentally different runtime environments:

- **Web (Webapp)** — Browser. React SPA. Full network access. Stateless from
  the client's perspective.
- **Desktop (Tauri)** — Native OS process with a Rust backend and a WebView
  front end. Can maintain local state, background threads, and file-system
  access.
- **VS Code Extension** — Node.js extension host process plus an optional
  WebView panel. Deeply integrated with the editor: captures file, line, Git,
  and repository context. Constrained by the VS Code extension API.

None of these clients contains business logic. All authoritative state
transitions happen on the backend. Clients consume contracts.

## Decision

### 1. Directory Structure

The monorepo adopts the following top-level layout. Directories that do not
yet contain implementation code are documented here as **planned** to
communicate intention without creating placeholder artifacts.

```
EventFlow/
│
├── contracts/                  # Language-independent machine-readable contracts
│   ├── openapi/                # HTTP API specifications (OpenAPI 3.1)
│   ├── asyncapi/               # Async message specifications (AsyncAPI 3.0)
│   ├── schemas/                # Reusable JSON Schema documents (Draft 2020-12)
│   └── examples/               # Non-production workflow examples
│
├── docs/
│   ├── adr/                    # Architecture Decision Records
│   ├── architecture/           # Descriptive architecture documents
│   ├── concepts/               # Explanatory concept guides
│   ├── development/            # Developer how-to guides
│   └── roadmap/                # Issue mindmap and critical path
│
├── services/                   # Backend microservices (polyglot)
│   ├── orders/                 # Python/FastAPI — Order Processing domain (planned)
│   ├── inventory/              # Java/Spring Boot — Inventory (planned)
│   ├── notifications/          # Go — Notifications (planned)
│   └── work-management/        # Python/FastAPI — Work Management domain (planned)
│
├── packages/                   # Shared TypeScript packages (planned)
│   ├── domain/                 # Generated entity types (single source of truth)
│   │   ├── work-management/    # Types derived from contracts/schemas/work_management.yaml
│   │   └── orders/             # Types derived from the Order JSON Schemas in contracts/schemas/
│   ├── api-client/             # HTTP client wrappers for each OpenAPI spec
│   ├── auth/                   # Token management and session utilities
│   └── ui/                     # Shared React component library (Tauri + Web)
│
├── clients/                    # Client applications (planned)
│   ├── webapp/                 # React SPA (Vite + React + TypeScript)
│   ├── desktop/                # Tauri application (Rust backend + React WebView)
│   └── vscode/                 # VS Code extension (Node.js + optional WebView)
│
└── scripts/                    # Validation, generation, and tooling scripts
```

> **Layout authority:** This section refines the directory layout proposed in
> [ADR-006](ADR-006-product-scope-and-bounded-contexts.md) section 3. The names
> defined here (`clients/`, `services/work-management/`) are authoritative:
> ADR-006's `apps/` and `services/work-core/` names are superseded. The
> bounded-context isolation rules from ADR-006 are unchanged.

**Rationale for `packages/` separation:**
- `packages/domain` contains TypeScript interfaces generated from JSON Schema
  and OpenAPI definitions. It is the single source of truth for entity shapes
  in TypeScript. No client may define its own version of `Consultation`,
  `Proposal`, or `WorkItem`.
- `packages/api-client` provides typed HTTP clients generated from OpenAPI
  specs. Clients import these functions rather than hand-coding `fetch` calls.
- `packages/auth` encapsulates token storage and refresh logic so that all
  three clients share the same authentication behaviour.
- `packages/ui` contains React components usable by both Webapp and the Tauri
  WebView. VS Code uses a subset or its own simplified components when the
  VS Code Webview API imposes constraints.

### 2. Technology Evaluation and Decisions

#### 2.1 TypeScript Across All Clients

**Decision:** TypeScript is the shared language for all three clients and for
all shared packages.

**Rationale:**
- The VS Code extension API is TypeScript-first; there is no viable alternative.
- Tauri supports any WebView technology; TypeScript with React is the natural
  choice to share UI components with the Webapp.
- A single language across clients eliminates serialization boundaries between
  packages and clients, and allows genuine code sharing.

**Trade-offs:**
- Rust code inside the Tauri desktop sidecar remains separate and cannot share
  TypeScript packages directly. The Rust layer only handles native OS concerns
  (file system, IPC, tray); it does not contain business logic.
- TypeScript compilation must be coordinated across packages. A workspace
  manager (pnpm workspaces or npm workspaces) is required.

#### 2.2 React for Web and Desktop

**Decision:** React (with Vite) is the rendering framework for Webapp and for
the Tauri WebView.

**Rationale:**
- Components in `packages/ui` can be reused without modification in both
  environments.
- React's declarative model integrates cleanly with server-driven state
  (consultation lists, proposal approval results).
- The VS Code extension may use React in its optional WebView panel but cannot
  share the same component tree with the app because VS Code imposes a Content
  Security Policy. A thin adapter layer isolates the extension's WebView from
  `packages/ui`.

**Alternative considered:** Vue or Svelte. Rejected because neither has the
same VS Code WebView community support, and component sharing with Tauri would
require adapters in any case.

#### 2.3 Tauri for Desktop

**Decision:** Tauri 2.x is the desktop framework.

**Rationale:**
- Tauri provides a native OS window with a WebView that runs the React
  application. The Rust core handles file-system access, system tray, local
  state persistence, and the offline synchronization queue.
- Tauri produces significantly smaller bundles than Electron and avoids
  shipping a full Chromium instance.
- The Rust core does not contain EventFlow business logic. It is a thin
  platform adapter that invokes the backend API or queues requests for later.

**Trade-offs:**
- Requires Rust toolchain in the development environment.
- WebView rendering differs across operating systems (WebKit on macOS/Linux,
  WebView2 on Windows). UI tests must cover multiple platforms.

**Alternative considered:** Electron. Rejected because of bundle size and the
absence of any advantage specific to EventFlow's requirements.

#### 2.4 VS Code Extension Architecture

**Decision:** The VS Code extension uses the standard `ExtensionHost` process
(Node.js) and an optional WebView panel for interactive forms (consultation
submission, board card view).

**Key constraints:**
- The extension must request explicit consent before capturing editor context
  (file path, line range, Git commit, repository identity). Consent is recorded
  per workspace and stored in VS Code's `workspaceState`.
- The extension accesses only `vscode.workspace`, `vscode.window`, and the
  EventFlow HTTP API. It does not access the file system directly for user
  content.
- The WebView panel is sandboxed by VS Code's CSP. It cannot import from
  `packages/ui` directly; a bundled subset is compiled into the extension.

### 3. Shared Contract Policy

#### 3.1 TypeScript Types from JSON Schema

TypeScript interfaces for all domain entities (`Consultation`, `Proposal`,
`Approval`, `WorkItem`, `BoardCard`) are **generated** from
`contracts/schemas/work_management.yaml` (JSON Schema Draft 2020-12) using
`json-schema-to-typescript` or an equivalent tool. No client may hand-write
these interfaces.

The generated types live in `packages/domain/work-management/`. When the
schema changes, the types are regenerated and the package version is bumped.

#### 3.2 HTTP Client from OpenAPI

The typed HTTP client in `packages/api-client/` is generated from
`contracts/openapi/work-management.yaml` using `openapi-typescript` or
`openapi-generator-cli`. Clients call typed functions such as
`createConsultation(body)` rather than raw `fetch`.

#### 3.3 Versioning Strategy

| Layer | Version Carrier | Compatibility Rule |
|---|---|---|
| JSON Schema | `$schema` + `$id` + `schema_version` field in event envelope | Minor: additive optional fields allowed. Major: new `$id` version segment. |
| OpenAPI | `info.version` in the spec | URL-prefixed (`/v1/`). Breaking changes require a new version prefix. |
| AsyncAPI | `info.version` in the spec | Applies to the existing Order Processing workflow contract. Event `schema_version` in envelope. Consumers must tolerate unknown fields. |
| `packages/domain` | `package.json` semver | Breaking TypeScript interface changes → major version. |
| `packages/api-client` | `package.json` semver | Tied to OpenAPI version. |

The Work Management domain currently exposes HTTP (OpenAPI) and JSON Schema
contracts only. Its asynchronous contract (for example a future
`contracts/asyncapi/work-events.yaml`) does not exist yet and is deferred to
[Issue #46](https://github.com/jacksonsr451/EventFlow/issues/46).

#### 3.4 Error Handling Contract

**Target model (client-facing).** All clients consume one error shape based on
RFC 9457 (Problem Details): `type`, `title`, `status`, `detail`, `instance`,
plus the EventFlow extensions `correlation_id`, `request_id`, and an optional
`errors[]` array for field-level validation. Order Processing already uses this
shape (`contracts/schemas/common.yaml#/$defs/Error`, exposed as
`contracts/schemas/http.yaml#/$defs/ErrorResponse`). Clients implement a single
error handler against this model.

**Current reality (two shapes).** Work Management still defines a custom
`ErrorResponse` (`error_code`, `message`, `details`, `timestamp`) in
`contracts/schemas/work_management.yaml#/$defs/ErrorResponse`. Both domains use
the `application/problem+json` media type, so this is a genuine shape
incompatibility, not a media-type distinction. Until
[Amendment A-01](#amendment-a-01--align-work-management-errors-with-rfc-9457) is
applied:

- Clients must use the per-domain generated error type.
- `packages/domain`/`packages/api-client` map the Work Management shape into the
  shared client error model **at the boundary**; application code only sees the
  unified model. This mapping is temporary and must not leak into domain types.
- A single shared handler without a mapping layer is possible only after the
  amendment.

Clients must handle:
- `400 Bad Request` — validation failure; display field-level errors.
- `401 Unauthorized` — redirect to login / trigger token refresh.
- `403 Forbidden` — display a role-insufficient message; do not retry.
- `409 Conflict` — optimistic-locking or idempotency conflict; reload and re-apply user intent.
- `5xx` — display a transient error; offer retry with exponential backoff.

The full client-facing policy and the amendment proposal are documented in
[client-integration.md](../architecture/client-integration.md).

#### 3.5 Authentication and RBAC

All clients authenticate using a shared token mechanism (details in
[Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10)). The token
is stored per platform:

| Client | Token Storage |
|---|---|
| Webapp | `HttpOnly` session cookie or `sessionStorage` (never `localStorage`) |
| Desktop | OS keychain / secure store (for example `tauri-plugin-stronghold` or a keyring plugin), not a plain JSON store |
| VS Code | VS Code `SecretStorage` API |

RBAC roles (`submitter`, `triager`, `proposer`, `approver`, `assignee`,
`viewer`) are enforced by the backend. Clients use role information only to
show or hide UI elements; they must never assume a role grants access without
a backend response confirming it.

A shared token must not grant cross-workspace access. The backend scopes every
request to the caller's workspaces and returns `403`/`404` rather than leaking
other tenants' data ([Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47)).
The Tauri application must configure a Content Security Policy and an explicit
IPC allowlist so the WebView can reach only the backend API and first-party
assets; the concrete policy is defined in
[Issue #25](https://github.com/jacksonsr451/EventFlow/issues/25).

#### 3.6 Idempotency

**Principle.** Any unsafe HTTP operation that a client may retry — after a
timeout, a network failure, or an offline replay — must carry a client-generated
`Idempotency-Key`. The backend stores the key together with the resulting
response inside the same local transaction that performs the domain change, so a
retry returns the stored response and never repeats side effects. Storage and
retention are backend implementation parameters
([Issue #7](https://github.com/jacksonsr451/EventFlow/issues/7)).

**Semantics.**
- Same key + semantically equivalent request → replay; return the original
  response (success or error) without repeating effects.
- Same key + different request (different body or parameters) → `409`
  idempotency conflict; the client must use a new key for a genuinely new intent.
- New key → new operation.

**Current contract.** `contracts/openapi/work-management.yaml` declares
`Idempotency-Key` **only** on
`POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide`. No other
mutating endpoint accepts it, so only approval decisions are currently
replay-safe. Clients must not assume consultation, triage, proposal, or card
operations are idempotent. Extending the header to the remaining unsafe endpoints
is [Amendment A-02](#amendment-a-02--idempotency-for-mutating-endpoints).

#### 3.7 Offline and Synchronization

The backend is the single source of truth. Read operations always fetch from the
backend; stale local data is never presented as authoritative.

The Desktop and VS Code clients maintain a local queue of pending operations.
Only operations with a defined idempotency contract may be **auto-replayed**
(currently only approval decisions, which carry a stored `Idempotency-Key`).
Other writes (consultation, triage, proposal, card move) may be queued while
offline, but they must **not** be replayed automatically until
[Amendment A-02](#amendment-a-02--idempotency-for-mutating-endpoints) is applied;
the client keeps them pending and surfaces them for explicit user confirmation
when connectivity returns.

Conflict handling uses **optimistic locking**, not silent last-writer-wins:
approval decisions submit `proposal_version`. On `409`, the client reloads the
entity and asks the user to re-confirm; a new `Idempotency-Key` is generated only
for a new, deliberate intent. Board cards have no version field today, so
offline reordering is out of scope until the contract provides one (Issues
[#8](https://github.com/jacksonsr451/EventFlow/issues/8) /
[#42](https://github.com/jacksonsr451/EventFlow/issues/42)).

### 4. Bounded Context Isolation

The `packages/domain/work-management` and `packages/domain/orders` packages
must not import from each other. A lint rule (ESLint `no-restricted-imports`
or a custom boundary plugin) enforces this at build time. The backend services
enforce isolation at the API and persistence layers.

Client code must not import directly from `services/`. All data comes through
`packages/api-client`. Within `packages/domain` and `packages/api-client`, the
Order Processing and Work Management entry modules are separate and must not
cross-import; cross-domain presentation composition, if ever required, happens
at the UI layer only.

### 5. Integration with GitHub and GitLab

Work Management cards and tasks may reference GitHub issues, pull requests,
and GitLab merge requests as **external references** (stored as URIs in the
`external_references` field of `Consultation`). The backend validates URI
format but does not call GitHub or GitLab APIs synchronously during the
consultation workflow.

Future issues ([#27](https://github.com/jacksonsr451/EventFlow/issues/27),
[#29](https://github.com/jacksonsr451/EventFlow/issues/29),
[#44](https://github.com/jacksonsr451/EventFlow/issues/44)) will define the
webhook-driven integration where GitHub events trigger consultation creation.
That integration uses backend adapters, not client-side API calls, to avoid
exposing GitHub credentials to client code.

### 6. Testing Strategy by Client

| Layer | Framework | Scope |
|---|---|---|
| `packages/domain` | `vitest` | Type-level tests; JSON Schema round-trip |
| `packages/api-client` | `vitest` + `msw` (mock service worker) | HTTP client correctness against mocked OpenAPI responses |
| `packages/ui` | `vitest` + React Testing Library | Component rendering and accessibility |
| Webapp | `vitest` + Playwright | Unit + E2E against a local backend |
| Desktop | `vitest` + Playwright with Tauri driver | Unit + E2E |
| VS Code extension | `@vscode/test-electron` | Extension host integration tests |
| Backend contracts | `jsr-testrunner` (Python) | JSON Schema and OpenAPI validation (already implemented) |

Contract compatibility tests verify that the generated TypeScript types are
structurally compatible with the JSON Schema source after each schema update.

## Amendment Proposals (Not Applied)

The two proposals below describe how to remove the divergences explained in
sections 3.4 and 3.6. They require modifying contracts already accepted in
[Issue #2](https://github.com/jacksonsr451/EventFlow/issues/2), so they are
**proposals only** and are **not applied** by this ADR. They must be scheduled
and reviewed as a dedicated contract revision before being implemented.

### Amendment A-01 — Align Work Management errors with RFC 9457

- **Affected files:** `contracts/schemas/work_management.yaml`
  (`$defs/ErrorResponse`) and every `application/problem+json` response in
  `contracts/openapi/work-management.yaml`.
- **Change:** replace the custom `ErrorResponse` (`error_code`, `message`,
  `details`, `timestamp`) with an RFC 9457 problem shape (`type`, `title`,
  `status`, `detail`, `instance`, optional `correlation_id`, `request_id`,
  `errors[]`), reusing the shared Order Processing `Error` definition or a
  newly extracted shared schema.
- **Expected behaviour:** both bounded contexts emit one problem+json shape; a
  single shared error handler and a single generated error type replace the
  per-domain mapping described in 3.4.
- **Compatibility:** breaking for any consumer that reads `error_code`,
  `message`, `details`, or `timestamp`. No consumer is implemented yet (Issue #2
  defines contracts only), so a coordinated change before first implementation
  is low risk. If that assumption changes, keep `error_code` as a deprecated
  extension field for one version.
- **Required tests:** draft-2020-12 schema validation; positive and negative
  problem+json fixtures per endpoint; a boundary test asserting a single shared
  `ErrorResponse` definition; a cross-domain error-type compatibility test.
- **Owner:** [Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11)
  with [Issue #49](https://github.com/jacksonsr451/EventFlow/issues/49).

### Amendment A-02 — Idempotency for mutating endpoints

- **Affected endpoints (all currently unsafe and non-idempotent):**
  `POST /v1/workspaces/{workspace_id}/consultations`,
  `POST /v1/workspaces/{workspace_id}/consultations/{consultation_id}/triage`,
  `POST /v1/workspaces/{workspace_id}/proposals`,
  `POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/submit`, and
  `PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards`.
  `POST /v1/workspaces/{workspace_id}/proposals/{proposal_id}/decide` already
  declares `Idempotency-Key` and needs no change.
- **Change:** add an `Idempotency-Key` request header parameter (same UUID
  constraints as the existing `decide` parameter) to each endpoint above. The
  backend persists `(workspace_id, idempotency_key, request_fingerprint,
  response_status, response_body)` in the same transaction as the domain change.
- **Expected behaviour:** same key + equivalent request → the stored response is
  returned and no extra effect occurs; same key + different request → `409`;
  headers missing → the request is processed once without replay protection
  (acceptable for one-time online clients, not for queued offline writes).
- **Compatibility:** additive and optional, so not breaking for existing callers
  that omit the header; mandatory for offline-capable Desktop and VS Code
  clients.
- **Required tests:** per-endpoint duplicate-submission tests (same key → a
  single effect; different body → `409`); a concurrent-submission test; an
  offline-queue replay test asserting exactly-once effects.
- **Owner:** [Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11),
  with domain behaviour in [Issue #4](https://github.com/jacksonsr451/EventFlow/issues/4),
  [Issue #6](https://github.com/jacksonsr451/EventFlow/issues/6), and
  [Issue #8](https://github.com/jacksonsr451/EventFlow/issues/8).

## Consequences

### Positive

- Single source of truth for entity shapes: JSON Schema → TypeScript types via
  code generation. No manual synchronization.
- All three clients share auth logic, error handling, and entity types via
  `packages/`. Reduces divergence.
- Clear directory boundary between `clients/`, `packages/`, `services/`, and
  `contracts/` makes it easy to scope CI triggers and code ownership.
- Offline support is architecturally motivated (Desktop + VS Code) without
  over-engineering the Webapp.
- Tauri and VS Code extension constraints are explicitly acknowledged before
  implementation begins, preventing surprise compatibility issues.

### Negative

- pnpm workspaces (or equivalent) adds a configuration layer before any client
  code is written.
- Code generation for TypeScript types introduces a build step that must be
  kept in sync. A stale generation produces type drift.
- WebView CSP restrictions in VS Code require a bundled subset of `packages/ui`
  rather than a direct import, creating duplication risk.
- Tauri requires Rust toolchain, expanding the local development requirements.
- Cross-platform WebView rendering differences require multi-platform test
  environments for the Desktop client.

## Alternatives Considered

### Multi-Repo Client Split

Each client in its own repository. Rejected because:
- Contract changes would require coordinated PR across multiple repositories.
- Shared packages would need to be published to a registry (npm) even for
  internal changes, slowing iteration.
- The unified 55-issue roadmap spans all clients; splitting repos fragments
  traceability.

### Nx or Turborepo Monorepo Tooling

Using a full monorepo build system (Nx, Turborepo) for task orchestration.
Deferred: the current scale does not justify the additional configuration
complexity. The decision to adopt a build system will be made when the number
of TypeScript packages grows to the point where manual build ordering becomes
untenable. If adopted, it must not alter the directory structure defined here.

### Single TypeScript Application with Tauri

A single React application deployed to both Web and Desktop, with
platform-specific modules gated by environment detection. Rejected because:
- The VS Code extension cannot share a React application root with the Webapp.
- A single app obscures the platform adaptation boundaries that the project
  intends to demonstrate architecturally.

### GraphQL Instead of REST

A GraphQL API layer to reduce client-specific query endpoints. Rejected for
this phase because:
- The backend domains are already specified as REST/OpenAPI.
- GraphQL subscription complexity (for realtime Kanban updates) is a separate
  concern deferred to later issues.
- Introducing GraphQL here would require regenerating all existing contracts.

## Notes

- The implementation of `packages/` and `clients/` begins in
  [Issue #13](https://github.com/jacksonsr451/EventFlow/issues/13) (Webapp),
  [Issue #23](https://github.com/jacksonsr451/EventFlow/issues/23) (VS Code),
  and [Issue #25](https://github.com/jacksonsr451/EventFlow/issues/25)
  (Desktop).
- TypeScript code generation tooling is selected in
  [Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11).
- Workspace tooling (pnpm or npm workspaces) is configured in
  [Issue #33](https://github.com/jacksonsr451/EventFlow/issues/33).
- See [client-integration.md](../architecture/client-integration.md) for
  sequence diagrams and integration patterns.
- See [monorepo-layout.md](../development/monorepo-layout.md) for the
  developer guide to working with the directory structure.
