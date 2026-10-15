# EventFlow Security Documentation

This directory is the security specification baseline for EventFlow. It defines
the threat model, security policies, data governance rules, and security
observability requirements for the Work Management bounded context and its three
clients (Webapp, Desktop, VS Code extension).

## Status

Specified (Phase 0). These documents describe accepted security requirements for
planned behavior. They do not imply that any control is implemented. No service,
client, or authentication system exists yet; the controls below are binding for
the issues that implement them.

This specification is subordinate to:

- [ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md) — product
  scope, bounded contexts, and monorepo architecture.
- [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) —
  multi-client layout, shared contracts, authentication, and idempotency.

No separate ADR is introduced for this work. Threat modeling and data governance
are requirements layered on top of the accepted architecture; they refine
behaviour without changing a system boundary, consistency guarantee, or
infrastructure choice. Decisions that would do so are recorded as open decisions
in [open-decisions.md](open-decisions.md) and, if accepted, become ADRs later.

## Documents

- [Threat model](threat-model.md): assets, actors, trust boundaries, and the
  STRIDE-based scenario catalog.
- [Risk register](risk-register.md): residual risks with likelihood, severity,
  owners, controls, and verification.
- [Tenant isolation](tenant-isolation.md): workspace isolation invariants and the
  non-disclosive HTTP behaviour for unauthorized access.
- [OAuth and credentials](oauth-and-credentials.md): authorization flow, token
  storage per platform, scopes, rotation, and revocation.
- [Webhooks](webhooks.md): signature verification, replay protection, tenant
  routing, and webhook secret handling.
- [Untrusted content](untrusted-content.md): source code, issue/PR text, and
  attachment handling.
- [Data governance](data-governance.md): classification, retention, deletion,
  exports, and data subject rights.
- [Security observability](security-observability.md): security event taxonomy
  and redacted telemetry rules.
- [Open decisions](open-decisions.md): decisions that require product or
  platform ownership before implementation.

## Identifier Conventions

| Prefix | Meaning | Defined in |
|---|---|---|
| `TM-<AREA>-<NN>` | Threat scenario (`OA`, `SC`, `WH`, `AT`, `MT`, `DG`) | [threat-model.md](threat-model.md) |
| `R-<NNN>` | Residual risk | [risk-register.md](risk-register.md) |
| `OA-<NN>` | OAuth and credential control | [oauth-and-credentials.md](oauth-and-credentials.md) |
| `SC-<NN>` | Untrusted source-content control | [untrusted-content.md](untrusted-content.md) |
| `AT-<NN>` | Attachment control | [untrusted-content.md](untrusted-content.md) |
| `WH-<NN>` | Webhook control | [webhooks.md](webhooks.md) |
| `TI-<NN>` | Tenant isolation invariant/control | [tenant-isolation.md](tenant-isolation.md) |
| `DG-<NN>` | Data governance control | [data-governance.md](data-governance.md) |
| `SO-<NN>` | Security observability control | [security-observability.md](security-observability.md) |
| `SE-<NN>` | Security event type | [security-observability.md](security-observability.md) |

The machine-readable taxonomy for `SE-*` events is
[`contracts/schemas/security_events.yaml`](../../contracts/schemas/security_events.yaml).

## Trust Boundaries

- **TB-01 — Client boundary:** untrusted user input and client runtime storage.
- **TB-02 — Edge / API gateway:** authentication, authorization, and request
  validation before domain logic.
- **TB-03 — Work Management domain:** authoritative business state.
- **TB-04 — Tenant boundary:** workspace data must never cross this line.
- **TB-05 — External integration boundary:** GitHub/GitLab webhooks and OAuth
  providers.
- **TB-06 — Persistence boundary:** databases, object storage, and backups.

## Traceability

This specification is delivered by
[Issue #35](https://github.com/jacksonsr451/EventFlow/issues/35) and constrains
the following implementation issues:

| Concern | Implementing issue |
|---|---|
| Authentication (OAuth flow, tokens) | [#10](https://github.com/jacksonsr451/EventFlow/issues/10) |
| Workspaces and RBAC | [#9](https://github.com/jacksonsr451/EventFlow/issues/9) |
| Versioned API and error model | [#11](https://github.com/jacksonsr451/EventFlow/issues/11) |
| Persistence and migrations | [#12](https://github.com/jacksonsr451/EventFlow/issues/12) |
| Approvals and audit trail | [#7](https://github.com/jacksonsr451/EventFlow/issues/7) |
| Tenant isolation | [#47](https://github.com/jacksonsr451/EventFlow/issues/47) |
| GitHub integration | [#27](https://github.com/jacksonsr451/EventFlow/issues/27) |
| GitLab integration | [#28](https://github.com/jacksonsr451/EventFlow/issues/28) |
| AI assistance | [#45](https://github.com/jacksonsr451/EventFlow/issues/45) |
| Events and outbox | [#46](https://github.com/jacksonsr451/EventFlow/issues/46) |
