# Work Management Persistence

This document describes how the Work Management bounded context is persisted.
It implements [ADR-008](../adr/ADR-008-work-management-persistence.md) and the
Work Management workflow in
[work-management-workflow.md](work-management-workflow.md). The authoritative
field shapes are the entity definitions in
[work_management.yaml](../../contracts/schemas/work_management.yaml); the
database adds the constraints those contracts cannot express.

## Stack

- **PostgreSQL** is the system of record.
- **SQLAlchemy 2.x** defines the models (`services/work-management/src/eventflow_work_management/models/`).
- **Alembic** owns schema evolution; `Base.metadata.create_all()` is not a
  deployment path.
- **psycopg 3** is the driver, used through the `postgresql+psycopg` dialect.

The service is a self-contained Poetry project at `services/work-management/`
and does not depend on Order Processing code or tables.

## Tables

| Table | Purpose | Key constraints |
|---|---|---|
| `workspaces` | Tenant boundary | unique `slug` (format checked) |
| `projects` | Grouping inside a workspace | unique `(workspace_id, key)`, unique `(workspace_id, id)` |
| `consultations` | Submitted requests | enums; `(workspace_id, project_id)` FK to `projects`; unique `(workspace_id, project_id, id)` |
| `proposals` | Versioned plans | unique `(consultation_id, version)`; project-bound consultation FK; array checks |
| `approvals` | One decision per proposal version | unique `(proposal_id, proposal_version)`; `sha256` hash |
| `work_items` | Execution work | unique `origin_proposal_id`; origin trigger; project-bound proposal FK; composite FKs to project and approval |
| `boards` / `board_cards` | Kanban placement | card `project_id` bound to board and WorkItem by composite FKs; unique `(board_id, work_item_id)`, unique `(board_id, column_id, rank)` |
| `audit_records` | Append-only audit trail | block `UPDATE`/`DELETE`/`TRUNCATE` triggers; `sha256` snapshot hash |
| `idempotency_records` | Stored responses per client key | unique `(workspace_id, operation, idempotency_key)` |
| `remote_integration_references` | GitHub/GitLab identity mapping | unique external resource key; same-workspace entity guard |

## Invariants Enforced by the Database

Application code validates first; the database is the last line of defense.

- **Tenant integrity.** Every tenant-owned table carries a non-null
  `workspace_id`. Child rows reference parents through composite foreign keys
  `(workspace_id, parent_id) -> parent(workspace_id, id)`, so a row can never
  point at another workspace's data. This supports the
  [tenant isolation](../security/tenant-isolation.md) invariants.
