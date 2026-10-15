# Order Processing and Work Management Separation

EventFlow is a monorepo with two strictly isolated bounded contexts
([ADR-006](../../adr/ADR-006-product-scope-and-bounded-contexts.md)). This
document records the separation rules that protect Order Processing from being
reinterpreted, replaced or silently coupled to Work Management.

## The Two Bounded Contexts

| Bounded context | Owns | Clients |
|---|---|---|
| Distributed Order Processing (Order Saga) | `Order`, `Cart`, `PriceQuote`, `Reservation`, `Payment`, `NotificationOperation` | Order Gateway consumers |
| Work Management | `Workspace`, `Consultation`, `Proposal`, `Approval`, `WorkItem`, `BoardCard` | Webapp, VS Code, Desktop |

Ownership is exclusive even when both domains share one physical PostgreSQL
instance ([data-ownership.md](../data-ownership.md)).

## Mandatory Invariants

1. **Work Management does not replace Order Processing.** Order Processing
   remains a first-class domain and its educational and contractual value is
   preserved ([ADR-006](../../adr/ADR-006-product-scope-and-bounded-contexts.md),
   "Discarding the Order Saga Domain").
2. **Both domains retain independent business rules.** `Order` is not a generic
   work order; consultations, triage and Kanban stages are not e-commerce
   concepts.
3. **Order Processing continues to own its state transitions.** No external
   domain drives `PENDING → STOCK_RESERVED → PAYMENT_PROCESSING → CONFIRMED` or
   the `CANCELLING → CANCELLED` path ([workflow.md](workflow.md)).
4. **Work Management must not modify Order, Inventory or Payments
   persistence.** No Work Management service reads or writes an Order
   Processing table, and no cross-domain foreign key exists.
5. **Existing order contracts must not be reinterpreted.** `orders.yaml`,
   `workflow.yaml` and the Order Processing schemas keep their meaning; Work
   Management contracts are added in separate files.
6. **Client sharing does not imply domain ownership.** A single client shell or
   a shared `packages/api-client` entry point does not merge the domains
   ([client-integration.md](../client-integration.md)).
7. **Any future integration requires an explicit contract and justified
   ownership.** A cross-domain feature needs a new contract and an ADR; it is
   never an implicit table join or shared entity.
8. **Shared infrastructure must not create hidden business coupling.** A shared
   broker, database instance, CI or telemetry stack must not carry business
   rules from one domain into the other.

## Permitted Dependencies

These dependencies are allowed because they carry information without
transferring ownership:

- Orders reads **current** Catalog commercial data and Inventory availability to
  render a Cart; checkout still uses authoritative preconditions
  ([order-workflow.md](../order-workflow.md)).
- Orders coordinates Inventory and Payments through the workflow events in
  [`contracts/asyncapi/workflow.yaml`](../../../contracts/asyncapi/workflow.yaml).
- Both domains depend on **shared engineering infrastructure**: pre-commit, CI,
  contract validators, telemetry conventions and the common envelope.
- Both domains may use the shared primitives in
  [`common.yaml`](../../../contracts/schemas/common.yaml) (`UUID`, `Timestamp`,
  `Money`, `Error`). Sharing a primitive is not sharing an ownership boundary.
- A Work Management `Consultation` may store an Order-related URL as an opaque
  `external_references` URI. The URI is data; Work Management does not read or
  mutate Order state.

Concrete example (allowed): a future dashboard composes an Order status widget
and a Kanban widget side by side in the UI layer, each calling its own generated
client, with no shared domain type
([client-integration.md](../client-integration.md)).

## Prohibited Dependencies

| Prohibited | Why | Concrete example |
|---|---|---|
| Cross-domain foreign keys | Violates exclusive ownership | A `WorkItem` row with an `order_id` FK |
| Cross-domain joins/queries | Reads another service's tables | `SELECT ... FROM orders JOIN work_items` |
| Reusing `Order` for work | Corrupts an e-commerce model | Modelling a bug ticket as an `Order` with `PriceQuote` |
| Importing across domain packages | Merges bounded contexts in code | `packages/domain/work-management` importing `packages/domain/orders` |
| Clients reading service source or tables | Bypasses the API boundary | The Webapp importing `services/orders` |
| Reinterpreting order events | Breaks consumer contracts | Consuming `order.confirmed` as a Work Management approval |
| Silent shared mutable state | Hidden business coupling | A shared cache keyed only by `sku` that both domains mutate |

Concrete example (prohibited): implementing "approve a proposal" by writing an
`Approval` into the Order Saga or by reusing `order.confirmed` as the Work
Management approval event.

## Shared Infrastructure Versus Business Coupling

| Shared element | Allowed use | Prohibited use |
|---|---|---|
| Kafka-compatible broker | Transport of each domain's own events | A Work Management consumer driving an Order transition |
| PostgreSQL instance | Physically shared with logical isolation | Cross-domain joins or a shared write transaction |
| CI pipeline | Lint, contracts, tests for both domains | A Work Management test asserting Order internals |
| Telemetry | Common envelope conventions | A metric label mixing domains |

## Executable Enforcement

The separation is checked automatically, not only documented:

- `tests/contracts/test_monorepo_boundaries.py` — Work Management schemas define
  no Order Processing entities and vice versa.
- `tests/contracts/test_order_processing_preservation.py` — Order Processing
  contracts do not reference Work Management, and Work Management contracts do
  not reference Order Processing files.
- `tests/contracts/test_order_processing_preservation.py` also freezes the
  Order Processing contract surface, so a Work Management change cannot silently
  alter it.

These are contract-level checks. Backend and client import boundaries become
executable once service and package code exists (Issues #33, #50–#54).
