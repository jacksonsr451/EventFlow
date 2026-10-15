# Open Decisions

The items below require a product or platform owner decision before
implementation. Until each is resolved, the most restrictive behaviour applies.
A decision that changes a system boundary, consistency guarantee, or
infrastructure choice becomes an ADR; the rest are recorded in the owning issue.

Status: Open. Each item names the issue that owns the decision and the criteria
for closing it.

## OD-01 — Identity provider

- **Question:** Which identity provider and OAuth 2.0 / OIDC implementation is
  authoritative for EventFlow?
- **Context:** [oauth-and-credentials.md](oauth-and-credentials.md) requires
  Authorization Code with PKCE regardless of provider.
- **Owner:** [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10).
- **Closure criteria:** provider selected, token format fixed, redirect allowlist
  defined.

## OD-02 — Session and token lifetime

- **Question:** What are the access-token lifetime, refresh-token lifetime, and
  idle timeout?
- **Owner:** [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10).
- **Closure criteria:** values documented and consistent with `OA-06`/`OA-09`.

## OD-03 — Key management

- **Question:** Which key-management service holds encryption keys, and what is
  the rotation policy?
- **Owner:** [Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12).
- **Closure criteria:** KMS selected, rotation policy defined (`DG-05`).

## OD-04 — Malware scanning provider

- **Question:** Which engine scans uploaded attachments, and how are detections
  routed?
- **Owner:** [Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12).
- **Closure criteria:** scanner selected and quarantine flow defined (`AT-03`).

## OD-05 — Attachment allowlist and limits

- **Question:** Which file types are allowed, and what are the size and quota
  limits?
- **Owner:** [Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12).
- **Closure criteria:** allowlist and limits published (`AT-01`, `AT-02`).

## OD-06 — AI provider and data boundary

- **Question:** Which AI provider is used, and are source code or personal data
  ever sent to it?
- **Owner:** [Issue #45](https://github.com/jacksonsr451/EventFlow/issues/45).
- **Closure criteria:** provider and data boundary approved; redaction defined
  (`SC-06`).

## OD-07 — Webhook secret rotation policy

- **Question:** What is the rotation cadence and emergency rotation procedure for
  webhook secrets?
- **Owner:** Issues [#27](https://github.com/jacksonsr451/EventFlow/issues/27),
  [#28](https://github.com/jacksonsr451/EventFlow/issues/28).
- **Closure criteria:** cadence and procedure documented (`WH-08`).

## OD-08 — Break-glass administrative access

- **Question:** Is there an emergency administrator path, who may use it, and how
  is it audited?
- **Owner:** Issues [#9](https://github.com/jacksonsr451/EventFlow/issues/9),
  [#47](https://github.com/jacksonsr451/EventFlow/issues/47).
- **Closure criteria:** path, approvers, and audit defined (`TI-06`).

## OD-09 — Backup region and encryption

- **Question:** In which region are backups stored, and how are they encrypted?
- **Owner:** [Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12).
- **Closure criteria:** region selected, encryption and expiry defined (`DG-09`).

## OD-10 — LGPD legal basis, DPIA, and DPO

- **Question:** What is the legal basis for each personal-data category, and is a
  DPIA required and a DPO appointed?
- **Owner:** [Issue #36](https://github.com/jacksonsr451/EventFlow/issues/36).
- **Closure criteria:** legal basis recorded and DPIA outcome documented
  (`DG-08`).

## OD-11 — Security log retention and SIEM

- **Question:** Which SIEM receives security events, and what is the retention
  period?
- **Owner:** [Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47).
- **Closure criteria:** destination and retention defined (`SO-03`, `SO-08`).

## OD-12 — Final OAuth scopes

- **Question:** What is the exact, minimal scope set for each integration?
- **Owner:** Issues [#27](https://github.com/jacksonsr451/EventFlow/issues/27),
  [#28](https://github.com/jacksonsr451/EventFlow/issues/28).
- **Closure criteria:** scope list per integration published (`OA-05`).

## OD-13 — Multi-factor authentication

- **Question:** Is MFA required, for which roles, and how is it enforced?
- **Owner:** [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10).
- **Closure criteria:** MFA policy defined (`OA-01`, `TI-06`).

## OD-14 — Webhook payload persistence

- **Question:** Is the full webhook payload persisted, or only a hash and the
  required identifiers?
- **Owner:** Issues [#27](https://github.com/jacksonsr451/EventFlow/issues/27),
  [#46](https://github.com/jacksonsr451/EventFlow/issues/46).
- **Closure criteria:** persistence decision recorded (`WH-10`, `DG-03`).

## OD-15 — Rate limiting policy

- **Question:** What rate limits apply to authentication, webhook, attachment,
  and API endpoints?
- **Owner:** [Issue #47](https://github.com/jacksonsr451/EventFlow/issues/47).
- **Closure criteria:** limits published (`WH-04`, `AT-02`).

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md)
- [Risk register](risk-register.md)
