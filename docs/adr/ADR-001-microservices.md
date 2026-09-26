# ADR-001: Microservices Architecture

## Status

Accepted

## Context

EventFlow deliberately studies distributed-systems problems. A modular
monolith would be simpler for this domain, but would hide service ownership,
network failure and partial-failure boundaries.

## Decision

Use independently deployable boundaries for Gateway, Orders, Inventory,
Payments and Notifications. Keep Catalog as a domain boundary without
requiring a separate operational service yet. Each service owns its data and
communicates through contracts, events or justified projections.

This is an accepted architectural choice, not a claim that microservices are
universally superior or already implemented.

## Consequences

### Positive

- Failure and consistency boundaries are explicit.
- Distributed workflow patterns are visible and testable.

### Negative

- Network, deployment and operational complexity increase.
- Eventual consistency and duplicated resilience logic are unavoidable.
- A modular monolith would be cheaper for a system of this size.

## Alternatives Considered

- Modular monolith: simpler local transactions, but less direct exposure to
  the problems this project is intended to study.
- A separate service for every domain, including Catalog: deferred because
  Catalog operational isolation is not decided.

## Notes

See [services](../architecture/services.md) and [overview](../architecture/overview.md).
