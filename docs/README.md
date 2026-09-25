# EventFlow Documentation

This directory contains the technical documentation for EventFlow.

The documentation is part of the project architecture and must evolve together
with the source code.

Its purpose is not only to describe the final implementation, but also to
record the reasoning, architectural decisions, system constraints and
engineering concepts used throughout the project.

---

## Documentation Structure

```text
docs/
├── README.md
│
├── architecture/
│   ├── overview.md
│   ├── services.md
│   ├── communication.md
│   ├── data-ownership.md
│   └── order-workflow.md
│
├── adr/
│   ├── README.md
│   ├── ADR-001-microservices.md
│   ├── ADR-002-event-streaming.md
│   ├── ADR-003-transactional-outbox.md
│   └── ADR-004-order-orchestration.md
│
├── concepts/
│   ├── event-driven-architecture.md
│   ├── idempotency.md
│   ├── at-least-once-delivery.md
│   ├── transactional-outbox.md
│   ├── saga-compensation.md
│   └── distributed-tracing.md
│
└── development/
    ├── getting-started.md
    ├── conventions.md
    └── testing-strategy.md
```

Not every document needs to exist from the beginning.

Documentation should be introduced as the corresponding architecture,
decision or implementation becomes relevant.

---

# Architecture

The `architecture/` directory describes how EventFlow is structured as a
system.

These documents answer questions such as:

- What are the system boundaries?
- Which services exist?
- What responsibility belongs to each service?
- Which service owns each piece of data?
- How do services communicate?
- How does an order move through the distributed workflow?
- Where are consistency boundaries?
- How are failures handled?

Architecture documentation describes the system itself.

It should not be used to teach general software engineering concepts.

Example:

```text
architecture/order-workflow.md
```

should explain how an order moves through EventFlow.

It should not attempt to be a generic tutorial about event-driven systems.

---

# Architecture Decision Records

The `adr/` directory contains Architecture Decision Records.

An ADR records an important architectural decision together with:

- the context that required the decision;
- the alternatives or constraints considered;
- the decision that was made;
- the consequences of that decision.

Example:

```text
ADR-003-transactional-outbox.md
```

answers:

> Why does EventFlow use the Transactional Outbox Pattern?

It does not need to explain the pattern from first principles.

Detailed ADR conventions are documented in:

```text
docs/adr/README.md
```

---

# Concepts

The `concepts/` directory contains engineering concepts that are important for
understanding EventFlow.

These documents are intentionally educational.

They should answer questions such as:

- What problem does this concept solve?
- Why does the problem exist?
- How does the solution work?
- What guarantees does it provide?
- What guarantees does it not provide?
- What trade-offs does it introduce?
- How is the concept applied inside EventFlow?

Examples:

```text
concepts/idempotency.md
concepts/transactional-outbox.md
concepts/at-least-once-delivery.md
```

A concept document should be written only after the concept is understood well
enough to explain it clearly.

The goal is not to accumulate definitions.

The goal is to document engineering understanding.

---

# Development

The `development/` directory contains information required to build, test and
work on EventFlow.

Examples include:

- local development setup;
- coding conventions;
- testing strategy;
- repository conventions;
- commands;
- development workflow.

These documents should describe reproducible procedures whenever possible.

---

# Documentation vs Contracts

Technical documentation and system contracts have different responsibilities.

Documentation lives under:

```text
docs/
```

Machine-readable contracts live under:

```text
contracts/
```

Examples:

```text
contracts/openapi/
contracts/asyncapi/
contracts/schemas/
```

The distinction is important.

Documentation explains the architecture and reasoning.

Contracts define interfaces that implementations must satisfy.

For example:

```text
docs/architecture/order-workflow.md
```

explains how order processing works.

While:

```text
contracts/schemas/orders/order-created-v1.json
```

defines the exact structure of the `order.created` event.

---

# Documentation Principles

## Documentation is versioned

Documentation must be committed to Git together with the code it describes.

Architecture changes that make existing documentation incorrect must update
that documentation in the same change whenever practical.

---

## Document decisions, not only results

The final architecture alone is insufficient.

Important engineering decisions should record why they were made.

This prevents future contributors from accidentally reversing a decision
without understanding the original constraints.

---

## Avoid speculative documentation

Do not document features as implemented when they do not exist.

When describing planned behavior, make its status explicit.

Prefer:

```text
Status: Proposed
```

over documentation that makes future functionality appear complete.

---

## Prefer precise statements

Avoid statements such as:

```text
The system is highly scalable.
```

Prefer statements that can be reasoned about or verified:

```text
Orders Service instances are stateless with respect to HTTP sessions and can
be horizontally replicated.
```

---

## Keep diagrams close to the explanation

Diagrams should explain a specific architectural concept or workflow.

A diagram without corresponding explanation quickly becomes ambiguous.

Text-based diagrams such as Mermaid may be used when they remain readable in
the repository.

---

## Documentation must match reality

When implementation and documentation disagree, the inconsistency is a defect.

It should not be assumed automatically that either the documentation or the
implementation is correct.

The intended contract and architectural decision must be checked.

---

# Initial Documentation Roadmap

The initial documentation should be developed in this order:

```text
architecture/overview.md
        ↓
architecture/services.md
        ↓
architecture/data-ownership.md
        ↓
architecture/communication.md
        ↓
architecture/order-workflow.md
        ↓
ADR-001
        ↓
ADR-002
        ↓
ADR-003
        ↓
ADR-004
```

Concept documents should be written as the corresponding subjects are studied.

For example:

```text
Study Transactional Outbox
        ↓
Understand the failure it solves
        ↓
Write concepts/transactional-outbox.md
        ↓
Decide how EventFlow will use it
        ↓
Write ADR-003
        ↓
Implement it
```

This keeps implementation tied to explicit engineering reasoning.

---

# Current Documentation Status

Current project phase:

```text
Phase 0 — Architecture and Contracts
```

During this phase the priority is:

1. understand the system;
2. define architectural boundaries;
3. document important decisions;
4. define API and event contracts;
5. define expected behavior;
6. only then begin service implementation.

The objective is to make the architecture explicit before framework-specific
code begins to shape it accidentally.