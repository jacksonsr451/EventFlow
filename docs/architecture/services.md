# EventFlow Services and Domain Boundaries

## Status

Planned service responsibilities. No service implementation exists in the
current repository.

## Gateway

- **Purpose:** HTTP entry point for clients.
- **Technology:** Python/FastAPI.
- **Responsibilities:** JWT authentication, routing and request/correlation IDs.
- **Owns:** Gateway concerns and request context only.
- **Does not own:** Order, Catalog, Inventory or Payment domain state.
- **Communication:** HTTP with clients and downstream service contracts.
- **Dependencies:** Orders and the configured authentication concerns.
- **Failure considerations:** Must not contain business decisions or access service databases.

## Orders

- **Purpose:** Own the Order workflow and Saga coordination.
- **Technology:** Python/FastAPI.
- **Responsibilities:** Order, Cart, accepted PriceQuote data and local Saga progress.
- **Owns:** `Order`, `OrderItem`, `Cart`, accepted quote snapshots and workflow state.
- **Does not own:** Stock, Reservation authority, Product data or financial state.
- **Communication:** HTTP for immediate reads; asynchronous commands/events for the Saga.
- **Dependencies:** Catalog boundary, Inventory and Payments contracts, and the broker.
- **Failure considerations:** Must handle duplicate/out-of-order messages, ambiguous payment outcomes and reconciliation.

## Inventory

- **Purpose:** Authority for physical stock and temporary reservations.
- **Technology:** Java/Spring Boot.
- **Responsibilities:** Stock, Reservation, ReservationItem, expiry, release, consumption and concurrency.
- **Owns:** Stock quantity and Reservation state.
- **Does not own:** Cart, Order state, Product commercial data or Payment state.
- **Communication:** HTTP/read contract for current availability when serving Cart views; asynchronous workflow commands/events for reservations and local PostgreSQL transactions.
- **Dependencies:** Broker and PostgreSQL; no other service database.
- **Failure considerations:** Multi-item reservations are atomic; local locking preserves the stock invariant.

## Payments

- **Purpose:** Authority for financial operations and their reconciliation.
- **Technology:** Python/FastAPI.
- **Responsibilities:** Authorization/capture, financial idempotency, compensation and provider reconciliation.
- **Owns:** Payment state, financial operations and compensations.
- **Does not own:** Order workflow, Reservation state or notification delivery.
- **Communication:** Asynchronous payment and compensation commands/events, with provider calls behind its boundary.
- **Dependencies:** Payment provider, broker and its own persistence.
- **Failure considerations:** Timeout is not rejection; `UNKNOWN`/`PROCESSING` requires reconciliation and may keep Orders in `CANCELLING`.

## Notifications

- **Purpose:** Consume relevant workflow events and produce notifications.
- **Technology:** Go.
- **Responsibilities:** Asynchronous notification delivery for events such as `order.confirmed`, `order.cancelled` and explicitly designated payment-related events.
- **Owns:** Notification records and the processing/audit information required for notification idempotency. A conceptual record may contain `notification_id`, `source_event_id`, `correlation_id`, channel, recipient reference, template/type, status, attempts and timestamps.
- **Does not own:** Order state, stock, payment state, Saga decisions, Catalog data or any other service's database.
- **Communication:** Consumes the common event envelope from the Kafka-compatible broker and calls external providers through provider contracts.
- **Dependencies:** Broker, its own persistence, notification providers and shared telemetry conventions.
- **Failure considerations:** Assumes at-least-once delivery; uses transport and business-operation idempotency, bounded concurrency, provider-aware retries, backpressure and DLQ handling. External provider side effects are not exactly-once.

Notifications is not a Saga participant that can change workflow state. A
notification failure does not reopen or alter a `CONFIRMED` or `CANCELLED`
Order. A future exception would require a separate architectural decision.

Conceptual notification states may include `PENDING`, `PROCESSING`, `SENT`
and `FAILED`; this is not a final schema.

Go is selected because Notifications is an event-oriented, I/O-bound consumer
that may integrate with multiple providers and is a useful context for
controlled concurrency, cancellation, timeout, graceful shutdown and
backpressure in a polyglot system. This is not a claim that Go is universally
faster or that every Go concurrency primitive must be used. Goroutines,
channels, worker pools and `context.Context` are implementation options only
when concrete needs justify them.

### Notifications Operational Behavior

Notifications may use a configurable, bounded worker pool. Its concurrency
must respect provider capacity, rate limits, memory, CPU, connections and
backpressure; the worker count is not decided at this phase. Transient
provider failures such as timeouts, 429, 502, 503 or temporary network errors
use bounded retries with exponential backoff and jitter. Permanent failures
do not receive useless retries and follow the applicable DLQ policy.

Future Go operations that call providers, the broker, persistence or telemetry
should receive and propagate `context.Context` for deadlines and cancellation.
It is not a container for domain data. During graceful shutdown, the planned
behavior is to stop accepting new work, cancel operations when appropriate,
allow in-flight work to finish within a limit, avoid premature message
acknowledgement, close connections, flush telemetry and exit. Exact mechanics
are implementation concerns.

Future Notifications metrics should cover processed and deduplicated events,
created/sent/failed notifications, provider latency and failures, retries and
exhaustion, DLQ routing, backlog and oldest-item age, active/in-flight workers,
rate-limit responses, cancellation and shutdown drain. Labels remain bounded,
such as `channel`, `provider`, `result` and `event_type`; identifiers such as
`notification_id`, `order_id`, `event_id` and `correlation_id` belong in logs or
traces instead.

## Catalog Domain Boundary

- **Purpose:** Authority for products and commercial information.
- **Technology:** Operational isolation/deployment is undecided.
- **Responsibilities:** Product, SKU, name/description, current price and commercial status.
- **Owns:** Product and current commercial data.
- **Does not own:** Physical quantity, Reservation or Order state.
- **Communication:** A Catalog-owned HTTP/read model or equivalent boundary for Cart and quote-related reads; the exact operational isolation remains undecided.
- **Dependencies:** None specified at this phase.
- **Failure considerations:** A timeout is technical unavailability, not an `INACTIVE` business state.

Catalog may initially be hosted with an existing application or service. Do
not infer a standalone microservice from this domain boundary.

## Ownership Summary

- Orders owns `Order`, `OrderItem`, `Cart`, accepted `PriceQuote` data and Saga progress.
- Inventory owns `Stock`, `Reservation`, `ReservationItem` and reservation state.
- Payments owns `Payment`, financial operations and financial compensations.
- Catalog owns `Product` and current commercial information.

Ownership is exclusive even when development uses one physical PostgreSQL
instance. See [data ownership](data-ownership.md).
