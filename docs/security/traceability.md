# Traceability Matrix

This matrix is the authoritative cross-reference from every threat to its risk,
controls, policy, verification, and owning issue, and from every control to its
acceptance criterion. It exists so that a reviewer can identify, at a glance,
which critical controls are still unimplemented.

Status: Specified (Phase 0). No control in this matrix is **Implemented**.

- Threats and controls are defined in [threat-model.md](threat-model.md).
- Risks are defined in [risk-register.md](risk-register.md).
- Control state values are defined in the [risk register legend](risk-register.md#control-state-legend).
- "Verification" names the test or issue that will assert the control; the
  repository contract tests under `tests/security/` assert the parts expressible
  today.

## Threat to Control Traceability

| Threat | Risk | Controls | Owner | Verification |
|---|---|---|---|---|
| TM-OA-01 | R-001 | OA-07, OA-10, SO-01, SO-02 | Issue #10 | tests/security/test_security_contracts.py |
| TM-OA-02 | R-002 | OA-01, OA-04, SO-01 | Issue #10 | tests/security/test_security_contracts.py |
| TM-OA-03 | R-003 | OA-02, SO-01 | Issue #10 | tests/security/test_security_contracts.py |
| TM-OA-04 | R-004 | OA-03, SO-01 | Issue #10 | tests/security/test_security_contracts.py |
| TM-OA-05 | R-005 | OA-05, SO-01 | Issues #27, #28 | tests/security/test_security_contracts.py |
| TM-OA-06 | R-006 | OA-06, OA-09, SO-01, SO-04 | Issue #10 | tests/security/test_security_contracts.py |
| TM-OA-07 | R-007 | OA-07, OA-08, SO-04 | Issues #23, #25 | tests/security/test_security_contracts.py |
| TM-OA-08 | R-008 | OA-10, OA-08, SO-02, SO-01 | Issue #10 | tests/security/test_security_contracts.py |
| TM-SC-01 | R-009 | SC-01, SC-07, SO-01 | Issues #27, #45 | tests/security/test_security_docs.py |
| TM-SC-02 | R-010 | SC-03, SO-01, SO-02 | Issue #24 | tests/security/test_security_docs.py |
| TM-SC-03 | R-011 | SC-04, SC-07, SO-01 | Issues #27, #46 | tests/security/test_security_docs.py |
| TM-SC-04 | R-012 | SC-05, SO-01 | Issues #13, #14 | tests/security/test_security_docs.py |
| TM-SC-05 | R-013 | SC-06, SC-01, SO-01 | Issue #45 | tests/security/test_security_docs.py |
| TM-SC-06 | R-014 | SC-07, TI-03, SO-01 | Issue #47 | tests/security/test_security_contracts.py |
| TM-WH-01 | R-015 | WH-01, WH-02, SO-01 | Issues #27, #28 | tests/security/test_security_docs.py |
| TM-WH-02 | R-016 | WH-05, WH-06, SO-01 | Issues #27, #46 | tests/security/test_security_docs.py |
| TM-WH-03 | R-017 | WH-03, SO-01 | Issues #27, #28 | tests/security/test_security_docs.py |
| TM-WH-04 | R-018 | WH-04, SO-01 | Issues #27, #47 | tests/security/test_security_docs.py |
| TM-WH-05 | R-019 | WH-07, SO-01 | Issues #27, #47 | tests/security/test_security_docs.py |
| TM-WH-06 | R-020 | WH-08, WH-10, SO-04 | Issues #27, #28 | tests/security/test_security_docs.py |
| TM-WH-07 | R-021 | WH-09, WH-05, SO-01 | Issue #46 | tests/security/test_security_docs.py |
| TM-WH-08 | R-022 | WH-10, SO-02 | Issues #27, #28 | tests/security/test_security_docs.py |
| TM-WH-09 | R-048 | WH-11, OA-05, SO-01 | Issues #27, #28 | tests/security/test_security_docs.py |
| TM-AT-01 | R-023 | AT-03, AT-02, SO-01 | Issues #4, #12 | tests/security/test_security_docs.py |
| TM-AT-02 | R-024 | AT-01, AT-02, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-AT-03 | R-025 | AT-07, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-AT-04 | R-026 | TI-04, AT-04, SO-01 | Issue #47 | tests/security/test_security_contracts.py |
| TM-AT-05 | R-027 | AT-05, TI-03, SO-01 | Issue #9 | tests/security/test_security_contracts.py |
| TM-AT-06 | R-028 | AT-06, SO-01 | Issues #14, #22 | tests/security/test_security_docs.py |
| TM-AT-07 | R-029 | AT-02, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-AT-08 | R-030 | AT-09, DG-04, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-MT-01 | R-031 | TI-01, TI-04, SO-01 | Issue #47 | tests/security/test_security_contracts.py |
| TM-MT-02 | R-032 | TI-02, TI-04, SO-01 | Issue #47 | tests/security/test_security_contracts.py |
| TM-MT-03 | R-033 | TI-03, TI-07, SO-01 | Issue #47 | tests/security/test_security_contracts.py |
| TM-MT-04 | R-034 | TI-05, TI-04, SO-01 | Issue #12 | tests/security/test_security_contracts.py |
| TM-MT-05 | R-035 | TI-06, TI-08, SO-01, SO-04 | Issue #9 | tests/security/test_security_contracts.py |
| TM-MT-06 | R-036 | TI-04, DG-06, SO-01 | Issues #31, #47 | tests/security/test_security_contracts.py |
| TM-MT-07 | R-037 | TI-03, SO-02 | Issue #11 | tests/security/test_security_contracts.py |
| TM-MT-08 | R-046 | TI-10, WH-07, TI-02, SO-01, SO-04 | Issues #27, #47 | tests/security/test_security_docs.py |
| TM-MT-09 | R-047 | TI-09, TI-04, SO-01 | Issue #46 | tests/security/test_security_docs.py |
| TM-DG-01 | R-038 | DG-10, DG-02, SO-01 | Issues #24, #35 | tests/security/test_security_docs.py |
| TM-DG-02 | R-039 | DG-03, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-DG-03 | R-040 | DG-04, DG-09, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-DG-04 | R-041 | DG-06, DG-01, SO-01, SO-04 | Issue #9 | tests/security/test_security_docs.py |
| TM-DG-05 | R-042 | DG-01, DG-05, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-DG-06 | R-043 | DG-07, SO-06, SO-04 | Issue #7 | tests/security/test_security_docs.py |
| TM-DG-07 | R-044 | DG-05, DG-09, SO-01 | Issue #12 | tests/security/test_security_docs.py |
| TM-DG-08 | R-045 | DG-08, SO-01 | Issue #36 | tests/security/test_security_docs.py |

## Control Register

Every control listed here is referenced by at least one threat. "State" uses the
[risk register legend](risk-register.md#control-state-legend).

| Control | Policy | State | Acceptance criterion | Verification | Owner |
|---|---|---|---|---|---|
| OA-01 | oauth-and-credentials.md | Specified | Auth flow uses PKCE S256; a flow without a verifier is rejected | Issue #10 tests | Issue #10 |
| OA-02 | oauth-and-credentials.md | Specified | A tampered or absent state is rejected; a valid state passes | Issue #10 tests | Issue #10 |
| OA-03 | oauth-and-credentials.md | Specified | A redirect to an unregistered URI is rejected | Issue #10 tests | Issue #10 |
| OA-04 | oauth-and-credentials.md | Specified | No token appears in a URL; code exchange requires the verifier | tests/security/test_security_contracts.py | Issue #10 |
| OA-05 | oauth-and-credentials.md | Specified (Pending Decision) | Each integration declares a minimal scope set; elevated scopes need consent | Issue #27 review | Issues #27, #28 |
| OA-06 | oauth-and-credentials.md | Specified | Reusing a rotated refresh token invalidates the family and emits credential.revoked | Issue #10 tests | Issue #10 |
| OA-07 | oauth-and-credentials.md | Specified | Web uses HttpOnly cookies; Desktop keychain; VS Code SecretStorage | tests/security/test_security_docs.py | Issues #10, #23, #25 |
| OA-08 | oauth-and-credentials.md | Specified | Credentials are TLS-protected and encrypted at rest | Issue #10 tests | Issue #10 |
| OA-09 | oauth-and-credentials.md | Specified | Logout and revocation invalidate access and refresh tokens | Issue #10 tests | Issue #10 |
| OA-10 | oauth-and-credentials.md | Specified | No token, secret, or code appears in logs, traces, metrics, or errors | tests/security/test_security_docs.py | Issue #10 |
| SC-01 | untrusted-content.md | Specified | A crafted instruction in ingested text does not change system behaviour | tests/security/test_security_docs.py | Issues #27, #45 |
| SC-02 | untrusted-content.md | Specified | Issue, PR, and commit text is handled as data in every pipeline | Issue #27 tests | Issues #27, #28 |
| SC-03 | untrusted-content.md | Specified | A snippet containing a secret is blocked or redacted and emits a security event | Issue #24 tests | Issue #24 |
| SC-04 | untrusted-content.md | Specified | No authoritative state changes without human confirmation | Issue #46 tests | Issue #46 |
| SC-05 | untrusted-content.md | Specified | Stored script content does not execute in the application origin | Issue #14 tests | Issues #13, #14 |
| SC-06 | untrusted-content.md | Specified | Model output is validated before use; input is separated from instructions | Issue #45 tests | Issue #45 |
| SC-07 | untrusted-content.md | Specified | An RBAC check gates every authoritative effect | Issue #9 tests | Issue #9 |
| AT-01 | untrusted-content.md | Specified (Pending Decision) | A file whose content contradicts its declared type is rejected | Issue #12 tests | Issue #12 |
| AT-02 | untrusted-content.md | Specified (Pending Decision) | An upload above the size limit is rejected with 413 | Issue #12 tests | Issue #12 |
| AT-03 | untrusted-content.md | Specified | Malware is quarantined and rejected; attachment.rejected is emitted | Issue #12 tests | Issue #12 |
| AT-04 | untrusted-content.md | Specified | Objects live under a per-tenant prefix with no public path | tests/security/test_security_contracts.py | Issue #47 |
| AT-05 | untrusted-content.md | Specified | A download without membership is denied; links are short-lived | Issue #9 tests | Issue #9 |
| AT-06 | untrusted-content.md | Specified | HTML and SVG attachments are not rendered inline | Issue #14 tests | Issues #14, #22 |
| AT-07 | untrusted-content.md | Specified | A filename with traversal never influences the storage path | Issue #12 tests | Issue #12 |
| AT-08 | untrusted-content.md | Specified | Stored attachments are encrypted at rest | Issue #12 tests | Issue #12 |
| AT-09 | untrusted-content.md | Specified | Deleting an attachment removes object, metadata, and derived data | tests/security/test_security_docs.py | Issue #12 |
| WH-01 | webhooks.md | Specified | A delivery with an invalid or missing signature is rejected before any effect | Issue #27 tests | Issues #27, #28 |
| WH-02 | webhooks.md | Specified | Signature comparison does not leak timing | Issue #27 tests | Issues #27, #28 |
| WH-03 | webhooks.md | Specified | Verification uses raw bytes; a re-serialized payload fails | Issue #27 tests | Issues #27, #28 |
| WH-04 | webhooks.md | Specified | An oversized payload returns 413 before parsing | Issue #27 tests | Issue #27 |
| WH-05 | webhooks.md | Specified | A duplicate delivery id is acknowledged once and not reprocessed | Issue #27 tests | Issues #27, #46 |
| WH-06 | webhooks.md | Specified | A stale timestamp is rejected and webhook.replay_detected is emitted | Issue #27 tests | Issues #27, #28 |
| WH-07 | webhooks.md | Specified | The tenant comes from the installation mapping; a payload tenant is ignored | tests/security/test_security_docs.py | Issues #27, #47 |
| WH-08 | webhooks.md | Specified | Secrets are unique per installation and rotated; old secrets stop verifying | Issue #27 tests | Issues #27, #28 |
| WH-09 | webhooks.md | Specified | Failed deliveries reach a dead-letter path without duplicate effects | Issue #46 tests | Issue #46 |
| WH-10 | webhooks.md | Specified (Pending Decision) | No full payload appears in logs | tests/security/test_security_docs.py | Issues #27, #28 |
| WH-11 | webhooks.md | Specified (Pending Decision) | App permissions are read-only unless an approved justification exists | Issue #27 review | Issues #27, #28 |
| TI-01 | tenant-isolation.md | Specified | A request body cannot alter the effective tenant | tests/security/test_security_contracts.py | Issue #47 |
| TI-02 | tenant-isolation.md | Specified | A non-member using a foreign path workspace_id is denied | Issue #47 tests | Issue #47 |
| TI-03 | tenant-isolation.md | Specified | A cross-tenant access returns 404, never 403 | tests/security/test_security_contracts.py | Issue #47 |
| TI-04 | tenant-isolation.md | Specified | Every query, projection, and export includes the tenant predicate | Issue #47 tests | Issue #12 |
| TI-05 | tenant-isolation.md | Specified | Tenant-data cache keys include the workspace id | Issue #12 tests | Issue #12 |
| TI-06 | tenant-isolation.md | Specified | Only an owner or admin changes roles; roles do not cross workspaces | Issue #9 tests | Issue #9 |
| TI-07 | tenant-isolation.md | Specified | Absence of a grant denies access | Issue #9 tests | Issue #9 |
| TI-08 | tenant-isolation.md | Specified | A cross-tenant attempt emits tenant.cross_access_attempt | Issue #47 tests | Issue #47 |
| TI-09 | tenant-isolation.md | Specified | A job without tenant context fails closed; a payload tenant is ignored | Issue #46 tests | Issue #46 |
| TI-10 | tenant-isolation.md | Specified | A service principal cannot act outside its installation binding | tests/security/test_security_docs.py | Issues #27, #47 |
| DG-01 | data-governance.md | Specified | A new field without an owner and classification is rejected at review | Issue #12 review | Issue #12 |
| DG-02 | data-governance.md | Specified | Each field's use matches its stated purpose | Issue #36 review | Issue #36 |
| DG-03 | data-governance.md | Specified (Pending Decision) | Each category has a retention period and a deletion mechanism | tests/security/test_security_docs.py | Issue #12 |
| DG-04 | data-governance.md | Specified | Deletion propagates to derived data, caches, and indexes | Issue #12 tests | Issue #12 |
| DG-05 | data-governance.md | Specified | Data is TLS-protected and encrypted with externally managed keys | Issue #12 tests | Issue #12 |
| DG-06 | data-governance.md | Specified | Bulk export requires elevated authorization and is audited | Issue #9 tests | Issue #9 |
| DG-07 | data-governance.md | Specified | Access to restricted data and approvals is append-only logged | Issue #7 tests | Issue #7 |
| DG-08 | data-governance.md | Specified (Pending Decision) | A data subject request is fulfilled within the approved window | Issue #36 process | Issue #36 |
| DG-09 | data-governance.md | Specified (Pending Decision) | Backups inherit classification, encryption, region, and deletion rules | Issue #12 tests | Issue #12 |
| DG-10 | data-governance.md | Specified | Source code is removed once the consultation closes per schedule | tests/security/test_security_docs.py | Issues #24, #35 |
| DG-11 | data-governance.md | Specified | Pseudonymization separates identifiers from the data they key | Issue #36 review | Issue #36 |
| SO-01 | security-observability.md | Specified | Each listed action emits the corresponding security event | tests/security/test_security_docs.py | Issue #47 |
| SO-02 | security-observability.md | Specified | Logs, traces, and metrics contain no token, secret, or full payload | tests/security/test_security_docs.py | Issue #47 |
| SO-03 | security-observability.md | Specified (Pending Decision) | Security events reach the approved destination | Issue #47 tests | Issue #47 |
| SO-04 | security-observability.md | Specified | High and critical events alert the on-call channel | Issue #47 tests | Issue #47 |
| SO-05 | security-observability.md | Specified | An event can be correlated with its request via correlation_id | tests/security/test_security_contracts.py | Issue #47 |
| SO-06 | security-observability.md | Specified | Approval and security audit records are append-only and tamper-evident | Issue #7 tests | Issue #7 |
| SO-07 | security-observability.md | Specified | Only security maintainers can read security logs | Issue #47 tests | Issue #47 |
| SO-08 | security-observability.md | Specified (Pending Decision) | Security events are retained for the approved period | Issue #47 tests | Issue #47 |
| SO-09 | security-observability.md | Specified | Metrics avoid raw user, workspace, and event-id labels | Issue #47 tests | Issue #47 |
| SO-10 | security-observability.md | Specified | Dashboards and alerts are reviewed on a documented cadence | Issue #36 process | Issue #36 |
