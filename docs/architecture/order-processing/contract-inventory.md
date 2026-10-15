# Order Processing Contract Inventory

This inventory covers every contract that belongs to the Distributed Order
Processing bounded context. It records the owning service, the operation or
event, required fields, validation, states, errors, side effects, idempotency,
authorization, retry/failure behaviour, versioning and implementation status,
based on repository evidence only.

No contract is invented here. When the architecture describes a capability for
which no contract exists, it is recorded as **PLANNED** or **MISSING**.

## How to Read This Inventory

- **Owner** is the bounded context that owns the data and the decision, per
  [services.md](../services.md) and [data-ownership.md](../data-ownership.md).
- **Status** uses the [status legend](README.md#status-legend).
- **Evidence** is a repository path; status is never inferred from a directory
  existing alone.
- Money is a decimal string plus an uppercase ISO-4217-style `currency`;
  timestamps are RFC 3339 UTC with a `Z` offset; identifiers are canonical UUID
  strings. These rules live in
  [`common.yaml`](../../../contracts/schemas/common.yaml) and the contracts
  [README](../../../contracts/README.md).

## Orders, Cart and PriceQuote

Owner: **Orders** (Saga orchestrator). Primary contract:
[`contracts/openapi/orders.yaml`](../../../contracts/openapi/orders.yaml).

| Contract | Kind | Operation / schema | Required fields | Status | Evidence |
|---|---|---|---|---|---|
| Cart read | HTTP `GET /v1/carts/{cart_id}` | `getCart` → `CartView` | `cart_id`, `items[]` (`sku`, `quantity`, `product`, `price`, `availability`) | CONTRACTED | orders.yaml, `http.yaml#/$defs/CartView` |
| Checkout request | HTTP body | `createOrderFromCheckout` → `CheckoutRequest` | `cart_id`, `items[]` (`sku`, `quantity`, `quote_id`) | CONTRACTED | orders.yaml, `http.yaml#/$defs/CheckoutRequest` |
| Checkout response | HTTP `201` | `CheckoutResponse` | `order`, `correlation_id` | CONTRACTED | orders.yaml, `http.yaml#/$defs/CheckoutResponse` |
| Order read | HTTP `GET /v1/orders/{order_id}` | `getOrder` → `OrderResponse` | `Order` | CONTRACTED | orders.yaml, `http.yaml#/$defs/OrderResponse` |
| `Order` | Schema | Aggregate view | `order_id`, `status`, `items[]`, `correlation_id`, `created_at` | CONTRACTED | `common.yaml#/$defs/Order` |
| `AcceptedOrderItem` | Schema | Immutable price snapshot | `sku`, `quantity`, `quote_id`, `unit_price`, `currency` | CONTRACTED | `common.yaml#/$defs/AcceptedOrderItem` |
| `CartItem` | Schema | Cart line intent | `sku`, `quantity` | CONTRACTED | `common.yaml#/$defs/CartItem` |
| `PriceQuote` | Schema | Time-limited offer | `quote_id`, `sku`, `unit_price`, `currency`, `valid_until` | CONTRACTED | `common.yaml#/$defs/PriceQuote` |
| `OrderStatus` | Enum | Lifecycle | `PENDING`, `STOCK_RESERVED`, `PAYMENT_PROCESSING`, `CONFIRMED`, `CANCELLING`, `CANCELLED` | CONTRACTED | `common.yaml#/$defs/OrderStatus` |
| Cancel / refund endpoint | HTTP | — | — | MISSING | No cancel or refund operation in orders.yaml |

Cart is purchase intent and never reserves stock. Checkout accepts server-issued
quote identifiers and never a client price or payment data
([order-workflow.md](../order-workflow.md)). `Idempotency-Key` is **required** on
`POST /v1/orders`; repeating an equivalent request replays the original result
and a different request under the same key is a `409` idempotency conflict.

Validation rules: `CheckoutRequest` and `CheckoutItem` are
`additionalProperties: false`; `items` has `minItems: 1`; checkout does not
declare `workspace_id`, `tenant_id`, payment state, reservation state or order
status. Errors use `application/problem+json` with the shared `Error`.

- Order creation error semantics: `400`, `401`, `403`, `409`, `422`, `503`
  (orders.yaml).
- Quote acquisition (issuance/validation API) is **MISSING** by design; checkout
  only consumes a server-controlled `quote_id` (OPD-02).

## Inventory

Owner: **Inventory** (Java/Spring Boot). Reservation contract:
[`contracts/asyncapi/workflow.yaml`](../../../contracts/asyncapi/workflow.yaml)
and [`contracts/schemas/events.yaml`](../../../contracts/schemas/events.yaml).

| Contract | Kind | Operation / schema | Required fields | Status | Evidence |
|---|---|---|---|---|---|
| Reserve command | Async | `inventory.reservation.requested` | `reservation_id`, `order_id`, `items[]` | CONTRACTED | events.yaml `ReservationRequested`, workflow.yaml |
| Reservation accepted | Async | `inventory.reserved` | `reservation_id`, `order_id`, `status=ACTIVE`, `items[]`, `expires_at` | CONTRACTED | events.yaml `ReservationReserved` |
| Reservation rejected | Async | `inventory.rejected` | `reservation_id`, `order_id`, `reason` | CONTRACTED | events.yaml `ReservationRejected` |
| Release command | Async | `inventory.release.requested` | `reservation_id`, `order_id` | CONTRACTED | events.yaml `ReleaseRequested` |
| Released | Async | `inventory.released` | `reservation_id`, `order_id`, `status=RELEASED` | CONTRACTED | events.yaml `Released` |
| `Reservation` | Schema | Aggregate | `reservation_id`, `order_id`, `status`, `created_at`, `expires_at`, `items[]` | CONTRACTED | `common.yaml#/$defs/Reservation` |
| `ReservationItem` | Schema | Reserved line | `sku`, `quantity` | CONTRACTED | `common.yaml#/$defs/ReservationItem` |
| `ReservationStatus` | Enum | Lifecycle | `ACTIVE`, `CONSUMED`, `RELEASED`, `EXPIRED` | CONTRACTED | `common.yaml#/$defs/ReservationStatus` |
| Availability read | HTTP | Cart availability | — | MISSING | No Inventory HTTP contract in `contracts/` |
| `ACTIVE → CONSUMED` | Transition | Atomic consume | — | PLANNED | order-workflow.md defers the exact point (OPD-03) |

Concurrency and consistency: multi-item reservations are atomic, all-or-nothing,
and the `ACTIVE → CONSUMED` race with `ACTIVE → EXPIRED` is decided atomically by
Inventory/PostgreSQL. Kafka does **not** enforce
`available_quantity >= requested_quantity`; the partition key `order_id` does not
protect stock ([order-workflow.md](../order-workflow.md)).

Idempotency: at-least-once delivery with `reservation_id` as the stable business
operation identifier; duplicate reserve/release results must not duplicate the
effect. Failure: invalid or exhausted messages follow DLQ policy; local deadlocks
may be retried with a bounded whole-transaction retry.

## Payments

Owner: **Payments** (Python/FastAPI). Payment events are carried on the same
workflow channel; there is no separate Payments OpenAPI contract.

| Contract | Kind | Operation / schema | Required fields | Status | Evidence |
|---|---|---|---|---|---|
| Payment command | Async | `payment.requested` | `payment_id`, `order_id`, `amount` | CONTRACTED | events.yaml `PaymentRequested` |
| Approved | Async | `payment.approved` | `payment_id`, `order_id`, `status∈{AUTHORIZED,CAPTURED}`, `amount` | CONTRACTED | events.yaml `PaymentApproved` |
| Declined | Async | `payment.declined` | `payment_id`, `order_id`, `status=DECLINED` | CONTRACTED | events.yaml `PaymentDeclined` |
| Processing | Async | `payment.processing` | `payment_id`, `order_id`, `status=PROCESSING` | CONTRACTED | events.yaml `PaymentProcessing` |
| Unknown | Async | `payment.unknown` | `payment_id`, `order_id`, `status=UNKNOWN` | CONTRACTED | events.yaml `PaymentUnknown` |
| Compensation command | Async | `payment.compensation.requested` | `payment_id`, `compensation_id`, `order_id` | CONTRACTED | events.yaml `CompensationRequested` |
| Compensated | Async | `payment.compensated` | `payment_id`, `compensation_id`, `order_id`, `result=COMPLETED` | CONTRACTED | events.yaml `Compensated` |
| `Payment` | Schema | Aggregate | `payment_id`, `order_id`, `status` (`amount` optional) | CONTRACTED | `common.yaml#/$defs/Payment` |
| `PaymentState` | Enum | Lifecycle | `AUTHORIZED`, `CAPTURED`, `UNKNOWN`, `PROCESSING`, `DECLINED` | CONTRACTED | `common.yaml#/$defs/PaymentState` |
| `CompensationResult` | Enum | Compensation | `COMPLETED` | CONTRACTED | `common.yaml#/$defs/CompensationResult` |
| Provider settlement/refund API | HTTP | — | — | MISSING | No provider contract in `contracts/` (OPD-05) |

Authorize/settle/refund are represented only by the `AUTHORIZED`/`CAPTURED`
enum values and by Orders requesting compensation; Payments — not Orders —
chooses VOID (authorization) versus REFUND (capture) or the provider-appropriate
action ([ADR-004](../../adr/ADR-004-order-orchestration.md),
[order-workflow.md](../order-workflow.md)). A timeout is not a decline:
`PROCESSING`/`UNKNOWN` require reconciliation with `payment_id`, idempotency key
and provider reference. Duplicate payment prevention relies on `payment_id` as
the stable operation identifier and on the financial idempotency key. A late
charge is compensated and never revives a cancelled order.

## Notifications

Owner: **Notifications** (Go). Notifications is an event consumer, not a Saga
participant; it produces no order-state change.

| Contract | Kind | Operation / schema | Required fields | Status | Evidence |
|---|---|---|---|---|---|
| Confirmed consumption | Async | `order.confirmed` (receive) | see `OrderConfirmed` | CONTRACTED | workflow.yaml `notificationsConsumeOrderConfirmed` |
| Cancelled consumption | Async | `order.cancelled` (receive) | see `OrderCancelled` | CONTRACTED | workflow.yaml `notificationsConsumeOrderCancelled` |
| `NotificationOperation` | Schema | Local record + idempotency | `notification_id`, `source_event_id`, `correlation_id`, `channel`, `status`, `attempts` | CONTRACTED | `common.yaml#/$defs/NotificationOperation` |
| Notification status enum | Enum | Local lifecycle | `PENDING`, `PROCESSING`, `SENT`, `FAILED` | CONTRACTED | `common.yaml#/$defs/NotificationOperation/properties/status` |
| Dedicated notification events | Async | — | — | MISSING | No `notification.*` event type exists |
| Provider delivery contract | HTTP | — | — | MISSING | No provider contract in `contracts/` |

Idempotency: a duplicate `event_id` or `source_event_id` must not create a
duplicate local notification operation. Retry: transient provider failures
(timeout, 429, 502, 503) use bounded exponential backoff with jitter; permanent
failures go to DLQ. Exactly-once external delivery is **not** promised; a stable
provider idempotency key is used only when the provider supports one
([services.md](../services.md), [order-workflow.md](../order-workflow.md)).

## Shared Primitives

Owner: shared contract baseline. Defined in
[`common.yaml`](../../../contracts/schemas/common.yaml); used by both domains
without conferring ownership.

| Definition | Purpose | Status |
|---|---|---|
| `UUID` | Canonical identifier pattern | CONTRACTED |
| `Timestamp` | RFC 3339 UTC instant | CONTRACTED |
| `Currency` | Uppercase three-letter code | CONTRACTED |
| `Money` | Decimal string + currency | CONTRACTED |
| `EventType` | Closed event-type enum (15 types) | CONTRACTED |
| `IdentifierEnvelope` | `order_id` correlation envelope | CONTRACTED |
| `Error` | RFC 9457-style problem shape with `code` enum | CONTRACTED |

`common.yaml` also hosts the Order Processing domain definitions `OrderStatus`,
`ReservationStatus`, `PaymentState`, `CompensationResult`, `CartItem`,
`PriceQuote`, `AcceptedOrderItem`, `ReservationItem`, `Order`, `Reservation`,
`Payment` and `NotificationOperation`. These are listed here because they are
consumed through the shared file; their ownership remains with the Order
Processing domain.

HTTP response wrappers live in
[`http.yaml`](../../../contracts/schemas/http.yaml): `CartLineView`, `CartView`,
`CheckoutItem`, `CheckoutRequest`, `OrderResponse`, `CheckoutResponse`,
`ErrorResponse`. Authorization is `bearerAuth` (HTTP bearer, JWT), validated by
the Gateway; resource ownership is checked server-side (orders.yaml).

## Event Catalog

All events use the common envelope from
[`envelope.yaml`](../../../contracts/schemas/envelope.yaml)
(`event_id`, `event_type`, `schema_version`, `occurred_at`, `producer`,
`correlation_id`, `causation_id`, `aggregate_type`, `aggregate_id`, `payload`).
Every event pins `schema_version` to `1` and partitions on `order_id`.

| Event type | Payload definition | Producer | Consumer(s) | Status |
|---|---|---|---|---|
| `order.created` | `OrderCreatedPayload` | Orders | (internal) | CONTRACTED |
| `inventory.reservation.requested` | `ReservationRequestedPayload` | Orders | Inventory | CONTRACTED |
| `inventory.reserved` | `ReservationResultPayload` | Inventory | Orders | CONTRACTED |
| `inventory.rejected` | `ReservationRejectedPayload` | Inventory | Orders | CONTRACTED |
| `payment.requested` | `PaymentRequestedPayload` | Orders | Payments | CONTRACTED |
| `payment.approved` | `PaymentApprovedPayload` | Payments | Orders | CONTRACTED |
| `payment.declined` | `PaymentDeclinedPayload` | Payments | Orders | CONTRACTED |
| `payment.processing` | `PaymentProcessingPayload` | Payments | Orders | CONTRACTED |
| `payment.unknown` | `PaymentUnknownPayload` | Payments | Orders | CONTRACTED |
| `inventory.release.requested` | `ReleaseRequestedPayload` | Orders | Inventory | CONTRACTED |
| `inventory.released` | `ReleasedPayload` | Inventory | Orders | CONTRACTED |
| `payment.compensation.requested` | `CompensationRequestedPayload` | Orders | Payments | CONTRACTED |
| `payment.compensated` | `CompensatedPayload` | Payments | Orders | CONTRACTED |
| `order.confirmed` | `OrderConfirmedPayload` | Orders | Notifications | CONTRACTED |
| `order.cancelled` | `OrderCancelledPayload` | Orders | Notifications | CONTRACTED |

The event schema definitions are `BaseEvent`, the payload definitions above,
and the event definitions `OrderCreated`, `ReservationRequested`,
`ReservationReserved`, `ReservationRejected`, `PaymentRequested`,
`PaymentApproved`, `PaymentDeclined`, `PaymentProcessing`, `PaymentUnknown`,
`ReleaseRequested`, `Released`, `CompensationRequested`, `Compensated`,
`OrderConfirmed` and `OrderCancelled`.

## Schema Definition Index

All definitions per file, for coverage verification:

| File | Definitions |
|---|---|
| `common.yaml` | `UUID`, `Timestamp`, `Currency`, `Money`, `OrderStatus`, `ReservationStatus`, `PaymentState`, `CompensationResult`, `EventType`, `IdentifierEnvelope`, `CartItem`, `PriceQuote`, `AcceptedOrderItem`, `ReservationItem`, `Order`, `Reservation`, `Payment`, `NotificationOperation`, `Error` |
| `http.yaml` | `CartLineView`, `CartView`, `CheckoutItem`, `CheckoutRequest`, `OrderResponse`, `CheckoutResponse`, `ErrorResponse` |
| `events.yaml` | `BaseEvent`, `OrderCreatedPayload`, `ReservationRequestedPayload`, `ReservationResultPayload`, `ReservationRejectedPayload`, `PaymentRequestedPayload`, `PaymentApprovedPayload`, `PaymentDeclinedPayload`, `PaymentProcessingPayload`, `PaymentUnknownPayload`, `ReleaseRequestedPayload`, `ReleasedPayload`, `CompensationRequestedPayload`, `CompensatedPayload`, `OrderConfirmedPayload`, `OrderCancelledPayload`, `OrderCreated`, `ReservationRequested`, `ReservationReserved`, `ReservationRejected`, `PaymentRequested`, `PaymentApproved`, `PaymentDeclined`, `PaymentProcessing`, `PaymentUnknown`, `ReleaseRequested`, `Released`, `CompensationRequested`, `Compensated`, `OrderConfirmed`, `OrderCancelled` |
| `envelope.yaml` | (top-level envelope object; no `$defs`) |

## Implementation Status Summary

| Capability | Status | Evidence |
|---|---|---|
| Contracts for Orders/Inventory/Payments/Notifications | CONTRACTED | `contracts/` |
| Contract validation (OpenAPI, AsyncAPI, JSON Schema, refs, example) | IMPLEMENTED | `scripts/validate_contracts.py`, `.github/workflows/ci.yml` |
| Contract / boundary regression tests | IMPLEMENTED | `tests/contracts/`, `tests/security/` |
| Gateway, Orders, Inventory, Payments, Notifications services | MISSING | no service code on `main` |
| Orders pure domain | PARTIALLY IMPLEMENTED (unmerged) | `origin/feat/orders-domain` (see [execution plan](execution-plan.md)) |
| Provider contracts (payment, notification) | MISSING | no files in `contracts/` |
| Cancel/refund HTTP operation, quote API, availability HTTP contract | MISSING | absent from `contracts/openapi/orders.yaml` |
| Happy-path workflow example | CONTRACTED | `contracts/examples/order-workflow.json` (no failure/compensation coverage) |
