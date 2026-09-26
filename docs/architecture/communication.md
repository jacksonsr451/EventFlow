# Communication and Event Contracts

## Synchronous and Asynchronous Paths

HTTP is reserved for an immediate answer, such as Gateway ingress or an
initial Cart read. Order processing is coordinated asynchronously. Orders is a
Saga orchestrator, but orchestration does not require synchronous calls between
all participants.

When implemented, a Kafka-compatible broker carries workflow commands and
events. Order workflow messages use `order_id` as partition key when
applicable, preserving related ordering. This does not protect Stock: orders
for the same SKU can land in different partitions, so Inventory/PostgreSQL
must enforce the stock invariant.

## Event Envelope

All events use this envelope; reusable schemas are under `contracts/schemas/`.
The files are a first contract baseline and do not imply that consumers or
producers are implemented.

```json
{
  "event_id": "...",
  "event_type": "...",
  "schema_version": 1,
  "occurred_at": "...",
  "producer": "...",
  "correlation_id": "...",
  "causation_id": "...",
  "aggregate_type": "...",
  "aggregate_id": "...",
  "payload": {}
}
```

`event_id` identifies the message; `correlation_id` identifies the long-lived
business workflow; `causation_id` identifies the direct cause. Do not add
sensitive identifiers merely for tracing.

The envelope and contracts are independent of Python classes, Java records or
Go structs. OpenAPI, AsyncAPI and JSON Schema describe interoperability; no
language-specific serialization is part of the architecture. Notifications
consumes the same envelope as the other services and must preserve the
correlation and tracing context across the asynchronous boundary.

For Go, `context.Context` is a local runtime mechanism for cancellation,
deadlines and operation-scoped values. It is not serialized as domain data and
does not cross the broker process boundary. Cross-runtime trace propagation is
carried by future transport metadata, while `correlation_id` and
`causation_id` remain application-level envelope fields.

Backward-compatible optional fields may remain in the same schema version.
Removing, renaming, retyping or semantically changing fields requires a new
version. During migration, versions may coexist and adapters may translate
external versions into an internal model.

Publishers and consumers assume at-least-once delivery. Retry transient
technical failures with bounded exponential backoff and jitter. Invalid
messages go directly to DLQ or equivalent handling. Business outcomes such as
insufficient stock or payment decline are not technical retry failures.

See [event-driven architecture](../concepts/event-driven-architecture.md) and
[at-least-once delivery](../concepts/at-least-once-delivery.md).
