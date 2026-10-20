# Architecture Decision Records

This directory is the index and convention guide for EventFlow's Architecture
Decision Records. An ADR preserves the context, decision, alternatives and
consequences of an architectural choice. Accepted means architecturally
approved; it does not mean the choice has already been implemented.

## ADR Index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-microservices.md) | Microservices Architecture | Accepted |
| [ADR-002](ADR-002-event-streaming.md) | Kafka-Compatible Event Streaming | Accepted |
| [ADR-003](ADR-003-transactional-outbox.md) | Transactional Outbox | Accepted |
| [ADR-004](ADR-004-order-orchestration.md) | Order Workflow Orchestration | Accepted |
| [ADR-005](ADR-005-polyglot-service-architecture.md) | Polyglot Service Architecture | Accepted |
| [ADR-006](ADR-006-product-scope-and-bounded-contexts.md) | Product Scope, Bounded Contexts, and Monorepo Architecture | Accepted |
| [ADR-007](ADR-007-multi-client-monorepo-layout-and-contracts.md) | Multi-Client Monorepo Layout and Shared Contracts | Accepted |
| [ADR-008](ADR-008-work-management-persistence.md) | Work Management Persistence Stack and Database Schema | Accepted |
| [ADR-009](ADR-009-oidc-authentication-and-secure-sessions.md) | OIDC Authentication and Secure Sessions | Accepted |
| [ADR-010](ADR-010-project-triage-configuration.md) | Project Triage Configuration and Versioned Templates | Accepted |

Future candidates such as detailed Inventory concurrency, event versioning,
OpenTelemetry instrumentation and detailed client adapters are not additional ADRs in
this set and must not be presented as accepted decisions.

## Statuses

- **Proposed**: under discussion; not yet the current architecture.
- **Accepted**: approved and represents the current architectural direction.
- **Deprecated**: retained for history but should not guide new work.
- **Superseded**: replaced by another ADR; retain it as architectural history.

## Format

New ADRs use:

```markdown
# ADR-XXX: Title

## Status

Proposed | Accepted | Deprecated | Superseded

## Context

## Decision

## Consequences

### Positive

### Negative

## Alternatives Considered

## Notes
```

Numbers are sequential and must not be reused. An ADR is appropriate for a
decision that affects multiple services, consistency guarantees, system
boundaries, infrastructure, reliability or significant operational behavior.

ADRs explain why a choice was made. [Architecture documentation](../architecture/overview.md)
describes what the system looks like, while [concept documentation](../concepts/event-driven-architecture.md)
explains how a mechanism works.
