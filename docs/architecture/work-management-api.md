# Work Management Public API: Versioning, DTOs, Errors and Compatibility

## Status

Accepted. Subordinate to [ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md)
and [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md), and
governing the public HTTP contract implemented for
[Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11).

This document describes the versioned public HTTP contract for Work Management
(Consultations, Triage, Proposals, Approvals, WorkItems and Boards). The
machine-readable source of truth is
[`contracts/openapi/work-management.yaml`](../../contracts/openapi/work-management.yaml)
and its reusable definitions in
[`contracts/schemas/work_management.yaml`](../../contracts/schemas/work_management.yaml).

## 1. What "versioned" means here

EventFlow uses several independent version carriers. They must not be confused:

| Layer | Carrier | Rule |
|---|---|---|
| Public HTTP API | `/v1/` URL prefix and OpenAPI `info.version` | Breaking changes require a new prefix (`/v2/`). |
| JSON Schema | `$id` and the schema document | Additive optional fields are compatible; removals or new required fields need a new `$id`. |
| Internal events | `schema_version` in the event envelope | Consumers must tolerate unknown fields within a version. Not part of this API. |
| Implementation release | Service version | Independent of the API version. |

The public Work Management API version is `v1` and is carried in the URL
prefix. Every operation lives under `/v1/workspaces/{workspace_id}/...`. The
`/api/v1/` form is **not** used: the repository convention established by the
Orders contract and [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.3 is a bare `/v1/` prefix.

## 2. Compatibility policy

The public contract evolves under these rules:

- **Compatible (same `v1`):** adding an optional request field, adding a
  response field, adding a new endpoint, adding a new enum value to a filter
  parameter, or relaxing a constraint. Clients must ignore unknown response
  fields.
- **Breaking (requires `v2`):** removing or renaming a field or endpoint,
  adding a required request field, tightening a constraint, changing a media
  type, or changing the meaning of an existing field.
- **Error contract:** the problem shape (section 4) is part of the public
  contract. Adding an optional member is compatible; removing or renaming a
  member is breaking.
- The Orders API (`contracts/openapi/orders.yaml`) and its shared schemas are
  **not** modified by Work Management changes; the two bounded contexts remain
  isolated (see [domain separation](order-processing/domain-separation.md)).

## 3. DTOs

Request and response payloads are declared as named JSON Schema definitions and
referenced from the OpenAPI operations, rather than being inlined. This gives a
single source of truth for TypeScript generation
([ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.1) and for contract tests.

| DTO | Used by |
|---|---|
| `CreateConsultationRequest` | `POST /v1/workspaces/{workspace_id}/consultations` |
| `TriageConsultationRequest` | `POST .../consultations/{consultation_id}/triage` |
| `CreateProposalRequest` | `POST /v1/workspaces/{workspace_id}/proposals` |
| `DecideProposalRequest` | `POST .../proposals/{proposal_id}/decide` |
| `DecideProposalResponse` | `POST .../proposals/{proposal_id}/decide` (200) |
| `MoveBoardCardRequest` | `PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards` |
| `ConsultationPage`, `WorkItemPage`, `BoardCardPage` | list responses |

Entity DTOs (`Consultation`, `Proposal`, `Approval`, `WorkItem`, `BoardCard`)
remain the canonical shapes shared by all three clients.

## 4. Errors: RFC 9457 problem details

Every error response uses the media type `application/problem+json` and the
single Work Management `ErrorResponse` definition, which is an RFC 9457 problem
document:

- `type`, `title`, `status`, `detail`, `instance` (RFC 9457 members),
- `code` — a stable machine-readable code for client branching,
- `correlation_id`, `request_id` — request tracing,
- `errors[]` — optional field-level validation details.

This applies [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
Amendment A-01: the previous custom shape (`error_code`, `message`, `details`,
`timestamp`) is removed in favour of the problem shape used across EventFlow.
The Work Management definition is structurally compatible with the shared error
model but is defined locally, so the Work Management contracts keep no
reference to Order Processing schemas. A contract test asserts the
compatibility.

`detail` must never contain a stack trace, SQL, a secret, or a
provider-internal error. Error bodies must not disclose another workspace's
existence: a resource the caller cannot access returns `404`, not `403`
([tenant isolation](../security/tenant-isolation.md)).

## 5. Pagination, filtering and sorting

List operations return a page envelope instead of a bare array:

```json
{ "items": [ ... ], "page_info": { "next_cursor": null, "has_more": false } }
```

- `limit` — page size, 1–200, default 50.
- `cursor` — opaque cursor taken from `page_info.next_cursor` of the previous
  page. Cursors are opaque and must not be constructed by clients.
- Filters are explicit query parameters (`status`, `category`, `priority`,
  `assignee_id`, `column_id`) validated against the entity enums.
- `sort` is a comma-separated list of sort keys; prefix a key with `-` for
  descending order. Each operation lists its allowed keys in
  `x-allowed-sort-fields`.

## 6. Optimistic concurrency (ETag)

Successful reads and mutations return an opaque `ETag`. Mutating operations
accept an optional `If-Match` header carrying a previously returned `ETag`; a
stale value yields `412 Precondition Failed`. Approval decisions additionally
pin the exact `proposal_version` and return `409 Conflict` when the submitted
version is superseded.

## 7. Idempotency

Applying [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
Amendment A-02, every unsafe operation a client may retry accepts an
`Idempotency-Key` header:

| Operation | Header | Required |
|---|---|---|
| `POST .../consultations` | `Idempotency-Key` | No (required for offline clients) |
| `POST .../consultations/{consultation_id}/triage` | `Idempotency-Key` | No |
| `POST .../proposals` | `Idempotency-Key` | No |
| `POST .../proposals/{proposal_id}/submit` | `Idempotency-Key` | No |
| `POST .../proposals/{proposal_id}/decide` | `Idempotency-Key` | Yes |
| `PATCH .../boards/{board_id}/cards` | `Idempotency-Key` | No |

Semantics: the same key with an equivalent request replays the stored response
without repeating effects; the same key with a different request is an
idempotency conflict (`409`). The key is stored in the same transaction as the
domain change. Only approval decisions are replay-safe by default; offline
clients must send the header on every write before auto-replaying it.

## 8. Authorization

Every operation requires bearer authentication (`bearerAuth`) and declares the
roles allowed to perform it in the `x-required-roles` extension. The
authoritative role vocabulary is owned by
[Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9):

`owner`, `admin`, `triager`, `approver`, `contributor`, `viewer`.

This vocabulary supersedes the provisional lists previously written in
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.5 and in the
[workflow specification](work-management-workflow.md) transition matrix, whose
descriptive names map as follows:

| Descriptive name | Authoritative role |
|---|---|
| Any authenticated / Author / Proposer / Assignee | `contributor` |
| Triager / Maintainer | `triager` |
| Reviewer / Approver | `approver` |
| Admin | `admin` / `owner` |

Roles are enforced server-side; clients use them only to show or hide UI. A
`workspace_id` in a path is a locator, never an authority
([tenant isolation](../security/tenant-isolation.md)).

## 9. Internal events

Versioned internal events (for example `work_item.created`,
`board_card.created`) are **optional** for this contract and are deferred to
[Issue #46](https://github.com/jacksonsr451/EventFlow/issues/46), consistent
with [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
section 3.3. No Work Management AsyncAPI document exists yet, and this API does
not invent one.

## 10. Traceability

| Requirement | Artifact | Verification |
|---|---|---|
| Versioned public API | `/v1/` prefix, this document | `tests/contracts/test_work_management_api.py` |
| DTOs | `work_management.yaml` `$defs` | `test_mutating_bodies_reference_dtos`, `test_all_dtos_are_valid` |
| problem+json errors (A-01) | `$defs/ErrorResponse` | `test_error_responses_reference_a_single_definition`, `test_error_schema_matches_the_shared_error_model` |
| Pagination/filter/sort | list operations | `test_list_operations_paginate` |
| ETag / If-Match | `ETag` header, `IfMatch` parameter | `test_optimistic_concurrency_declares_if_match_and_412` |
| Idempotency (A-02) | `Idempotency-Key` parameters | `test_idempotency_key_declared_on_retryable_operations` |
| Authorization | `bearerAuth`, `x-required-roles` | `test_every_operation_requires_bearer_auth`, `test_every_operation_declares_authorization_roles` |
| Per-flow examples | `contracts/examples/work-management/` | `test_per_flow_examples_validate` |

## 11. Related documents

- [Work Management workflow](work-management-workflow.md): state machines and approval guarantees.
- [Client integration](client-integration.md): how the three clients consume the API.
- [Tenant isolation](../security/tenant-isolation.md): workspace invariants.
- [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md): shared contract policy and amendments.
