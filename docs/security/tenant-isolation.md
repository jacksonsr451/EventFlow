# Tenant Isolation

Workspaces are the tenant boundary of the Work Management domain. This document
defines the invariants that keep one workspace's data from ever reaching another,
the non-disclosive HTTP behaviour for unauthorized access, and the separation
between the different identities involved in a request. It is subordinate to
[ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md) and
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md), and it
constrains [Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47).

Status: Partially implemented. Issue #9 enforces the workspace membership and RBAC
invariants (TI-02, TI-03, TI-06, TI-07 and the synchronous parts of TI-01/TI-04)
in `services/work-management`. The asynchronous invariants (TI-08, TI-09, TI-10)
remain specified and are owned by their respective issues.

## Identity Separation

Four identities must never be conflated:

| Identity | Established by | Must not be used for |
|---|---|---|
| User identity | The authenticated session | Choosing the tenant |
| Tenant identity | The verified workspace membership of the principal | Granting a permission |
| Internal authorization | Workspace RBAC evaluated by the backend | Third-party API access |
| External authorization | GitHub/GitLab app permissions and installation scope | EventFlow RBAC |

Authentication proves *who* a caller is; authorization proves *what* they may do
inside one workspace; external provider authorization is a separate grant that
never substitutes for internal RBAC, and vice versa. A caller who is authorized
at the provider is not thereby authorized in EventFlow.

## Invariants

An invariant is a statement that must hold for every request, in every client,
and in every asynchronous consumer, without exception.

- **TI-01** — Every request is scoped to the authenticated principal's workspace
  membership; the workspace context is derived from the authenticated session,
  never from the request body.
- **TI-02** — A `workspace_id` in a URL path is a locator, not an authority. It
  selects the target only after membership and permission checks pass.
- **TI-03** — A request for a resource the caller cannot access returns `404 Not
  Found`, not `403 Forbidden`, so that existence is not disclosed. `403` is
  reserved for a resource the caller may see but not modify.
- **TI-04** — Every read and write applies a server-side tenant predicate. No
  query, projection, export, or cache lookup may omit it.
- **TI-05** — No cross-workspace joins, shared tables, or shared mutable caches.
  A cache key that stores tenant data includes the workspace identity.
- **TI-06** — Workspace membership and RBAC assignments can only be changed by a
  principal with owner or admin rights in that workspace; no role grants access
  to a workspace the principal is not a member of.
- **TI-07** — Deny by default: absence of an explicit grant is denial.
- **TI-08** — A cross-tenant access attempt is recorded as a security event
  (`tenant.cross_access_attempt`) without exposing the other tenant's data.
- **TI-09** — Asynchronous jobs and events carry an explicit tenant identity
  established at admission. A consumer must never infer the tenant from event
  payload content, and a job without tenant context must fail closed rather than
  default to a shared scope.
- **TI-10** — A service principal (webhook or integration) acts with the minimum
  workspace scope required, and its tenant binding is fixed at installation and
  validated per operation. It must never act as a confused deputy that applies
  its own privilege to a target selected from untrusted input.

## Expected Behaviour

| Situation | Condition | Response |
|---|---|---|
| No credentials | Missing or malformed `Authorization` | `401 Unauthorized` |
| Invalid credentials | Expired or revoked token | `401 Unauthorized` |
| Authenticated, not a member | Valid token, no membership for the target workspace | `404 Not Found` |
| Authenticated, insufficient role | Member, but lacks the required RBAC permission | `403 Forbidden` |
| Cross-tenant object id | Object exists in another workspace | `404 Not Found` |
| Stale `If-Match` validator | ETag precondition fails | `412 Precondition Failed` |
| Stale proposal version or idempotency conflict | Domain version or key-fingerprint conflict | `409 Conflict` |
| Not authenticated at all | Anonymous request to a protected route | `401 Unauthorized` |

A client-supplied `workspace_id` never grants access. Body payloads for mutating
operations must not declare the tenant; the tenant comes from the authenticated
path and session context. See
[`contracts/openapi/work-management.yaml`](../../contracts/openapi/work-management.yaml)
for the current endpoints.

## Project Triage Configuration

Project triage rules and versioned templates are scoped by the composite key
`(workspace_id, project_id)`. Every repository query filters on both values, and
composite foreign keys make a template, version, or activation that references a
project in another workspace impossible to persist. Template ids supplied in a
path are locators only: a template from another project or workspace resolves to
`404 Not Found`. The `project_id` in a triage preview body must match the path.

Configuration and template reads follow the normal membership rules; mutations
require `triage_configuration:manage` or `triage_template:manage`, which only
owner and admin hold. Pinned consultation snapshots are tenant-scoped data and
must be returned only through the consultation read path.

## Non-Disclosure Rules

- Error bodies must not contain resource owner identifiers, other workspace
  identifiers, upstream internal identifiers, or stack traces.
- Enumeration-resistant identifiers (for example UUIDs) are used; sequential or
  guessable identifiers are not exposed in responses.
- Timing and error differences between "does not exist" and "not authorized"
  must not allow confirmation of another tenant's data.

## Service-Principal Isolation

Webhooks and integrations act as service principals, not as end users. A
service principal is granted the minimum workspace scope required, and its tenant
binding is resolved from a verified installation mapping, never from a payload
field. The repository-to-workspace mapping is the authority; a payload that names
a different workspace is rejected as a security event. See
[webhooks.md](webhooks.md) (`WH-07`, `WH-11`) and the confused-deputy scenario
`TM-MT-08`.

## Asynchronous Processing

Background work inherits the tenant identity recorded at admission (`TI-09`).
Outbox events, retries, dead-letter reprocessing, and projections each carry that
identity and re-validate membership before writing. A failed lookup or a missing
tenant context aborts the job; it never falls back to a default or global scope.

## Verification

Each invariant maps to an objective test criterion. Implementation tests live in
the owning issue; the repository contract tests assert the parts expressible
today.

| Invariant | Objective criterion | Verification | Owner |
|---|---|---|---|
| TI-01 | A request body cannot change the effective tenant | Contract + Issue #47 tests | Issue #47 |
| TI-02 | A foreign path `workspace_id` is denied for a non-member | Issue #47 tests | Issue #47 |
| TI-03 | Cross-tenant read returns `404`, never `403` | Issue #47 tests | Issue #47 |
| TI-04 | Every query, projection, and export includes the tenant predicate | Issue #47 / #31 tests | Issue #12 |
| TI-05 | Cache keys that hold tenant data include the workspace id | Issue #12 tests | Issue #12 |
| TI-06 | Only an owner/admin can change roles; roles do not cross workspaces | `services/work-management/tests/test_workspace_management_integration.py` | Issue #9 |
| TI-07 | Absence of a grant denies access | `services/work-management/tests/test_rbac_policy_unit.py`, `test_workspace_management_integration.py` | Issue #9 |
| TI-08 | A cross-tenant attempt emits `tenant.cross_access_attempt` | Issue #47 tests | Issue #47 |
| TI-09 | A job without tenant context fails closed; a payload tenant is ignored | Issue #46 tests | Issue #46 |
| TI-10 | A service principal cannot act on a workspace outside its binding | Issue #27 / #47 tests | Issue #27 |

The current repository contract tests assert that mutating request bodies do not
declare tenant identity and that workspace path parameters are required.

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-MT-01` to `TM-MT-09`.
- [Traceability matrix](traceability.md)
- [Webhooks](webhooks.md)
- [Data governance](data-governance.md)
