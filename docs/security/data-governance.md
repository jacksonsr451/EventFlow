# Data Governance

This document classifies the data EventFlow handles, states the purpose and
access rules for each category, and defines retention, deletion, export, and data
subject rights. It is subordinate to
[ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md) and constrains
[Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12) and
[Issue #36](https://github.com/jacksonsr451/EventFlow/issues/36).

Status: Specified (Phase 0). Concrete retention periods and the storage region
are open decisions ([open-decisions.md](open-decisions.md)).

## Classification

| Level | Meaning | Handling |
|---|---|---|
| Public | Published documentation and marketing | No restriction |
| Internal | Non-sensitive operational data | Authenticated staff only |
| Confidential | Workspace business content | Member-scoped access, encrypted |
| Restricted | Credentials, secrets, source code, personal data | Strict need-to-know, encrypted, audited |

## Data Categories

| Category | Examples | Classification | Purpose | Access | Encrypted | Retention | Owner |
|---|---|---|---|---|---|---|---|
| Account and profile | User id, email, display name | Confidential | Authentication and attribution | Self, workspace admins | Yes | Until account deletion | Issue #10 |
| Credentials and tokens | Access/refresh tokens, OAuth secrets | Restricted | Session and integration auth | Backend service only | Yes | Token lifetime; revoke immediately | Issue #10 |
| Workspace content | Consultations, proposals, work items, board cards | Confidential | Core product function | Workspace members by RBAC | Yes | Per schedule below | Issue #12 |
| Approvals and audit | Approval records, audit hashes | Restricted | Accountability and tamper evidence | Auditors, admins | Yes | Extended, see below | Issue #7 |
| Captured code and editor context | Snippets, file path, commit, line range | Restricted | Consultation context | Workspace members by RBAC | Yes | Minimized, see below | Issue #24 |
| Attachments | Uploaded files | Confidential | Supporting evidence | Workspace members by RBAC | Yes | Per schedule below | Issue #12 |
| Webhook payloads | Provider delivery bodies | Confidential | Integration processing | Service principal only | Yes | Minimal, hash preferred | Issues #27, #28 |
| Security events | Auth failures, denials, cross-tenant attempts | Confidential | Detection and response | Security maintainers | Yes | Per schedule below | Issue #47 |
| Personal data | Reporter identity, contact details | Restricted | Product function and support | Need-to-know | Yes | Per schedule below | Issue #36 |

## Controls

- **DG-01** — Every data element has an owner and a classification; a new element
  without one may not be persisted.
- **DG-02** — Data is collected and used only for a stated purpose; repurposing
  requires a new decision.
- **DG-03** — Every category has a defined retention period; data whose period is
  undefined defaults to the most restrictive handling until a decision is made.
- **DG-04** — Deletion removes the primary record and propagates to derived data,
  caches, search indexes, and object storage.
- **DG-05** — Data is encrypted in transit and at rest, using keys managed outside
  the application.
- **DG-06** — Access to each category is least-privilege and role-based; bulk
  export requires elevated authorization and is audited.
- **DG-07** — Access to confidential and restricted data, and every approval, is
  recorded in an append-only audit log.
- **DG-08** — Data subject access, correction, and erasure requests (LGPD) are
  fulfilled within the legally required window through a documented process.
- **DG-09** — Backups and replicas inherit the classification, encryption, region,
  and deletion rules of the primary data.
- **DG-10** — Captured source code is kept only as long as needed to resolve the
  consultation, and never beyond the retention schedule.
- **DG-11** — Where the purpose permits, data is anonymized or pseudonymized so
  that it can no longer identify a data subject; identifiers used for
  pseudonymization are stored separately and protected as restricted data.

## Retention Schedule

The periods below are **PENDING DECISION** until a product owner and a legal
reviewer approve them. The approval criteria are: a stated purpose, a legal
basis, a maximum period, and a deletion mechanism. This document does not assert
a legal basis or a statutory period; whether each category rests on consent, a
contract, a legitimate interest, or a legal obligation requires legal validation
([OD-10](open-decisions.md)).

| Category | Proposed period | Status |
|---|---|---|
| Account and profile | Life of account plus a bounded grace period | PENDING DECISION |
| Credentials and tokens | Token lifetime; revoked on logout | Defined by `OA-09` |
| Workspace content | Life of workspace plus a bounded archive window | PENDING DECISION |
| Approvals and audit | Extended, evidence-driven period | PENDING DECISION |
| Captured code and editor context | Minimized; deletion once the consultation closes | PENDING DECISION |
| Attachments | Life of the consultation plus a bounded window | PENDING DECISION |
| Webhook payloads | Store a hash, not the body, where possible | PENDING DECISION |
| Security events | A period sufficient for incident response | PENDING DECISION |
| Personal data | Per the request or the account lifecycle | PENDING DECISION |
| Backups | Bounded rotation aligned to the longest category | PENDING DECISION |

## Deletion and Legal Hold

Deletion is distinguished from archival:

- **Logical deletion** removes the record from active use and is reversible during
  the grace period.
- **Physical deletion** removes the record and its derived data permanently.
- **Backup expiry** is the point at which a deleted record can no longer be
  restored from backup.
- **Legal hold** suspends deletion for records relevant to an investigation or
  legal proceeding; holds are explicit, scoped, and time-bounded.

A deletion request is only "fulfilled" when the primary record, derived data, and
search indexes are removed and backups have expired under the retention policy.

## Exports and Data Subject Rights

- Bulk export is an audited, privileged operation (`DG-06`).
- Data subject requests are logged and answered within the statutory window
  (`DG-08`).
- Export and deletion produce security events (`data.export`, `data.deletion`);
  see [security-observability.md](security-observability.md).

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-DG-01` to `TM-DG-08`.
- [Untrusted content](untrusted-content.md)
- [Open decisions](open-decisions.md)
- [Security observability](security-observability.md)
