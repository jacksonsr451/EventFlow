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
4. How is idempotency persisted so retried approval decisions have at-most-once
   local database effects (ADR-007 section 3.6)?
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
- `work_items` has `UNIQUE (origin_proposal_id)`: at most one WorkItem per
  Proposal, matching workflow step 7 ("Insert WorkItem (Unique constraint on
  `origin_proposal_id`)").
- Composite foreign keys keep a Proposal in the same project as its Consultation
  and a WorkItem in the same project as its origin Proposal:
  `fk_proposals_workspace_project_consultation` and
  `fk_work_items_workspace_project_proposal`.
- `board_cards` carries an internal `project_id` and two composite foreign keys,
  `fk_board_cards_workspace_project_board` and
  `fk_board_cards_workspace_project_work_item`, so a card's Board and WorkItem
  must belong to the same project. The column is functionally determined by the
  board and kept consistent by the constraints, so it cannot drift.
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
request fingerprint and response status/body metadata. The domain change (for
example an Approval) and its idempotency record are written in the **same**
transaction. A retry with the same key and fingerprint recovers the same
persisted approval result; a different fingerprint conflicts. The repository
does not yet rehydrate the full HTTP body from its stored response metadata.
This implements ADR-007 section 3.6 for `ApprovalRepository.decide` only. The table
provides a persistence primitive for other A-02 operation scopes, but their
repository integrations and HTTP response replay are not implemented by Issue
#12. [Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11) defines
those as API contract requirements; this ADR does not claim runtime completion.

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

## Amendment Proposals

### Amendment A-01 — Independent proposals and immutable revisions (Issue #6)

**Status:** Accepted.

