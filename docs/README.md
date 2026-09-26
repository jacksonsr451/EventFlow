# EventFlow Documentation

This is the central index for EventFlow documentation. The repository is in
Phase 0: the documents describe accepted architecture and planned behavior;
they do not imply that services are implemented. The first machine-readable
contract baseline exists under `contracts/`.

## Architecture

Architecture documents describe how EventFlow is structured and how its
domains interact.

- [Overview](architecture/overview.md): purpose, boundaries and reliability model.
- [Services](architecture/services.md): service responsibilities and domain authorities.
- [Communication](architecture/communication.md): HTTP, commands, events, envelope and versioning.
- [Data ownership](architecture/data-ownership.md): exclusive persistence ownership and access rules.
- [Order workflow](architecture/order-workflow.md): Cart, PriceQuote, Order, Reservation, Saga and reconciliation.

## Architecture Decision Records

ADRs explain why important architectural choices were made, including
alternatives and consequences.

- [ADR index and conventions](adr/README.md)
- [ADR-001: Microservices Architecture](adr/ADR-001-microservices.md)
- [ADR-002: Kafka-Compatible Event Streaming](adr/ADR-002-event-streaming.md)
- [ADR-003: Transactional Outbox](adr/ADR-003-transactional-outbox.md)
- [ADR-004: Order Workflow Orchestration](adr/ADR-004-order-orchestration.md)
- [ADR-005: Polyglot Service Architecture](adr/ADR-005-polyglot-service-architecture.md)

## Concepts

Concept documents explain how distributed-systems mechanisms work and what
they do and do not guarantee.

- [Event-driven architecture](concepts/event-driven-architecture.md)
- [Idempotency](concepts/idempotency.md)
- [At-least-once delivery](concepts/at-least-once-delivery.md)
- [Transactional Outbox](concepts/transactional-outbox.md)
- [Saga and compensation](concepts/saga-compensation.md)
- [Distributed tracing](concepts/distributed-tracing.md)

## Development

Development documents describe how contributors will work with the repository
and how future implementations should be validated.

- [Getting started](development/getting-started.md): current repository status and future workflow.
- [Conventions](development/conventions.md): terminology and architectural constraints.
- [Testing strategy](development/testing-strategy.md): planned invariant, contract and resilience coverage.

## Documentation Boundaries

- `docs/architecture/` answers: “How is EventFlow structured?”
- `docs/adr/` answers: “Why was this architectural choice made?”
- `docs/concepts/` answers: “How does this mechanism work?”
- `docs/development/` answers: “How should contributors work and validate it?”
- `contracts/` contains machine-readable interfaces; service implementations
  and contract-driven tests are not present yet.

Avoid documenting planned features as implemented. Update the relevant section
when an architectural decision or public contract changes.
