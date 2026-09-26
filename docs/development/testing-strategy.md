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
validate OpenAPI, AsyncAPI and schema artifacts under `contracts/`.

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
