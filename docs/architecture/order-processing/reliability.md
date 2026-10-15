# Order Processing Reliability and Failure Scenarios

This document separates three things that are easy to conflate:

1. What the architecture **requires**.
2. What is **implemented and verifiable** in the repository today.
3. What is **not specified** and must be decided during implementation.

Sources: [order-workflow.md](../order-workflow.md),
[communication.md](../communication.md), [services.md](../services.md),
[ADR-004](../../adr/ADR-004-order-orchestration.md),
[ADR-005](../../adr/ADR-005-polyglot-service-architecture.md).

## Documented Reliability Model

| Mechanism | Documented requirement | Status today |
|---|---|---|
| Transactional outbox | State change and event appended in one local transaction | MISSING (no service code) |
| Inbox / consumer dedup | Duplicate delivery must not change state or re-fire effects | MISSING |
| At-least-once delivery | Consumers must be idempotent; exactly-once is not promised | CONTRACTED (envelope + idempotent keys) |
| Idempotent commands | Stable operation ids: `order_id`, `reservation_id`, `payment_id`, `compensation_id`, `event_id` | CONTRACTED |
| HTTP idempotency | `POST /v1/orders` requires `Idempotency-Key`; replay vs `409` conflict | CONTRACTED |
| Saga compensation | Inventory release + payment compensation before terminal `CANCELLED` | CONTRACTED (events + workflow) |
| Provider ambiguity handling | `PROCESSING`/`UNKNOWN` reconciled, never assumed declined | CONTRACTED (events) |
| Retry / backoff / jitter | Transient failures retried with bounded exponential backoff; permanent failures to DLQ | PLANNED (OPD-06) |
| Timeout values | Per-step timeouts and expiry windows | PLANNED (OPD-06) |
| Backlog / DLQ thresholds | Alerting thresholds | PLANNED (OPD-06) |
| Reconciliation job | Detects and repairs deterministic projection divergence | PLANNED (Issue #54) |
| Crash recovery | A restart resumes from persisted state and Outbox | MISSING |

No runtime reliability guarantee can be claimed today: Order Processing is
**contract-specified only** on `main`. The guarantees below are therefore
**contract-level** expectations and a **test plan**, not evidence of a running
system.

## Verifiable Scenarios

Each scenario has an expected behavior and the invariant it protects. These are
candidates for executable tests once services exist; the contract-level aspects
are already fixed by the workflow events.

| ID | Scenario | Stimulus | Expected behavior | Protected invariant |
|---|---|---|---|---|
| RS-01 | Broker unavailable during checkout | Kafka-compatible broker unreachable | Checkout fails cleanly (`503`) or the Outbox row remains for later publish; an Order without an Outbox row must never exist | Atomic state + event |
| RS-02 | Duplicate event delivery | `inventory.reserved` delivered twice | Reservation stored once; second delivery is a no-op; payment requested once | Idempotent by `reservation_id` |
| RS-03 | Insufficient stock | Inventory cannot reserve all items | Atomic all-or-nothing rejection; `inventory.rejected`; order goes `CANCELLED` with no payment | Atomic reservation, no partial hold |
| RS-04 | Cart changed during checkout | Prices/contents differ at checkout | Reject with `409`/`422`; no order from a stale quote | Server-authoritative quote |
| RS-05 | Provider timeout | No provider response in the window | `PROCESSING`/`UNKNOWN`, **not** declined; reconciliation with idempotency key and `payment_id` | No false decline; funds not duplicated |
| RS-06 | Late charge after cancellation | Approval arrives after terminal `CANCELLED` | Late charge compensated; order not revived | Terminal state; compensation |
| RS-07 | Payment declined | Provider returns decline | `PAYMENT_PROCESSING → CANCELLING`; release reservation; compensate if needed; `CANCELLED` | Confirm requires approval |
| RS-08 | Crash after persisting a transition | Process dies mid-workflow | Restart resumes from persisted state + Outbox; no lost or duplicated effect | Outbox + idempotency |
| RS-09 | Poison message | Unprocessable event | Bounded retries then DLQ; workflow observable at `CANCELLING` if compensation pending | No infinite loop; no silent drop |
| RS-10 | Same idempotency key, different content | Reused `Idempotency-Key` with changed body | `409` idempotency conflict; original result preserved | Replay safety |
| RS-11 | Sends exhausted retries while outbox has pending records | Shutdown with pending Outbox rows | Sends stop; rows are published after restart | At-least-once delivery |

## Unspecified Values

The following are intentionally **not invented** and must be chosen and
documented during implementation (OPD-06): retry counts, base and max backoff,
jitter policy, per-step timeouts, reservation expiry window, reconciliation
cadence, DLQ alert thresholds, and the payment idempotency key derivation.

## Contract-Level Evidence Today

The workflow events that make these scenarios decidable are frozen by
[`tests/contracts/order_processing_preservation.py`](../../../tests/contracts/test_order_processing_preservation.py):
the 15 event types, the envelope reuse (including `schema_version` pinned to
`1`), and the enum values for order, reservation and payment state. Runtime
reliability tests belong to Issues [#50](https://github.com/jacksonsr451/EventFlow/issues/50)
through [#54](https://github.com/jacksonsr451/EventFlow/issues/54).
