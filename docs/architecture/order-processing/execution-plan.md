# Order Processing Execution Plan

This plan sequences the work needed to move Order Processing from
**contract-specified** to **implemented**, without merging domains and without
an incompatible contract change. It is dependency-aware: each milestone lists
what it needs and what it unlocks.

The plan references existing issues only. Issue #49 does not create issues.

## Principles

- Preserve the Order Saga domain; never replace it with Work Management.
- One bounded context per deliverable; no cross-domain coupling.
- Contracts are the source of truth; implementation must match the contract.
- Prefer additive, compatible contract changes behind explicit review.
- Tests use `jsr-testrunner` only; no `pytest`, plugins or fixtures.
- No milestone may remove a contract or event from the frozen baseline without an
  ADR and a compatibility review.

## Assessment of `origin/feat/orders-domain`

The unmerged branch is a useful **reference**, not a merge candidate.

| Finding | Evidence | Consequence |
|---|---|---|
| Based on a baseline that predates architecture work #1, #2 and #35 | branch diff deletes contracts, docs and Work Management material | Merging would regress the repository |
| Pure domain, no HTTP/AsyncAPI wiring | `services/orders/` sources | Reuse the domain logic only, behind new interfaces |
| `money.py` complete; `order_item.py` near-complete with a minor type-annotation bug | branch sources | Reuse after review and typing fix |
| `order_status.py` values are lowercase (`pending`) | branch source | **Contract violation**; must be `PENDING` etc. (OPD-07) |
| `order.py` partial (~57 lines): `create`, `accept_reservation`, `reject_reservation`, `start_payment`; missing `approve_payment`, `confirm`, `begin_cancellation`, `mark_inventory_released`, `mark_payment_compensated`, `complete_cancellation`, unknown/decline paths | branch source | The full state machine still has to be built |
| 13 test files use `conftest.py` and declare `pytest`/`pytest-cov` | branch `pyproject.toml`, `conftest.py` | **Policy violation**; tests must be ported to `jsr-testrunner` (OPD-08) |

