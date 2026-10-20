# ADR-010: Project Triage Configuration and Versioned Templates

## Status

Accepted

## Context

The differentiated category contract (Issue #5) is authoritative but fixed. Real
projects need extra, project-owned triage requirements: a mandatory reproduction
link for bugs, a customer tier list, an enum of affected environments, or a rule
that a category needs evidence before a proposal. Those requirements must not
fork the category contract, execute arbitrary validation code, or weaken the
approval gate.

[Issue #41](https://github.com/jacksonsr451/EventFlow/issues/41) requires:

1. project-scoped, additive configuration;
2. templates that evolve without mutating published behaviour;
3. safe, declarative custom fields;
4. deterministic validation and historical snapshots;
5. tenant isolation, RBAC, audit, idempotency, and optimistic concurrency.

## Decision

1. **Additive only.** Project rules layer on top of the baseline category
   criteria. They can add required fields and restrict categories or evidence,
   but cannot remove baseline criteria or bypass approval, WorkItem, or BoardCard
   creation.
2. **Four new tenant-scoped tables.** `project_triage_configurations`,
   `project_triage_templates`, `project_triage_template_versions`, and
   `project_triage_template_activations`. Composite foreign keys on
   `(workspace_id, project_id)` make cross-project references unrepresentable,
   and a unique activation per `(workspace_id, project_id, category)` keeps one
   effective template.
3. **Immutable published versions.** Templates hold metadata and one category;
   versions hold the bounded definition. A published version is never edited:
   changes create a new draft version, and activation switches the project to it.
   Archiving removes the activation while preserving version history and pinned
   consultation snapshots.
4. **Declarative field descriptors.** Field types are a closed enum
   (`string`, `multiline_text`, `integer`, `number`, `boolean`, `date`,
   `datetime`, `enum`, `multi_select`, `reference`). Definitions are size-,
   depth-, and count-bounded, and reject regular expressions, SQL, expressions,
   imports, remote references, and executable constructs. Unknown submitted keys
   are rejected; defaults are applied before validation.
5. **Precedence and snapshots.** The effective field set is baseline →
   active template → enabled configuration. Triage pins the template id,
   version, schema version, validation snapshot, and normalized custom fields on
   the consultation so later template changes cannot rewrite history.
6. **Authorization and concurrency.** Reads use new read actions available to all
   workspace roles; mutations require owner/admin `triage_configuration:manage`
   or `triage_template:manage`. Mutations accept `Idempotency-Key`; config update,
   activation, archive, and deprecate accept `If-Match`. Activation is serialized
   per project/category, and every change writes an audit record.

## Consequences

- Existing consultations remain valid; their snapshot columns stay `NULL` until
  they are re-triaged or reclassified under a project rule.
- Clients must send `custom_fields` only as declared; validation errors list
  per-field messages with stable codes.
- Templates cannot be shared across projects by design; copying a definition is
  an explicit client action.
- Published behaviour changes only through activation, so rollbacks are
  performed by activating a prior published version.

## Alternatives Considered

- **Executable validation hooks** (regex, scripts, expressions): rejected for
  security and determinism; unbounded evaluation is a denial-of-service and data
  exfiltration risk.
- **Mutable published templates**: rejected because historical triage could no
  longer be explained.
- **A second workflow engine**: rejected; project rules must not duplicate or
  bypass the existing consultation/proposal pipeline.

## Related Documents

- [Work Management workflow](../architecture/work-management-workflow.md)
  (section 3.10)
- [Tenant isolation](../security/tenant-isolation.md)
- [Work Management API](../architecture/work-management-api.md)
- [ADR-008](ADR-008-work-management-persistence.md)
