# ADR-002: Kafka-Compatible Event Streaming

## Status

Accepted

## Context

Order workflows need asynchronous communication, replayable handling and
at-least-once delivery. The repository has no broker implementation yet.

## Decision

Use a Kafka-compatible event broker for workflow commands and events when
implemented. Use `order_id` as partition key for Order workflow messages where
applicable. Consumers tolerate duplicates; broker ordering is not a domain
integrity mechanism.

This is an accepted architectural decision; broker implementation remains
pending in the repository.

## Consequences

### Positive

- Asynchronous boundaries and consumer recovery can be studied explicitly.
- Related Order messages can preserve partition-local ordering.

### Negative

- Delivery remains at least once and needs Inbox/business idempotency.
- Broker lag and DLQ require operational tooling.
- Same-SKU contention can cross partitions and remains an Inventory concern.

## Alternatives Considered

- Direct synchronous calls everywhere: simpler initially, but stronger temporal
  coupling and less visibility into asynchronous failures.
- An in-process queue: insufficient for independent service recovery.

## Notes

This ADR does not assert that Kafka/Redpanda is provisioned today. See
[communication](../architecture/communication.md).