- **Project consistency.** A Proposal's `(workspace_id, project_id,
  consultation_id)` must match an existing Consultation through the composite FK
  `fk_proposals_workspace_project_consultation`, and a WorkItem's
  `(workspace_id, project_id, origin_proposal_id)` must match its origin
  Proposal through `fk_work_items_workspace_project_proposal`. A Proposal
  therefore cannot belong to a different project than its Consultation, and a
  WorkItem cannot belong to a different project than the approved Proposal it
  came from.
- **Board card project consistency.** `board_cards` stores an internal
  `project_id` and references `boards` and `work_items` through the composite
  foreign keys `fk_board_cards_workspace_project_board` and
  `fk_board_cards_workspace_project_work_item`. A card's Board and WorkItem must
  therefore belong to the same workspace *and* the same project; a card cannot
  join a board in one project to a WorkItem in another. The column is
  functionally dependent on the board and is kept consistent by the constraints.
- **WorkItem cardinality.** `work_items` has `UNIQUE (origin_proposal_id)`: at
  most one WorkItem can originate from a given Proposal, per workflow step 7.
- **Proposal versioning.** `proposals` has `UNIQUE (consultation_id, version)`;
  `approvals` has `UNIQUE (proposal_id, proposal_version)`.
- **WorkItem provenance.** A `BEFORE INSERT/UPDATE` trigger requires the
  referenced approval to exist in the same workspace, to match the proposal and
  version, and to be `approved`. A WorkItem cannot come from a Consultation or
  an unapproved Proposal, and the origin columns cannot be updated to an
  invalid Proposal/version.
- **Append-only audit.** `BEFORE UPDATE`, `BEFORE DELETE` and `BEFORE TRUNCATE`
  triggers on `audit_records` raise, preserving history against row and
  whole-table mutation.
- **Remote reference integrity.** A `BEFORE INSERT/UPDATE` trigger requires a
  `remote_integration_references` row whose `entity_type` names a Work
  Management entity to reference an entity that exists in the same workspace.
  Unknown entity types are forward-compatible and are not validated here.
- **Idempotency.** The decision and its `idempotency_records` row are written in
  one transaction; a retry with the same key and fingerprint returns the stored
  result, a different request under the same key conflicts.

## Idempotency

`ApprovalRepository.decide` computes a SHA-256 fingerprint of the request,
reserves `(workspace_id, operation, idempotency_key)`, writes the Approval, the
proposal status change, an audit record and the idempotency record, then commits
once. Concurrent retries with the same key resolve to a single effect: the loser
of the unique-insert race reads the stored result and replays it. This implements
ADR-007 section 3.6 for `.../decide` and provides the storage primitive that
Amendment A-02 relies on; A-02 itself is a contract change applied by
[Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11).

## Tenant Isolation Scope

Composite foreign keys and application-layer workspace scoping are enforced
today. PostgreSQL Row-Level Security is **deferred** until an authentication
context exists (Issues #9/#10); see
[open decisions](../security/open-decisions.md). The deferral is intentional and
must not be read as full isolation coverage.

## Running Migrations

```bash
export EVENTFLOW_DATABASE_URL="postgresql+psycopg://eventflow:<password>@localhost:5432/eventflow"
alembic -c services/work-management/alembic.ini upgrade head
alembic -c services/work-management/alembic.ini downgrade base
```

Local PostgreSQL is provided by the root `docker-compose.yml`. CI runs the same
migrations and the PostgreSQL-backed suite; see
[ci-cd.md](../development/ci-cd.md) and
[testing-strategy.md](../development/testing-strategy.md).

## Traceability

Each control is traced from its requirement to the database object that enforces
it, the repository behavior, and the PostgreSQL-backed test that proves it.

| Requirement | Database object | Repository behavior | Test |
|---|---|---|---|
| Tenant isolation (cross-workspace) | composite FKs `fk_*_workspace_*` | workspace-scoped `get`/`list` methods | `test_cross_workspace_reference_is_rejected`, `test_reference_to_another_workspace_entity_is_rejected` |
| Project consistency | `fk_proposals_workspace_project_consultation`, `fk_work_items_workspace_project_proposal` | callers pass matching `project_id` | `test_proposal_project_must_match_consultation_project`, `test_work_item_project_must_match_origin_proposal_project` |
| Board card project consistency | `fk_board_cards_workspace_project_board`, `fk_board_cards_workspace_project_work_item` | `BoardCardRepository.add_card` derives `project_id` from the board | `test_board_card_cross_project_is_rejected`, `test_board_card_cross_project_direct_sql_is_rejected`, `test_board_card_cross_workspace_is_rejected`, `test_board_card_update_to_cross_project_work_item_is_rejected`, `test_changing_work_item_project_cannot_invalidate_existing_card` |
| WorkItem cardinality | `uq_work_items_origin_proposal` | `WorkItemRepository.create_from_approved_proposal` conflict handling | `test_second_work_item_from_same_proposal_is_rejected`, `test_duplicate_work_item_via_direct_sql_is_rejected`, `test_concurrent_work_items_from_same_proposal_has_exactly_one_effect` |
| WorkItem origin | `trg_work_items_origin_guard` | `WorkItemRepository.create_from_approved_proposal` | `test_work_item_requires_approved_proposal`, `test_work_item_rejects_mismatched_proposal_version`, `test_work_item_origin_cannot_be_updated_to_invalid_version` |
| Audit immutability | `trg_audit_records_no_update/_no_delete/_no_truncate` | `AuditRepository.append` (insert only) | `test_audit_records_are_append_only`, `test_audit_records_cannot_be_truncated` |
| Idempotency | `uq_idempotency_records_scope_key` | `ApprovalRepository.decide` + `IdempotencyRepository` | `test_same_key_replays_without_new_effects`, `test_same_key_different_request_conflicts`, `test_concurrent_same_key_has_exactly_one_effect` |
| Approval uniqueness | `uq_approvals_proposal_version` | `ApprovalRepository.decide` conflict handling | `test_new_key_for_decided_version_is_rejected` |
| Remote reference uniqueness and integrity | `uq_remote_integration_references_resource`, `trg_remote_references_entity_guard` | `RemoteReferenceRepository.link` | `test_duplicate_remote_resource_is_rejected`, `test_reference_to_unknown_entity_is_rejected` |
| Proposal version uniqueness | `uq_proposals_consultation_version` | `ProposalRepository._next_version` | `test_duplicate_proposal_version_is_rejected`, `test_concurrent_proposals_never_duplicate_versions` |
| Migration reproducibility | Alembic `0001_initial` | `support.run_migrations` | `test_migrations_integration.py` |

## Residual Risks and Deferred Controls

- **Row-Level Security is deferred** until an authentication context exists
  (Issues #9/#10). Until then, application-layer scoping remains load-bearing and
  a missing `WHERE workspace_id = ...` is a real risk (Issue #47).
- **Test database configuration fails closed.** Integration tests require an
  explicit `EVENTFLOW_TEST_DATABASE_URL`; they never fall back to
  `EVENTFLOW_DATABASE_URL`, and destructive operations only target generated
  `eventflow_test_<12 hex>` databases. A shared application/test URL is still
  possible by configuration (as CI does), so point the test URL at a disposable
  database.
- **Remote references with unknown `entity_type`** are accepted without
  existence or workspace validation; provider integrations own those semantics.
- **`updated_at`** is maintained by the ORM `onupdate`, not a database trigger,
  so a direct SQL `UPDATE` does not refresh it.
- **Migration and application use the same PostgreSQL role** in development.
  A production deployment must separate the migration administrator from the
  least-privilege application role; that separation is not implemented here.
- **`downgrade base` drops populated tables**, so it is technically reversible
  but not data-preserving. It must never run against production data.
