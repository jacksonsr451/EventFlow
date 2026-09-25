# Architecture Decision Records

This directory contains the Architecture Decision Records (ADRs) for EventFlow.

An ADR records an architecturally significant decision made during the
development of the system.

The objective is to preserve not only **what** was decided, but also **why**
the decision was made and which consequences were accepted.

---

# Why EventFlow Uses ADRs

EventFlow intentionally explores distributed systems engineering.

Many architectural choices introduce trade-offs.

Examples include:

- microservices vs modular monolith;
- synchronous vs asynchronous communication;
- orchestration vs choreography;
- optimistic vs pessimistic concurrency;
- transactional outbox vs direct event publishing;
- delivery guarantees;
- event versioning;
- observability strategy.

Without ADRs, only the resulting implementation remains visible.

That is insufficient because future changes may remove an architectural
mechanism without understanding the problem it originally solved.

---

# ADR Naming Convention

ADR files follow this format:

```text
ADR-NNN-short-description.md
```

Examples:

```text
ADR-001-microservices.md
ADR-002-event-streaming.md
ADR-003-transactional-outbox.md
ADR-004-order-orchestration.md
```

Numbers are sequential and must not be reused.

---

# ADR Status

Every ADR must have one of the following statuses.

## Proposed

The decision is under discussion.

```text
Status: Proposed
```

## Accepted

The decision has been approved and represents the current architecture.

```text
Status: Accepted
```

## Deprecated

The decision is still part of the historical record but should no longer be
used for new development.

```text
Status: Deprecated
```

## Superseded

Another ADR replaced this decision.

Example:

```text
Status: Superseded by ADR-012
```

Superseded ADRs must not be deleted.

They are part of the architectural history of the project.

---

# ADR Template

New ADRs should use the following structure.

```markdown
# ADR-NNN: Decision Title

## Status

Proposed

## Date

YYYY-MM-DD

## Context

Describe the architectural problem.

Explain:

- what needs to be decided;
- why the decision is necessary;
- relevant technical constraints;
- failure modes or operational concerns;
- existing architecture that influences the decision.

Do not describe the solution yet.

## Decision

Describe the chosen solution precisely.

Explain what EventFlow will do.

Avoid vague statements.

## Alternatives Considered

### Alternative A

Describe the alternative.

Explain its advantages and disadvantages.

### Alternative B

Describe another relevant alternative.

Explain why it was not selected.

## Consequences

### Positive

- consequence;
- consequence.

### Negative

- consequence;
- consequence.

### Risks

- risk;
- risk.

## Implementation Notes

Describe constraints that implementations must respect.

Do not turn this section into implementation code.

## Validation

Describe how the project can prove that the decision works as intended.

Examples:

- automated tests;
- failure injection;
- metrics;
- integration tests;
- architecture tests.

## References

Add relevant specifications, documentation or related ADRs when applicable.
```

---

# What Requires an ADR?

An ADR should be created when a decision:

- affects multiple services;
- changes system boundaries;
- changes consistency guarantees;
- introduces infrastructure;
- establishes an architectural pattern;
- creates an important constraint;
- has significant operational consequences;
- would be expensive to reverse;
- is likely to be questioned later.

---

# What Does Not Require an ADR?

Do not create ADRs for trivial implementation decisions.

Examples:

```text
variable naming
directory naming inside one module
minor refactoring
formatting
small dependency updates
individual endpoint implementation details
```

ADRs should remain significant enough that reading them explains the evolution
of the architecture.

---

# ADR Lifecycle

The expected lifecycle is:

```text
Problem identified
        │
        ▼
ADR created
Status: Proposed
        │
        ▼
Alternatives evaluated
        │
        ▼
Decision made
        │
        ▼
Status: Accepted
        │
        ▼
Implementation
        │
        ▼
Validation
```

If the architecture changes later:

```text
Existing ADR
      │
      ▼
New decision required
      │
      ▼
Create new ADR
      │
      ▼
Old ADR:
Status: Superseded by ADR-NNN
```

Do not rewrite architectural history.

---

# ADRs vs Concept Documentation

ADRs and concept documents have different purposes.

A concept document answers:

> How does this engineering technique work?

An ADR answers:

> Why did EventFlow choose this technique?

Example:

```text
docs/concepts/transactional-outbox.md
```

explains Transactional Outbox itself.

While:

```text
docs/adr/ADR-003-transactional-outbox.md
```

explains why EventFlow adopted it.

The concept document may evolve as understanding improves.

The ADR should preserve the decision that existed at that point in the
project's history.

---

# ADRs vs Architecture Documentation

Architecture documentation describes the resulting system.

For example:

```text
docs/architecture/communication.md
```

may state that domain events are published through Redpanda.

The corresponding ADR explains why that architecture was chosen.

Therefore:

```text
Architecture documentation
        ↓
What does the system look like?

ADR
        ↓
Why does it look like that?
```

---

# Initial EventFlow ADRs

The initial architecture requires at least the following decisions:

| ADR | Decision | Initial Status |
|---|---|---|
| ADR-001 | Microservices architecture | Proposed |
| ADR-002 | Kafka-compatible event streaming | Proposed |
| ADR-003 | Transactional Outbox | Proposed |
| ADR-004 | Order workflow orchestration | Proposed |
| ADR-005 | Inventory concurrency strategy | Future |
| ADR-006 | Event versioning strategy | Future |
| ADR-007 | OpenTelemetry observability | Future |
| ADR-008 | Monorepo strategy | Future |

These ADRs should not be marked `Accepted` merely because they appear in the
project plan.

Each decision should first be understood and evaluated.

---

# Review Rule

Before changing an architectural mechanism, check whether an ADR already
governs that decision.

If one exists, determine whether the change:

1. is compatible with the existing decision;
2. requires an amendment;
3. requires a new ADR that supersedes the previous decision.

This prevents architecture from changing accidentally through isolated code
changes.
