# Work Management Domain: Workflow, State Machines, and Approval Specification

## Status

Accepted architectural specification subordinate to [ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md)
and governing the implementation of [Issue #2](https://github.com/jacksonsr451/EventFlow/issues/2).

## Context and Purpose

As established in [ADR-006](../adr/ADR-006-product-scope-and-bounded-contexts.md),
EventFlow incorporates a dedicated **Work Management** bounded context strictly
isolated from the legacy distributed order processing domain.

This document formally specifies the domain entities, triage criteria, state
machines, transition matrices, approval mechanics, atomicity and idempotency
guarantees, and client contracts required to support the full lifecycle:

$$\text{Consultation} \longrightarrow \text{Triage} \longrightarrow \text{Proposal} \longrightarrow \text{Review} \longrightarrow \text{Approval} \longrightarrow \text{WorkItem} \longrightarrow \text{BoardCard}$$

## 1. Domain Entities and Boundary Invariants

The domain models five distinct entities. No entity may substitute for another,
and none may inherit or reuse tables or identifiers from the Order Saga domain.

```mermaid
classDiagram
    class Consultation {
        +UUID consultation_id
        +UUID workspace_id
        +UUID project_id
        +UUID author_id
        +UUID assignee_id
        +Origin origin
        +String title
        +String description
        +TriageCategory category
        +ConsultationStatus status
        +Priority priority
        +EditorContext editor_context
        +List~String~ external_references
        +UUID active_proposal_id
        +DateTime created_at
        +DateTime updated_at
    }

    class Proposal {
        +UUID proposal_id
        +UUID consultation_id
        +UUID workspace_id
        +UUID project_id
        +Integer version
        +String title
        +String technical_description
        +String scope
        +String justification
        +List~String~ acceptance_criteria
        +TriageCategory category
        +Priority priority
        +List~String~ risks
        +List~String~ dependencies
        +Float estimated_hours
        +ProposalStatus status
        +UUID proposer_id
        +UUID reviewer_id
        +DateTime created_at
        +DateTime updated_at
    }

    class Approval {
        +UUID approval_id
        +UUID proposal_id
        +Integer proposal_version
        +UUID workspace_id
        +UUID decider_id
        +ApprovalDecision decision
        +String decision_justification
        +String idempotency_key
        +DateTime decided_at
        +String audit_snapshot_hash
    }

    class WorkItem {
        +UUID work_item_id
        +UUID workspace_id
        +UUID project_id
        +UUID origin_proposal_id
        +Integer origin_proposal_version
        +UUID origin_approval_id
        +String title
        +String description
        +List~String~ acceptance_criteria
        +TriageCategory category
        +Priority priority
        +WorkItemStatus status
        +UUID assignee_id
        +List~String~ external_issue_links
        +DateTime created_at
        +DateTime updated_at
    }

    class BoardCard {
        +UUID card_id
        +UUID workspace_id
        +UUID board_id
        +String column_id
        +UUID work_item_id
        +String rank
        +String title
        +Priority priority
        +TriageCategory category
        +UUID assignee_id
        +DateTime created_at
        +DateTime updated_at
    }

    class ConsultationAttachment {
        +UUID attachment_id
        +UUID consultation_id
        +UUID uploaded_by
        +String file_name
        +String content_type
        +Integer size_bytes
        +String checksum_sha256
        +AttachmentStatus status
        +AttachmentScanVerdict scan_verdict
    }

    class ConsultationEvidence {
        +UUID evidence_id
        +UUID consultation_id
        +UUID created_by
        +EvidenceKind kind
        +String description
        +String content
        +UUID attachment_id
    }

    Consultation "1" --> "0..*" Proposal : derives
    Consultation "1" --> "0..*" ConsultationAttachment : attaches
    Consultation "1" --> "0..*" ConsultationEvidence : evidenced by
    ConsultationEvidence "0..*" --> "0..1" ConsultationAttachment : cites
    Proposal "1" --> "0..*" Approval : evaluates
    Approval "1" --> "0..1" WorkItem : authorizes
    WorkItem "1" --> "1..*" BoardCard : projects into
```

### Entity Responsibilities and Non-Negotiable Invariants

1. **Consultation:**
   - *Responsibility:* Raw intake mechanism capturing user inquiries, reported problems,
     feature suggestions, or technical discussions from Web, VS Code, Desktop, or external webhooks.
   - *Invariants:*
     - A Consultation is **never** an approved task and **cannot** be scheduled directly on a Kanban board.
     - Context captured via the VS Code extension (`editor_context`) strictly requires developer consent (`consent_granted: true`).
     - A Consultation may be closed, rejected, or marked as duplicate without ever producing a Proposal.
2. **Proposal:**
   - *Responsibility:* Structured technical proposal derived from a triaged Consultation.
     Contains technical scope, acceptance criteria, architectural impact, and version tracking.
   - *Invariants:*
     - Creating a Proposal **does not** create a `WorkItem` or allocate execution capacity.
     - Any modification to a Proposal increments its `version` integer and sets status back to `DRAFT` or `IN_REVIEW`, superseding previous review states.
3. **Approval:**
   - *Responsibility:* The formal, auditable decision record issued by an authorized reviewer
     evaluating a specific `(proposal_id, proposal_version)`.
   - *Invariants:*
     - Approvals bind strictly to an exact proposal version. An approval for version 1 **never** authorizes version 2.
     - Self-approval is restricted by workspace RBAC policy (the author of a proposal cannot approve it unless explicit single-user mode is active).
     - An approval operation is strictly idempotent through client-provided `Idempotency-Key`.
4. **WorkItem:**
   - *Responsibility:* The authoritative unit of actionable work authorized for development.
   - *Invariants:*
     - A `WorkItem` can **only** be created following a valid, authorized `Approval` with decision `APPROVED`.
     - Direct creation of a `WorkItem` bypassing the Consultation/Proposal/Approval pipeline is prohibited.
     - Copies the immutable snapshot of acceptance criteria and technical scope approved in the Proposal.
5. **BoardCard:**
   - *Responsibility:* Visual representation, ordering, and board placement of a `WorkItem`.
   - *Invariants:*
     - A `BoardCard` cannot exist without a backing `WorkItem`.
     - Moving a card between columns mirrors or validates against allowable `WorkItem` operational transitions (e.g., WIP limits).
     - Deleting or archiving a card does not delete the authoritative `WorkItem`.

---

## 2. Differentiated Triage Criteria

Every raw consultation must undergo categorization during triage before a Proposal
can be created. Categories enforce distinct criteria to maintain input quality:

```mermaid
flowchart TD
    Raw["Raw Consultation (OPEN)"] --> Triage{"Triage Classifier"}
    Triage -->|Bug| BugNode["Bug Criteria:<br/>Expected vs Observed, Steps, Env, Severity, Regression"]
    Triage -->|Feature| FeatNode["Feature Criteria:<br/>Problem, Value, Req, Acceptance Criteria, Dependencies"]
    Triage -->|Chore| ChoreNode["Chore Criteria:<br/>Maintenance Need, Tech Debt Type, Inaction Risk"]
    Triage -->|Docs| DocsNode["Docs Criteria:<br/>Affected Document, Gap Summary, Target Audience"]
    Triage -->|Security| SecNode["Security Criteria:<br/>Vulnerability Type, Confidentiality Flag, Safe Handling"]
```

### 1. Bug
- **Expected vs. Observed Behavior:** Clear contrast between what the system should do and what it did.
- **Reproduction Steps:** Sequential, deterministic steps to replicate the defect.
- **Environment and Version:** Runtime version, operating system, browser/client build, commit hash.
- **Impact and Severity:** Critical (service outage/data corruption), High (core flow blocked), Medium (workaround available), Low (cosmetic).
- **Regression Analysis:** Identifies whether the bug was introduced in a known recent release or commit.

### 2. Feature
- **Problem Statement & Opportunity:** The user pain point or business capability addressed.
- **Expected Value:** Quantifiable efficiency gain, developer productivity improvement, or user benefit.
- **Functional Requirements:** Granular behavioral specifications.
- **Acceptance Criteria:** Objective, testable assertions required for completion.
- **Architectural Impact:** External dependencies, breaking API changes, or schema alterations.

### 3. Chore
- **Maintenance Need:** Dependency upgrades, deprecation removals, code refactoring, or CI optimizations.
- **Technical Debt Classification:** Architectural, testing, documentation, or operational debt.
- **Justification & Inaction Risk:** Consequences if deferred (security vulnerability, build slowdown, fragility).
- **Verifiable Outcome:** Concrete metrics (e.g., zero build warnings, updated dependencies).

### 4. Docs
- **Affected Documentation:** Absolute path or URL of existing documents or location for new guides.
- **Inconsistency or Gap:** Discrepancy between code behavior and documented claims.
- **Target Audience:** Contributors, system operators, API consumers, or end users.
- **Deliverable:** Reviewed markdown files passing repository contract and link validation.

### 5. Security (Special Protected Handling)
- **Vulnerability Classification:** CWE category, injection, authorization bypass, data exposure, etc.
- **Confidentiality Level:** Flagged as `confidential` or `restricted`. Access is restricted strictly to designated security maintainers.
- **Safe Evidence Handling:** Exploit payloads or proofs of concept are stored in encrypted, access-controlled storage; **never** logged to stdout, plaintext tables, or distributed notifications.
- **Responsible Disclosure Process:** Coordinated fix timeline prior to public release or changelog disclosure.

---

## 3. State Machines and Lifecycle Workflows

### 3.1 Consultation State Machine

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Create Draft (Web/VSCode/Desktop)
    [*] --> OPEN: Submit (Web/VSCode/Desktop)
    DRAFT --> OPEN: Submit Draft
    OPEN --> TRIAGING: Start Triage
    TRIAGING --> PROPOSED: Proposal Drafted
    TRIAGING --> REJECTED: Invalid / Out of Scope
    TRIAGING --> DUPLICATE: Duplicate of existing ID
    TRIAGING --> CLOSED: Resolved without task
    REJECTED --> REOPENED: New evidence submitted
    DUPLICATE --> REOPENED: Disproven duplicate
    CLOSED --> REOPENED: Reopened inquiry
    REOPENED --> TRIAGING: Re-triage
    PROPOSED --> CLOSED: Associated WorkItem Completed
```

### 3.2 Proposal State Machine

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Create from Triaged Consultation
    DRAFT --> IN_REVIEW: Submit for Review
    IN_REVIEW --> CHANGES_REQUESTED: Peer Reviewer Requests Adjustments
    CHANGES_REQUESTED --> DRAFT: Edit Scope / Acceptance Criteria (version++)
    IN_REVIEW --> REJECTED: Decider Formally Rejects
    IN_REVIEW --> APPROVED: Authorized Decider Approves
    IN_REVIEW --> SUPERSEDED: Newer version submitted
    DRAFT --> SUPERSEDED: Abandoned for new version
    APPROVED --> [*]: WorkItem & BoardCard Created
    REJECTED --> [*]
```

### 3.3 WorkItem State Machine

```mermaid
stateDiagram-v2
    [*] --> READY: Authorized Approval Event
    READY --> IN_PROGRESS: Developer Assigns / Starts Work
    IN_PROGRESS --> BLOCKED: External Blocker Encountered
    BLOCKED --> IN_PROGRESS: Blocker Cleared
    IN_PROGRESS --> IN_REVIEW: Pull Request / Peer Review
    IN_REVIEW --> IN_PROGRESS: Review Comments / Changes Needed
    IN_REVIEW --> DONE: Accepted / Merged to Main
    READY --> CANCELLED: Business Priority Change
    IN_PROGRESS --> CANCELLED: Obsoleted
    DONE --> [*]
    CANCELLED --> [*]
```

### 3.4 Consultation Attachments, Evidence, and History

Attachments and evidence are supporting records that enrich a Consultation
without changing its identity or bypassing triage. They are not part of the
Consultation → Proposal → Approval → WorkItem → BoardCard chain and never create
a Proposal, Approval, WorkItem, or BoardCard.

- **Attachment lifecycle.** An upload is validated (filename, size, declared vs.
  sniffed content type against a published allowlist), then scanned through an
  injected, fail-closed scanner. A `clean` verdict becomes `available`; an
  `unknown` verdict is `quarantined` and never downloadable; an `infected`
  verdict is `rejected` and its bytes are not stored. Every outcome is recorded
  in the append-only audit trail. Deletion removes the object and its metadata
  and is restricted to the uploader or a workspace administrator.
- **Evidence.** Evidence is `text`, `link`, or a reference to an `available`
  attachment in the same consultation; a quarantined or rejected attachment can
  never be cited. Text and link evidence require inline `content`.
- **History.** The consultation history endpoint is a read-only,
  cursor-paginated projection of the append-only audit records for that
  consultation, so intake, draft edits, triage, uploads, evidence, and deletion
  appear as one ordered timeline.

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE: Clean scan
    [*] --> QUARANTINED: Unknown scan (fail closed)
    [*] --> REJECTED: Infected scan (bytes not stored)
    AVAILABLE --> [*]: Deleted by uploader or admin
    QUARANTINED --> [*]: Deleted by uploader or admin
    REJECTED --> [*]: Deleted by uploader or admin
```

---

## 4. Comprehensive Transition Matrix

The "Authorized Role" column uses descriptive role names. The authoritative RBAC
vocabulary is owned by [Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9)
(`owner`, `admin`, `triager`, `approver`, `contributor`, `viewer`); the public
API declares each operation's allowed roles in `x-required-roles`
([work-management-api.md](work-management-api.md)). The descriptive names map as
follows: *Any Authenticated / Author / Proposer / Assignee* → `contributor`;
*Triager / Maintainer* → `triager`; *Reviewer / Approver* → `approver`;
*Admin* → `admin` / `owner`.

| Entity | From State | To State | Authorized Role | Pre-conditions | Invariants Enforced | Side Effects & Domain Events | Error Codes |
|---|---|---|---|---|---|---|---|
| **Consultation** | `None` | `DRAFT` | `Author` | Valid title and description; optional reporter category; consent granted if editor context present | Status initialized to `DRAFT`; not eligible for triage | `consultation.draft_created` event published | `400 Bad Request` |
| **Consultation** | `DRAFT` | `DRAFT` | `Author`, `Admin` | Draft is in `DRAFT` state; `If-Match` valid when supplied | Editable fields only; status unchanged | `consultation.draft_updated` event published | `403 Forbidden`, `409 Conflict`, `412 Precondition Failed` |
| **Consultation** | `DRAFT` | `OPEN` | `Author`, `Admin` | Draft is in `DRAFT` state; `If-Match` valid when supplied | Status becomes `OPEN`; eligible for triage | `consultation.submitted` event published | `403 Forbidden`, `409 Conflict`, `412 Precondition Failed` |
| **Consultation** | `None` | `OPEN` | `Any Authenticated` | Valid title and description; consent granted if editor context present | Status initialized to `OPEN` | `consultation.created` event published | `400 Bad Request` |
| **Consultation** | `OPEN` | `TRIAGING` | `Triager`, `Maintainer` | Consultation is in `OPEN` or `REOPENED` | Category and priority must be assigned | `consultation.triaged` event published | `409 Conflict` |
| **Consultation** | `TRIAGING` | `PROPOSED` | `Author`, `Maintainer` | A valid Proposal references this `consultation_id` | `active_proposal_id` linked | Consultation status locked to `PROPOSED` | `400 Bad Request`, `409 Conflict` |
| **Consultation** | `TRIAGING` | `REJECTED` | `Triager`, `Maintainer` | Explicit rejection justification required | No active proposal may exist | `consultation.rejected` event published | `400 Bad Request` |
| **Consultation** | `TRIAGING` | `DUPLICATE` | `Triager`, `Maintainer` | Valid target `duplicate_of_id` supplied | Target consultation must exist | Linked to parent consultation | `404 Not Found` |
| **Proposal** | `None` | `DRAFT` | `Proposer` | Origin Consultation is in `TRIAGING` or `PROPOSED` | `version` starts at 1 | Proposal record created; does **not** create WorkItem | `400 Bad Request`, `404 Not Found` |
| **Proposal** | `DRAFT` | `IN_REVIEW` | `Proposer`, `Maintainer` | Complete technical description, scope, and $\ge 1$ acceptance criteria | Status changes to `IN_REVIEW` | `proposal.submitted` event published | `422 Unprocessable Entity` |
| **Proposal** | `IN_REVIEW` | `CHANGES_REQUESTED` | `Reviewer`, `Approver` | Decider cannot be proposer (if anti-self-approval active); justification provided | Decision recorded as `CHANGES_REQUESTED` | `proposal.changes_requested` event published | `403 Forbidden` |
| **Proposal** | `CHANGES_REQUESTED` | `DRAFT` | `Proposer` | New revision prepared; `version` incremented by 1 | Stale version marked `SUPERSEDED` | New version draft created | `409 Conflict` |
| **Proposal** | `IN_REVIEW` | `REJECTED` | `Approver`, `Admin` | Decider possesses `approver` RBAC role; justification provided | Decision recorded as `REJECTED`; terminal for this version | `proposal.rejected` event published | `403 Forbidden`, `409 Conflict` |
| **Proposal** | `IN_REVIEW` | `APPROVED` | `Approver`, `Admin` | Decider possesses `approver` RBAC role; `proposal_version` matches current; `Idempotency-Key` present | Proposal locked to `APPROVED`; generates WorkItem & BoardCard atomically | `proposal.approved`, `work_item.created`, `board_card.created` events | `403 Forbidden`, `409 Conflict` |
| **WorkItem** | `None` | `READY` | `System (Approval Handler)` | Generated exclusively via valid, authorized `Approval` | Copies immutable acceptance criteria snapshot | Atomically placed on initial Board column | `500 Internal Error` (atomic rollback) |
| **WorkItem** | `READY` | `IN_PROGRESS` | `Assignee`, `Maintainer` | Assignee assigned; WIP limits respected | Status updated to `IN_PROGRESS` | Card position synchronized | `409 Conflict` |
| **WorkItem** | `IN_PROGRESS` | `IN_REVIEW` | `Assignee` | Linked PR or execution artifacts submitted | Status updated to `IN_REVIEW` | Card position synchronized | `400 Bad Request` |
| **WorkItem** | `IN_REVIEW` | `DONE` | `Maintainer`, `Reviewer` | All acceptance criteria checked; tests passing in CI | Status set to `DONE`; Consultation marked `CLOSED` | `work_item.completed` event published | `422 Unprocessable Entity` |

---

## 5. Approval, Atomicity, and Idempotency Architecture

The approval step is the critical gateway where unstructured ideas transform into
authoritative commitments. The architecture enforces end-to-end transactional safety:

```mermaid
sequenceDiagram
    autonumber
    actor Approver as Authorized Reviewer
    participant API as Work Management API
    participant Tx as Local Database Transaction (ACID)
    participant Outbox as Transactional Outbox
    participant Clients as Web / VS Code / Desktop

    Approver->>API: POST /v1/workspaces/{id}/proposals/{id}/decide<br/>[Idempotency-Key, proposal_version, decision='APPROVED']
    API->>API: 1. Verify Authentication & RBAC role (approver/admin)
    API->>API: 2. Check Anti-Self-Approval policy (proposer != decider)

    API->>Tx: 3. Begin Database Transaction
    Tx->>Tx: 4. SELECT proposal FOR UPDATE (Optimistic Concurrency Lock)
    Note over Tx: If version != expected_version -> Abort (409 Conflict)<br/>If status != IN_REVIEW -> Abort (409 Conflict)

    Tx->>Tx: 5. Insert Approval Record (Unique constraint on proposal_id, version)
    Tx->>Tx: 6. Update Proposal status -> APPROVED
    Tx->>Tx: 7. Insert WorkItem (Unique constraint on origin_proposal_id)
    Tx->>Tx: 8. Insert BoardCard in Backlog column (Rank calculation)
    Tx->>Outbox: 9. Insert Outbox events: proposal.approved, work_item.created, board_card.created
    API->>Tx: 10. Commit Transaction

    API-->>Approver: 200 OK [Approval, WorkItem, BoardCard]
    Outbox-->>Clients: Realtime updates via WebSockets / SSE
```

### Key Safety Guarantees

1. **Separation of Duties (Anti-Self-Approval):**
   - In production workspaces, an author of a Proposal cannot approve their own proposal.
   - The backend validates: `proposal.proposer_id != request.authenticated_user_id`.
2. **Version Pinning and Stale Review Prevention:**
   - The approval request must explicitly supply `proposal_version`.
   - If a proposer edits a proposal while an approver is reading it, `version` increments to $N+1$.
   - The approver's submission for version $N$ will fail immediately with `409 Conflict (stale_proposal_version)`.
3. **Double-Approval Prevention:**
   - The database enforces a `UNIQUE` constraint on `(proposal_id, proposal_version, decision)`.
   - Simultaneous approval attempts by two reviewers will result in one acquiring the row lock and committing; the other receives `409 Conflict`.
4. **Idempotency with Replay:**
   - The client sends a unique `Idempotency-Key` header (e.g., UUID v4).
   - The backend stores `(workspace_id, idempotency_key, response_payload)` in an operations log.
   - If network drops and client retries with the same key and identical payload, the backend returns the cached `200 OK` response without duplicating downstream records.
5. **Atomic Generation of WorkItem and BoardCard:**
   - Steps 5 through 9 execute inside **a single local ACID transaction**.
   - If inserting the `BoardCard` fails (e.g., column constraint violation), the entire transaction rolls back.
   - It is impossible for a `WorkItem` to exist without its corresponding `BoardCard`, or for a proposal to be marked `APPROVED` without its `WorkItem`.
6. **Immutable Audit Trail:**
   - Every approval stores `audit_snapshot_hash` (SHA-256 of the canonical JSON representation of title, technical description, scope, and acceptance criteria).
   - Ensures tamper-evident proof of exactly what scope was authorized.

---

## 6. Multi-Client Contracts and Interoperability

The three clients (Webapp, VS Code, Desktop) share uniform API specifications
formalized in [`contracts/openapi/work-management.yaml`](../../contracts/openapi/work-management.yaml)
and reusable schemas in [`contracts/schemas/work_management.yaml`](../../contracts/schemas/work_management.yaml).

```mermaid
flowchart LR
    subgraph Clients["Clients"]
        Web["Web Application<br/>(Full Backlog & Review)"]
        VSCode["VS Code Extension<br/>(Context Intake & Triage)"]
        Desktop["Desktop Application<br/>(Offline Queue & Management)"]
    end

    subgraph API["API Layer (contracts/openapi/work-management.yaml)"]
        ConsultationEP["/v1/.../consultations"]
        TriageEP["/v1/.../triage"]
        ProposalEP["/v1/.../proposals"]
        DecideEP["/v1/.../decide"]
        WorkItemEP["/v1/.../work-items"]
        BoardEP["/v1/.../boards/.../cards"]
    end

    Web --> API
    VSCode --> API
    Desktop --> API
```

### Client-Specific Integration Patterns

- **Web Application:** Primary administrative and planning interface. Renders interactive Kanban boards,
  visual diffs between proposal revisions, and approval audit logs.
- **VS Code Extension:** Streamlined developer intake. Features an editor command: *"EventFlow: Create Consultation from Selection"*.
  - Requires explicit consent prompt: *"Send highlighted code snippet and repository metadata to EventFlow?"*
  - Automatically populates `editor_context` (`repository`, `branch`, `commit_sha`, `file_path`, `line_start`, `line_end`).
  - Does **not** allow bypassing triage or approving tasks directly without appropriate workspace privileges.
- **Desktop Application:** Optimized for multi-project workflows and offline resilience.
  - Maintains a local SQLite cache of active boards and consultations.
  - Submissions made offline are buffered in an outbox queue and replayed idempotently upon network reconnect.

---

## 7. Concrete Scenarios and Payload Examples

### 7.1 Positive Scenario: Bug Consultation to Approved WorkItem

1. **Intake (VS Code with Consent):**
   ```json
   POST /v1/workspaces/a1b2c3d4-0000-0000-0000-000000000001/consultations
   {
     "project_id": "b2c3d4e5-0000-0000-0000-000000000002",
     "origin": "vscode",
     "title": "Null pointer on empty cart checkout payload",
     "description": "Submitting an empty cart checkout returns 500 instead of 400 Bad Request.",
     "editor_context": {
       "repository": "github.com/jacksonsr451/EventFlow",
       "branch": "feat/orders-domain",
       "commit_sha": "1670d908234a56c78d9012e34f56789012345678",
       "file_path": "services/orders/src/eventflow_orders/domain/order.py",
       "line_start": 42,
       "line_end": 58,
       "consent_granted": true
     }
   }
   ```
2. **Triage Classification (Bug):**
   ```json
   POST /v1/workspaces/.../consultations/{id}/triage
   {
     "category": "bug",
     "priority": "high",
     "triage_notes": "Reproduced locally; input validation missing on checkout handler.",
     "bug_criteria": {
       "expected_behavior": "Returns 400 ProblemDetails with code INVALID_CART_EMPTY.",
       "observed_behavior": "Unhandled AttributeError raised causing 500 Internal Error.",
       "reproduction_steps": [
         "1. Send POST /v1/orders with empty items array.",
         "2. Inspect HTTP status code."
       ],
       "environment": "Python 3.11 / FastAPI 0.115",
       "severity": "high",
       "is_regression": false
     }
   }
   ```
3. **Structured Proposal (Version 1):**
   ```json
   POST /v1/workspaces/.../proposals
   {
     "consultation_id": "c3d4e5f6-0000-0000-0000-000000000003",
     "title": "Enforce non-empty cart validation in order creation",
     "technical_description": "Add domain validation rule requiring at least one item before order construction.",
     "scope": "services/orders/src/eventflow_orders/domain/order.py and unit tests",
     "justification": "Prevents downstream saga failures and unhandled 500 errors.",
     "acceptance_criteria": [
       "Order constructor raises DomainError when items collection is empty.",
       "Unit tests test_order_requires_at_least_one_item passes.",
       "No regressions in existing order creation suite."
     ],
     "category": "bug",
     "priority": "high",
     "estimated_hours": 3.0
   }
   ```
4. **Approval and Atomic Card Generation:**
   ```json
   POST /v1/workspaces/.../proposals/{id}/decide
   Headers:
     Idempotency-Key: 9f8e7d6c-5b4a-3210-fedc-ba9876543210
   Body:
   {
     "proposal_version": 1,
     "decision": "approved",
     "decision_justification": "Technical approach is sound and acceptance criteria are comprehensive.",
     "target_board_id": "d4e5f6a7-0000-0000-0000-000000000004"
   }
   ```
   *Response (200 OK):* Returns created `Approval`, `WorkItem` (status: `READY`), and `BoardCard` (column: `Ready`, rank: `0hzzzzz`, valid under the persisted rank constraint).

### 7.2 Negative Scenarios

1. **Attempting to Approve Stale Version:**
   - Approver sends `proposal_version: 1`, but the author updated the proposal to version `2`.
   - Response: `409 Conflict` with a problem+json body carrying `"code": "STALE_VERSION"` and `"detail": "Proposal version 1 is superseded by version 2"`.
2. **Attempting to Bypass Approval to Create WorkItem:**
   - Client calls `POST /v1/workspaces/.../work-items` directly.
   - Response: `405 Method Not Allowed` or `403 Forbidden`. Work items cannot be created directly; they only arise from approved proposals.
3. **Missing Consent in Editor Context:**
   - VS Code client sends `consent_granted: false` or omits the boolean.
   - Response: `422 Unprocessable Entity` (`Schema validation failed: consent_granted must be true`).
4. **Self-Approval Violation:**
   - User Alice drafts proposal P1 and calls `/decide` to approve P1 in an enterprise workspace.
   - Response: `403 Forbidden` with a problem+json body carrying `"code": "SELF_APPROVAL_DISALLOWED"` and `"detail": "Proposer cannot approve their own proposal"`.

---

## 8. Traceability and Downstream Issue Alignment

| Requirement in Issue #2 | Architectural Artifact | Downstream Dependent Issue |
|---|---|---|
| Five distinct entities | Section 1, [`work_management.yaml`](../../contracts/schemas/work_management.yaml) | Issue [#9](https://github.com/jacksonsr451/EventFlow/issues/9), [#12](https://github.com/jacksonsr451/EventFlow/issues/12) |
| Differentiated triage criteria | Section 2, [`work_management.yaml`](../../contracts/schemas/work_management.yaml) | Issue [#4](https://github.com/jacksonsr451/EventFlow/issues/4), [#5](https://github.com/jacksonsr451/EventFlow/issues/5) |
| State machines & transitions | Sections 3 & 4 | Issue [#6](https://github.com/jacksonsr451/EventFlow/issues/6), [#7](https://github.com/jacksonsr451/EventFlow/issues/7), [#8](https://github.com/jacksonsr451/EventFlow/issues/8) |
| Approval atomicity & idempotency | Section 5 | Issue [#7](https://github.com/jacksonsr451/EventFlow/issues/7), [#10](https://github.com/jacksonsr451/EventFlow/issues/10) |
| Client contracts & interoperability | Section 6, [`work-management.yaml`](../../contracts/openapi/work-management.yaml) | Issue [#3](https://github.com/jacksonsr451/EventFlow/issues/3), [#11](https://github.com/jacksonsr451/EventFlow/issues/11), [#13](https://github.com/jacksonsr451/EventFlow/issues/13), [#23](https://github.com/jacksonsr451/EventFlow/issues/23) |
| Automated contract tests | `tests/contracts/test_work_management_workflow.py` | Issue [#32](https://github.com/jacksonsr451/EventFlow/issues/32), [#33](https://github.com/jacksonsr451/EventFlow/issues/33) |

---

## 9. Related Documents

- [Product Scope and Bounded Contexts (ADR-006)](../adr/ADR-006-product-scope-and-bounded-contexts.md)
- [System Architecture Overview](overview.md)
- [Order Workflow (Legacy Domain)](order-workflow.md)
- [Work Management Schemas](../../contracts/schemas/work_management.yaml)
- [Work Management OpenAPI Specification](../../contracts/openapi/work-management.yaml)
