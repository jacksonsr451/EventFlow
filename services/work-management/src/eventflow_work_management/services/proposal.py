"""Proposal application service (Issue #6).

One triaged consultation may yield zero, one, or many independent proposals.
Each proposal is its own aggregate: it has its own ``proposal_id`` and its own
revision counter starting at 1, and every accepted content edit appends an
immutable snapshot to the revision history. Creating, editing, previewing,
submitting, or duplicating a proposal never creates an Approval, WorkItem,
BoardCard, or remote issue.

Every public mutation is one unit of work: it authorizes through
``AuthorizationService`` (the tenant and actor come from the verified principal,
never the request body), performs a single transactional change, writes an
append-only audit record, and commits once. An optional ``Idempotency-Key`` is
reserved in the same transaction so a retried submission never duplicates a
proposal.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import ADMINISTRATOR_ROLES
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Proposal
from eventflow_work_management.models.enums import (
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
)
from eventflow_work_management.repositories.attachment_repository import (
    EvidenceRepository,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.proposal_repository import (
    SORT_COLUMNS,
    ProposalRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.triage_configuration import (
    TriageConfigurationService,
)

CREATE_OPERATION = "proposal.create"
UPDATE_OPERATION = "proposal.update"
SUBMIT_OPERATION = "proposal.submit"
DUPLICATE_OPERATION = "proposal.duplicate"

DRAFT_STATUS = "draft"
IN_REVIEW_STATUS = "in_review"
CHANGES_REQUESTED_STATUS = "changes_requested"
SUPERSEDED_STATUS = "superseded"

# A proposal may only be derived from a consultation whose manual triage has
# completed. Raw intake (draft/open) and terminal states cannot produce one.
PROPOSAL_ELIGIBLE_STATUSES = frozenset({"triaging", "proposed", "reopened"})
EDITABLE_STATUSES = frozenset({DRAFT_STATUS, CHANGES_REQUESTED_STATUS})
SUBMITTABLE_STATUSES = frozenset({DRAFT_STATUS, CHANGES_REQUESTED_STATUS})

ALLOWED_SORT_KEYS = frozenset(SORT_COLUMNS)
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

MAX_ACCEPTANCE_CRITERIA = 50
MAX_CHECKLIST_ITEMS = 100
MAX_DEPENDENCIES = 50
MAX_EVIDENCE_LINKS = 50
MAX_ESTIMATED_HOURS = 9999.99
MIN_ESTIMATED_HOURS = 0.5

_NOT_FOUND = "The requested resource was not found."


def _now() -> datetime:
    return datetime.now(UTC)


def _validation(detail: str, *, status_code: int = 400) -> ProblemError:
    return ProblemError(
        status_code=status_code,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request" if status_code == 400 else "Unprocessable entity",
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _conflict(detail: str, *, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def proposal_etag(proposal: Proposal) -> str:
    """Strong validator over the persisted proposal revision."""
    return (
        '"'
        + fingerprint(
            [
                "proposal",
                str(proposal.id),
                proposal.version,
                proposal.updated_at.isoformat(),
            ]
        )
        + '"'
    )


@dataclass(frozen=True, slots=True)
class ProposalResult:
    """A persisted proposal plus whether it was served from an idempotent replay."""

    proposal: Proposal
    replayed: bool


def _encode_cursor(sort_key: str, descending: bool, value, proposal_id: UUID) -> str:
    payload = {
        "k": sort_key,
        "d": descending,
        "v": value.isoformat() if isinstance(value, datetime) else value,
        "id": str(proposal_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str, sort_key: str, descending: bool) -> tuple:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        if payload["k"] != sort_key or payload["d"] is not descending:
            raise ValueError("cursor is bound to a different sort")
        proposal_id = UUID(payload["id"])
        value = payload["v"]
        if sort_key in {"created_at", "updated_at"}:
            value = datetime.fromisoformat(value)
        return value, proposal_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _validation("The pagination cursor is invalid.") from exc


def _parse_sort(sort: str | None) -> tuple[str, bool]:
    if not sort:
        return "created_at", False
    token = sort.split(",", 1)[0].strip()
    if not token:
        raise _validation("The sort parameter is invalid.")
    descending = token.startswith("-")
    key = token[1:] if descending else token
    if key not in ALLOWED_SORT_KEYS:
        raise _validation("The sort parameter is invalid.")
    return key, descending


def _encode_revision_cursor(version: int) -> str:
    raw = json.dumps({"v": version}, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_revision_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        version = int(payload["v"])
        if version < 0:
            raise ValueError("negative version")
        return version
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _validation("The pagination cursor is invalid.") from exc


class ProposalService:
    """Authorization, validation, and persistence for consultation proposals."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.proposals = ProposalRepository(session)
        self.consultations = ConsultationRepository(session)
        self.evidence = EvidenceRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)
        self.triage_configuration = TriageConfigurationService(session)

    # -- create / preview -------------------------------------------------

    def create(
        self,
        context: AuthorizationContext,
        *,
        consultation_id: UUID,
        title: str,
        technical_description: str,
        scope: str,
        justification: str,
        acceptance_criteria: list,
        category: str,
        priority: str,
        checklist: list | None = None,
        risks: list | None = None,
        dependencies: list | None = None,
        evidence_ids: list | None = None,
        estimated_hours: float | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProposalResult:
        normalized = self._normalize(
            category=category,
            priority=priority,
            acceptance_criteria=acceptance_criteria,
            checklist=checklist,
            risks=risks,
            dependencies=dependencies,
            estimated_hours=estimated_hours,
        )
        evidence_ids = self._normalize_evidence_ids(evidence_ids)

        request_fingerprint = fingerprint(
            {
                "operation": CREATE_OPERATION,
                "consultation_id": str(consultation_id),
                "title": title,
                "technical_description": technical_description,
                "scope": scope,
                "justification": justification,
                **normalized,
                "evidence_ids": [str(item) for item in evidence_ids],
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, CREATE_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            consultation = self.consultations.get_for_update(
                workspace_id=context.workspace_id, consultation_id=consultation_id
            )
            if consultation is None:
                raise _not_found()
            self._require_eligible(consultation)
            self.triage_configuration.assert_proposal_eligible(context, consultation)
            self._require_evidence(context.workspace_id, consultation_id, evidence_ids)
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=CREATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            proposal = self.proposals.add(
                workspace_id=context.workspace_id,
                project_id=consultation.project_id,
                consultation_id=consultation_id,
                proposer_id=context.actor_id,
                title=title,
                technical_description=technical_description,
                scope=scope,
                justification=justification,
                acceptance_criteria=normalized["acceptance_criteria"],
                checklist=normalized["checklist"],
                category=normalized["category"],
                priority=normalized["priority"],
                risks=normalized["risks"],
                dependencies=normalized["dependencies"],
                estimated_hours=normalized["estimated_hours"],
                summary="Initial proposal",
            )
            if evidence_ids:
                self.proposals.set_evidence(
                    workspace_id=context.workspace_id,
                    proposal_id=proposal.id,
                    evidence_ids=evidence_ids,
                )
            consultation.active_proposal_id = proposal.id
            self.audit.append(
                workspace_id=context.workspace_id,
                action="proposal.created",
                entity_type="proposal",
                entity_id=proposal.id,
                actor_id=context.actor_id,
                snapshot={
                    "proposal_id": str(proposal.id),
                    "consultation_id": str(consultation_id),
                    "version": proposal.version,
                    "category": proposal.category,
                    "priority": proposal.priority,
                    "status": proposal.status,
                    "duplicated_from_proposal_id": None,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"proposal_id": str(proposal.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return ProposalResult(proposal=proposal, replayed=False)

    def preview(
        self,
        context: AuthorizationContext,
        *,
        consultation_id: UUID,
        title: str,
        technical_description: str,
        scope: str,
        justification: str,
        acceptance_criteria: list,
        category: str,
        priority: str,
        checklist: list | None = None,
        risks: list | None = None,
        dependencies: list | None = None,
        evidence_ids: list | None = None,
        estimated_hours: float | None = None,
    ) -> dict:
        """Validate and normalize a prospective proposal without persisting it."""
        normalized = self._normalize(
            category=category,
            priority=priority,
            acceptance_criteria=acceptance_criteria,
            checklist=checklist,
            risks=risks,
            dependencies=dependencies,
            estimated_hours=estimated_hours,
        )
        evidence_ids = self._normalize_evidence_ids(evidence_ids)
        consultation = self.consultations.get(
            workspace_id=context.workspace_id, consultation_id=consultation_id
        )
        if consultation is None:
            raise _not_found()
        self._require_eligible(consultation)
        self.triage_configuration.assert_proposal_eligible(context, consultation)
        self._require_evidence(context.workspace_id, consultation_id, evidence_ids)
        return {
            "consultation_id": consultation_id,
            "workspace_id": context.workspace_id,
            "project_id": consultation.project_id,
            "version": 1,
            "title": title,
            "technical_description": technical_description,
            "scope": scope,
            "justification": justification,
            "acceptance_criteria": normalized["acceptance_criteria"],
            "checklist": normalized["checklist"],
            "category": normalized["category"],
            "priority": normalized["priority"],
            "risks": normalized["risks"],
            "dependencies": normalized["dependencies"],
            "evidence": evidence_ids,
            "estimated_hours": normalized["estimated_hours"],
            "status": DRAFT_STATUS,
        }

    # -- edit / submit ----------------------------------------------------

    def update(
        self,
        context: AuthorizationContext,
        proposal_id: UUID,
        *,
        changes: dict[str, object],
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProposalResult:
        if not changes:
            raise _validation("At least one field must be provided.")
        evidence_supplied = "evidence_ids" in changes
        raw_evidence = changes.pop("evidence_ids", None)
        normalized_changes = self._normalize_changes(changes)
        evidence_ids = (
            self._normalize_evidence_ids(raw_evidence) if evidence_supplied else None
        )

        request_fingerprint = fingerprint(
            {
                "operation": UPDATE_OPERATION,
                "proposal_id": str(proposal_id),
                "version": if_match,
                "changes": normalized_changes,
                "evidence_ids": (
                    [str(item) for item in evidence_ids]
                    if evidence_ids is not None
                    else None
                ),
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, UPDATE_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            proposal = self.proposals.get_for_update(
                workspace_id=context.workspace_id, proposal_id=proposal_id
            )
            if proposal is None:
                raise _not_found()
            self._require_proposer_or_admin(context, proposal)
            if if_match is not None and if_match != proposal_etag(proposal):
                raise _precondition_failed()
            if proposal.status not in EDITABLE_STATUSES:
                raise _conflict(
                    "Only a draft or changes-requested proposal can be edited.",
                    code="INVALID_STATE",
                )
            if evidence_ids is not None:
                self._require_evidence(
                    context.workspace_id, proposal.consultation_id, evidence_ids
                )
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=UPDATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            if normalized_changes:
                self.proposals.update_content(
                    proposal, changes=normalized_changes, updated_at=_now()
                )
                self.proposals.append_revision(
                    proposal,
                    author_id=context.actor_id,
                    summary="Revised proposal",
                )
            elif evidence_supplied:
                proposal.updated_at = _now()
                self.proposals.append_revision(
                    proposal,
                    author_id=context.actor_id,
                    summary="Updated evidence links",
                )
            if evidence_ids is not None:
                self.proposals.set_evidence(
                    workspace_id=context.workspace_id,
                    proposal_id=proposal.id,
                    evidence_ids=evidence_ids,
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="proposal.revised",
                entity_type="proposal",
                entity_id=proposal.id,
                actor_id=context.actor_id,
                snapshot={
                    "proposal_id": str(proposal.id),
                    "consultation_id": str(proposal.consultation_id),
                    "version": proposal.version,
                    "fields": sorted(set(normalized_changes) | ({"evidence_ids"} if evidence_supplied else set())),
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=200,
                    response_body={"proposal_id": str(proposal.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    UPDATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return ProposalResult(proposal=proposal, replayed=False)

    def submit(
        self,
        context: AuthorizationContext,
        proposal_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProposalResult:
        request_fingerprint = fingerprint(
            {
                "operation": SUBMIT_OPERATION,
                "proposal_id": str(proposal_id),
                "version": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, SUBMIT_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            proposal = self.proposals.get_for_update(
                workspace_id=context.workspace_id, proposal_id=proposal_id
            )
            if proposal is None:
                raise _not_found()
            self._require_proposer_or_admin(context, proposal)
            if if_match is not None and if_match != proposal_etag(proposal):
                raise _precondition_failed()
            if proposal.status not in SUBMITTABLE_STATUSES:
                raise _conflict(
                    "Only a draft or changes-requested proposal can be submitted.",
                    code="INVALID_STATE",
                )
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=SUBMIT_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            self.proposals.set_status(
                proposal, status=IN_REVIEW_STATUS, updated_at=_now()
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="proposal.submitted",
                entity_type="proposal",
                entity_id=proposal.id,
                actor_id=context.actor_id,
                snapshot={
                    "proposal_id": str(proposal.id),
                    "consultation_id": str(proposal.consultation_id),
                    "version": proposal.version,
                    "status": proposal.status,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=200,
                    response_body={"proposal_id": str(proposal.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    SUBMIT_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return ProposalResult(proposal=proposal, replayed=False)

    def duplicate(
        self,
        context: AuthorizationContext,
        proposal_id: UUID,
        *,
        title: str | None = None,
        supersede_source: bool = False,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProposalResult:
        """Create an independent copy of a proposal; never creates downstream work."""
        request_fingerprint = fingerprint(
            {
                "operation": DUPLICATE_OPERATION,
                "proposal_id": str(proposal_id),
                "title": title,
                "supersede_source": supersede_source,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                DUPLICATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay

        try:
            source = self.proposals.get_for_update(
                workspace_id=context.workspace_id, proposal_id=proposal_id
            )
            if source is None:
                raise _not_found()
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=DUPLICATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            copy = self.proposals.add(
                workspace_id=context.workspace_id,
                project_id=source.project_id,
                consultation_id=source.consultation_id,
                proposer_id=context.actor_id,
                title=title or f"{source.title} (copy)",
                technical_description=source.technical_description,
                scope=source.scope,
                justification=source.justification,
                acceptance_criteria=list(source.acceptance_criteria),
                checklist=list(source.checklist),
                category=source.category,
                priority=source.priority,
                risks=list(source.risks),
                dependencies=list(source.dependencies),
                estimated_hours=(
                    float(source.estimated_hours)
                    if source.estimated_hours is not None
                    else None
                ),
                duplicated_from_proposal_id=source.id,
                summary=f"Duplicated from {source.id}",
            )
            source_evidence = self.proposals.list_evidence_ids(
                workspace_id=context.workspace_id, proposal_id=source.id
            )
            if source_evidence:
                self.proposals.set_evidence(
                    workspace_id=context.workspace_id,
                    proposal_id=copy.id,
                    evidence_ids=source_evidence,
                )
            if supersede_source and source.status != SUPERSEDED_STATUS:
                self.proposals.supersede(
                    source,
                    superseded_by_proposal_id=copy.id,
                    updated_at=_now(),
                )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="proposal.duplicated",
                entity_type="proposal",
                entity_id=copy.id,
                actor_id=context.actor_id,
                snapshot={
                    "proposal_id": str(copy.id),
                    "consultation_id": str(source.consultation_id),
                    "duplicated_from_proposal_id": str(source.id),
                    "source_superseded": supersede_source
                    and source.status == SUPERSEDED_STATUS,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"proposal_id": str(copy.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    DUPLICATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return ProposalResult(proposal=copy, replayed=False)

    # -- reads ------------------------------------------------------------

    def get(self, context: AuthorizationContext, proposal_id: UUID) -> Proposal:
        proposal = self.proposals.get(
            workspace_id=context.workspace_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise _not_found()
        return proposal

    def list_page(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        *,
        status: str | None = None,
        sort: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[Proposal], str | None]:
        if (
            self.consultations.get(
                workspace_id=context.workspace_id, consultation_id=consultation_id
            )
            is None
        ):
            raise _not_found()
        if status is not None and status not in {
            "draft",
            "in_review",
            "approved",
            "rejected",
            "changes_requested",
            "superseded",
        }:
            raise _validation("Unknown proposal status filter.")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        sort_key, descending = _parse_sort(sort)
        after = (
            _decode_cursor(cursor, sort_key, descending) if cursor is not None else None
        )
        rows = self.proposals.list_for_consultation(
            workspace_id=context.workspace_id,
            consultation_id=consultation_id,
            sort_key=sort_key,
            descending=descending,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            value = getattr(last, sort_key)
            next_cursor = _encode_cursor(sort_key, descending, value, last.id)
        return page, next_cursor

    def list_revisions_page(
        self,
        context: AuthorizationContext,
        proposal_id: UUID,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ):
        if (
            self.proposals.get(
                workspace_id=context.workspace_id, proposal_id=proposal_id
            )
            is None
        ):
            raise _not_found()
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        after_version = _decode_revision_cursor(cursor) if cursor is not None else None
        rows = self.proposals.list_revisions(
            workspace_id=context.workspace_id,
            proposal_id=proposal_id,
            limit=limit + 1,
            after_version=after_version,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = _encode_revision_cursor(page[-1].version) if has_more and page else None
        return page, next_cursor

    def evidence_ids(
        self, context: AuthorizationContext, proposal_id: UUID
    ) -> list[UUID]:
        return self.proposals.list_evidence_ids(
            workspace_id=context.workspace_id, proposal_id=proposal_id
        )

    # -- internals --------------------------------------------------------

    @staticmethod
    def _require_eligible(consultation) -> None:
        if (
            consultation.triaged_at is None
            or consultation.status not in PROPOSAL_ELIGIBLE_STATUSES
        ):
            raise _conflict(
                "The consultation has not completed triage and cannot yield a proposal.",
                code="INVALID_STATE",
            )

    @staticmethod
    def _require_proposer_or_admin(
        context: AuthorizationContext, proposal: Proposal
    ) -> None:
        if proposal.proposer_id == context.actor_id:
            return
        if context.role in ADMINISTRATOR_ROLES:
            return
        raise ProblemError(
            status_code=403,
            code="FORBIDDEN",
            detail="Only the proposer or a workspace administrator may do this.",
            title="Forbidden",
        )

    def _require_evidence(
        self, workspace_id: UUID, consultation_id: UUID, evidence_ids: list[UUID]
    ) -> None:
        for evidence_id in evidence_ids:
            if (
                self.evidence.get(
                    workspace_id=workspace_id,
                    consultation_id=consultation_id,
                    evidence_id=evidence_id,
                )
                is None
            ):
                raise _not_found()

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ProposalResult | None:
        stored = self.idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise ProblemError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                detail="The idempotency key was reused with a different request.",
                title="Conflict",
            )
        proposal_id = (
            stored.response_body.get("proposal_id") if stored.response_body else None
        )
        if proposal_id is None:
            return None
        proposal = self.proposals.get(
            workspace_id=stored.workspace_id, proposal_id=UUID(proposal_id)
        )
        if proposal is None:
            return None
        return ProposalResult(proposal=proposal, replayed=True)

    def _normalize_changes(self, changes: dict[str, object]) -> dict[str, object]:
        allowed = {
            "title",
            "technical_description",
            "scope",
            "justification",
            "acceptance_criteria",
            "checklist",
            "category",
            "priority",
            "risks",
            "dependencies",
            "estimated_hours",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise _validation(
                f"Unexpected proposal field(s): {', '.join(sorted(unexpected))}."
            )
        normalized: dict[str, object] = {}
        if "title" in changes:
            normalized["title"] = self._normalize_title(changes["title"])
        if "technical_description" in changes:
            normalized["technical_description"] = self._normalize_description(
                changes["technical_description"]
            )
        if "scope" in changes:
            normalized["scope"] = self._normalize_scope(changes["scope"])
        if "justification" in changes:
            normalized["justification"] = self._normalize_justification(
                changes["justification"]
            )
        if "category" in changes:
            normalized["category"] = self._normalize_category(changes["category"])
        if "priority" in changes:
            normalized["priority"] = self._normalize_priority(changes["priority"])
        if "acceptance_criteria" in changes:
            normalized["acceptance_criteria"] = self._normalize_criteria(
                changes["acceptance_criteria"]
            )
        if "checklist" in changes:
            normalized["checklist"] = self._normalize_checklist(changes["checklist"])
        if "risks" in changes:
            normalized["risks"] = self._normalize_risks(changes["risks"])
        if "dependencies" in changes:
            normalized["dependencies"] = self._normalize_dependencies(
                changes["dependencies"]
            )
        if "estimated_hours" in changes:
            normalized["estimated_hours"] = self._normalize_estimated_hours(
                changes["estimated_hours"]
            )
        return normalized

    def _normalize(
        self,
        *,
        category,
        priority,
        acceptance_criteria,
        checklist,
        risks,
        dependencies,
        estimated_hours,
    ) -> dict:
        return {
            "category": self._normalize_category(category),
            "priority": self._normalize_priority(priority),
            "acceptance_criteria": self._normalize_criteria(acceptance_criteria),
            "checklist": self._normalize_checklist(checklist),
            "risks": self._normalize_risks(risks),
            "dependencies": self._normalize_dependencies(dependencies),
            "estimated_hours": self._normalize_estimated_hours(estimated_hours),
        }

    @staticmethod
    def _normalize_title(value) -> str:
        if not isinstance(value, str) or not 5 <= len(value) <= 200:
            raise _validation("A proposal title must be 5 to 200 characters.")
        return value

    @staticmethod
    def _normalize_description(value) -> str:
        if not isinstance(value, str) or len(value) < 10:
            raise _validation(
                "A technical description must be at least 10 characters."
            )
        return value

    @staticmethod
    def _normalize_scope(value) -> str:
        if not isinstance(value, str) or len(value) < 5:
            raise _validation("A proposal scope must be at least 5 characters.")
        return value

    @staticmethod
    def _normalize_justification(value) -> str:
        if not isinstance(value, str) or len(value) < 5:
            raise _validation("A proposal justification must be at least 5 characters.")
        return value

    @staticmethod
    def _normalize_category(value) -> str:
        if value not in TRIAGE_CATEGORY_VALUES:
            raise _validation("Unknown triage category.")
        return value

    @staticmethod
    def _normalize_priority(value) -> str:
        if value not in PRIORITY_VALUES:
            raise _validation("Unknown priority.")
        return value

    @staticmethod
    def _normalize_criteria(value) -> list[str]:
        if not isinstance(value, list) or not value:
            raise _validation("At least one acceptance criterion is required.")
        if len(value) > MAX_ACCEPTANCE_CRITERIA:
            raise _validation("Too many acceptance criteria.")
        normalized = []
        for item in value:
            if not isinstance(item, str) or not 1 <= len(item) <= 500:
                raise _validation("Each acceptance criterion must be 1 to 500 characters.")
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_checklist(value) -> list[dict]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise _validation("The checklist must be an array.")
        if len(value) > MAX_CHECKLIST_ITEMS:
            raise _validation("Too many checklist items.")
        normalized = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                raise _validation("Each checklist item must be an object.")
            unexpected = set(item) - {"item_id", "text", "done"}
            if unexpected:
                raise _validation("Each checklist item may only have item_id, text, done.")
            text = item.get("text")
            if not isinstance(text, str) or not 1 <= len(text) <= 200:
                raise _validation("Each checklist item text must be 1 to 200 characters.")
            done = item.get("done", False)
            if not isinstance(done, bool):
                raise _validation("Each checklist item 'done' flag must be a boolean.")
            item_id = item.get("item_id")
            if item_id is None:
                item_id = str(uuid4())
            else:
                try:
                    item_id = str(UUID(str(item_id)))
                except (ValueError, TypeError) as exc:
                    raise _validation("Each checklist item_id must be a UUID.") from exc
            if item_id in seen:
                raise _validation("Checklist item_id values must be unique.")
            seen.add(item_id)
            normalized.append({"item_id": item_id, "text": text, "done": done})
        return normalized

    @staticmethod
    def _normalize_risks(value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 50:
            raise _validation("Risks must be an array of at most 50 entries.")
        normalized = []
        for item in value:
            if not isinstance(item, str) or not 1 <= len(item) <= 500:
                raise _validation("Each risk must be 1 to 500 characters.")
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_dependencies(value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > MAX_DEPENDENCIES:
            raise _validation("Dependencies must be an array of at most 50 entries.")
        normalized = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not 1 <= len(item) <= 200:
                raise _validation("Each dependency must be 1 to 200 characters.")
            if item in seen:
                raise _validation("Dependencies must be unique.")
            seen.add(item)
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_estimated_hours(value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _validation("Estimated hours must be a number.")
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            raise _validation("Estimated hours must be a finite number.")
        if not MIN_ESTIMATED_HOURS <= numeric <= MAX_ESTIMATED_HOURS:
            raise _validation(
                "Estimated hours must be between 0.5 and 9999.99."
            )
        return numeric

    @staticmethod
    def _normalize_evidence_ids(value) -> list[UUID]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > MAX_EVIDENCE_LINKS:
            raise _validation("Evidence must be an array of at most 50 identifiers.")
        normalized: list[UUID] = []
        seen: set[UUID] = set()
        for item in value:
            try:
                evidence_id = UUID(str(item))
            except (ValueError, TypeError) as exc:
                raise _validation("Each evidence identifier must be a UUID.") from exc
            if evidence_id in seen:
                raise _validation("Evidence identifiers must be unique.")
            seen.add(evidence_id)
            normalized.append(evidence_id)
        return normalized
