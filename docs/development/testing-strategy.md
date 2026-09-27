# Testing Strategy

Testing will combine unit, integration, contract, end-to-end and resilience
tests. This document defines future coverage; it does not claim that tests
exist in the current repository.

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
restart, provider timeout and DLQ reprocessing. Future contract tests will
extend the existing CI validation of OpenAPI, AsyncAPI and schema artifacts
under `contracts/`.

## Quality Tooling Strategy

| Area | Pre-commit | CI | Status |
|---|---|---|---|
| Repository | whitespace, EOF, YAML/JSON syntax, conflicts, large files, case conflicts and private-key detection | contract/documentation validation | Active |
| Contracts | `scripts/validate_contracts.py` with scoped execution | OpenAPI, AsyncAPI, JSON Schema, refs and examples | Active |
| Python | None until service code and project tooling exist; repository tooling is not treated as FastAPI code | Ruff, type checking and tests when services exist | Future |
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
