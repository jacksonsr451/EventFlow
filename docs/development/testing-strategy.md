# Testing Strategy

Testing will combine unit, integration, contract, end-to-end and resilience
tests. Repository-level contract tests already exist under `tests/contracts/`
and security specification tests under `tests/security/`; both run in CI. The
Work Management service also has PostgreSQL-backed persistence unit and
integration tests under `services/work-management/tests/` (ADR-008). End-to-end
and resilience tests do not exist yet.

## Required Invariants

- Two concurrent orders cannot oversell the same stock.
- A multi-item Reservation is atomic.
- A duplicate event does not duplicate a business effect.
- A duplicate release does not return stock twice.
- A duplicate refund or compensation does not duplicate a financial effect.
- `CONFIRMED` requires approved payment and a valid Reservation.
- `CANCELLED` requires all mandatory compensations to be complete.
- An old or contradictory event cannot cause an invalid transition.
- Outbox republication does not break consumers.
- Deterministic reconciliation can auto-heal a projection.
- Ambiguous divergence is recorded and not silently corrected.

Resilience scenarios should include broker outage, publisher crash, consumer
restart, provider timeout and DLQ reprocessing. The existing CI validation of
OpenAPI, AsyncAPI and schema artifacts under `contracts/` plus the
`tests/contracts/` suite (run via `testrunner tests -v --disable-plugin-autoload`)
is extended by future implementation-level contract tests once services and
clients exist.

## Order Processing (Contract Level)

The Order Processing bounded context has no service yet, so its coverage is
contractual. `tests/contracts/test_order_processing_preservation.py` freezes the
Orders, Inventory, Payments and Notifications contract surface against
`tests/contracts/order_processing_baseline.json`, checks the event taxonomy and
envelope, the `problem+json` errors and the Work Management boundary, and
verifies the documentation set. The invariants above and the failure scenarios
are detailed per transition in
[order-processing/workflow.md](../architecture/order-processing/workflow.md) and
[order-processing/reliability.md](../architecture/order-processing/reliability.md);
runtime coverage begins with Issues #50–#54.

## Work Management Persistence (Implemented)

The Work Management service persists its bounded context in PostgreSQL
([ADR-008](../adr/ADR-008-work-management-persistence.md),
[work-management-persistence.md](../architecture/work-management-persistence.md)).
Its suite runs with `jsr-testrunner` and proves behavior against a real
PostgreSQL instance:

- migrations apply from empty to `head`, are idempotent and downgrade to `base`;
- every contract enum, check constraint, unique constraint and composite
  workspace foreign key rejects invalid or cross-tenant rows;
- an Approval is bound to one Proposal version and a WorkItem can only be
  created from an approved Proposal/version (database trigger);
- audit records are append-only (database trigger);
- an approval retry with the same `Idempotency-Key` replays without new effects,
  a different request under the same key conflicts, and concurrent same-key
  decisions produce exactly one effect;
- concurrent proposal creation never duplicates a `(consultation_id, version)`
  pair;
- remote integration references are unique per external resource;
- the development seed is deterministic and idempotent.

Integration tests skip themselves when no PostgreSQL URL is configured, so the
suite is inert in environments without a database.

## Quality Tooling Strategy

| Area | Pre-commit | CI | Status |
|---|---|---|---|
| Repository | whitespace, EOF, YAML/JSON syntax, conflicts, large files, case conflicts and private-key detection | Same repository hooks plus contract/documentation validation | Active |
| Contracts | `scripts/validate_contracts.py` with scoped execution | OpenAPI, AsyncAPI, JSON Schema, refs and examples; `tests/contracts` and `tests/security` via `testrunner tests -v --disable-plugin-autoload` | Active |
| Python | None; `scripts/validate_contracts.py` is repository tooling, not service code | Work Management persistence tests via `testrunner services/work-management/tests -v --disable-plugin-autoload` against PostgreSQL; Ruff and type checking still PLANNED | Partial |
| Java | The service build's fast formatter/checks when Inventory exists | Maven/Gradle compile, analysis and tests | Future |
| Go | `gofmt` and possibly fast `go vet` when a module exists | `gofmt -l`, `go vet` and tests | Future |
| Docker | Parser/lint checks when Dockerfiles exist | Image build and scanning | Future |
| Kubernetes | Manifest/chart checks when manifests exist | Full manifest/chart validation | Future |
| Terraform | `terraform fmt -check` when `.tf` files exist | Format, validate and security checks | Future |

Python type checking is **TO BE DECIDED**. Maven versus Gradle and Java
analysis tools are intentionally left to the Inventory project. The existing
CI remains authoritative; pre-commit is only fast local feedback.

Operational tests should also verify trace propagation across asynchronous
boundaries, bounded Outbox recovery, retry exhaustion, DLQ metadata and safe
reconciliation. Exact metric names, thresholds and alert rules belong to the
implementation phase.

## Notifications Coverage

Future Notifications tests should cover:

- a valid event producing the expected notification operation;
- duplicate events not producing duplicate local effects;
- stable provider idempotency keys when supported;
- bounded retries for transient provider failures;
- no useless retries for permanent failures;
- DLQ routing after the applicable policy is exhausted;
- bounded concurrency, rate limiting and backpressure;
- graceful shutdown, cancellation and provider timeouts;
- correlation and trace propagation across the broker boundary;
- provider unavailability and recovery.

These tests must not claim exactly-once external side effects. They should
verify behavior when a provider accepts a request before the consumer persists
its local result.
