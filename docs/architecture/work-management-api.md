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
- Before the first Work Management runtime or client release, the initial
  contract may be normalized in a reviewed change without a deployed-client
  compatibility window. The board-card move route is card-specific so its
  `If-Match` validator corresponds to the ETag returned by that card's detail
  read. Once clients consume the released `v1` API, a path change requires `v2`.
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
| `CreateConsultationRequest` | `POST /v1/workspaces/{workspace_id}/consultations` and `POST .../consultations/drafts` |
| `Consultation` | detail GET and create/create-draft/update-draft/submit-draft/list/triage responses |
| `UpdateConsultationDraftRequest` | `PATCH .../consultations/{consultation_id}` |
| `TriageConsultationRequest` | `POST .../consultations/{consultation_id}/triage` |
| `BugTriageRequest`, `FeatureTriageRequest`, `ChoreTriageRequest`, `DocsTriageRequest`, `SecurityTriageRequest` | the category-discriminated variants of `TriageConsultationRequest` (Issue #5) |
| `BugCriteria`, `FeatureCriteria`, `ChoreCriteria`, `DocsCriteria`, `SecurityCriteria` | the per-category criteria objects (Issue #5) |
| `ReclassifyConsultationRequest` | `POST .../consultations/{consultation_id}/reclassify` (Issue #5) |
| `TriageTemplate`, `TriageTemplates` | `GET .../consultations/triage-templates` (Issue #5) |
| `CreateProposalRequest` | `POST /v1/workspaces/{workspace_id}/proposals` |
| `Proposal` | detail GET and list/create/update/submit/duplicate responses |
| `ChecklistItem` | the checklist entry used by `CreateProposalRequest`, `UpdateProposalRequest`, and `Proposal` (Issue #6) |
| `UpdateProposalRequest` | `PATCH .../proposals/{proposal_id}` (Issue #6) |
| `DuplicateProposalRequest` | `POST .../proposals/{proposal_id}/duplicate` (Issue #6) |
| `ProposalPreview` | `POST .../proposals/preview` (Issue #6) |
| `ProposalRevision`, `ProposalRevisionPage` | `GET .../proposals/{proposal_id}/revisions` (Issue #6) |
| `ProposalPage` | `GET .../consultations/{consultation_id}/proposals` (Issue #6) |
| `DecideProposalRequest` | `POST .../proposals/{proposal_id}/decide` |
| `DecideProposalResponse` | `POST .../proposals/{proposal_id}/decide` (200) |
| `MoveBoardCardRequest` | `PATCH /v1/workspaces/{workspace_id}/boards/{board_id}/cards/{card_id}` |
| `ConsultationPage`, `ProposalPage`, `ProposalRevisionPage`, `WorkItemPage`, `BoardCardPage` | list responses |
| `WorkItem`, `Board` | corresponding detail GET responses |
| `CreateWorkspaceRequest`, `UpdateWorkspaceRequest` | workspace administration (Issue #9) |
| `CreateProjectRequest`, `UpdateProjectRequest` | project administration (Issue #9) |
| `WorkspaceMember`, `ChangeMemberRoleRequest` | membership administration (Issue #9) |
| `WorkspaceInvitation`, `CreatedInvitation`, `CreateInvitationRequest`, `AcceptInvitationRequest` | invitation administration (Issue #9) |
| `CreateAttachmentRequest`, `ConsultationAttachment`, `ConsultationAttachmentList` | consultation attachments (Issue #4) |
| `CreateEvidenceRequest`, `ConsultationEvidence`, `ConsultationEvidenceList` | consultation evidence (Issue #4) |
| `ConsultationHistoryEntry`, `ConsultationHistoryPage` | consultation history (Issue #4) |

Entity DTOs (`Consultation`, `Proposal`, `Approval`, `WorkItem`, `BoardCard`)
remain the canonical shapes shared by all three clients.

## 4. Errors: RFC 9457 problem details

Every error response uses the media type `application/problem+json` and the
single Work Management `ErrorResponse` definition, which follows RFC 9457:

- `type`, `title`, `status`, `detail`, `instance` (RFC 9457 members),
- `code` — a stable machine-readable code for client branching,
- `correlation_id`, `request_id` — request tracing,
- `errors[]` — optional field-level validation details.

The standard RFC 9457 members are optional: when `type` is absent it means
`about:blank`; `title`, `status`, `detail`, and `instance` are included when
appropriate. `correlation_id` is the required EventFlow extension. When a body
includes `status`, the status-specific OpenAPI response schema constrains it to
match the HTTP response status.

This applies [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
Amendment A-01: the previous custom shape (`error_code`, `message`, `details`,
`timestamp`) is removed in favour of the problem shape used across EventFlow.
The Work Management definition uses the same core property names and types as
the existing shared Order error shape, while keeping RFC members optional as
required by RFC 9457. It is defined locally, so Work Management contracts keep
no reference to Order Processing schemas. The shared core parser can handle both
forms. Clients must tolerate RFC 9457 members being omitted in Work Management
errors, so generated requiredness differs from the existing Orders schema.
Contract tests assert field compatibility without making optional RFC members
required.

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
  page. Cursors are opaque and must not be constructed by clients. An
  implementation must integrity-protect the token and bind it to the workspace,
  operation, filters, and sort order; it must not expose raw database offsets or
  internal identifiers.
- Filters are explicit query parameters (`status`, `category`, `priority`,
  `assignee_id`, `column_id`) validated against the entity enums.
- `sort` is a comma-separated list of sort keys; prefix a key with `-` for
  descending order. Each operation lists its allowed keys in
  `x-allowed-sort-fields`; unsupported keys and malformed cursors return `400`.
- Ordering is keyset-stable with a unique resource identifier as the final
  tie-breaker. Empty pages return `items: []`, `has_more: false`, and
  `next_cursor: null`. This contract does not promise snapshot isolation across
  pages.
- When omitted, consultations and work items are ordered by ascending creation
  time then their identifier; board cards are ordered by column, rank, then
  card identifier. The `x-default-sort-fields` values are authoritative.

## 6. Optimistic concurrency (ETag)

Successful reads and mutations return a strong, quoted, opaque `ETag` validator.
Validators are scoped to one resource (or one exact list representation) and
must not be reused across unrelated resources. Mutating operations that declare
`If-Match` accept the exact strong validator previously returned for the target;
weak validators are not accepted, and a stale value yields `412 Precondition
Failed`. The header is optional in this contract, so omission does not imply
`428`. Approval decisions additionally pin the exact `proposal_version` and
return `409 Conflict` when that submitted version is superseded. The persistence
model has no general-purpose row-version column for these resources; HTTP handler
enforcement remains an implementation dependency and is not claimed here.

## 7. Idempotency

Applying [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
Amendment A-02, every unsafe operation a client may retry accepts an
`Idempotency-Key` header:

| Operation | Header | Required |
|---|---|---|
| `POST .../consultations` | `Idempotency-Key` | No (required for offline clients) |
| `POST .../consultations/drafts` | `Idempotency-Key` | No (required for offline clients) |
| `PATCH .../consultations/{consultation_id}` | `Idempotency-Key` | No |
| `POST .../consultations/{consultation_id}/submit` | `Idempotency-Key` | No |
| `POST .../consultations/{consultation_id}/triage` | `Idempotency-Key` | No |
| `POST .../consultations/{consultation_id}/reclassify` | `Idempotency-Key` | No |
| `POST .../consultations/{consultation_id}/attachments` | `Idempotency-Key` | No |
| `POST .../consultations/{consultation_id}/evidence` | `Idempotency-Key` | No |
| `POST .../proposals` | `Idempotency-Key` | No |
| `PATCH .../proposals/{proposal_id}` | `Idempotency-Key` | No |
| `POST .../proposals/{proposal_id}/submit` | `Idempotency-Key` | No |
| `POST .../proposals/{proposal_id}/duplicate` | `Idempotency-Key` | No |
| `POST .../proposals/{proposal_id}/decide` | `Idempotency-Key` | Yes |
| `PATCH .../boards/{board_id}/cards/{card_id}` | `Idempotency-Key` | No |

Contract semantics: keys use the ASCII token characters `[A-Za-z0-9._~-]` and
length 8–128. The request fingerprint covers the operation, all resource path
identifiers, the normalized body, and any supplied precondition that affects
the operation; it excludes authentication and tracing headers. The key namespace
is `(workspace_id, operationId, key)`,
matching the persistence model's `(workspace_id, operation, idempotency_key)`
uniqueness. Reusing a key in a different workspace or operation is independent.
Within one namespace, an equivalent request replays the original HTTP status and
body without repeating effects; a different request fingerprint returns
`409 Conflict`. Concurrent same-key/same-request calls produce one business
effect and replay the same response. The fingerprint must be committed atomically
with the business effect and response record. If an optional key is omitted, no
replay guarantee applies. These are normative API requirements, not a claim that HTTP handlers
exist. The current persistence implementation provides database-level
idempotent effect recovery for approval decisions, returning the persisted
approval result; it does not replay the full HTTP response body from the stored
response metadata. Other endpoint integrations and HTTP replay remain future
runtime work. The contract concerns local database effects and HTTP response
replay only; it does not promise exactly-once external side effects. Offline
clients must send a key before auto-replaying a write.
Retention is unspecified; implementations must document their effective replay
window and must not claim replay outside it.

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

Roles must be enforced server-side; clients use them only to show or hide UI.
Issue #11 declares these requirements, Issue #10 supplies the verified principal,
and Issue #9 supplies the RBAC enforcement. A
`workspace_id` in a path is a locator, never an authority
([tenant isolation](../security/tenant-isolation.md)).

### 8.1 Workspace administration and RBAC (Issue #9)

Issue #9 adds the workspace, project, membership and invitation operations and
the server-side authorization that enforces `x-required-roles`. The action matrix
lives in `eventflow_work_management.authorization.policy` and is cross-checked
against this contract by `tests/test_rbac_policy_unit.py`, so the declared roles
and the enforced policy cannot drift.

Three operations are **authentication-scoped** rather than workspace-role-scoped:

| Operation | Why no workspace role applies |
|---|---|
| `createWorkspace` | The caller is not yet a member of any workspace. |
| `listWorkspaces` | The response set is selected by membership, not by a runtime role. |
| `acceptInvitation` | Authorization is identity-bound to the invited identity. |

They declare `x-required-roles: [viewer]` — the baseline authenticated tier, so
the least-privilege lower bound — plus an explicit
`x-authorization-scope: authenticated` marker. Enforcement additionally requires
the verified principal (and, for acceptance, the exact token digest and matching
`invited_user_id`). The authoritative roles are the six values `owner`, `admin`,
`triager`, `approver`, `contributor`, and `viewer`; `viewer` is read-only,
`owner` has every action, and only an owner may grant or revoke the owner seat.

Tenant isolation is enforced by resolving membership before any action: a missing
workspace, a missing active membership, or a foreign resource all return `404`,
while a visible workspace with an insufficient role returns `403` (TI-02/TI-03).
Membership invariants that span rows (at least one active owner) are serialized
with a workspace row lock (`SELECT ... FOR UPDATE`). Invitations store only a
SHA-256 digest of the one-time token and are bound to one identity and workspace.

Authorization defaults to deny. A workspace role is evaluated only after
workspace membership is established; it does not grant access to another
workspace. Where a request includes `project_id` or a board/card relationship,
the server must additionally verify that each referenced resource belongs to
that workspace and that the caller is authorized for its project scope. Resource
ownership rules (such as submitting only one's own proposal unless an elevated
role applies) are separate from the role list and must be checked by the
backend. A cross-workspace resource is reported as `404`; a visible resource
with insufficient action permission is `403`.

### 8.2 Consultation attachments, evidence, and history (Issue #4)

Issue #4 adds the evidence pipeline that sits beside consultation intake. All
three resource families are workspace-scoped and use the same authorization,
tenant-isolation, and problem+json rules as the rest of the API; `workspace_id`
and `consultation_id` in the path are locators, never authority.

| Operation | Method and path | Required role (`x-required-roles`) |
|---|---|---|
| Upload attachment | `POST .../consultations/{consultation_id}/attachments` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| List attachments | `GET .../consultations/{consultation_id}/attachments` | any member (incl. `viewer`) |
| Read attachment | `GET .../consultations/{consultation_id}/attachments/{attachment_id}` | any member (incl. `viewer`) |
| Download content | `GET .../consultations/{consultation_id}/attachments/{attachment_id}/content` | any member (incl. `viewer`) |
| Delete attachment | `DELETE .../consultations/{consultation_id}/attachments/{attachment_id}` | uploader or `owner`/`admin` |
| Create evidence | `POST .../consultations/{consultation_id}/evidence` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| List evidence | `GET .../consultations/{consultation_id}/evidence` | any member (incl. `viewer`) |
| Read history | `GET .../consultations/{consultation_id}/history` | any member (incl. `viewer`) |

- **Upload transport.** Bytes travel as base64 in the JSON body
  (`content_base64`) so the upload reuses the authenticated JSON transport; the
  server enforces the size limit and content-type allowlist on the decoded bytes,
  never the declared type alone. Upload returns `201` with the created resource
  whose `status` is `available`, `quarantined`, or `rejected`; a client error
  (bad filename, unsupported or mismatched type, oversized or malformed content)
  is a `400`/`422` problem and stores nothing.
- **Fail-closed scanning.** With no scanning backend configured every upload is
  quarantined (`scan_verdict: unknown`); quarantined and rejected objects are
  never downloadable (`409 ATTACHMENT_QUARANTINED`) and can never be cited as
  evidence.
- **Quota.** Exceeding the per-consultation attachment quota returns
  `409 ATTACHMENT_LIMIT_REACHED`.
- **Evidence shape.** Evidence is `text`, `link`, or `attachment`; an
  `attachment` entry requires an `attachment_id` that points at an `available`
  attachment in the same consultation, and text/link entries must not carry one.
- **History.** History is a read-only, cursor-paginated projection of the
  append-only audit trail for one consultation. It uses the same page envelope
  and `limit`/`cursor` rules as other list operations but is not a filterable
  entity list; attachment and evidence lifecycle actions appear in the timeline.
- **Idempotency.** Attachment upload and evidence creation accept an optional
  `Idempotency-Key` (section 7); an equivalent replay returns the original
  resource and a different fingerprint returns `409`.

### 8.3 Differentiated triage and reclassification (Issue #5)

Issue #5 makes triage category-specific and adds a manual reclassification
operation. The triage request is a **category-discriminated union**: the
`category` field selects exactly one criteria variant (`bug`, `feature`, `chore`,
`docs`, `security`) and the request must supply that variant's criteria object
and no other. The contract expresses this as `oneOf` plus a `discriminator` on
`category`, replacing the earlier `if`/`then` chain; the backend Pydantic union
is authoritative and the OpenAPI is generated to match.

| Operation | Method and path | Required role (`x-required-roles`) |
|---|---|---|
| Triage | `POST .../consultations/{consultation_id}/triage` | `triager`, `admin`, `owner` |
| Reclassify | `POST .../consultations/{consultation_id}/reclassify` | `triager`, `admin`, `owner` |
| List triage templates | `GET .../consultations/triage-templates` | `triager`, `admin`, `owner` |

- **Manual only.** Nothing infers a category from free text and nothing creates a
  Proposal, Approval, WorkItem, or BoardCard. An optional intake `category` is a
  reporter hint, not a completed triage decision.
- **Lifecycle.** Triage moves `OPEN`/`REOPENED` to `TRIAGING`; a draft cannot be
  triaged. Reclassification is only valid after triage has completed (the
  consultation has a recorded triage) and keeps the current lifecycle state; a
  raw or untriaged consultation returns `409 INVALID_STATE`.
- **Justification and audit.** Reclassification requires an explicit
  `justification` and appends a `consultation.reclassified` audit record carrying
  the previous and new category, the previous and new criteria snapshot, the
  justification, the actor, and the correlation id. The audit trail is
  append-only and visible through the history read.
- **Concurrency and idempotency.** Both operations honour a strong `If-Match`
  (`412` on a stale validator) and accept an optional `Idempotency-Key`; a replay
  returns the original resource without a second audit row.
- **Templates.** `TriageTemplate`/`TriageTemplates` expose reusable backend
  metadata (category, title, description, guidance, and required fields) for the
  differentiated categories. They are guidance contracts, not client UIs.

### 8.4 Consultation task proposals (Issue #6)

Issue #6 makes the Proposal a first-class, independent aggregate. One triaged
consultation may yield **zero, one, or many** proposals; the relationship is
1→N and is never collapsed. Each proposal has its own identity and its own
revision counter starting at 1, so two proposals of the same consultation are
both "version 1" and are distinguished by `proposal_id`.

| Operation | Method and path | Required role (`x-required-roles`) |
|---|---|---|
| Preview proposal | `POST .../proposals/preview` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| Create proposal | `POST .../proposals` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| List proposals | `GET .../consultations/{consultation_id}/proposals` | any member (incl. `viewer`) |
| Read proposal | `GET .../proposals/{proposal_id}` | any member (incl. `viewer`) |
| Read revisions | `GET .../proposals/{proposal_id}/revisions` | any member (incl. `viewer`) |
| Edit proposal | `PATCH .../proposals/{proposal_id}` | proposer, or `owner`/`admin` |
| Submit for review | `POST .../proposals/{proposal_id}/submit` | proposer, or `owner`/`admin` |
| Duplicate proposal | `POST .../proposals/{proposal_id}/duplicate` | `owner`, `admin`, `triager`, `approver`, `contributor` |

- **Eligibility.** A proposal may only be derived from a consultation whose
  manual triage has completed (`triaged_at` recorded) and whose status is
  `triaging`, `proposed`, or `reopened`; raw `open`/`draft` intake and terminal
  states return `409 INVALID_STATE`. Preview and create enforce the same rule.
- **Preview.** `POST .../proposals/preview` validates and normalizes a
  prospective proposal (including checklist item ids and evidence references)
  and returns a `ProposalPreview` without persisting anything.
- **Revisions.** Editing a `draft` or `changes_requested` proposal with content
  changes increments `version` and appends an immutable `ProposalRevision`
  snapshot; the revision history is read-only and cursor-paginated. A
  `proposal.revised` audit record accompanies each edit.
- **Lifecycle.** `submit` moves `draft`/`changes_requested` to `in_review`; an
  already-submitted proposal returns `409 INVALID_STATE`. Creating, editing,
  previewing, submitting, or duplicating a proposal **never** creates an
  Approval, WorkItem, BoardCard, or remote issue.
- **Duplication.** `duplicate` creates a new independent `draft` at version 1
  that references its source through `duplicated_from_proposal_id`. With
  `supersede_source: true` the source becomes `superseded` and records
  `superseded_by_proposal_id`. Duplication never fabricates downstream work.
- **Concurrency and idempotency.** `PATCH`, `submit`, and `duplicate` honour a
  strong `If-Match` (`412` on a stale validator) and accept an optional
  `Idempotency-Key`; an equivalent replay returns the original resource without
  repeating effects. Audit actions are `proposal.created`, `proposal.revised`,
  `proposal.submitted`, and `proposal.duplicated`.

### 8.5 Entity comments, generic attachments, and history (Issue #29)

Issue #29 makes comments, attachments, and history available on every
collaborable entity through one generic, entity-scoped route family. The path
names the public collection (`consultations`, `proposals`, `work-items`,
`board-cards`) and the entity id; the server resolves the target inside the
caller's workspace and copies its project scope. Consultations keep their more
specific Issue #4 attachment/evidence/history routes, which remain authoritative
for that collection.

| Operation | Method and path | Required role (`x-required-roles`) |
|---|---|---|
| Create comment | `POST .../{entity_collection}/{entity_id}/comments` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| List comments | `GET .../{entity_collection}/{entity_id}/comments` | any member (incl. `viewer`) |
| Read comment | `GET .../{entity_collection}/{entity_id}/comments/{comment_id}` | any member (incl. `viewer`) |
| Delete comment | `DELETE .../{entity_collection}/{entity_id}/comments/{comment_id}` | author, or `owner`/`admin` |
| Upload attachment | `POST .../{entity_collection}/{entity_id}/attachments` | `owner`, `admin`, `triager`, `approver`, `contributor` |
| List attachments | `GET .../{entity_collection}/{entity_id}/attachments` | any member (incl. `viewer`) |
| Read attachment | `GET .../{entity_collection}/{entity_id}/attachments/{attachment_id}` | any member (incl. `viewer`) |
| Download content | `GET .../{entity_collection}/{entity_id}/attachments/{attachment_id}/content` | any member (incl. `viewer`) |
| Delete attachment | `DELETE .../{entity_collection}/{entity_id}/attachments/{attachment_id}` | uploader, or `owner`/`admin` |
| Read history | `GET .../{entity_collection}/{entity_id}/history` | any member (incl. `viewer`) |

- **Collection resolution.** `board-cards` is a flat path
  (`.../board-cards/{card_id}`); the other collections use their resource ids.
  An unsupported collection, a missing entity, and an entity in another
  workspace all return `404`, so a probe cannot distinguish "unsupported" from
  "not visible".
- **Comments.** `body` is trimmed and limited to 4,000 characters; empty bodies
  are `400` and control characters are rejected with `422`. The author is taken
  from the verified principal, never the body. Comments cannot be edited.
  Deleting one stores a tombstone: the audit trail is unchanged and the API
  returns `body: null`, `deleted: true`. Deleting an already-deleted comment is
  a `204` no-op.
- **Attachments.** The transport, content-type allowlist, size bound, fail-closed
  scanning, `409 ATTACHMENT_QUARANTINED` download refusal, and per-entity quota
  (`409 ATTACHMENT_LIMIT_REACHED`) match section 8.2. Proposals, work items, and
  board cards use the generic pair. The same path shape for `consultations` is
  served by the dedicated Issue #4 handlers, so consultation attachments always
  use the evidence pipeline and never the generic tables.
- **History.** History is a read-only, cursor-paginated projection of the
  append-only audit trail for one entity, oldest first. It uses the same page
  envelope as section 5. Entries can never be created, rewritten, or deleted
  through the API.
- **Idempotency.** Comment creation and attachment upload accept an optional
  `Idempotency-Key`; an equivalent replay returns the original resource and a
  different fingerprint returns `409 IDEMPOTENCY_CONFLICT`.

### 8.6 Project repository configuration (Issue #44)

Projects can be associated with external GitHub or GitLab repositories under
`/v1/workspaces/{workspace_id}/projects/{project_id}/repositories`. Issue #44
**configures** the association only: it does not call a provider, clone a
repository, inspect branches, link issues, or mutate remote state, and it stores
no provider credentials, installation ids, tokens, or sync cursors.

| Operation | Method and path | Required role (`x-required-roles`) |
|---|---|---|
| Link repository | `POST .../repositories` | `owner`, `admin` |
| List repositories | `GET .../repositories` | any member (incl. `viewer`) |
| Read repository | `GET .../repositories/{repository_id}` | any member (incl. `viewer`) |
| Update or deactivate/reactivate | `PATCH .../repositories/{repository_id}` | `owner`, `admin` |
| Archive repository | `DELETE .../repositories/{repository_id}` | `owner`, `admin` |

- **Identity and deduplication.** The unique key is
  `(workspace_id, project_id, provider, provider_instance_id,
  remote_repository_id)`; `provider_instance_id` is the provider host (for
  example `github.com` or a self-hosted GitLab host) and is **not** an
  installation id. The same repository can be linked to different projects, and
  the same provider repository id on different instances is a different remote.
  A duplicate active/inactive link returns `409 REPOSITORY_ALREADY_LINKED`; a
  previously archived link returns `409 REPOSITORY_ARCHIVED`.
- **Canonicalization.** HTTPS, `ssh://git@host/path`, and `git@host:path` forms
  of the same repository normalize to one credential-free
  `https://host/full/path` URL (`.git` removed). HTTP, userinfo/passwords,
  ports, query strings, fragments, and whitespace are rejected with `400`. A
  supplied `repository_full_path` must match the URL, and
  `provider_instance_id` must equal the URL host. The URL is mutable metadata and
  is never used for deduplication.
- **Lifecycle.** `active ↔ inactive` is changed through `PATCH status`;
  deactivation records `deactivated_at` and reactivation clears it. `archived`
  is terminal and is reached only through `DELETE`, which preserves history and
  never contacts the provider. `PATCH status: archived` is rejected (`400`), and
  an archived link cannot be updated. Repeating `DELETE` returns `204`.
- **Verification.** `verification_status` is `configured` for every link created
  here; `verified` is reserved for a future provider adapter and is not produced
  by this API.
- **Concurrency and idempotency.** `POST`, `PATCH`, and `DELETE` accept an
  optional `Idempotency-Key`; equivalent retries replay the stored result, while
  a different fingerprint returns `409 IDEMPOTENCY_CONFLICT`. `PATCH` and
  `DELETE` accept `If-Match` and return `412 PRECONDITION_FAILED` for a stale
  strong validator; successful reads and mutations return an `ETag`.
- **Audit.** Link, update, deactivate, reactivate, and archive append
  `project_repository.linked|updated|deactivated|reactivated|unlinked` to the
  workspace audit trail with `entity_type = "project_repository"`.

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
| Consultation task proposals (Issue #6) | section 8.4, `Proposal*` DTOs | `services/work-management/tests/test_proposal_api_integration.py`, `services/work-management/tests/test_proposal_unit.py` |
| Entity comments, attachments, history (Issue #29) | section 8.5, `EntityComment*`/`EntityAttachment*`/`EntityHistoryPage` DTOs | `services/work-management/tests/test_collaboration_integration.py` |
| Project repository configuration (Issue #44) | section 8.6, `ProjectRepository*` DTOs | `services/work-management/tests/test_project_repository_unit.py`, `test_project_repository_integration.py` |
| Per-flow examples | `contracts/examples/work-management/` | `test_per_flow_examples_validate` |

## 11. Related documents

- [Work Management workflow](work-management-workflow.md): state machines and approval guarantees.
- [Client integration](client-integration.md): how the three clients consume the API.
- [Tenant isolation](../security/tenant-isolation.md): workspace invariants.
- [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md): shared contract policy and amendments.
