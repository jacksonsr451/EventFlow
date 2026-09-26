# ADR-004: Order Workflow Orchestration

## Status

Accepted

## Context

An Order spans Inventory and Payments, each with authoritative state. The
workflow needs progress, timeout handling, compensation and reconciliation
without a distributed transaction.

## Decision

Orders is the Saga orchestrator. It coordinates participants with commands and
events, maintains local Saga progress and decides workflow-level outcomes.
Participants retain authority over their own state. Orchestration does not
require synchronous communication.

Orders may request payment compensation but does not choose VOID versus
REFUND. Payments decides based on financial state and provider rules.

## Consequences

### Positive

- Workflow progress and cancellation criteria are explicit.
- Compensation remains with domain authorities.
- Reconciliation can compare Orders with Inventory and Payments.

### Negative

- Orders handles duplicate and out-of-order messages.
- Cancellation can remain `CANCELLING` during operational recovery.
- Ambiguous payment outcomes require careful reconciliation.

## Alternatives Considered

- Choreography: distributes workflow rules and makes global progress harder to
  inspect.
- Distributed transaction: rejected because services own separate data and
  partial failure is a core concern.

## Notes

See [order workflow](../architecture/order-workflow.md) and [Saga and
compensation](../concepts/saga-compensation.md).