Recommended approach: extract the pure domain as a starting point in
[#50](https://github.com/jacksonsr451/EventFlow/issues/50), reconcile enums to
the contract, port the tests, and discard the branch's deletions.

## Milestones

### M0 — Preservation (this issue: #49)

- Objective: freeze and document Order Processing before any implementation.
- Deliverables: this documentation set, the compatibility baseline and the
  regression suite.
- Prerequisites: none.
- Acceptance: `validate_contracts.py`, `jsr-testrunner tests`, pre-commit and
  `git diff --check` pass; no contract changed; boundaries enforced by tests.
- Unlocks: safe implementation work in M1–M4.

### M1 — Orders domain and Gateway vertical (#50)

- Objective: implement the Orders bounded context and the order HTTP surface.
- Scope: pure domain state machine; transactional Outbox; `POST /v1/orders`,
  `GET /v1/orders/{order_id}`, `GET /v1/carts/{cart_id}`; `Idempotency-Key`
  handling; issue `inventory.reservation.requested` and `payment.requested`;
  consume `inventory.*`, `payment.*`; `order.confirmed`, `order.cancelled`.
- Prerequisites: M0.
- Acceptance: order reaches `CONFIRMED` and `CANCELLED` in tests; duplicate
  delivery and duplicate idempotency key behave per [RS-02, RS-10](reliability.md);
  domain enums uppercase.
- Evidence: domain unit tests, HTTP contract tests, saga integration tests
  (`jsr-testrunner`).
- Risk: state-machine gaps (assessing `feat/orders-domain`, above).
- Unlocks: M2, M3, M4 integration and M5.

### M2 — Inventory reservation service (#51)

- Objective: own stock and reservations.
- Scope: consume `inventory.reservation.requested` and
  `inventory.release.requested`; emit `inventory.reserved`,
  `inventory.rejected`, `inventory.released`; atomic all-or-nothing reservation;
  atomic `ACTIVE → EXPIRED`/`RELEASED`/`CONSUMED`; idempotency by
  `reservation_id`.
- Prerequisites: M1 (event channel), decision OPD-03.
- Acceptance: [RS-03, RS-04](reliability.md) pass; concurrency test proves no
  oversell.
- Risk: database-level concurrency; must not rely on Kafka for stock guarantees.
- Unlocks: reliable confirmation path.

### M3 — Payments service (#52)

- Objective: own payment state and compensation.
- Scope: consume `payment.requested` and `payment.compensation.requested`; emit
  `payment.approved`, `payment.declined`, `payment.processing`,
  `payment.unknown`, `payment.compensated`; provider integration; VOID vs
  REFUND; idempotency by `payment_id`.
- Prerequisites: M1; decision OPD-05 (provider and idempotency support).
- Acceptance: [RS-05, RS-06, RS-07](reliability.md) pass; timeout never causes a
  duplicate charge.
- Risk: provider semantics; ambiguity handling.
- Unlocks: reliable confirmation and terminal cancellation.

### M4 — Notifications consumer (#53)

- Objective: deliver notifications without affecting Order state.
- Scope: consume `order.confirmed` and `order.cancelled`; `NotificationOperation`
  lifecycle; dedup by `event_id`/`source_event_id`; retry and DLQ.
- Prerequisites: M1.
- Acceptance: duplicate event produces one notification; permanent failure goes
  to DLQ.
- Risk: at-least-once external delivery is intended; exactly-once is not claimed.
- Unlocks: user-visible workflow feedback.

### M5 — Saga observability and reconciliation (#54)

- Objective: make the workflow diagnosable and self-repairing.
- Scope: correlation/causation propagation; metrics for Saga progress,
  inventory/payment outcome, recovery, backlog, DLQ, terminal-state age;
  reconciliation job that repairs deterministic projection divergence.
- Prerequisites: M1–M3.
- Acceptance: [RS-08, RS-09, RS-11](reliability.md) pass; ambiguous payments and
  `CANCELLING` age are observable.
- Risk: reconciliation must not "fix" contradictory evidence; it records it.
- Unlocks: operational readiness for the order path.

### M6 — Cross-cutting readiness

- [#46](https://github.com/jacksonsr451/EventFlow/issues/46) async events and
  Outbox patterns; [#47](https://github.com/jacksonsr451/EventFlow/issues/47)
  tenant isolation; [#34](https://github.com/jacksonsr451/EventFlow/issues/34)
  local infrastructure; [#33](https://github.com/jacksonsr451/EventFlow/issues/33)
  CI; [#32](https://github.com/jacksonsr451/EventFlow/issues/32) end-to-end.
- Prerequisites: M1–M5 for meaningful coverage.
- Acceptance: end-to-end happy path and at least one compensation path run in CI
  against local infrastructure.

## Dependency Graph

```
M0 #49 ─┬─> M1 #50 ─┬─> M2 #51 ─┐
        │           ├─> M3 #52 ─┼─> M5 #54 ─> M6
        │           └─> M4 #53 ─┘
        └─ (contracts frozen) ──────────────> #46, #47
```

## Contract Changes Required

All changes below are additive and require review; none is performed by #49.

| Change | Milestone | Compatible? |
|---|---|---|
| Add `$id` to event schema files (OPD-09, CR-02) | before/with M1 | Yes (additive) |
| Add cancel/refund endpoints under `/v1/` when needed (CR-05) | M1/M3 | Yes |
| Add failure-path workflow examples (CR-04) | M1 | Yes (examples only) |
| Add notification provider contract (CR-07) | M4 | Yes (new file) |
| Decide the `ACTIVE → CONSUMED` event (OPD-03) | M2 | Yes (new event) |
| Applied A-01 (RFC 9457) to Work Management only (CR-01) | #11 (done) | Yes for Orders |

## Migration and Compatibility Risks

| Risk | Mitigation |
|---|---|
| Merging `feat/orders-domain` wholesale regresses `main` | Extract domain only; do not merge the branch |
| Lowercase status leaks to the wire | Reconcile enums; regression test freezes the contract enum |
| A new required field breaks clients | Additive optional only; baseline review gate |
| Two problem+json shapes confuse clients | Resolved: A-01 applied to Work Management; Orders fields unchanged |
| Stocks/payments logic drifts into Orders | Boundary tests + ownership rules in [domain-separation.md](domain-separation.md) |

## CI/CD Requirements

- Keep the existing `contracts` CI job (OpenAPI, AsyncAPI, JSON Schema, refs,
  example, boundary and preservation tests).
- Add domain/service jobs per milestone using `jsr-testrunner`.
- No milestone may weaken the frozen baseline; any intentional baseline change is
  a reviewed diff with a documented reason.
- Declare the Python 3.12 CI target; local development may run 3.11.
