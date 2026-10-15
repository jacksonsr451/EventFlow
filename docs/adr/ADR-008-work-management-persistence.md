# ADR-008: Work Management Persistence Stack and Database Schema

## Status

Accepted

## Context

ADR-006 established Work Management as one of two bounded contexts, and ADR-007
fixed its backend location as a Python/FastAPI service at
`services/work-management/`. The machine-readable Work Management contracts
already exist (`contracts/schemas/work_management.yaml` and
`contracts/openapi/work-management.yaml`), but no architectural decision records
how the domain is persisted. Implementation in
[Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12) requires answers
to:

1. Which database engine, ORM and migration tool own Work Management state?
2. How are enum values, identifiers, timestamps and tenant boundaries
   represented so they stay faithful to the contracts?
3. How are the Work Management workflow invariants — an Approval is bound to one
   Proposal version, a WorkItem can only be created from an approved Proposal,
   audit history is append-only — enforced?
4. How is idempotency persisted so that retried approval decisions have
   exactly-once effects (ADR-007 section 3.6)?
5. How do migrations run in local development and CI?

The following constraints already apply:

- ADR-001: independent services with independent data stores.
- ADR-006 and [data ownership](../architecture/data-ownership.md): a service is
  the exclusive writer of its own tables; no cross-context database coupling.
- [Tenant isolation](../security/tenant-isolation.md): every tenant-owned row is
  scoped to a workspace.