**Context.** The original schema made `proposals` unique on
`(consultation_id, version)`, which implied a single version chain per
Consultation and prevented one Consultation from producing several independent
Proposals. [Issue #6](https://github.com/jacksonsr451/EventFlow/issues/6)
requires a 1→N relationship: a triaged Consultation may yield zero, one, or many
Proposals, each with its own identity and its own revision counter.

**Decision.**

- `proposals` no longer carries `UNIQUE (consultation_id, version)`. A Proposal's
  `version` is scoped to its own `proposal_id` and starts at 1.
- A new `proposal_revisions` table stores the immutable snapshot of each accepted
  revision, with `UNIQUE (proposal_id, version)` and a workspace-bound composite
  foreign key to `proposals`. `BEFORE UPDATE`/`BEFORE DELETE`/`BEFORE TRUNCATE`
  triggers (`eventflow_proposal_revisions_block_mutation`) make the history
  append-only.
- A new `proposal_evidence` table links a Proposal to `consultation_evidence`
  rows in the same workspace (composite primary key
  `(proposal_id, evidence_id)`).
- `proposals` gains `checklist` (`JSONB`), `duplicated_from_proposal_id`, and
  `superseded_by_proposal_id`, with self-referencing composite foreign keys that
  keep a duplicate/superseding Proposal in the same workspace and project.
- No proposal operation creates an `Approval`, `WorkItem`, `BoardCard`, or remote
  issue; those remain gated behind the existing approval path.

**Consequences.** The `(consultation_id, version)` uniqueness documented in
section 4 and in
[work-management-persistence.md](../architecture/work-management-persistence.md)
is superseded by `UNIQUE (proposal_id, version)` on `proposal_revisions`.
`ApprovalRepository` continues to bind a decision to a `(proposal_id,
proposal_version)` pair, which remains unambiguous because `proposal_id`
identifies the Proposal. Verified by
`services/work-management/tests/test_proposal_api_integration.py`,
`services/work-management/tests/test_proposal_unit.py`, and the migration tests.

### Amendment A-03 — Configurable Kanban boards and card movement history (Issue #8)

**Status:** Accepted.

**Context.** The original schema stored a board's columns as an ordered JSONB
key list on `boards`, which cannot carry per-column state (canonical status
mapping, WIP limit, stable identity) and cannot be managed as an independent
resource. [Issue #8](https://github.com/jacksonsr451/EventFlow/issues/8) requires
configurable boards, dedicated column-management endpoints, deterministic card
ordering, WIP limits and a persistent movement history, while preserving the
Issue #7 approval-only rule that a card exists only as a projection of an
approved WorkItem.

**Decision.**

- `boards` gains `version` (`integer NOT NULL DEFAULT 1`, `CHECK >= 1`) for
  optimistic concurrency and `archived_at` (`timestamptz NULL`) for archival.
- A new `board_columns` table holds independently managed columns: a stable
  `key`, `name`, ordered `position`, canonical `mapped_status` (a WorkItem status
  value) and an optional positive `wip_limit`. It carries
  `UNIQUE (board_id, key)` and `UNIQUE (workspace_id, id)` plus a workspace-bound
  composite FK to `boards`. `position` is not unique; the service renumbers it to
  `0..n-1` inside the transaction.
- A new append-only `card_movements` table records each accepted move
  (from/to column, rank, status, actor, correlation id, timestamp), guarded by
  `BEFORE UPDATE`/`BEFORE DELETE`/`BEFORE TRUNCATE` triggers
  (`eventflow_card_movements_block_mutation`).
- **No foreign key** is added from `board_cards.column_id` to `board_columns`:
  a card's column is a validated logical label, so boards and cards materialized
  before Issue #8 remain valid. `Board.columns` is kept in sync as the ordered
  key list for read compatibility.
- **No BoardCard or WorkItem creation endpoint is added.** Direct card creation
  is deliberately out of scope; a card continues to be produced only by the
  approved-Proposal materialization path (workflow step 7). Card creation remains
  **blocked by architecture** until an authorizing decision exists.
- Card ordering uses a variable-length lexicographic fractional index (base-62,
  seeded `U`), producing a deterministic `rank` between any two neighbours; an
  exhausted key space raises a `RANK_SPACE_EXHAUSTED` conflict rather than
  silently renumbering. Lifecycle transitions are server-authoritative
  (`ready→in_progress→in_review→done`, with `blocked`/`cancelled` reachable as
  specified); WIP limits are enforced per target column.

**Consequences.** The `boards.columns` JSONB list documented in section 3 is now
a derived mirror of `board_columns`; the authoritative column state is
relational. Read endpoints fall back to the mirror for boards that predate the
table. New HTTP operations (`board.create/update`,
`board_column.create/update/delete`, `board_card.move`) join Amendment A-02's
retryable-idempotency and optimistic-concurrency scope. Verified by
`services/work-management/tests/test_board_api_integration.py`,
`test_board_ranking_unit.py`, `test_models_unit.py` and the migration tests.

### Amendment A-04 — Entity comments and generic attachments (Issue #29)

**Status:** Accepted.

**Context.** [Issue #29](https://github.com/jacksonsr451/EventFlow/issues/29)
requires collaborative comments, authorized attachments, and an immutable audit
timeline for consultations, proposals, work items, and board cards. Issue #4
already provides consultation attachments, evidence, and history. Duplicating
that pipeline per entity type would let the upload rules, malware scanning, and
tenant checks drift, while rewriting the existing consultation tables would
break their released contract.

**Decision.**

- A new `entity_comments` table stores comments for all four entity types. It is
  **tombstone-only**: `deleted_at`/`deleted_by` mark removal, and triggers
  (`eventflow_entity_comments_block_rewrite`,
  `eventflow_entity_comments_block_mutation`) reject rewrites of the workspace,
  project, target, author, body, or creation time, and reject hard `DELETE` and
  `TRUNCATE`. There is no edit operation; the API never returns a tombstoned
  body.
- A new `entity_attachments`/`entity_attachment_blobs` pair stores attachments
  for proposals, work items, and board cards. Consultations keep their original
  `consultation_attachments` tables. Both paths share
  `services/attachment_support.py`, so the size bound, filename rules,
  content-type sniffing, and fail-closed scan classification are identical.
  Rejected objects store no blob; quarantined and rejected objects are never
  downloadable.
- `entity_comments.entity_id` and `entity_attachments.entity_id` are opaque
  UUIDs without a foreign key because the target spans four tables. The
  application resolves the public collection segment (`consultations`,
  `proposals`, `work-items`, `board-cards`) inside the caller's workspace and
  copies the resolved `project_id`; an unknown collection, a missing entity, or
  a foreign entity is reported as `404`. Composite FKs to
  `projects (workspace_id, id)` therefore keep every row in one workspace and
  project even though the entity itself is polymorphic.
- History is a read-only projection of the existing append-only
  `audit_records` table. No history table is added and no history entry can be
  created, rewritten, or deleted through the API. Actions are
  `comment.created`, `comment.deleted`, `attachment.uploaded`,
  `attachment.rejected`, and `attachment.deleted`.
- The cascade from `projects`/`workspaces` to comments is intentionally blocked
  by the `BEFORE DELETE` trigger once comments exist: evidence may not be
  silently discarded by deleting a parent row. Parent removal requires a
  controlled archival or maintenance path rather than an accidental cascade.
- **No WorkItem or BoardCard creation endpoint is added.** Creating a comment or
  attachment never fabricates downstream work.

**Consequences.** Ten new HTTP operations (`createEntityComment`,
`listEntityComments`, `getEntityComment`, `deleteEntityComment`,
`uploadEntityAttachment`, `listEntityAttachments`, `getEntityAttachment`,
`downloadEntityAttachment`, `deleteEntityAttachment`, `listEntityHistory`) join
Amendment A-02's retryable-idempotency scope for the two POSTs (comment create
and attachment upload). Consultation attachment/history routes keep their more
specific Issue #4 paths and remain authoritative for consultations; the generic
router is registered after them. Verified by
`services/work-management/tests/test_collaboration_integration.py`,
`test_models_unit.py`, and `test_migrations_integration.py`.

### Amendment A-05 — Project repository configuration (Issue #44)

**Status:** Accepted.

**Context.** [Issue #44](https://github.com/jacksonsr451/EventFlow/issues/44)
requires projects to reference GitHub or GitLab repositories without coupling
Work Management to provider APIs. The existing
`remote_integration_references` table maps an already-resolved remote resource
(provider, installation id, resource type, resource id); it is not a
project-level configuration record and must not be reused or overloaded. URL-only
uniqueness is unsafe because a repository can move and SSH/HTTPS forms differ.
Credentials must never be persisted.

**Decision.**

- A new `project_repositories` table owns project-level configuration. Its
  unique key is
  `(workspace_id, project_id, provider, provider_instance_id,
  remote_repository_id)`. `provider_instance_id` is the provider host and is
  deliberately distinct from an installation id.
- `repository_url` is normalized to a credential-free `https://host/full/path`
  form (`.git` removed) and is mutable metadata, not identity. HTTP, userinfo,
  ports, query strings, fragments, and host/instance mismatches are rejected
  before persistence. `repository_full_path` is stored for display and must
  agree with the URL.
- Status is `active`, `inactive`, or `archived`. `PATCH` may move only between
  active and inactive; `archived` is terminal and is reached through `DELETE`.
  `deactivated_at` is non-null exactly while inactive and `archived_at` exactly
  while archived. Archived identities block re-linking with
  `409 REPOSITORY_ARCHIVED`; only application-level deduplication is forbidden.
- `version` supports strong `If-Match` validators, and the existing
  `idempotency_records` primitive stores retry results for POST/PATCH/DELETE.
  Audit actions are `project_repository.linked|updated|deactivated|reactivated|unlinked`.
- **No provider integration is added.** There is no sync, clone, issue linking,
  branch inspection, remote mutation, or credential storage. New links are
  `verification_status = configured`; `verified` is reserved for a future
  adapter. No WorkItem, BoardCard, Proposal, or Approval is created or changed.

**Consequences.** Five HTTP operations (`createProjectRepository`,
`listProjectRepositories`, `getProjectRepository`, `updateProjectRepository`,
`unlinkProjectRepository`) are added. The existing remote-reference mapping is
unchanged and remains a separate concern. Verified by
`services/work-management/tests/test_project_repository_unit.py`,
`test_project_repository_integration.py`, `test_models_unit.py`,
`test_rbac_policy_unit.py`, and `test_migrations_integration.py`.

### Amendment A-06 — Business priority, SLA clocks, dependencies and notifications (Issue #30)

**Status:** Accepted.

**Context.** [Issue #30](https://github.com/jacksonsr451/EventFlow/issues/30)
requires approved WorkItems to carry a business priority derived from impact and
urgency, durable SLA clocks that respect business calendars, acyclic dependency
edges, and durable notifications. These concerns must not duplicate priority
logic across services, mutate historical SLA policy decisions, or lose
notifications when a transaction commits. Existing WorkItems and Consultations
already carry a `priority`, so the migration must be additive.

**Decision.**

- The matrix is implemented once in `services/priority.py`. `business_impact`
  and `business_urgency` are nullable additions to `consultations`; when both are
  supplied the service derives `priority` and requires a 10-300 character
  `priority_override_reason` if the submitted priority differs. Bug and security
  severity remain separate triage criteria and never feed the matrix.
- `work_items` gains nullable `calculated_priority`, `priority_override_reason`,
  and `priority_overridden_by`. An override preserves the matrix-derived value;
  the reason/actor pair is enforced by
  `ck_work_items_priority_override_actor_consistency`, and the override is
  audited and notified.
- SLA policies are immutable version rows in `sla_policies`. Versions are unique
  on `(workspace_id, project_id, name, version)`, and partial unique indexes
  allow one active version per name and scope (workspace default or project).
  Activation retires the prior active version; it never rewrites a running
  clock.
- `sla_instances` holds exactly one clock per WorkItem, pinned to the policy
  version and an immutable JSON snapshot. `started_at` is the WorkItem creation
  time. `sla_pause_intervals` and `sla_events` are append-only chronology; the
  unique `(instance_id, event_type, due_at)` key makes warning/breach emission
  idempotent. Evaluation runs on read and in a `FOR UPDATE SKIP LOCKED` worker.
- `work_item_dependencies` stores directed edges with a unique
  `(workspace_id, blocking_work_item_id, blocked_work_item_id)` key, a no-self
  edge check, and composite FKs to both WorkItems and the project. Cycle
  detection cannot be a CHECK constraint, so it runs under
  `pg_advisory_xact_lock(hashtextextended(:key, 0))` in the writing
  transaction.
- Notifications are written transactionally with the domain change;
  `notifications` is unique on `(workspace_id, dedup_key)`.
  `notification_deliveries` stores one row per channel with bounded retry state,
  and `notification_preferences` is unique per recipient and event type. The
  notification insert and its delivery rows use a savepoint so a concurrent
  duplicate can reuse the committed winner without aborting the domain
  transaction. In-app delivery is immediate; email has no transport in this
  scope and is recorded as `unavailable`. Recipients come only from trusted
  entity data, and security-category WorkItems produce metadata-only redacted
  notification copy. Mark-read and identical preference writes are naturally
  idempotent and do not declare `Idempotency-Key`.
- Migration `0011_priority_sla_dependencies` is additive; existing priority
  values are retained and the new columns are nullable. No provider credentials,
  webhooks, installation ids, or external delivery are introduced.

**Consequences.** Fourteen HTTP operations are added (five SLA policy
operations, WorkItem SLA read, priority override, three dependency operations,
two notification operations, and two preference operations). The existing
approval gate is unchanged, and starting an SLA clock never creates downstream
work. Verified by `services/work-management/tests/test_priority_sla_unit.py`,
`test_priority_sla_notification_integration.py`, `test_models_unit.py`,
`test_migrations_integration.py`, and the contract suite.

## Consequences

### Positive

- One authoritative store per bounded context, consistent with ADR-001/006.
- Contract enum values and workflow invariants are enforced by the database, so
  invalid states are rejected even if application validation regresses.
- Composite foreign keys make cross-tenant references unrepresentable.
- Alembic migrations give reviewable, reversible schema history and avoid
  `create_all()` drift.
- The idempotency table supports ADR-007 section 3.6. The approval decision,
  Kanban board operations, and project repository operations use it; other A-02
  endpoint integrations remain future runtime work.

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
