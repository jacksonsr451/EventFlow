# ADR-003: Transactional Outbox

## Status

Accepted

## Context

Updating domain state and publishing an external event are separate systems.
A crash between them creates a dual-write inconsistency. A distributed
database transaction is not part of EventFlow's design.

## Decision

When a domain change emits an external event, one local transaction modifies
domain state, updates local workflow progress when needed, and inserts an
Outbox row before commit. A later publisher sends pending rows. The broker is
outside the database transaction.

If a publisher crashes after publishing and before marking `published_at`, the
event may be published again. The guarantee is at-least-once, not exactly-once
end to end.

## Consequences

### Positive

- The database/broker dual-write window is controlled by one local commit.
- Pending work can be retried and monitored.

### Negative

- Duplicates are expected and require idempotent consumers.
- Backlog and publisher recovery add operational concerns.

## Alternatives Considered

- Publish directly after commit: can lose events or create state/event gaps.
- Distributed transaction with the broker: adds coupling and conflicts with
  the local-transaction model.

## Notes

See [Transactional Outbox](../concepts/transactional-outbox.md).
