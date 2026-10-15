# Webhooks and Integrations

GitHub and GitLab deliver events to EventFlow through webhooks. A webhook
endpoint is an unauthenticated network surface that must authenticate every
delivery, reject replays, and route the event to the correct workspace. This
document constrains [Issue #27](https://github.com/jacksonsr451/EventFlow/issues/27),
[Issue #28](https://github.com/jacksonsr451/EventFlow/issues/28), and the
asynchronous handling in [Issue #46](https://github.com/jacksonsr451/EventFlow/issues/46).

Status: Specified (Phase 0). No webhook endpoint exists yet.

## Delivery Verification

1. Read the raw request body without parsing it.
2. Verify the provider signature over the raw body before any parsing.
3. Reject the delivery if verification fails.
4. Deduplicate by delivery identifier and enforce a freshness window.
5. Resolve the target workspace from a verified installation mapping.
6. Hand the parsed event to the asynchronous pipeline.
7. Acknowledge quickly; perform the work outside the request.

## Controls

- **WH-01** — Verify the provider signature on every delivery: HMAC-SHA256 in
  `X-Hub-Signature-256` for GitHub, and the `X-Gitlab-Token` secret for GitLab.
- **WH-02** — Compare signatures with a constant-time comparison to avoid timing
  oracles.
- **WH-03** — Verify the signature over the exact raw body bytes, before parsing,
  re-serializing, or normalizing the payload.
- **WH-04** — Enforce a maximum request size and reject oversized or
  unreasonably nested payloads with `413` before deep parsing.
- **WH-05** — Deduplicate deliveries by the provider delivery id in a bounded
  time window; a duplicate is acknowledged without re-applying effects.
- **WH-06** — Reject deliveries whose timestamp is outside a short freshness
  window to limit replay.
- **WH-07** — Resolve the tenant from the verified installation mapping keyed by
  the provider's installation or repository id; never trust a tenant or workspace
  field from the payload.
- **WH-08** — Webhook secrets are unique per installation, stored in the
  deployment secret store, and rotated on a schedule and on suspected compromise.
- **WH-09** — Failed processing goes to a dead-letter path with bounded retries;
  deliveries are never retried blindly in a way that duplicates effects.
- **WH-10** — Webhook payloads are not logged in full. Logs record identifiers,
  delivery ids, and outcome, never tokens or full payload bodies.
- **WH-11** — GitHub/GitLab App installation permissions are minimized to the
  read-only scopes the feature needs; write scopes require an explicit,
  documented justification and are reviewed.

## Provider-Specific Verification

| Provider | Authenticity | Delivery id | Deduplication key |
|---|---|---|---|
| GitHub | HMAC-SHA256 in `X-Hub-Signature-256` | `X-GitHub-Delivery` | delivery id |
| GitLab | `X-Gitlab-Token` secret comparison | `X-Gitlab-Event-UUID` when present | event uuid or stable payload id |

GitHub App installations are authorized by installation id, not by user tokens.
The installation id maps to exactly one workspace (`WH-07`), and the processing
service acts only within that mapping. A request that would make the service
principal act outside its binding is rejected rather than executed with the
service principal's privilege (see `TI-10` and `TM-MT-08`).

## Tenant Routing

The service principal that processes a delivery acts with the minimum scope for
the resolved workspace. The tenant binding comes from the installation mapping
(WH-07) and is cross-checked against the repository owner's membership. A
payload that names a different workspace than the mapping is rejected as a
security event.

## Replay and Idempotency

Webhook handling is at-least-once. Deduplication ([WH-05]) plus the downstream
idempotency contract for created consultations keeps a repeated delivery from
creating duplicate work. Where a downstream operation is not yet idempotent,
refer to [ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md)
Amendments A-02.

## Failure Handling

| Condition | Behaviour |
|---|---|
| Missing or invalid signature | `401`/`403`; record `webhook.verification_failure` |
| Duplicate delivery id | `200`; no reprocessing |
| Stale timestamp | `400`; record a security event |
| Oversized payload | `413`; do not parse |
| Unknown installation | `404`; no disclosure |
| Processing failure | Bounded retry, then dead-letter |

## Verification

- Implementation tests (Issues #27, #28) must use signed fixtures, assert
  raw-body verification, reject tampered payloads, and prove deduplication.
- The dead-letter path is exercised and asserted to not duplicate effects.

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-WH-01` to `TM-WH-08`.
- [Tenant isolation](tenant-isolation.md)
- [Security observability](security-observability.md)
- [Open decisions](open-decisions.md)
