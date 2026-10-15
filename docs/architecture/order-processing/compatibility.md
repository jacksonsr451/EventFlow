# Contract Compatibility and Error Semantics

This document assesses whether the Order Processing contracts can evolve and
coexist with the Work Management contracts without breaking existing Order
Processing clients. It does not change any accepted contract.

## Versioning Carriers

Per [ADR-007](../../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.3:

| Layer | Carrier today | Compatibility rule | Status |
|---|---|---|---|
| HTTP (Orders) | `info.version: 1.0.0`, URL prefix `/v1/` | Breaking change requires a new version prefix | CONTRACTED |
| Events (Order workflow) | envelope `schema_version` (pinned `1` per event) | Additive optional fields allowed; removal/rename/retype/new required field needs a new version | CONTRACTED |
| JSON Schema | `$schema: draft/2020-12` | Same additive rule | CONTRACTED |
| JSON Schema `$id` | **absent** | ADR-007 expects `$schema` + `$id` + `schema_version` | GAP (OPD-09) |

Adding a semantically safe optional field may stay in the same version;
consumers must tolerate unknown fields. Removing, renaming, retyping, changing
meaning or adding an incompatible required field requires a new version, and old
and new versions may coexist during migration
([contracts/README.md](../../../contracts/README.md)).

## Error Semantics

Both domains use the `application/problem+json` media type, so the divergence
below is a genuine **shape** incompatibility, not a media-type distinction.

| Domain | Error shape | Definition |
|---|---|---|
| Order Processing | RFC 9457-style problem `type`, `title`, `status`, `detail`, `instance` + `correlation_id`, `request_id`, optional `errors[]` and `code` | [`common.yaml#/$defs/Error`](../../../contracts/schemas/common.yaml), exposed as `http.yaml#/$defs/ErrorResponse` |
| Work Management | Custom `error_code`, `message`, `details`, `timestamp` | `work_management.yaml#/$defs/ErrorResponse` |

Order Processing already follows the RFC 9457 target model. Amendment
[A-01](../../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md#amendment-a-01--align-work-management-errors-with-rfc-9457)
proposes aligning **Work Management** to the Order Processing shape — not the
reverse. For Order Processing the implication is:

- **No Order Processing error contract change is required** by A-01.
- A-01 must **reuse** the Order Processing `Error` definition (or extract a
  shared schema) rather than redefine it, so Orders clients are unaffected.
- If a shared `ErrorResponse` is extracted, the Orders contract must keep the
  same observable fields and media type.

Order error responses and codes are frozen in the compatibility baseline:
`400`, `401`, `403`, `409`, `422`, `503` and the `code` enum
`VALIDATION_ERROR`, `NOT_FOUND`, `UNAUTHORIZED`, `FORBIDDEN`, `CONFLICT`,
`IDEMPOTENCY_CONFLICT`, `QUOTE_EXPIRED`, `INVALID_QUOTE`,
`DEPENDENCY_UNAVAILABLE`, `INVALID_STATE`.

## Backward-Compatibility Assessment

| Rule | Order Processing today | Verdict |
|---|---|---|
| Additive optional field | `additionalProperties: true` on payloads and aggregate views | Compatible |
| Remove required field | All required fields frozen in the baseline | Protected by regression test |
| Rename field | Baseline path/required comparison fails on rename | Protected |
| Change enum value | Enum lists frozen in the baseline | Protected |
| Add enum value | Would change the enum snapshot and require a reviewed baseline update | Requires review |
| Add a new required field | Would change the required snapshot | Requires review (treated as breaking) |
| Add a new event type | Would change the event/message snapshot | Requires review |
| Remove/rename HTTP operation | `openapi_operations` snapshot changes | Protected |
| Reuse `Error` across domains | No order change required | Compatible |

The concrete mechanism is
[`tests/contracts/order_processing_baseline.json`](../../../tests/contracts/order_processing_baseline.json);
see the [regression strategy](regression-strategy.md) for the review process.

## Incompatibility and Coverage Risks

| ID | Risk | Evidence | Impact | Smallest compatible response |
|---|---|---|---|---|
| CR-01 | Work Management error model diverges (two problem+json shapes) | ADR-007 3.4, A-01 | Clients need a per-domain error type and a mapping layer | Apply A-01 to Work Management only; keep Orders fields stable |
| CR-02 | Event schema files have no `$id` | schema files, ADR-007 3.3 | Version carrier is incomplete; tooling cannot pin a schema URI | Add `$id` additively in a reviewed change (OPD-09) |
| CR-03 | Many payloads are `additionalProperties: true` | `events.yaml` | Unknown fields are tolerated but not constrained | Documented as intentional; do not tighten without a new version |
| CR-04 | Workflow example covers only the happy path | `contracts/examples/order-workflow.json` | Rejection, decline, unknown, cancellation and compensation are unexercised | Add coherent failure-path examples in a reviewed change |
| CR-05 | No cancel/refund HTTP operation, no quote API, no availability HTTP contract | `orders.yaml` | Some architecture behaviour has no HTTP surface | Add new endpoints additively under `/v1/` when needed |
| CR-06 | Order status wire case mismatch in the unmerged branch | `origin/feat/orders-domain` `order_status.py` (`pending`) vs `common.yaml` (`PENDING`) | A naive serialization breaks the enum contract | Reconcile the implementation to the contract (OPD-07) |
| CR-07 | Notifications has no dedicated event or provider contract | `common.yaml`, `workflow.yaml` | Notification delivery is described but not contractually observable | Add contracts additively when Notifications is implemented |
| CR-08 | No Order Processing threat model | Issue #35 is Work-Management scoped | Order-specific security review is missing | Track as OPD-04; do not claim runtime security coverage |

None of these requires an incompatibly changed Order Processing contract. Each
is either an additive future change (requires review) or an implementation
follow-up.

## Required Follow-Ups

These are registered here; no new tracking issue is created by Issue #49.

- Keep the RFC 9457 target and apply A-01 to Work Management, owned by
  [#11](https://github.com/jacksonsr451/EventFlow/issues/11) with
  [#49](https://github.com/jacksonsr451/EventFlow/issues/49).
- Add `$id` to event schema files as an additive, reviewed change (OPD-09).
- Add failure-path workflow examples in a reviewed change (CR-04).
- Reconcile the `feat/orders-domain` enum and tooling when it is incorporated
  ([execution plan](execution-plan.md)).
