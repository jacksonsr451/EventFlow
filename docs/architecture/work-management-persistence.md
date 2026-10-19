# Work Management Persistence

This document describes how the Work Management bounded context is persisted.
It implements [ADR-008](../adr/ADR-008-work-management-persistence.md) and the
Work Management workflow in
[work-management-workflow.md](work-management-workflow.md). The authoritative
field shapes are the entity definitions in
[work_management.yaml](../../contracts/schemas/work_management.yaml); the
database adds the constraints those contracts cannot express.

## Stack

- **PostgreSQL** is the system of record.
- **SQLAlchemy 2.x** defines the models (`services/work-management/src/eventflow_work_management/models/`).
- **Alembic** owns schema evolution; `Base.metadata.create_all()` is not a
  deployment path.
- **psycopg 3** is the driver, used through the `postgresql+psycopg` dialect.

The service is a self-contained Poetry project at `services/work-management/`
and does not depend on Order Processing code or tables.

## Tables

| Table | Purpose | Key constraints |
|---|---|---|
| `workspaces` | Tenant boundary | unique `slug` (format checked) |
| `projects` | Grouping inside a workspace | unique `(workspace_id, key)`, unique `(workspace_id, id)` |
| `consultations` | Submitted requests | enums; `(workspace_id, project_id)` FK to `projects`; unique `(workspace_id, project_id, id)` |
| `proposals` | Independent plans (1→N per consultation) | project-bound consultation FK; array/JSON checks; self FKs for `duplicated_from`/`superseded_by` |
| `proposal_revisions` | Immutable per-proposal snapshots | unique `(proposal_id, version)`; append-only triggers; workspace-bound proposal FK |
| `proposal_evidence` | Proposal→consultation evidence links | composite PK `(proposal_id, evidence_id)`; workspace-bound FKs |
| `approvals` | One decision per proposal version | unique `(proposal_id, proposal_version)`; `sha256` hash |
| `work_items` | Execution work | unique `origin_proposal_id`; origin trigger; project-bound proposal FK; composite FKs to project and approval |
| `boards` / `board_cards` | Kanban placement | card `project_id` bound to board and WorkItem by composite FKs; unique `(board_id, work_item_id)`, unique `(board_id, column_id, rank)`; board `version` and `archived_at` |
| `board_columns` | Independently managed columns | unique `(board_id, key)`, unique `(workspace_id, id)`; one row per board column with `position`, `mapped_status` and optional `wip_limit`; no FK from `board_cards.column_id` |
| `card_movements` | Append-only card movement history | block `UPDATE`/`DELETE`/`TRUNCATE` triggers; workspace-bound board and card FKs; column ids stored as bare keys |
| `entity_comments` | Comments on consultations, proposals, work items, board cards | tombstone-only; block rewrite/`DELETE`/`TRUNCATE` triggers; composite project FK; entity type check; body length and deletion-consistency checks |
| `entity_attachments` | Generic attachments for proposals, work items, board cards | status/scan-verdict checks; rejection/reason consistency; `sha256` checksum; opaque `storage_key`; composite project FK |
| `entity_attachment_blobs` | Bytes for generic attachments | one row per attachment; rejected attachments store no blob; cascade from metadata and workspace |
| `audit_records` | Append-only audit trail | block `UPDATE`/`DELETE`/`TRUNCATE` triggers; `sha256` snapshot hash |
| `idempotency_records` | Stored responses per client key | unique `(workspace_id, operation, idempotency_key)` |
| `remote_integration_references` | GitHub/GitLab identity mapping | unique external resource key; same-workspace entity guard |
| `project_repositories` | Project→remote repository configuration | unique `(workspace_id, project_id, provider, provider_instance_id, remote_repository_id)`; canonical HTTPS URL; status/verification checks; composite project FK |

## Invariants Enforced by the Database

Application code validates first; the database is the last line of defense.

- **Tenant integrity.** Every tenant-owned table carries a non-null
  `workspace_id`. Child rows reference parents through composite foreign keys
  `(workspace_id, parent_id) -> parent(workspace_id, id)`, so a row can never
  point at another workspace's data. This supports the
  [tenant isolation](../security/tenant-isolation.md) invariants.
