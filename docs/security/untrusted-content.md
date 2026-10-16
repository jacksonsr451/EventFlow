# Untrusted Content

EventFlow ingests content it does not control: repository code captured by the
VS Code extension, issue and pull-request text pulled from GitHub or GitLab, and
user-uploaded attachments. None of it is trusted. This document constrains the
editor-context capture ([Issue #24](https://github.com/jacksonsr451/EventFlow/issues/24)),
the integration ingestion ([Issue #27](https://github.com/jacksonsr451/EventFlow/issues/27),
[Issue #28](https://github.com/jacksonsr451/EventFlow/issues/28)),
the clients ([Issue #14](https://github.com/jacksonsr451/EventFlow/issues/14),
[Issue #22](https://github.com/jacksonsr451/EventFlow/issues/22)),
and future AI assistance ([Issue #45](https://github.com/jacksonsr451/EventFlow/issues/45)).

Status: Partially implemented. The Work Management consultation service
([Issue #4](https://github.com/jacksonsr451/EventFlow/issues/4)) implements the
attachment controls AT-01, AT-02, AT-03, AT-04, AT-05, AT-06, AT-07 and AT-09:
uploads are size- and quota-bounded, content-sniffed against a published
allowlist, scanned through an injected fail-closed scanner that quarantines every
unscanned object, stored tenant-scoped with no public path, downloaded only
through an authorized endpoint with `nosniff`, and deleted with their metadata.
Encryption at rest (AT-08) and the scanning provider selection remain owned by
[Issue #12](https://github.com/jacksonsr451/EventFlow/issues/12). The source-code
and editor-context controls remain specified (Phase 0).

## Principle

Untrusted content is data, never instructions. Text, code, or metadata captured
from a repository, an issue tracker, or an upload must never be treated as a
command, a rule, a tool invocation, or a decision. Any system that consumes it
(AI assistance, automation, or rendering) preserves this distinction.

## Source Code and Editor Context

The VS Code extension captures the developer's current selection only with
explicit consent (`consent_granted: true`). Captured snippets are sensitive and
are handled as confidential data.

- **SC-01** — Ingested content is treated as data. It is never interpreted as an
  instruction to the system, an agent, or a tool.
- **SC-02** — Issue, pull-request, comment, and commit text is untrusted input,
  regardless of the apparent author or repository.
- **SC-03** — Captured snippets are scanned for secrets before persistence; a
  detected secret blocks or redacts the capture and raises a security event.
- **SC-04** — No automatic state change, work-item creation, or tool execution is
  triggered directly by ingested content; a human confirms consequential actions.
- **SC-05** — All rendered content is output-encoded; raw HTML, Markdown HTML
  extensions, and script-bearing content are stripped or escaped.
- **SC-06** — Content supplied to AI or automation features is separated from the
  system prompt or instruction channel, and model output is treated as untrusted
  until validated.
- **SC-07** — A human with the appropriate RBAC role authorizes any effect that
  changes authoritative state.

## Attachments

Attachments are uploaded by users and stored for later retrieval. They are
treated as potentially hostile.

- **AT-01** — File type is determined from magic bytes and content, cross-checked
  against the declared content type, not from the filename extension alone.
- **AT-02** — Upload size limits and per-workspace quotas are enforced; oversized
  uploads are rejected.
- **AT-03** — Every upload is scanned for malware and held in quarantine until it
  passes.
- **AT-04** — Objects are stored in a per-tenant namespace outside any web root,
  with no direct public path.
- **AT-05** — Downloads require authorization and are served through a controlled
  endpoint; links are short-lived and not public.
- **AT-06** — Attachments are never rendered inline as HTML or SVG in the
  application origin; they are downloaded or displayed as inert content.
- **AT-07** — Filenames are normalized and never used to build a storage path;
  traversal sequences are rejected.
- **AT-08** — Stored attachments are encrypted at rest.
- **AT-09** — Deleting an attachment removes the object, its metadata, and its
  derived data according to the retention schedule.

## AI and Automation Inputs

AI assistance (`SC-06`) is subordinate to
[Issue #45](https://github.com/jacksonsr451/EventFlow/issues/45) and to
[open-decisions.md](open-decisions.md). Until that work defines the provider and
data boundary, no source code or personal data is sent to an external model
without an explicit, recorded decision.

## Verification

- Documentation tests assert the "data, never instructions" principle and the
  presence of the source-content and attachment controls.
- Implementation tests must assert secret scanning, output encoding, magic-byte
  validation, quarantine, and authorized download.

## Related Documents

- [Security index](README.md)
- [Threat model](threat-model.md): scenarios `TM-SC-*` and `TM-AT-*`.
- [Data governance](data-governance.md)
- [Open decisions](open-decisions.md)
