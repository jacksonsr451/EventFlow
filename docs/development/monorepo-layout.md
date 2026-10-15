# Monorepo Layout Guide

This guide explains the EventFlow monorepo directory structure for developers
contributing to any part of the project.

See [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
for the architectural decisions behind this layout.

## Directory Map

```
EventFlow/
│
├── contracts/               ← Language-independent contracts (DO NOT edit by hand if generated)
│   ├── openapi/             ← OpenAPI 3.1 HTTP API specifications
│   │   ├── orders.yaml      ← Order Processing HTTP contract
│   │   └── work-management.yaml  ← Work Management HTTP contract
│   ├── asyncapi/            ← AsyncAPI 3.0 async message specifications
│   │   └── workflow.yaml    ← Order Processing Kafka workflow
│   ├── schemas/             ← Reusable JSON Schema (Draft 2020-12) documents
│   │   ├── common.yaml      ← Shared primitives (UUID, Money, timestamps)
│   │   ├── envelope.yaml    ← Event envelope structure
│   │   ├── events.yaml      ← Order Processing event payload schemas
│   │   ├── http.yaml        ← HTTP request/response schemas for Orders
│   │   └── work_management.yaml  ← Work Management entity and enum schemas
│   └── examples/            ← Non-production coherent workflow examples
│
├── docs/
│   ├── adr/                 ← Architecture Decision Records (sequential, never deleted)
│   ├── architecture/        ← Descriptive system architecture documents
│   ├── concepts/            ← Educational concept explanations
│   ├── development/         ← Developer how-to guides (this file lives here)
│   └── roadmap/             ← Issue dependency mindmap and critical path
│
├── services/                ← Backend microservices
│   └── orders/              ← Python/FastAPI — Order Processing domain (planned location)
│       ├── src/             ← Application source code
│       └── tests/           ← Service-level tests
│
├── packages/                ← Shared TypeScript packages (PLANNED — Issue #11, #33)
│   ├── domain/              ← Generated entity types from JSON Schema
│   │   ├── work-management/ ← Types from contracts/schemas/work_management.yaml
│   │   └── orders/          ← Types from contracts/openapi/orders.yaml
│   ├── api-client/          ← Typed HTTP clients from OpenAPI specs
│   ├── auth/                ← Token storage and session management
│   └── ui/                  ← Shared React component library
│
├── clients/                 ← Client applications (PLANNED — Issues #13, #23, #25)
│   ├── webapp/              ← React SPA (Vite + TypeScript)
│   ├── desktop/             ← Tauri application (Rust + React WebView)
│   └── vscode/              ← VS Code extension (Node.js + WebView panel)
│
├── scripts/                 ← Tooling scripts
│   └── validate_contracts.py ← Contract validation (run by pre-commit)
│
├── tests/                   ← Root-level cross-domain tests
│   └── contracts/           ← Contract boundary and schema validation tests
│
├── .pre-commit-config.yaml  ← Pre-commit hook configuration
├── Makefile                 ← Common developer commands
└── docker-compose.yml       ← Local infrastructure (Kafka, Postgres, etc.)
```

## Working with Contracts

### Editing a Schema

1. Edit the relevant file in `contracts/schemas/` or `contracts/openapi/`.
2. Run validation: `python scripts/validate_contracts.py`
3. If the change is breaking (removes a required field, changes a type, renames
   a property), update the version identifier in the schema's `$id` or the
   OpenAPI `info.version`.
4. Run the test suite: `poetry run testrunner --verbose` (from repo root).
5. Update any affected examples in `contracts/examples/`.

### Adding a New Schema Definition

Add the `$def` to the appropriate schema file. Cross-schema references use
relative paths from the referencing document (e.g.,
`../schemas/work_management.yaml#/$defs/UUID`).

Do not duplicate definitions across schema files. Use `$ref` to the canonical
definition.

## Working with Backend Services

Each service in `services/` is self-contained with its own `pyproject.toml`
(Python services), `build.gradle` (Java), or `go.mod` (Go).

**Python services** use Poetry. From the service directory:
```powershell
poetry install
poetry run testrunner --verbose   # jsr-testrunner only; no pytest
```

**Do not add pytest** to any Python service. The test framework is
`jsr-testrunner` exclusively.

## Working with Shared Packages (Planned)

When `packages/` is implemented (Issue #33):
- pnpm is the intended workspace manager; the exact choice between pnpm and npm
  workspaces is finalized in Issue #33 (see ADR-007 section 2.1).
- Each package has its own `package.json` with explicit peer dependencies.
- TypeScript types in `packages/domain/` are generated; do not edit them manually.
- Regenerate after any schema change: `pnpm run codegen` (command TBD in Issue #11).

## Bounded Context Rules

These rules are enforced by lint and must be respected manually until tooling
is in place:

| Rule | Rationale |
|---|---|
| `packages/domain/work-management` must not import from `packages/domain/orders` | Bounded context isolation |
| `clients/` must not import from `services/` | Clients consume APIs, not source code |
| `contracts/` files must not contain implementation language constructs | Language-independent contracts |
| Schemas in `work_management.yaml` must not reference schemas in `common.yaml` using absolute URLs | Portability |

## Pre-Commit Hooks

The following hooks run on every commit:

| Hook | What it checks |
|---|---|
| `trim trailing whitespace` | Whitespace cleanliness |
| `fix end of files` | Trailing newline |
| `check yaml` | YAML syntax |
| `check json` | JSON syntax |
| `check for merge conflicts` | No leftover conflict markers |
| `check for added large files` | No accidental large file commits |
| `detect private key` | No credentials in commits |
| `Validate contracts and repository references` | Runs `scripts/validate_contracts.py` |

Run manually: `pre-commit run --all-files`

## Issue-to-Directory Mapping

| Issue | Directory / Artefact |
|---|---|
| #1 ADR-006 | `docs/adr/ADR-006-*.md` |
| #2 Workflow Specification | `docs/architecture/work-management-workflow.md`, `contracts/openapi/work-management.yaml`, `contracts/schemas/work_management.yaml` |
| #3 Monorepo Layout (this issue) | `docs/adr/ADR-007-*.md`, `docs/architecture/client-integration.md`, `docs/development/monorepo-layout.md` |
| #9 Workspaces + RBAC | `services/work-management/` (planned) |
| #10 Authentication | `services/auth/` or `services/work-management/auth/` (planned) |
| #11 Versioned API + codegen | `packages/` configuration (planned) |
| #13 Webapp | `clients/webapp/` (planned) |
| #23 VS Code Extension | `clients/vscode/` (planned) |
| #25 Desktop | `clients/desktop/` (planned) |
| #33 CI and workspace tooling | `pnpm-workspace.yaml`, `.github/workflows/` (planned) |
