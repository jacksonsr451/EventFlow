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
│   │   ├── security_events.yaml  ← Security event envelope and taxonomy
│   │   └── work_management.yaml  ← Work Management entity and enum schemas
│   └── examples/            ← Non-production coherent workflow examples
│
├── docs/
│   ├── adr/                 ← Architecture Decision Records (sequential, never deleted)
│   ├── architecture/        ← Descriptive system architecture documents
│   │   └── order-processing/← Order Saga contract inventory, separation, reliability and execution plan
│   ├── concepts/            ← Educational concept explanations
│   ├── development/         ← Developer how-to guides (this file lives here)
│   ├── security/            ← Threat model, security policies and data governance
│   └── roadmap/             ← Issue dependency mindmap and critical path
│
├── services/                ← Backend microservices
│   ├── orders/              ← Python/FastAPI — Order Processing domain (planned location)
│   │   ├── src/             ← Application source code
│   │   └── tests/           ← Service-level tests
│   └── work-management/     ← Python/FastAPI — Work Management domain (persistence foundation, ADR-008)
│       ├── alembic.ini      ← Migration configuration
│       ├── pyproject.toml   ← Self-contained Poetry project
│       ├── src/eventflow_work_management/  ← config, db, models, repositories, seeds, migrations
│       └── tests/           ← jsr-testrunner persistence tests (PostgreSQL-backed)
│
├── packages/                ← Shared TypeScript packages (initial set implemented)
│   ├── domain/              ← Generated Work Management OpenAPI types
│   ├── api-client/          ← Typed HTTP clients from OpenAPI specs
│   ├── auth/                ← Existing authentication contracts
│   └── ui/                  ← Shared React component library
│
├── clients/                 ← Client applications (Webapp initial shell implemented)
│   ├── webapp/              ← React SPA (Vite + TypeScript)
│   ├── desktop/             ← Tauri application (Rust + React WebView)
│   └── vscode/              ← VS Code extension (Node.js + WebView panel)
│
├── scripts/                 ← Tooling scripts
│   └── validate_contracts.py ← Contract validation (run by pre-commit)
│
├── tests/                   ← Root-level cross-domain tests
│   ├── contracts/           ← Contract boundary and schema validation tests
│   │   └── order_processing_baseline.json  ← Frozen Order Processing contract snapshot
│   └── security/            ← Security documentation and contract tests
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

`jsr-testrunner` is a pytest fork that can auto-load third-party plugins from
the `pytest11` entry-point group. Because pytest is intentionally absent, such
plugins fail to import (for example `platformdirs`, pulled in transitively by
`pre-commit`). The repository sets `addopts = ["--disable-plugin-autoload"]` in
`[tool.testrunner]` (`pyproject.toml`) so plain `testrunner` invocations stay
pytest-free; the `--disable-plugin-autoload` flag can also be passed directly
(same behavior). Do not install pytest to work around this.

## Working with Shared Packages

The initial shared package workspace is implemented:
- pnpm 11.0.8 is configured in `pnpm-workspace.yaml`.
- Each package has its own `package.json` with explicit peer dependencies.
- TypeScript types in `packages/domain/` are generated; do not edit them manually.
- Regenerate after any Work Management contract change with `pnpm codegen`.
- Validate the workspace with `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build`.

## Bounded Context Rules

These rules are enforced by lint and must be respected manually until tooling
is in place:

| Rule | Rationale |
|---|---|
| `packages/domain` contains only Work Management generated types; future Order types must remain a separate bounded package | Bounded context isolation |
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
| #35 Threat model and data governance | `docs/security/`, `contracts/schemas/security_events.yaml`, `tests/security/` |
| #49 Order Processing preservation | `docs/architecture/order-processing/`, `tests/contracts/order_processing_baseline.json`, `tests/contracts/test_order_processing_preservation.py` |
| #12 Work Management persistence | `services/work-management/`, `docker-compose.yml`, `docs/adr/ADR-008-*.md`, `docs/architecture/work-management-persistence.md` |
| #9 Workspaces + RBAC | `services/work-management/` (planned) |
| #10 Authentication | `services/auth/` or `services/work-management/auth/` (planned) |
| #11 Versioned API + codegen | `packages/` configuration (planned) |
| #13 Webapp | `clients/webapp/`, `packages/ui/`, `packages/api-client/`, `packages/domain/` (initial shell implemented) |
| #23 VS Code Extension | `clients/vscode/` (planned) |
| #25 Desktop | `clients/desktop/` (planned) |
| #33 CI and workspace tooling | `pnpm-workspace.yaml`, root TypeScript tooling, `.github/workflows/` (initial frontend checks implemented) |
