# Threat Model

This document is the STRIDE-based threat model for the EventFlow Work Management
bounded context and its three clients. It is subordinate to
[ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md) and
[ADR-007](../adr/ADR-007-multi-client-monorepo-layout-and-contracts.md), and it
is delivered by [Issue #35](https://github.com/jacksonsr451/EventFlow/issues/35).

Status: Specified (Phase 0). No control below is implemented yet; each is binding
for the issue that owns it.

## Method

Each scenario is classified with STRIDE (Spoofing, Tampering, Repudiation,
Information disclosure, Denial of service, Elevation of privilege). Every
scenario records its preconditions, attack path, impact, likelihood, severity,
preventive and detective controls, residual risk, owner, and verification.

Severity reflects the worst credible impact once the whole workflow is in use;
likelihood reflects a motivated attacker against the specified design. Residual
risk is tracked in the [risk register](risk-register.md).

## Assets

| ID | Asset |
|---|---|
| A-01 | User credentials, access tokens, refresh tokens |
| A-02 | Captured source code, editor context, and code snippets |
| A-03 | Consultations, proposals, work items, and board cards |
| A-04 | Approvals and the audit trail |
| A-05 | Attachments |
| A-06 | Workspace membership and RBAC assignments |
| A-07 | Webhook secrets and integration credentials |
| A-08 | Personal data of users and reporters (LGPD-relevant) |
| A-09 | External references (GitHub/GitLab links) |

## Actors

| ID | Actor |
|---|---|
| U-01 | Authenticated workspace member |
| U-02 | Workspace owner, admin, or approver |
| U-03 | Malicious or curious user of another workspace |
| U-04 | Unauthenticated attacker on the network |
| U-05 | Compromised external integration or OAuth provider |
| U-06 | Insider with partial access |
| S-01 | Backend service identity |
| S-02 | External AI/automation provider (future) |

## Trust Boundaries

- **TB-01 Client boundary** — untrusted user input and client runtime storage.
- **TB-02 Edge/API gateway** — authentication, authorization, validation.
- **TB-03 Work Management domain** — authoritative state.
- **TB-04 Tenant boundary** — workspace isolation.
- **TB-05 External integration boundary** — webhooks and OAuth providers.
- **TB-06 Persistence boundary** — databases, object storage, and backups.

## Authentication and credentials (OA)

#### TM-OA-01 — Insecure token storage in the web client

- **Area:** Authentication and credentials
- **STRIDE:** Information disclosure, Elevation of privilege
- **Preconditions:** A user has authenticated in the Webapp; an XSS or malicious
  extension can run in the browser origin.
- **Attack path:** A stolen access or refresh token is read from a script-readable
  store and replayed from the attacker's host.
- **Impact:** Full account takeover for the token lifetime; access to A-01, A-03,
  A-06.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** OA-07, OA-10
- **Detective controls:** SO-01, SO-02
- **Residual risk:** R-001
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-02 — Authorization code interception without PKCE

- **Area:** Authentication and credentials
- **STRIDE:** Spoofing, Information disclosure
- **Preconditions:** A public native or browser client initiates an authorization
  request; an attacker can observe or intercept the redirect.
- **Attack path:** A captured authorization code is exchanged for tokens because
  no proof key binds the code to the initiating client.
- **Impact:** Token issuance to the attacker; access to A-01.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** OA-01, OA-04
- **Detective controls:** SO-01
- **Residual risk:** R-002
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-03 — Cross-site request forgery in the authentication flow

- **Area:** Authentication and credentials
- **STRIDE:** Spoofing, Tampering
- **Preconditions:** A login flows through a browser redirect and the response is
  not bound to the initiating session.
- **Attack path:** An attacker forces a victim browser to complete an
  authorization response the attacker chose, binding the victim to the attacker's
  account or replaying a chosen code.
- **Impact:** Session confusion and loss of action attribution.
- **Likelihood:** low
- **Severity:** medium
- **Preventive controls:** OA-02
- **Detective controls:** SO-01
- **Residual risk:** R-003
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-04 — Redirect URI manipulation

- **Area:** Authentication and credentials
- **STRIDE:** Spoofing, Information disclosure
- **Preconditions:** The authorization server accepts a loosely matched redirect
  URI or a wildcard subdomain.
- **Attack path:** The attacker registers a look-alike redirect target and
  receives authorization codes or tokens.
- **Impact:** Code and token theft; access to A-01.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** OA-03
- **Detective controls:** SO-01
- **Residual risk:** R-004
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-05 — Over-broad OAuth scopes

- **Area:** Authentication and credentials
- **STRIDE:** Elevation of privilege
- **Preconditions:** A client requests repository or organization scopes it does
  not need for its feature.
- **Attack path:** A stolen token grants access far beyond EventFlow's needs,
  letting an attacker read unrelated repositories.
- **Impact:** Excessive third-party data exposure; amplified blast radius.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** OA-05
- **Detective controls:** SO-01
- **Residual risk:** R-005
- **Owner:** Issues #27, #28
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-06 — Refresh token replay after theft

- **Area:** Authentication and credentials
- **STRIDE:** Spoofing, Information disclosure
- **Preconditions:** A refresh token is stolen and remains valid indefinitely.
- **Attack path:** The attacker silently refreshes access tokens and keeps a
  parallel session alive.
- **Impact:** Long-lived unauthorized access; detection is delayed.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** OA-06, OA-09
- **Detective controls:** SO-01, SO-04
- **Residual risk:** R-006
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-07 — Insecure desktop and VS Code token storage

- **Area:** Authentication and credentials
- **STRIDE:** Information disclosure
- **Preconditions:** A Desktop or VS Code client persists tokens to a plain file
  or an unencrypted store.
- **Attack path:** Malware or another local user reads the token from disk.
- **Impact:** Account takeover on the affected workstation; A-01, A-02 exposure.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** OA-07, OA-08
- **Detective controls:** SO-04
- **Residual risk:** R-007
- **Owner:** Issues #23, #25
- **Verification:** tests/security/test_security_contracts.py

#### TM-OA-08 — Credential leakage through URLs, logs, or telemetry

- **Area:** Authentication and credentials
- **STRIDE:** Information disclosure
- **Preconditions:** A token, code, or secret is placed in a query string, log
  line, trace attribute, or crash report.
- **Attack path:** Anyone with access to logs, proxies, or telemetry reads the
  credential and replays it.
- **Impact:** Credential compromise from an otherwise protected channel.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** OA-10, OA-08
- **Detective controls:** SO-02, SO-01
- **Residual risk:** R-008
- **Owner:** Issue #10
- **Verification:** tests/security/test_security_contracts.py

## Untrusted source content (SC)

#### TM-SC-01 — Prompt injection via issue, PR, or commit text

- **Area:** Untrusted source content
- **STRIDE:** Tampering, Elevation of privilege
- **Preconditions:** External issue, PR, commit, or ticket text is ingested into a
  consultation or an AI-assisted flow.
- **Attack path:** An attacker embeds instructions in the content hoping the
  system treats them as commands rather than data.
- **Impact:** Unauthorized actions, data exfiltration, or corrupted triage.
- **Likelihood:** high
- **Severity:** high
- **Preventive controls:** SC-01, SC-07
- **Detective controls:** SO-01
- **Residual risk:** R-009
- **Owner:** Issues #27, #45
- **Verification:** tests/security/test_security_docs.py

#### TM-SC-02 — Secrets embedded in captured source snippets

- **Area:** Untrusted source content
- **STRIDE:** Information disclosure
- **Preconditions:** A developer attaches a code selection that contains an API
  key, token, or password.
- **Attack path:** The secret is stored as part of the consultation and later read
  by anyone with workspace access.
- **Impact:** Leakage of A-02 and third-party credentials.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** SC-03
- **Detective controls:** SO-01, SO-02
- **Residual risk:** R-010
- **Owner:** Issue #24
- **Verification:** tests/security/test_security_docs.py

#### TM-SC-03 — Untrusted content triggering automatic actions

- **Area:** Untrusted source content
- **STRIDE:** Tampering, Elevation of privilege
- **Preconditions:** An integration automatically creates work items, comments, or
  state changes from external content without human confirmation.
- **Attack path:** A crafted issue body causes the system to take an action the
  attacker is not authorized to perform directly.
- **Impact:** Unauthorized state change and audit ambiguity.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** SC-04, SC-07
- **Detective controls:** SO-01
- **Residual risk:** R-011
- **Owner:** Issues #27, #46
- **Verification:** tests/security/test_security_docs.py

#### TM-SC-04 — Stored cross-site scripting from rendered content

- **Area:** Untrusted source content
- **STRIDE:** Tampering, Information disclosure
- **Preconditions:** External or user content is rendered as HTML without output
  encoding.
- **Attack path:** A script stored in a title, description, or comment executes in
  a victim's session.
- **Impact:** Session theft and action forgery in the victim's workspace.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** SC-05
- **Detective controls:** SO-01
- **Residual risk:** R-012
- **Owner:** Issues #13, #14
- **Verification:** tests/security/test_security_docs.py

#### TM-SC-05 — Data poisoning of AI-assisted triage

- **Area:** Untrusted source content
- **STRIDE:** Tampering
- **Preconditions:** An AI assistance feature learns from or is prompted by
  untrusted external content.
- **Attack path:** An attacker biases classification or proposals with crafted
  content.
- **Impact:** Degraded decisions and misallocated work; reputational harm.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** SC-06, SC-01
- **Detective controls:** SO-01
- **Residual risk:** R-013
- **Owner:** Issue #45
- **Verification:** tests/security/test_security_docs.py

#### TM-SC-06 — Repository content used to enumerate other tenants

- **Area:** Untrusted source content
- **STRIDE:** Information disclosure
- **Preconditions:** Repository or issue content references identifiers that are
  resolved without a tenant check.
- **Attack path:** An attacker supplies another workspace's identifier inside
  content to confirm existence or retrieve data.
- **Impact:** Cross-tenant information disclosure.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** SC-07, TI-03
- **Detective controls:** SO-01
- **Residual risk:** R-014
- **Owner:** Issue #47
- **Verification:** tests/security/test_security_contracts.py

## Webhooks and integrations (WH)

#### TM-WH-01 — Forged webhook without a valid signature

- **Area:** Webhooks and integrations
- **STRIDE:** Spoofing, Tampering
- **Preconditions:** A webhook endpoint is reachable and a verification secret is
  configured.
- **Attack path:** An attacker posts a crafted payload and relies on missing or
  broken signature verification.
- **Impact:** Fabricated consultations or state changes.
- **Likelihood:** high
- **Severity:** high
- **Preventive controls:** WH-01, WH-02
- **Detective controls:** SO-01
- **Residual risk:** R-015
- **Owner:** Issues #27, #28
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-02 — Replayed webhook delivery

- **Area:** Webhooks and integrations
- **STRIDE:** Tampering, Repudiation
- **Preconditions:** A previously valid delivery is captured and re-sent.
- **Attack path:** The system processes the same delivery more than once without
  deduplication or a freshness window.
- **Impact:** Duplicate work and inconsistent audit.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** WH-05, WH-06
- **Detective controls:** SO-01
- **Residual risk:** R-016
- **Owner:** Issues #27, #46
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-03 — Signature computed over parsed rather than raw body

- **Area:** Webhooks and integrations
- **STRIDE:** Tampering
- **Preconditions:** The endpoint re-serializes the payload before verifying.
- **Attack path:** Parser differences let an attacker alter fields between the
  signature check and the parsed value.
- **Impact:** Signature bypass; forged effect with a valid-looking signature.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** WH-03
- **Detective controls:** SO-01
- **Residual risk:** R-017
- **Owner:** Issues #27, #28
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-04 — Oversized or malformed webhook payload

- **Area:** Webhooks and integrations
- **STRIDE:** Denial of service
- **Preconditions:** The endpoint accepts unbounded request bodies.
- **Attack path:** A large or deeply nested payload exhausts memory or CPU.
- **Impact:** Availability loss for the integration path.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** WH-04
- **Detective controls:** SO-01
- **Residual risk:** R-018
- **Owner:** Issues #27, #47
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-05 — Webhook routed to the wrong tenant

- **Area:** Webhooks and integrations
- **STRIDE:** Tampering, Information disclosure
- **Preconditions:** The tenant is derived from a payload field rather than from a
  verified installation mapping.
- **Attack path:** An attacker supplies a foreign installation or workspace
  identifier so the event is applied to another tenant.
- **Impact:** Cross-tenant data corruption and disclosure.
- **Likelihood:** medium
- **Severity:** critical
- **Preventive controls:** WH-07
- **Detective controls:** SO-01
- **Residual risk:** R-019
- **Owner:** Issues #27, #47
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-06 — Compromised webhook secret

- **Area:** Webhooks and integrations
- **STRIDE:** Spoofing
- **Preconditions:** A webhook secret is static, widely shared, or stored in
  plaintext.
- **Attack path:** A leaked secret enables undetectable forged deliveries.
- **Impact:** Full integrity loss for the webhook channel.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** WH-08, WH-10
- **Detective controls:** SO-04
- **Residual risk:** R-020
- **Owner:** Issues #27, #28
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-07 — Blind retry and duplicate downstream effects

- **Area:** Webhooks and integrations
- **STRIDE:** Repudiation
- **Preconditions:** Failed deliveries are retried without deduplication or a
  dead-letter path.
- **Attack path:** Retries create repeated consultations or repeated outbox
  events.
- **Impact:** Duplicate work and unreliable audit.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** WH-09, WH-05
- **Detective controls:** SO-01
- **Residual risk:** R-021
- **Owner:** Issue #46
- **Verification:** tests/security/test_security_docs.py

#### TM-WH-08 — Sensitive payload data written to logs

- **Area:** Webhooks and integrations
- **STRIDE:** Information disclosure
- **Preconditions:** Full webhook payloads are logged for debugging.
- **Attack path:** Payloads containing private repository data are read from logs.
- **Impact:** Disclosure of A-02 and third-party metadata.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** WH-10
- **Detective controls:** SO-02
- **Residual risk:** R-022
- **Owner:** Issues #27, #28
- **Verification:** tests/security/test_security_docs.py

## Attachments (AT)

#### TM-AT-01 — Upload of a malicious attachment

- **Area:** Attachments
- **STRIDE:** Tampering, Elevation of privilege
- **Preconditions:** Attachments can be uploaded and later downloaded by a user.
- **Attack path:** An attacker uploads a file carrying malware that a victim
  opens.
- **Impact:** Endpoint compromise of the victim; reputational harm.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** AT-03, AT-02
- **Detective controls:** SO-01
- **Residual risk:** R-023
- **Owner:** Issues #4, #12
- **Verification:** tests/security/test_security_docs.py

#### TM-AT-02 — Disallowed or disguised file type

- **Area:** Attachments
- **STRIDE:** Tampering
- **Preconditions:** File type is determined from the extension or client-supplied
  content type only.
- **Attack path:** A polyglot or renamed file bypasses type restrictions.
- **Impact:** Bypass of downstream handling assumptions.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** AT-01, AT-02
- **Detective controls:** SO-01
- **Residual risk:** R-024
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-AT-03 — Path traversal through a crafted filename

- **Area:** Attachments
- **STRIDE:** Tampering
- **Preconditions:** The stored object key is derived from the client filename.
- **Attack path:** A filename containing `../` writes outside the intended
  per-tenant prefix.
- **Impact:** Overwrite or exposure of other objects.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** AT-07
- **Detective controls:** SO-01
- **Residual risk:** R-025
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-AT-04 — Cross-tenant attachment access

- **Area:** Attachments
- **STRIDE:** Information disclosure
- **Preconditions:** Attachment retrieval resolves a blob id without checking the
  caller's workspace.
- **Attack path:** A guessed or leaked blob id returns another tenant's file.
- **Impact:** Cross-tenant data disclosure of A-05.
- **Likelihood:** medium
- **Severity:** critical
- **Preventive controls:** TI-04, AT-04
- **Detective controls:** SO-01
- **Residual risk:** R-026
- **Owner:** Issue #47
- **Verification:** tests/security/test_security_contracts.py

#### TM-AT-05 — Unauthorized attachment download

- **Area:** Attachments
- **STRIDE:** Elevation of privilege, Information disclosure
- **Preconditions:** Download links are public or long-lived.
- **Attack path:** A leaked link is used by an actor without membership.
- **Impact:** Disclosure of A-05.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** AT-05, TI-03
- **Detective controls:** SO-01
- **Residual risk:** R-027
- **Owner:** Issue #9
- **Verification:** tests/security/test_security_contracts.py

#### TM-AT-06 — Script execution via inline HTML or SVG

- **Area:** Attachments
- **STRIDE:** Tampering, Information disclosure
- **Preconditions:** Attachments are rendered inline in the application origin.
- **Attack path:** An SVG or HTML attachment executes script in the app context.
- **Impact:** Session theft and action forgery.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** AT-06
- **Detective controls:** SO-01
- **Residual risk:** R-028
- **Owner:** Issues #14, #22
- **Verification:** tests/security/test_security_docs.py

#### TM-AT-07 — Denial of service through large uploads

- **Area:** Attachments
- **STRIDE:** Denial of service
- **Preconditions:** Upload size and rate are unbounded.
- **Attack path:** Repeated large uploads exhaust storage or bandwidth.
- **Impact:** Availability and cost impact.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** AT-02
- **Detective controls:** SO-01
- **Residual risk:** R-029
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-AT-08 — Attachment persistence after deletion request

- **Area:** Attachments
- **STRIDE:** Information disclosure
- **Preconditions:** Deletion removes metadata but not the stored object or its
  backups.
- **Attack path:** A deleted attachment remains retrievable.
- **Impact:** Failure to honor deletion; regulatory exposure.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** AT-09, DG-04
- **Detective controls:** SO-01
- **Residual risk:** R-030
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

## Multi-tenant isolation (MT)

#### TM-MT-01 — Insecure direct object reference across workspaces

- **Area:** Multi-tenant isolation
- **STRIDE:** Information disclosure, Elevation of privilege
- **Preconditions:** An endpoint fetches an object by id without a tenant filter.
- **Attack path:** A user substitutes another workspace's object id and reads it.
- **Impact:** Cross-tenant disclosure of A-03 and A-04.
- **Likelihood:** high
- **Severity:** critical
- **Preventive controls:** TI-01, TI-04
- **Detective controls:** SO-01
- **Residual risk:** R-031
- **Owner:** Issue #47
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-02 — Cross-tenant write through a foreign workspace_id

- **Area:** Multi-tenant isolation
- **STRIDE:** Tampering
- **Preconditions:** The backend trusts a client-supplied `workspace_id` in the
  path or body.
- **Attack path:** A user posts to a workspace they do not belong to.
- **Impact:** Corruption of another tenant's state.
- **Likelihood:** high
- **Severity:** critical
- **Preventive controls:** TI-02, TI-04
- **Detective controls:** SO-01
- **Residual risk:** R-032
- **Owner:** Issue #47
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-03 — Resource discovery through enumerable identifiers

- **Area:** Multi-tenant isolation
- **STRIDE:** Information disclosure
- **Preconditions:** Unauthorized access returns a distinguishable 403 versus 404.
- **Attack path:** An attacker enumerates ids to learn which resources exist.
- **Impact:** Confirmation of other tenants' resources.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** TI-03, TI-07
- **Detective controls:** SO-01
- **Residual risk:** R-033
- **Owner:** Issue #47
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-04 — Shared cache or connection leakage between tenants

- **Area:** Multi-tenant isolation
- **STRIDE:** Information disclosure
- **Preconditions:** A shared cache key omits the tenant, or a connection reuses
  session state.
- **Attack path:** A cached response for one tenant is served to another.
- **Impact:** Cross-tenant data disclosure.
- **Likelihood:** low
- **Severity:** critical
- **Preventive controls:** TI-05, TI-04
- **Detective controls:** SO-01
- **Residual risk:** R-034
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-05 — Workspace membership escalation

- **Area:** Multi-tenant isolation
- **STRIDE:** Elevation of privilege
- **Preconditions:** Role assignment can be changed without an owner/admin check.
- **Attack path:** A member grants themselves an approver or admin role.
- **Impact:** Unauthorized approvals and governance bypass.
- **Likelihood:** medium
- **Severity:** critical
- **Preventive controls:** TI-06, TI-08
- **Detective controls:** SO-01, SO-04
- **Residual risk:** R-035
- **Owner:** Issue #9
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-06 — Missing tenant filter in a projection or export

- **Area:** Multi-tenant isolation
- **STRIDE:** Information disclosure
- **Preconditions:** A reporting, search, or export path queries without a tenant
  predicate.
- **Attack path:** A bulk read returns rows from multiple workspaces.
- **Impact:** Large-scale cross-tenant disclosure.
- **Likelihood:** low
- **Severity:** critical
- **Preventive controls:** TI-04, DG-06
- **Detective controls:** SO-01
- **Residual risk:** R-036
- **Owner:** Issues #31, #47
- **Verification:** tests/security/test_security_contracts.py

#### TM-MT-07 — Error messages disclosing another tenant's existence

- **Area:** Multi-tenant isolation
- **STRIDE:** Information disclosure
- **Preconditions:** Errors include resource owner or upstream identifiers.
- **Attack path:** An attacker reads owner identifiers from error bodies.
- **Impact:** Targeted follow-up attacks against a known tenant.
- **Likelihood:** medium
- **Severity:** low
- **Preventive controls:** TI-03
- **Detective controls:** SO-02
- **Residual risk:** R-037
- **Owner:** Issue #11
- **Verification:** tests/security/test_security_contracts.py

## Data governance (DG)

#### TM-DG-01 — Excessive source code retention

- **Area:** Data governance
- **STRIDE:** Information disclosure
- **Preconditions:** Captured code snippets are stored indefinitely with the
  consultation.
- **Attack path:** Historical snippets accumulate sensitive code that later leaks.
- **Impact:** Long-tail disclosure of A-02.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** DG-10, DG-02
- **Detective controls:** SO-01
- **Residual risk:** R-038
- **Owner:** Issues #24, #35
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-02 — Indefinite retention without a schedule

- **Area:** Data governance
- **STRIDE:** Information disclosure
- **Preconditions:** No retention period is defined for a data category.
- **Attack path:** Data is kept forever because nothing deletes it.
- **Impact:** Growing regulatory and breach exposure.
- **Likelihood:** high
- **Severity:** medium
- **Preventive controls:** DG-03
- **Detective controls:** SO-01
- **Residual risk:** R-039
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-03 — Incomplete deletion across backups and derived data

- **Area:** Data governance
- **STRIDE:** Information disclosure
- **Preconditions:** Deletion removes the primary row but not backups, caches, or
  derived records.
- **Attack path:** Deleted personal data resurfaces from a backup or projection.
- **Impact:** Failure to honor erasure; regulatory exposure.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** DG-04, DG-09
- **Detective controls:** SO-01
- **Residual risk:** R-040
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-04 — Unauthorized bulk data export

- **Area:** Data governance
- **STRIDE:** Information disclosure, Elevation of privilege
- **Preconditions:** Export can be triggered without elevated authorization or
  logging.
- **Attack path:** An insider or compromised account exfiltrates workspace data.
- **Impact:** Large-scale disclosure of A-03, A-08.
- **Likelihood:** low
- **Severity:** high
- **Preventive controls:** DG-06, DG-01
- **Detective controls:** SO-01, SO-04
- **Residual risk:** R-041
- **Owner:** Issue #9
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-05 — Unclassified data exposure

- **Area:** Data governance
- **STRIDE:** Information disclosure
- **Preconditions:** A new data element is added without a classification.
- **Attack path:** Sensitive data is treated as internal and stored or shared
  weakly.
- **Impact:** Inconsistent protection of A-08.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** DG-01, DG-05
- **Detective controls:** SO-01
- **Residual risk:** R-042
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-06 — Missing audit trail for approvals and security events

- **Area:** Data governance
- **STRIDE:** Repudiation
- **Preconditions:** An approval or security-relevant action is not recorded in a
  tamper-evident log.
- **Attack path:** An actor denies performing an action that has no durable
  record.
- **Impact:** Loss of accountability for A-04.
- **Likelihood:** medium
- **Severity:** high
- **Preventive controls:** DG-07, SO-06
- **Detective controls:** SO-04
- **Residual risk:** R-043
- **Owner:** Issue #7
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-07 — Backup or replica outside the approved region

- **Area:** Data governance
- **STRIDE:** Information disclosure
- **Preconditions:** Backups or replicas are created in an unapproved location.
- **Attack path:** Data is stored outside the jurisdiction or security boundary
  the tenant expects.
- **Impact:** Compliance violation and unexpected exposure of A-08.
- **Likelihood:** low
- **Severity:** medium
- **Preventive controls:** DG-05, DG-09
- **Detective controls:** SO-01
- **Residual risk:** R-044
- **Owner:** Issue #12
- **Verification:** tests/security/test_security_docs.py

#### TM-DG-08 — Data subject access request not fulfilled

- **Area:** Data governance
- **STRIDE:** Repudiation
- **Preconditions:** No process maps a data subject to their stored data.
- **Attack path:** A lawful request cannot be answered within the required
  window.
- **Impact:** Regulatory penalty and loss of trust.
- **Likelihood:** medium
- **Severity:** medium
- **Preventive controls:** DG-08
- **Detective controls:** SO-01
- **Residual risk:** R-045
- **Owner:** Issue #36
- **Verification:** tests/security/test_security_docs.py

## Related Documents

- [Security index](README.md)
- [Risk register](risk-register.md)
- [Tenant isolation](tenant-isolation.md)
- [OAuth and credentials](oauth-and-credentials.md)
- [Webhooks](webhooks.md)
- [Untrusted content](untrusted-content.md)
- [Data governance](data-governance.md)
- [Security observability](security-observability.md)
