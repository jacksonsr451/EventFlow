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
- [Work management workflow](architecture/work-management-workflow.md): Consultation, triage, proposal, approval, WorkItem and BoardCard.
- [Client integration](architecture/client-integration.md): how Web, Desktop and VS Code consume the API and share contracts.

## Security

Security documents describe the threat model, policies and data governance rules
that future implementations must satisfy.

- [Security index](security/README.md): overview, identifier conventions and trust boundaries.
- [Threat model](security/threat-model.md): STRIDE scenario catalog for the Work Management domain and clients.
- [Risk register](security/risk-register.md): residual risks, owners and verification.
- [Tenant isolation](security/tenant-isolation.md): workspace isolation invariants.
- [OAuth and credentials](security/oauth-and-credentials.md): authentication, token storage and revocation.
- [Webhooks](security/webhooks.md): signature verification, replay protection and tenant routing.
- [Untrusted content](security/untrusted-content.md): source code, integration text and attachment handling.
- [Data governance](security/data-governance.md): classification, retention, deletion and data subject rights.
- [Security observability](security/security-observability.md): security event taxonomy and redaction.
- [Traceability matrix](security/traceability.md): threats, risks, controls and verification.
- [Open decisions](security/open-decisions.md): security decisions awaiting an owner.

## Architecture Decision Records

ADRs explain why important architectural choices were made, including
alternatives and consequences.

- [ADR index and conventions](adr/README.md)
- [ADR-001: Microservices Architecture](adr/ADR-001-microservices.md)
- [ADR-002: Kafka-Compatible Event Streaming](adr/ADR-002-event-streaming.md)
- [ADR-003: Transactional Outbox](adr/ADR-003-transactional-outbox.md)
- [ADR-004: Order Workflow Orchestration](adr/ADR-004-order-orchestration.md)
- [ADR-005: Polyglot Service Architecture](adr/ADR-005-polyglot-service-architecture.md)
- [ADR-006: Product Scope, Bounded Contexts, and Monorepo Architecture](adr/ADR-006-product-scope-and-bounded-contexts.md)
- [ADR-007: Multi-Client Monorepo Layout and Shared Contracts](adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)

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
- [Monorepo layout](development/monorepo-layout.md): directories, contracts and bounded-context rules.
- [Testing strategy](development/testing-strategy.md): implemented contract coverage plus planned invariant and resilience coverage.
- [CI/CD strategy](development/ci-cd.md): active validation and future delivery stages.

## Documentation Boundaries

- `docs/architecture/` answers: “How is EventFlow structured?”
- `docs/adr/` answers: “Why was this architectural choice made?”
- `docs/concepts/` answers: “How does this mechanism work?”
- `docs/development/` answers: “How should contributors work and validate it?”
- `docs/security/` answers: “What must be protected, and how?”
- `contracts/` contains machine-readable interfaces; contract validation tests
  exist under `tests/contracts/` and `tests/security/`, but service
  implementations are not present yet.

Avoid documenting planned features as implemented. Update the relevant section
when an architectural decision or public contract changes.
