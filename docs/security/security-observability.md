# Security Observability

Security-relevant actions produce events that can be detected, investigated, and
alerted on. This document defines the security event taxonomy and the redaction
rules for telemetry. It is subordinate to
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md) and
constrains [Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47) and
the observability work in
[Issue #46](https://github.com/jacksonsr451/EventFlow/issues/46).

Status: Specified (Phase 0). The machine-readable taxonomy is
[`contracts/schemas/security_events.yaml`](../../contracts/schemas/security_events.yaml).

## Controls

- **SO-01** — Security-relevant actions emit a structured security event from the
  taxonomy below.
- **SO-02** — Tokens, secrets, credentials, and full payload bodies are never
  written to logs, traces, metrics, or error messages.
- **SO-03** — Security events are shipped to centralized, access-controlled
  logging.
- **SO-04** — High and critical severity events raise an alert to the on-call or
  security channel.
- **SO-05** — Events carry a correlation id so a request can be traced across the
  client, gateway, and backend without exposing credentials.
- **SO-06** — Approval and security audit records are append-only and
  tamper-evident.
- **SO-07** — Access to security logs is restricted to security maintainers.
- **SO-08** — Security events are retained for a period sufficient for incident
  response, per the retention schedule.
- **SO-09** — Metrics avoid high-cardinality labels such as raw user, workspace,
  or event ids.
- **SO-10** — Security dashboards and alerts are reviewed on a regular cadence.

## Event Taxonomy

| ID | Event type | Trigger | Default severity |
|---|---|---|---|
| SE-01 | `auth.failure` | Failed authentication or token validation | medium |
| SE-02 | `authz.denial` | Authorization or RBAC denial | low |
| SE-03 | `tenant.cross_access_attempt` | Access to another workspace's resource | high |
| SE-04 | `webhook.verification_failure` | A webhook failed signature verification | medium |
| SE-05 | `webhook.replay_detected` | A duplicate or stale webhook delivery | medium |
| SE-06 | `credential.revoked` | A token, session, or integration secret was revoked | medium |
| SE-07 | `attachment.rejected` | An upload was rejected or quarantined | low |
| SE-08 | `security.config_change` | A security-relevant configuration changed | high |
| SE-09 | `data.export` | A bulk data export was performed | high |
| SE-10 | `data.deletion` | Data or an account was deleted | high |

## Event Fields

Each event records: `event_id`, `event_type`, `severity`, `outcome`,
`occurred_at`, `actor` (type and opaque id), optional `workspace_id`, optional
`subject`, optional `correlation_id`, `source`, and a redacted `details` object.
The full contract is in the schema referenced above.

## Redaction Rules

Logs, traces, and metrics must never contain tokens, secrets, or full payloads.
In addition:

- Actor identifiers are opaque ids, never email addresses or access tokens.
- `details` never contains credentials, authorization headers, cookies, request
  bodies, or captured source code.
- Webhook payloads are represented by identifiers and hashes, not bodies
  ([WH-10](webhooks.md)).
- Error messages never include stack traces, SQL, or upstream internal errors.

## Detection Mapping

| Event | Detection use | Alert |
|---|---|---|
| SE-01 | Credential-stuffing or brute force | Threshold alert |
| SE-02 | Permission probing | Trend alert |
| SE-03 | Cross-tenant attack | Immediate alert |
| SE-04 | Forged or misconfigured webhook | Immediate alert |
| SE-05 | Replay attempt | Trend alert |
| SE-06 | Credential compromise response | Informational |
| SE-07 | Malicious upload attempt | Trend alert |
| SE-08 | Unauthorized configuration change | Immediate alert |
| SE-09 | Data exfiltration | Immediate alert |
| SE-10 | Unauthorized deletion | Immediate alert |

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md)
- [Webhooks](webhooks.md)
- [Data governance](data-governance.md)
- [`contracts/schemas/security_events.yaml`](../../contracts/schemas/security_events.yaml)
