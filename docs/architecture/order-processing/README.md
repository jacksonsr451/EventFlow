# Order Processing Preservation

This directory is the contract inventory, separation audit and execution plan
for the **Distributed Order Processing (Order Saga)** bounded context. It exists
so that Order Processing remains independently evolvable while the Work
Management bounded context develops as a separate product domain.

Issue: [#49 — Preserve Order Processing contracts and define execution plan](https://github.com/jacksonsr451/EventFlow/issues/49).

Status: **Specified (Phase 0).** This directory documents and protects existing
contracts. It does not implement a service, does not change an accepted contract
incompatibly and does not replace any authoritative document.

## Scope

In scope:

- Inventory of the existing Orders, Inventory, Payments and Notifications
  contracts, with an evidence-based implementation status.
- Bounded-context separation between Order Processing and Work Management.
- Contract compatibility and error-semantics assessment.
- Workflow state and transition mapping.
- Reliability, idempotency and failure scenarios.
- A dependency-aware execution roadmap, including an assessment of the
  unmerged `feat/orders-domain` branch.
- Automated regression checks that protect the contracts above.

Out of scope (deferred, not decided here): implementing Orders, Inventory,
Payments or Notifications; new messaging infrastructure; new clients; any
incompatible contract change; any cross-domain integration.

## Authoritative Documents

This directory is a derived view. Where it disagrees with an authoritative
document, the authoritative document wins:

- [Overview](../overview.md) — system context.
- [Services](../services.md) — service responsibilities and ownership.
- [Data ownership](../data-ownership.md) — exclusive persistence ownership.
- [Communication](../communication.md) — envelope and versioning.
- [Order workflow](../order-workflow.md) — Cart, quote, Saga, compensation,
  reconciliation.
- [ADR-001](../../adr/ADR-001-microservices.md) through
  [ADR-005](../../adr/ADR-005-polyglot-service-architecture.md) — Order Saga
  architecture.
- [ADR-006](../../adr/ADR-006-product-scope-and-bounded-contexts.md) and
  [ADR-007](../../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) —
  bounded contexts, monorepo layout and shared contracts.
- [Contracts](../../../contracts/README.md) — the machine-readable baseline.

## Document Index

- [Contract inventory](contract-inventory.md) — every Orders, Inventory,
  Payments and Notifications contract with status and evidence.
- [Domain separation](domain-separation.md) — ownership, permitted and
  prohibited dependencies, executable boundary rules.
- [Compatibility](compatibility.md) — versioning, error semantics and
  incompatibility risks.
- [Workflow and transitions](workflow.md) — trigger, precondition, emitted
  event, side effects, retry, compensation and idempotency per transition.
- [Reliability and failure scenarios](reliability.md) — documented guarantees,
  implemented behaviour and verifiable scenarios.
- [Execution plan](execution-plan.md) — milestones, dependencies and the
  `feat/orders-domain` assessment.
- [Regression strategy](regression-strategy.md) — the compatibility baseline
  and its review process.

## Status Legend

| Status | Meaning |
|---|---|
| IMPLEMENTED | Code exists and is verifiable in the repository today |
| PARTIALLY IMPLEMENTED | Some code exists, but the capability is incomplete or not wired |
| CONTRACTED | A machine-readable contract exists; no implementation |
| PLANNED | Described in architecture; no contract and no implementation |
| MISSING | Required by the architecture but no contract and no implementation |
| DEPRECATED | Superseded; retained only for migration |

No Order Processing capability is **IMPLEMENTED** on `main` today. The
`feat/orders-domain` branch holds a **PARTIALLY IMPLEMENTED** pure domain that is
not merged; see the [execution plan](execution-plan.md).

## Open Decisions and Blockers

These are recorded here as evidence, not resolved. Creating or assigning tracking
issues is out of scope for Issue #49.

| ID | Decision or blocker | Owner / where tracked |
|---|---|---|
| OPD-01 | Catalog operational isolation (shared host vs standalone service) is undecided | [services.md](../services.md) |
| OPD-02 | Quote issuance and validation contract is intentionally deferred to contract design | [order-workflow.md](../order-workflow.md) |
| OPD-03 | Exact `ACTIVE → CONSUMED` reservation transition point is deferred | [order-workflow.md](../order-workflow.md) |
| OPD-04 | No Order Processing threat model; the Issue #35 security specification is Work-Management scoped | [security/README.md](../../security/README.md) |
| OPD-05 | Payment provider selection and its idempotency support are undecided | [services.md](../services.md) |
| OPD-06 | Retry counts, timeouts, backlog thresholds and DLQ policy values are not specified | [testing-strategy.md](../../development/testing-strategy.md) |
| OPD-07 | `feat/orders-domain` serializes order status as lowercase (`pending`); the contract enum is uppercase (`PENDING`) | [execution-plan.md](execution-plan.md) |
| OPD-08 | `feat/orders-domain` declares `pytest`/`pytest-cov` and a `conftest.py`; the repository requires `jsr-testrunner` only | [execution-plan.md](execution-plan.md) |
| OPD-09 | Event schema files define `$schema` but no `$id`, while ADR-007 versioning expects an `$id` | [compatibility.md](compatibility.md) |
| OPD-10 | Work Management and Order Processing used two `problem+json` shapes; resolved by A-01 in [#11](https://github.com/jacksonsr451/EventFlow/issues/11) | [ADR-007](../../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) |
