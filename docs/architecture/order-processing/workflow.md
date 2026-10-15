# Order Processing Workflow and Transitions

This document reconstructs the contracted workflow from the authoritative
sources and maps every transition to its trigger, precondition, owner, contract,
emitted event, side effects, errors, retry, compensation and idempotency. It
does not change workflow semantics; where sources disagree, the discrepancy is
recorded in [Discrepancies](#discrepancies).

Sources: [order-workflow.md](../order-workflow.md),
[communication.md](../communication.md),
[ADR-004](../../adr/ADR-004-order-orchestration.md) and the contracts under
[`contracts/`](../../../contracts/README.md).

## States

Order lifecycle (`common.yaml#/$defs/OrderStatus`): `PENDING`,
`STOCK_RESERVED`, `PAYMENT_PROCESSING`, `CONFIRMED`, `CANCELLING`, `CANCELLED`.
`CONFIRMED` and `CANCELLED` are terminal.

Reservation lifecycle (`common.yaml#/$defs/ReservationStatus`): `ACTIVE`,
`CONSUMED`, `RELEASED`, `EXPIRED` (Inventory-owned).

Payment lifecycle (`common.yaml#/$defs/PaymentState`): `AUTHORIZED`, `CAPTURED`,
`UNKNOWN`, `PROCESSING`, `DECLINED` (Payments-owned).

## Order Transition Matrix

| From → To | Trigger | Preconditions | Owner | Input contract | Emitted event / command | Persistent side effects | Expected errors | Retry | Compensation | Idempotency | Observability |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (none) → `PENDING` | `POST /v1/orders` | Valid server-issued `quote_id` per item, `items` ≥ 1, quote valid | Orders | `CheckoutRequest` | `order.created` | Order row + Outbox row in one local transaction | `400`, `401`, `403`, `409`, `422`, `503` | Client retries safely | None | `Idempotency-Key` replay; equivalent request returns stored result | `correlation_id`, `order.created`, Outbox lag |
| `PENDING` → `STOCK_RESERVED` | `inventory.reserved` | Order is `PENDING`; reservation belongs to this order; not expired | Orders (records), Inventory (authority) | `ReservationResultPayload` | `payment.requested` | Store `reservation_id`, `reservation_expires_at` | Ignore/deny incompatible identity | Duplicate result is idempotent | None | `reservation_id` | Saga progress, reservation id |
| `PENDING` → `CANCELLED` | `inventory.rejected` | Order is `PENDING` | Orders | `ReservationRejectedPayload` | `order.cancelled` | Cancel without payment; no stock to release | Ignore late/duplicate | Duplicate result is idempotent | None (no stock held) | `reservation_id` | `order.cancelled`, rejection `reason` |
| `STOCK_RESERVED` → `PAYMENT_PROCESSING` | Orders issues payment | Reservation active | Orders | `PaymentRequestedPayload` | `payment.requested` | Store `payment_id` | Ignore if not `STOCK_RESERVED` | Duplicate start is idempotent | None | `payment_id` | Saga progress, payment id |
| `PAYMENT_PROCESSING` → `PAYMENT_PROCESSING` | `payment.processing` / `payment.unknown` | Payment awaiting provider outcome | Payments (authority), Orders (records) | `PaymentProcessingPayload` / `PaymentUnknownPayload` | Reconciliation query | No order transition; record ambiguous state | Do not treat as decline | Provider lookup with `payment_id` + idempotency key | None yet | `payment_id` | Ambiguity age, reconciliation outcomes |
| `PAYMENT_PROCESSING` → `CONFIRMED` | `payment.approved` | Payment approved (`AUTHORIZED`/`CAPTURED`) **and** reservation valid | Orders | `PaymentApprovedPayload` | `order.confirmed` | Order terminal `CONFIRMED` | Reject if payment not approved or reservation invalid | Duplicate confirmation idempotent | None | `event_id`, `order_id` | `order.confirmed`, terminal Saga age |
| `PAYMENT_PROCESSING` → `CANCELLING` | `payment.declined` | Order is `PAYMENT_PROCESSING` | Orders | `PaymentDeclinedPayload` | `inventory.release.requested` | Enter compensation; release reservation | Reject late decline after terminal | Duplicate decline idempotent | Inventory release required | `payment_id`, `reservation_id` | `CANCELLING` age, compensation id |
| `STOCK_RESERVED` or `PAYMENT_PROCESSING` → `CANCELLING` | Cancellation decision | Reservation held; no authoritative payment yet | Orders | (decision) | `inventory.release.requested`; `payment.compensation.requested` when an authorization/capture exists | Record required compensations | Reject cancellation from terminal | Duplicate decision idempotent | Per payment/stock state | `compensation_id`, `reservation_id` | Required vs completed compensations |
| `CANCELLING` → `CANCELLED` | All mandatory compensations complete | Inventory released, and payment compensated when a financial effect exists | Orders | `ReleasedPayload`, `CompensatedPayload` | `order.cancelled` | Order terminal `CANCELLED` | Stay `CANCELLING` while any known effect is unresolved | Duplicate completion idempotent | Complete only when all required effects finish | `compensation_id`, `reservation_id` | `order.cancelled`, unresolved effects |

## Participant State Transitions

| Owner | From → To | Trigger | Notes |
|---|---|---|---|
| Inventory | `ACTIVE` → `RELEASED` | `inventory.release.requested` | Idempotent by `reservation_id`; a duplicate release must not return stock twice |
| Inventory | `ACTIVE` → `EXPIRED` | Reservation `expires_at` passes | Atomic race with consume is decided by Inventory/PostgreSQL |
| Inventory | `ACTIVE` → `CONSUMED` | Successful confirmed workflow | Exact point is deferred (OPD-03); must be an Inventory-owned atomic transition |
| Payments | `PROCESSING` → `AUTHORIZED` / `CAPTURED` | Provider approval | Approval emitted as `payment.approved` |
| Payments | `PROCESSING` → `DECLINED` | Provider decline | Emitted as `payment.declined` |
| Payments | `PROCESSING` → `UNKNOWN` | Provider timeout | Not a decline; requires reconciliation |
| Payments | `CAPTURED`/`AUTHORIZED` → compensation | `payment.compensation.requested` | Payments chooses VOID vs REFUND |
| Notifications | local `PENDING` → `PROCESSING` → `SENT`/`FAILED` | Consumes `order.confirmed` / `order.cancelled` | Cannot change Order state; at-least-once |

## Invariants Preserved by Transitions

- `CONFIRMED` requires both an approved payment and a valid reservation.
- `CANCELLED` requires every mandatory compensation known for the workflow to be
  complete; an unresolved financial effect keeps the order `CANCELLING`.
- A late charge, release or payment result never revives a terminal order.
- Inventory and Payments alone mutate their authoritative state; Orders records
  progress and issues idempotent repair commands.
- Reconciliation repairs deterministic projection divergence only; contradictory
  evidence is recorded, not silently corrected.

## Discrepancies

| ID | Discrepancy | Sources | Smallest compatible correction |
|---|---|---|---|
| WD-01 | `feat/orders-domain` serializes `OrderStatus` as lowercase (`pending`); the contract enum is uppercase (`PENDING`) | branch `order_status.py` vs `common.yaml` | Reconcile the implementation to the contract during incorporation (OPD-07) |
| WD-02 | No HTTP operation exists for cancellation/refund even though the workflow defines `CANCELLING`/`CANCELLED` | `orders.yaml` vs order-workflow.md | Add endpoints additively under `/v1/` when a client needs them (CR-05) |
| WD-03 | `ACTIVE → CONSUMED` has no contract event | order-workflow.md (deferred) | Keep deferred; document the chosen event additively (OPD-03) |
