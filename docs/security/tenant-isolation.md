# Tenant Isolation

Workspaces are the tenant boundary of the Work Management domain. This document
defines the invariants that keep one workspace's data from ever reaching another,
and the non-disclosive HTTP behaviour for unauthorized access. It is subordinate
to [ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md) and
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md), and it
constrains [Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47).

Status: Specified (Phase 0). No enforcement code exists yet.

## Invariants

An invariant is a statement that must hold for every request, in every client,
without exception.

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
  principal with owner or admin rights in that workspace.
- **TI-07** — Deny by default: absence of an explicit grant is denial.
- **TI-08** — A cross-tenant access attempt is recorded as a security event
  (`tenant.cross_access_attempt`) without exposing the other tenant's data.

## Expected Behaviour

| Situation | Condition | Response |
|---|---|---|
| No credentials | Missing or malformed `Authorization` | `401 Unauthorized` |
| Invalid credentials | Expired or revoked token | `401 Unauthorized` |
| Authenticated, not a member | Valid token, no membership for the target workspace | `404 Not Found` |
| Authenticated, insufficient role | Member, but lacks the required RBAC permission | `403 Forbidden` |
| Cross-tenant object id | Object exists in another workspace | `404 Not Found` |
| Stale or conflicting write | Optimistic-locking or idempotency conflict | `409 Conflict` |
| Not authenticated at all | Anonymous request to a protected route | `401 Unauthorized` |

A client-supplied `workspace_id` never grants access. Body payloads for mutating
operations must not declare the tenant; the tenant comes from the authenticated
path and session context. See
[`contracts/openapi/work-management.yaml`](../../contracts/openapi/work-management.yaml)
for the current endpoints.

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
field. See [webhooks.md](webhooks.md) (`WH-07`).

## Verification

- Contract tests assert that mutating request bodies do not declare tenant
  identity and that workspace path parameters are required.
- Implementation tests (Issue #47) assert the `404` vs `403` behaviour of the
  table above and that no query omits the tenant predicate.

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-MT-01` to `TM-MT-07`.
- [Webhooks](webhooks.md)
- [Data governance](data-governance.md)