- ADR-003: future event publication uses a transactional outbox — the outbox
  shares the same database and transaction as the domain change. This ADR
  reserves that capability by keeping domain writes transactional, but the
  outbox table itself is deferred to
  [Issue #46](https://github.com/jacksonsr451/EventFlow/issues/46).
- ADR-007 section 3.6 and [Open decisions](../security/open-decisions.md):
  idempotency storage and retention are backend implementation parameters.

The Work Management asynchronous contract does not exist yet, so this ADR does
not define any Kafka/AsyncAPI persistence.

## Decision

### 1. Engine, driver and access layer

- **PostgreSQL** is the system of record for Work Management. It provides the
  transactional guarantees, partial/expression indexes, `JSONB`, and check
  constraints the schema relies on.
- **SQLAlchemy 2.x** is the access layer, used in its typed declarative style
  (`Mapped` / `mapped_column`) for the ORM models and Core statements for
  bulk/query work.
- **psycopg 3** (`psycopg`) is the driver, referenced through the
  `postgresql+psycopg` dialect.
- **Alembic** owns schema evolution. Schema changes are expressed as reviewed,
  ordered migration scripts under
  `services/work-management/src/eventflow_work_management/migrations/versions/`.
  `Base.metadata.create_all()` is **not** a supported deployment path; it is
  used only by isolated unit tests that never touch a real database.

### 2. Service packaging

The service is a self-contained Poetry project rooted at
`services/work-management/` with its own `pyproject.toml`, `alembic.ini`,
`src/` package and `tests/`. It does not depend on the repository-root test
package, and the root contract test suite does not import service code. This
keeps the bounded-context boundary enforced at build time (ADR-007 section 4).

### 3. Schema conventions

- **Primary keys** are client-addressable UUIDs (`uuid`), matching the contract
  `UUID` pattern. Rows expose their contract identifier as the primary key.
- **Timestamps** are `timestamptz` and default to `now()` at the database.
- **Enum-like columns** are stored as `varchar` with a `CHECK ... IN (...)`
  constraint that lists exactly the values from the contract schema (for
  example `ConsultationStatus`). This avoids PostgreSQL `ENUM` migration pain
  while keeping the database as the final guard against invalid states.
- **Structured arrays/objects** from the contracts (`external_references`,
  `acceptance_criteria`, `editor_context`, board columns) are stored as `JSONB`
  with `jsonb_typeof` checks where the contract requires an array.
- **Naming** uses a `MetaData` naming convention so every constraint and index
  has a deterministic name; unique and check constraints are named explicitly
  where the convention would collide.
- **Tenant scoping**: every tenant-owned table carries a non-null
  `workspace_id`. Child tables use composite foreign keys of the form
  `(workspace_id, parent_id) -> parent(workspace_id, id)`, backed by
  `UNIQUE (workspace_id, id)` on the parent. This makes cross-workspace
  references impossible to persist, not merely discouraged in application code.
- **User identifiers** (`author_id`, `proposer_id`, `decider_id`, `assignee_id`)
  are stored as bare `uuid` columns without a foreign key. The identity store is
  owned by [Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9) and
  [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10); adding a
  foreign key now would create a cross-context dependency on tables that do not
  exist.

### 4. Invariant enforcement in the database

Application code enforces workflow rules first; the database is the last line of
defense.

- `approvals` has `UNIQUE (proposal_id, proposal_version)`: at most one decision
  per proposal version.
- Composite foreign keys keep a Proposal in the same project as its Consultation
  and a WorkItem in the same project as its origin Proposal:
  `fk_proposals_workspace_project_consultation` and
  `fk_work_items_workspace_project_proposal`.
- A `BEFORE INSERT OR UPDATE` trigger on `work_items` requires that the
  referenced `origin_approval_id` exists in the same workspace, targets the same
  `origin_proposal_id` and `origin_proposal_version`, and has
  `decision = 'approved'`. A WorkItem therefore cannot be created directly from
  a Consultation or an unapproved Proposal, and its origin columns cannot be
  updated to an invalid Proposal/version.
- `audit_records` has `BEFORE UPDATE`/`BEFORE DELETE`/`BEFORE TRUNCATE` triggers
  that raise, making the table append-only.
- A `BEFORE INSERT OR UPDATE` trigger on `remote_integration_references` requires
  a reference whose `entity_type` names a Work Management entity to point at an
  entity in the same workspace.
- Workflow status columns are constrained to the contract enum values.

### 5. Idempotency

Idempotency is persisted in `idempotency_records`, keyed by
`UNIQUE (workspace_id, operation, idempotency_key)`. Each record stores a SHA-256
request fingerprint and the stored response status/body. The domain change (for
example an Approval) and its idempotency record are written in the **same**
transaction. A retry with the same key and fingerprint returns the stored
result; the same key with a different fingerprint is a conflict. This implements
ADR-007 section 3.6 for the one endpoint that currently declares
`Idempotency-Key` (`.../decide`) and provides the storage primitive for
Amendment A-02.

### 6. Transactions and repositories

Repositories are the unit of work. Every public repository method that mutates
state opens one transaction, performs all reads and writes for the operation,
and commits or rolls back as a unit. Cross-service calls are never made inside a
database transaction. Concurrency is handled by database constraints
(`UNIQUE`, `CHECK`, composite foreign keys) plus explicit conflict handling, not
by in-memory locks.

### 7. Tenant isolation scope

Application-layer workspace scoping and composite foreign keys are enforced now.
PostgreSQL Row-Level Security is **deferred** until an authentication context
exists: RLS policies need a verified caller identity and workspace claim from
[Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9)/
[Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10). Introducing
RLS before that context exists would create policies that cannot be tested
end-to-end. This deferral is recorded so it is not mistaken for completeness.

## Consequences

### Positive

- One authoritative store per bounded context, consistent with ADR-001/006.
- Contract enum values and workflow invariants are enforced by the database, so
  invalid states are rejected even if application validation regresses.
- Composite foreign keys make cross-tenant references unrepresentable.
- Alembic migrations give reviewable, reversible schema history and avoid
  `create_all()` drift.
- The idempotency table satisfies ADR-007 section 3.6 and is reused when
  Amendment A-02 extends the header to more endpoints.

### Negative

- PostgreSQL-specific features (`JSONB`, trigger functions) make a future
  engine change non-trivial. Accepted: the schema is inherently relational and
  tenant-scoped.
- `varchar + CHECK` enums are simpler to migrate but less self-documenting than
  native `ENUM` types; the constraint list must be updated by a migration when a
  contract enum changes.
- Triggers move some invariant logic out of Python, so it must be covered by
  integration tests against a real database.
- Application-layer tenant scoping remains necessary until RLS is added; a
  missing `WHERE workspace_id = ...` is a real risk that tests and review must
  catch ([Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47)).

## Alternatives Considered

### SQLite for development and PostgreSQL in production

Rejected. It cannot enforce the `JSONB`, trigger and concurrent-write semantics
the tests must prove, so a passing SQLite suite would not demonstrate production
behavior.

### Django ORM and migrations

Rejected. It would pull the Work Management service toward a full Django stack
that ADR-007 did not select, and the team of record is a FastAPI/SQLAlchemy
service.

### Raw SQL with a hand-written migration runner

Rejected. It loses model/metadata single-sourcing and makes autogenerate review
and typed query construction impossible.

### Native PostgreSQL `ENUM` types

Rejected for now. Adding or reordering values requires type-level migrations
with more operational friction than a `CHECK` constraint, and the contracts
evolve additively (ADR-007 section 3.3).

### Row-Level Security from the start

Deferred, not rejected. The policies depend on an authentication/workspace
context that Issues #9/#10 own; adding RLS before that context is testable would
produce unverifiable security guarantees.

## Notes

- Migrations run with
  `alembic -c services/work-management/alembic.ini upgrade head`, reading
  `EVENTFLOW_DATABASE_URL`.
- Local PostgreSQL is provided through the repository `docker-compose.yml`
  (`postgres` service); CI runs the same migration and integration tests against
  a PostgreSQL service container.
- `docs/architecture/work-management-workflow.md` describes the workflow this
  schema persists, and `docs/security/tenant-isolation.md` lists the isolation
  invariants the composite foreign keys support.
