# Risk Register

The risk register records the residual risk that remains after the preventive and
detective controls in the [threat model](threat-model.md) are applied. Every risk
maps to exactly one threat scenario and to the issue that owns its implementation.
Threat-to-control traceability is in [traceability.md](traceability.md).

## Control State Legend

| State | Meaning |
|---|---|
| Implemented | Control exists in code and is verifiable today |
| Partially Implemented | A runtime foundation exists, but one or more owned client/deployment controls remain |
| Specified | Control is defined here but not implemented |
| Planned | Implementation is identified and scheduled |
| Pending Decision | Behaviour is not yet approved (see [open-decisions.md](open-decisions.md)) |

Authentication controls owned by Issue #10 have backend implementation status
recorded per row. Controls for absent Web/Desktop/VS Code runtimes and all other
issues remain **Specified**; rows whose parameters still depend on an open
decision are marked **Specified (Pending Decision)**. Documentation alone is
never counted as an implemented security control.

## Register

| Risk ID | Area | Threat | Impact | Likelihood | Severity | Mitigation state | Owner | Controls | Verification |
|---|---|---|---|---|---|---|---|---|---|
| R-001 | Authentication | TM-OA-01 | Account takeover from a stolen web token | medium | high | Partially Implemented | Issue #10 | OA-07, OA-10 | services/work-management/tests/test_authentication_unit.py |
| R-002 | Authentication | TM-OA-02 | Token issuance to an attacker intercepting a code | medium | high | Implemented | Issue #10 | OA-01, OA-04 | services/work-management/tests/test_authentication_keycloak_integration.py |
| R-003 | Authentication | TM-OA-03 | Session confusion from a forged authorization response | low | medium | Implemented | Issue #10 | OA-02 | services/work-management/tests/test_authentication_keycloak_integration.py |
| R-004 | Authentication | TM-OA-04 | Code or token theft through a manipulated redirect | low | high | Implemented | Issue #10 | OA-03 | services/work-management/tests/test_authentication_unit.py |
| R-005 | Authentication | TM-OA-05 | Third-party data exposure through over-broad scopes | medium | high | Specified (Pending Decision) | Issues #27, #28 | OA-05 | tests/security/test_security_contracts.py |
| R-006 | Authentication | TM-OA-06 | Long-lived unauthorized access via refresh replay | low | high | Implemented | Issue #10 | OA-06, OA-09 | services/work-management/tests/test_authentication_keycloak_integration.py |
| R-007 | Authentication | TM-OA-07 | Workstation account takeover from plaintext token storage | medium | medium | Partially Implemented | Issues #23, #25 | OA-07, OA-08 | packages/auth/tests/auth.test.mjs |
| R-008 | Authentication | TM-OA-08 | Credential compromise through URLs, logs, or telemetry | medium | high | Implemented | Issue #10 | OA-10, OA-08 | services/work-management/tests/test_authentication_unit.py |
| R-009 | Untrusted content | TM-SC-01 | Unauthorized actions driven by injected instructions | high | high | Specified | Issues #27, #45 | SC-01, SC-07 | tests/security/test_security_docs.py |
| R-010 | Untrusted content | TM-SC-02 | Third-party credential leakage in captured snippets | medium | high | Specified | Issue #24 | SC-03 | tests/security/test_security_docs.py |
| R-011 | Untrusted content | TM-SC-03 | Unauthorized state change triggered by external content | medium | high | Specified | Issues #27, #46 | SC-04, SC-07 | tests/security/test_security_docs.py; services/work-management/tests/test_proposal_api_integration.py |
| R-012 | Untrusted content | TM-SC-04 | Session theft through stored cross-site scripting | medium | high | Specified | Issues #13, #14 | SC-05 | tests/security/test_security_docs.py |
| R-013 | Untrusted content | TM-SC-05 | Degraded decisions from poisoned AI inputs | medium | medium | Specified | Issue #45 | SC-06, SC-01 | tests/security/test_security_docs.py |
| R-014 | Untrusted content | TM-SC-06 | Cross-tenant disclosure through resolved content | low | high | Specified | Issue #47 | SC-07, TI-03 | tests/security/test_security_contracts.py |
| R-015 | Webhooks | TM-WH-01 | Fabricated consultations from forged deliveries | high | high | Specified | Issues #27, #28 | WH-01, WH-02 | tests/security/test_security_docs.py |
| R-016 | Webhooks | TM-WH-02 | Duplicate work from replayed deliveries | medium | medium | Specified | Issues #27, #46 | WH-05, WH-06 | tests/security/test_security_docs.py |
| R-017 | Webhooks | TM-WH-03 | Signature bypass over a re-serialized payload | low | high | Specified | Issues #27, #28 | WH-03 | tests/security/test_security_docs.py |
| R-018 | Webhooks | TM-WH-04 | Availability loss from oversized payloads | medium | medium | Specified | Issues #27, #47 | WH-04 | tests/security/test_security_docs.py |
| R-019 | Webhooks | TM-WH-05 | Cross-tenant corruption from misrouted deliveries | medium | critical | Specified | Issues #27, #47 | WH-07 | tests/security/test_security_docs.py |
| R-020 | Webhooks | TM-WH-06 | Undetectable forgeries after secret compromise | low | high | Specified | Issues #27, #28 | WH-08, WH-10 | tests/security/test_security_docs.py |
| R-021 | Webhooks | TM-WH-07 | Duplicate effects from blind retries | medium | medium | Specified | Issue #46 | WH-09, WH-05 | tests/security/test_security_docs.py |
| R-022 | Webhooks | TM-WH-08 | Repository data disclosure through logged payloads | medium | medium | Specified (Pending Decision) | Issues #27, #28 | WH-10 | tests/security/test_security_docs.py |
| R-023 | Attachments | TM-AT-01 | Endpoint compromise from a malicious attachment | medium | high | Implemented | Issues #4, #12 | AT-03, AT-02 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-024 | Attachments | TM-AT-02 | Control bypass through a disguised file type | medium | medium | Implemented | Issue #4 | AT-01, AT-02 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-025 | Attachments | TM-AT-03 | Object overwrite or exposure via path traversal | low | high | Implemented | Issue #4 | AT-07 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-026 | Attachments | TM-AT-04 | Cross-tenant attachment disclosure | medium | critical | Partially Implemented | Issues #4, #47 | TI-04, AT-04 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-027 | Attachments | TM-AT-05 | Unauthorized download through a leaked link | medium | high | Implemented | Issues #4, #9 | AT-05, TI-03 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-028 | Attachments | TM-AT-06 | Script execution from inline HTML or SVG | medium | high | Implemented | Issues #4, #14, #22 | AT-06 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-029 | Attachments | TM-AT-07 | Availability and cost impact from large uploads | medium | medium | Implemented | Issue #4 | AT-02 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-030 | Attachments | TM-AT-08 | Deleted attachments remaining retrievable | medium | medium | Implemented | Issues #4, #12 | AT-09, DG-04 | services/work-management/tests/test_consultation_attachment_integration.py |
| R-031 | Tenant isolation | TM-MT-01 | Cross-tenant read via insecure direct object reference | high | critical | Specified | Issue #47 | TI-01, TI-04 | tests/security/test_security_contracts.py |
| R-032 | Tenant isolation | TM-MT-02 | Cross-tenant write through a foreign workspace_id | high | critical | Specified | Issue #47 | TI-02, TI-04 | tests/security/test_security_contracts.py |
| R-033 | Tenant isolation | TM-MT-03 | Resource discovery through enumerable identifiers | medium | medium | Specified | Issue #47 | TI-03, TI-07 | tests/security/test_security_contracts.py |
| R-034 | Tenant isolation | TM-MT-04 | Cross-tenant disclosure from shared caches | low | critical | Specified | Issue #12 | TI-05, TI-04 | tests/security/test_security_contracts.py |
| R-035 | Tenant isolation | TM-MT-05 | Privilege escalation through membership changes | medium | critical | Specified | Issue #9 | TI-06, TI-08 | tests/security/test_security_contracts.py |
| R-036 | Tenant isolation | TM-MT-06 | Large-scale disclosure from an unfiltered export | low | critical | Specified | Issues #31, #47 | TI-04, DG-06 | tests/security/test_security_contracts.py |
| R-037 | Tenant isolation | TM-MT-07 | Tenant discovery through verbose errors | medium | low | Specified | Issue #11 | TI-03 | tests/security/test_security_contracts.py |
| R-038 | Data governance | TM-DG-01 | Disclosure of historic captured source code | medium | medium | Specified (Pending Decision) | Issues #24, #35 | DG-10, DG-02 | tests/security/test_security_docs.py |
| R-039 | Data governance | TM-DG-02 | Growing breach and regulatory exposure from indefinite retention | high | medium | Specified (Pending Decision) | Issue #12 | DG-03 | tests/security/test_security_docs.py |
| R-040 | Data governance | TM-DG-03 | Erasure failure from backups and derived data | medium | high | Specified (Pending Decision) | Issue #12 | DG-04, DG-09 | tests/security/test_security_docs.py |
| R-041 | Data governance | TM-DG-04 | Large-scale exfiltration through bulk export | low | high | Specified | Issue #9 | DG-06, DG-01 | tests/security/test_security_docs.py |
| R-042 | Data governance | TM-DG-05 | Inconsistent protection of unclassified data | medium | medium | Specified | Issue #12 | DG-01, DG-05 | tests/security/test_security_docs.py |
| R-043 | Data governance | TM-DG-06 | Loss of accountability for approvals and security events | medium | high | Specified | Issue #7 | DG-07, SO-06 | tests/security/test_security_docs.py; services/work-management/tests/test_proposal_api_integration.py |
| R-044 | Data governance | TM-DG-07 | Compliance violation from out-of-region backups | low | medium | Specified (Pending Decision) | Issue #12 | DG-05, DG-09 | tests/security/test_security_docs.py |
| R-045 | Data governance | TM-DG-08 | Regulatory penalty from an unfulfilled access request | medium | medium | Specified (Pending Decision) | Issue #36 | DG-08 | tests/security/test_security_docs.py |
| R-046 | Tenant isolation | TM-MT-08 | Confused-deputy privilege abuse via an integration principal | medium | high | Specified | Issues #27, #47 | TI-10, WH-07, TI-02 | tests/security/test_security_docs.py |
| R-047 | Tenant isolation | TM-MT-09 | Wrong-tenant effects from async jobs and events | medium | critical | Specified | Issue #46 | TI-09, TI-04 | tests/security/test_security_docs.py |
| R-048 | Webhooks | TM-WH-09 | Cross-organization exposure from over-scoped app permissions | medium | high | Specified (Pending Decision) | Issues #27, #28 | WH-11, OA-05 | tests/security/test_security_docs.py |

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md)
- [Traceability matrix](traceability.md)
- [Open decisions](open-decisions.md)
