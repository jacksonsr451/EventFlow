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
| `consultations` | Submitted requests | enums; `(workspace_id, project_id)` FK to `projects` |
| `proposals` | Versioned plans | unique `(consultation_id, version)`; array checks |
| `approvals` | One decision per proposal version | unique `(proposal_id, proposal_version)`; `sha256` hash |
| `work_items` | Execution work | origin trigger; composite FKs to project, proposal and approval |
| `boards` / `board_cards` | Kanban placement | unique `(board_id, work_item_id)`, unique `(board_id, column_id, rank)` |
| `audit_records` | Append-only audit trail | block `UPDATE`/`DELETE` triggers; `sha256` snapshot hash |
| `idempotency_records` | Stored responses per client key | unique `(workspace_id, operation, idempotency_key)` |
| `remote_integration_references` | GitHub/GitLab identity mapping | unique external resource key |

## Invariants Enforced by the Database

Application code validates first; the database is the last line of defense.

- **Tenant integrity.** Every tenant-owned table carries a non-null
  `workspace_id`. Child rows reference parents through composite foreign keys
  `(workspace_id, parent_id) -> parent(workspace_id, id)`, so a row can never
  point at another workspace's data. This supports the
  [tenant isolation](../security/tenant-isolation.md) invariants.
- **Proposal versioning.** `proposals` has `UNIQUE (consultation_id, version)`;
  `approvals` has `UNIQUE (proposal_id, proposal_version)`.
- **WorkItem provenance.** A `BEFORE INSERT/UPDATE` trigger requires the
  referenced approval to exist in the same workspace, to match the proposal and
  version, and to be `approved`. A WorkItem cannot come from a Consultation or
  an unapproved Proposal.
- **Append-only audit.** `BEFORE UPDATE` and `BEFORE DELETE` triggers on
  `audit_records` raise, preserving history.
- **Idempotency.** The decision and its `idempotency_records` row are written in
  one transaction; a retry with the same key and fingerprint returns the stored
  result, a different request under the same key conflicts.

## Idempotency

`ApprovalRepository.decide` computes a SHA-256 fingerprint of the request,
reserves `(workspace_id, operation, idempotency_key)`, writes the Approval, the
proposal status change, an audit record and the idempotency record, then commits
once. Concurrent retries with the same key resolve to a single effect: the loser
of the unique-insert race reads the stored result and replays it. This implements
ADR-007 section 3.6 for `.../decide` and provides the storage primitive for
Amendment A-02, which is not applied here.

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