- **Project consistency.** A Proposal's `(workspace_id, project_id,
  consultation_id)` must match an existing Consultation through the composite FK
  `fk_proposals_workspace_project_consultation`, and a WorkItem's
  `(workspace_id, project_id, origin_proposal_id)` must match its origin
  Proposal through `fk_work_items_workspace_project_proposal`. A Proposal
  therefore cannot belong to a different project than its Consultation, and a
  WorkItem cannot belong to a different project than the approved Proposal it
  came from.
- **Board card project consistency.** `board_cards` stores an internal
  `project_id` and references `boards` and `work_items` through the composite
  foreign keys `fk_board_cards_workspace_project_board` and
  `fk_board_cards_workspace_project_work_item`. A card's Board and WorkItem must
  therefore belong to the same workspace *and* the same project; a card cannot
  join a board in one project to a WorkItem in another. The column is
  functionally dependent on the board and is kept consistent by the constraints.
- **WorkItem cardinality.** `work_items` has `UNIQUE (origin_proposal_id)`: at
  most one WorkItem can originate from a given Proposal, per workflow step 7.
- **Proposal versioning.** Each Proposal owns its revision counter: two Proposals
  derived from the same Consultation are independent and may both be at version
  1. `proposal_revisions` enforces `UNIQUE (proposal_id, version)` and its
  `BEFORE UPDATE`/`BEFORE DELETE`/`BEFORE TRUNCATE` triggers
  (`eventflow_proposal_revisions_block_mutation`) make the revision history
  append-only. `approvals` has `UNIQUE (proposal_id, proposal_version)`.
- **WorkItem provenance.** A `BEFORE INSERT/UPDATE` trigger requires the
  referenced approval to exist in the same workspace, to match the proposal and
  version, and to be `approved`. A WorkItem cannot come from a Consultation or
  an unapproved Proposal, and the origin columns cannot be updated to an
  invalid Proposal/version.
- **Append-only audit.** `BEFORE UPDATE`, `BEFORE DELETE` and `BEFORE TRUNCATE`
  triggers on `audit_records` raise, preserving history against row and
  whole-table mutation.
- **Board columns.** A board's columns are first-class rows in `board_columns`,
  each with a stable `key`, an ordered `position`, a canonical `mapped_status`
  (one of the WorkItem status values) and an optional positive `wip_limit`.
  `key` is unique per board and constrained to a lowercase slug pattern.
  `board_cards.column_id` intentionally has **no** foreign key to `board_columns`:
  a card's column is a logical label that the application validates, so boards
  materialized before Issue #8 (for example a card in `ready` with no column row)
  remain valid.
- **Card movement history.** Every accepted move appends an immutable
  `card_movements` row with the source/target column, rank and status. `BEFORE
  UPDATE`/`BEFORE DELETE`/`BEFORE TRUNCATE` triggers
  (`eventflow_card_movements_block_mutation`) raise, so the history is
  append-only.
- **Comment immutability.** `entity_comments` is tombstone-only. A
  `BEFORE UPDATE` trigger (`eventflow_entity_comments_block_rewrite`) rejects any
  change to `workspace_id`, `project_id`, `entity_type`, `entity_id`,
  `author_id`, `body`, or `created_at`, while allowing the deletion columns;
  `BEFORE DELETE` and `BEFORE TRUNCATE` triggers
  (`eventflow_entity_comments_block_mutation`) reject hard removal. The
  `(deleted_at IS NULL) = (deleted_by IS NULL)` check keeps tombstones
  consistent.
- **Generic attachment lifecycle.** `entity_attachments` enforces the status
  (`quarantined`/`available`/`rejected`) and scan-verdict
  (`clean`/`infected`/`unknown`) vocabularies, requires a rejection reason
  exactly when the status is `rejected`, and validates the SHA-256 checksum and
  opaque storage key formats. `entity_attachment_blobs` is written only for
  non-rejected objects, so quarantined and rejected bytes are never persisted or
  served. Proposals, work items, and board cards use this pair; consultations
  keep their Issue #4 tables.
- **Polymorphic collaboration targets.** `entity_comments.entity_id` and
  `entity_attachments.entity_id` are opaque UUIDs because one column can name
  four tables. The application resolves the public collection segment inside the
  caller's workspace and copies the resolved `project_id`; the composite FK to
  `projects (workspace_id, id)` then guarantees that every comment or attachment
  stays in one workspace and project. Unknown collections and foreign entities
  are hidden as `404`.
- **Remote reference integrity.** A `BEFORE INSERT/UPDATE` trigger requires a
  `remote_integration_references` row whose `entity_type` names a Work
  Management entity to reference an entity that exists in the same workspace.
  Unknown entity types are forward-compatible and are not validated here.
- **Project repository identity.** `project_repositories` deduplicates on the
  provider-assigned identity `(workspace_id, project_id, provider,
  provider_instance_id, remote_repository_id)`, not on the URL. A URL is
  normalized metadata and can change when a repository moves. The same provider
  repository id on a different `provider_instance_id` is a distinct remote, and
  the same remote can be linked to multiple projects. `archived` is terminal,
  `deactivated_at` is non-null exactly while `inactive`, and `archived_at` is
  non-null exactly while `archived`.
- **Idempotency.** The implemented approval-decision repository and its
  `idempotency_records` row are written in one transaction; a retry with the
  same key and fingerprint returns the stored repository result, and a different
  request under the same key conflicts. Other A-02 HTTP operations are contract
  requirements, not persistence/runtime integrations implemented here.

## Idempotency

`ApprovalRepository.decide` computes a SHA-256 fingerprint of the request,
reserves `(workspace_id, operation, idempotency_key)`, writes the Approval, the
proposal status change, an audit record and the idempotency record, then commits
once. Concurrent retries with the same key resolve to a single effect: the loser
of the unique-insert race reads the stored result and replays it. This implements
ADR-007 section 3.6 for `.../decide` and provides the storage primitive that
Amendment A-02 relies on; A-02 itself is a contract change applied by
[Issue #11](https://github.com/jacksonsr451/EventFlow/issues/11).
The approval decision, Kanban board operations, and project repository
operations use this mechanism at the API boundary; the persistence layer itself
still provides only the storage primitive.

## Tenant Isolation Scope

Composite foreign keys and application-layer workspace scoping are enforced
today. PostgreSQL Row-Level Security is **deferred** until an authentication
context exists (Issues #9/#10); see
[open decisions](../security/open-decisions.md). The deferral is intentional and
must not be read as full isolation coverage.

## Running Migrations

```bash
export EVENTFLOW_DATABASE_URL="postgresql+psycopg://eventflow:<password>@localhost:5432/eventflow"
alembic -c services/work-management/alembic.ini upgrade head
alembic -c services/work-management/alembic.ini downgrade base
```

Local PostgreSQL is provided by the root `docker-compose.yml`. CI runs the same
migrations and the PostgreSQL-backed suite; see
[ci-cd.md](../development/ci-cd.md) and
[testing-strategy.md](../development/testing-strategy.md).

## Traceability

Each control is traced from its requirement to the database object that enforces
it, the repository behavior, and the PostgreSQL-backed test that proves it.

| Requirement | Database object | Repository behavior | Test |
|---|---|---|---|
| Tenant isolation (cross-workspace) | composite FKs `fk_*_workspace_*` | workspace-scoped `get`/`list` methods | `test_cross_workspace_reference_is_rejected`, `test_reference_to_another_workspace_entity_is_rejected` |
| Project consistency | `fk_proposals_workspace_project_consultation`, `fk_work_items_workspace_project_proposal` | callers pass matching `project_id` | `test_proposal_project_must_match_consultation_project`, `test_work_item_project_must_match_origin_proposal_project` |
| Board card project consistency | `fk_board_cards_workspace_project_board`, `fk_board_cards_workspace_project_work_item` | `BoardCardRepository.add_card` derives `project_id` from the board | `test_board_card_cross_project_is_rejected`, `test_board_card_cross_project_direct_sql_is_rejected`, `test_board_card_cross_workspace_is_rejected`, `test_board_card_update_to_cross_project_work_item_is_rejected`, `test_changing_work_item_project_cannot_invalidate_existing_card` |
| WorkItem cardinality | `uq_work_items_origin_proposal` | `WorkItemRepository.create_from_approved_proposal` conflict handling | `test_second_work_item_from_same_proposal_is_rejected`, `test_duplicate_work_item_via_direct_sql_is_rejected`, `test_concurrent_work_items_from_same_proposal_has_exactly_one_effect` |
| WorkItem origin | `trg_work_items_origin_guard` | `WorkItemRepository.create_from_approved_proposal` | `test_work_item_requires_approved_proposal`, `test_work_item_rejects_mismatched_proposal_version`, `test_work_item_origin_cannot_be_updated_to_invalid_version` |
| Audit immutability | `trg_audit_records_no_update/_no_delete/_no_truncate` | `AuditRepository.append` (insert only) | `test_audit_records_are_append_only`, `test_audit_records_cannot_be_truncated` |
| Idempotency | `uq_idempotency_records_scope_key` | `ApprovalRepository.decide` + `IdempotencyRepository` | `test_same_key_replays_without_new_effects`, `test_same_key_different_request_conflicts`, `test_concurrent_same_key_has_exactly_one_effect` |
| Approval uniqueness | `uq_approvals_proposal_version` | `ApprovalRepository.decide` conflict handling | `test_new_key_for_decided_version_is_rejected` |
| Remote reference uniqueness and integrity | `uq_remote_integration_references_resource`, `trg_remote_references_entity_guard` | `RemoteReferenceRepository.link` | `test_duplicate_remote_resource_is_rejected`, `test_reference_to_unknown_entity_is_rejected` |
| Proposal independence and revision uniqueness | `uq_proposal_revisions_proposal_version`, `trg_proposal_revisions_no_update/_no_delete/_no_truncate` | `ProposalRepository.add`/`update_content`/`append_revision` | `test_independent_proposals_share_consultation`, `test_duplicate_proposal_revision_is_rejected`, `test_concurrent_proposals_create_independent_rows` |
| Board column integrity | `uq_board_columns_board_key`, `uq_board_columns_workspace_id`, `ck_board_columns_*` | `BoardColumnRepository.add`/`update`/`delete` | `test_column_create_update_reorder_and_delete`, `test_last_column_cannot_be_deleted` |
| Card movement history | `trg_card_movements_no_update/_no_delete/_no_truncate` | `CardMovementRepository.append` (insert only) | `test_card_move_updates_work_item_and_records_history`, `test_migrations_integration.py` |
| Comment immutability and tombstones | `trg_entity_comments_no_rewrite/_no_delete/_no_truncate`, `ck_entity_comments_deletion_consistency` | `CommentService.create`/`delete`, `CommentRepository.soft_delete` | `test_comment_lifecycle_tombstone_and_history`, `test_comment_body_is_immutable_at_the_database_level` |
| Generic attachments fail closed | `ck_entity_attachments_status_values`, `ck_entity_attachments_rejection_reason_consistency`, blob separation | `EntityAttachmentService.upload`/`download`/`delete`, `validate_upload`, `classify` | `test_entity_attachment_scan_lifecycle_on_proposal` |
| Collaboration tenant isolation | composite FKs `fk_entity_comments_workspace_project`, `fk_entity_attachments_workspace_project` | `resolve_entity` + workspace-scoped repositories | `test_comment_rbac_and_tenant_isolation`, `test_comments_and_attachments_on_work_items_and_board_cards` |
| Entity history projection | append-only `audit_records` | `EntityHistoryService.list_page` (read only) | `test_comment_lifecycle_tombstone_and_history`, `test_entity_attachment_scan_lifecycle_on_proposal` |
| Deterministic ordering and transitions | integer `rank`/`position` columns, `uq_board_cards_board_column_rank` | `BoardCardService.move`, `BoardColumnService.create`/`update`/`delete` | `test_board_ranking_unit.py`, `test_card_move_rejects_invalid_transition_and_unknown_column`, `test_card_move_enforces_wip_limit` |
| Project repository identity and lifecycle | `uq_project_repositories_identity`, `fk_project_repositories_workspace_project`, `ck_project_repositories_*` | `ProjectRepositoryLinkRepository.find_identity`, `ProjectRepositoryService.create`/`update`/`unlink` | `test_remote_identity_dedup_is_url_and_instance_aware`, `test_lifecycle_idempotency_tenant_isolation_rbac_and_audit`, `test_concurrent_duplicate_create_converges_on_one_row` |
| Migration reproducibility | Alembic `0001_initial`…`0010_project_repositories` | `support.run_migrations` | `test_migrations_integration.py` |

## Residual Risks and Deferred Controls

- **Row-Level Security is deferred** until an authentication context exists
  (Issues #9/#10). Until then, application-layer scoping remains load-bearing and
  a missing `WHERE workspace_id = ...` is a real risk (Issue #47).
- **Test database configuration fails closed.** Integration tests require an
  explicit `EVENTFLOW_TEST_DATABASE_URL`; they never fall back to
  `EVENTFLOW_DATABASE_URL`, and destructive operations only target generated
  `eventflow_test_<12 hex>` databases. A shared application/test URL is still
  possible by configuration (as CI does), so point the test URL at a disposable
  database.
- **Comment tombstones block cascaded parent deletion.** Because the comment
  `BEFORE DELETE` trigger fires for cascades too, a project or workspace that
  owns comments cannot be removed by a plain cascade. There is no project or
  workspace delete endpoint today; a future archival path must handle comments
  explicitly rather than relying on cascade.
- **Remote references with unknown `entity_type`** are accepted without
  existence or workspace validation; provider integrations own those semantics.
- **`updated_at`** is maintained by the ORM `onupdate`, not a database trigger,
  so a direct SQL `UPDATE` does not refresh it.
- **Migration and application use the same PostgreSQL role** in development.
  A production deployment must separate the migration administrator from the
  least-privilege application role; that separation is not implemented here.
- **`downgrade base` drops populated tables**, so it is technically reversible
  but not data-preserving. It must never run against production data.
