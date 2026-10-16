"""Consultation application service: multi-source intake, reads, and triage.

Every public method is one unit of work: it authorizes through
``AuthorizationService`` (the tenant and actor are derived from the verified
principal, never from the request body), performs a single transactional change,
writes an append-only audit record, and commits exactly once. Optional
idempotency replay is stored in the same transaction as the change so a retried
submission never duplicates a consultation.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Consultation
from eventflow_work_management.models.enums import (
    CONSULTATION_STATUS_VALUES,
    ORIGIN_VALUES,
    PRIORITY_VALUES,
    TRIAGE_CATEGORY_VALUES,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.consultation_repository import (
    SORT_COLUMNS,
    ConsultationRepository,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
)
from eventflow_work_management.security.errors import ProblemError

CREATE_OPERATION = "consultation.create"
TRIAGE_OPERATION = "consultation.triage"

DEFAULT_PRIORITY = "medium"

TRIAGE_START_STATUSES = frozenset({"open", "reopened"})

CRITERIA_FIELD_FOR_CATEGORY = {
    "bug": "bug_criteria",
    "feature": "feature_criteria",
    "chore": "chore_criteria",
    "docs": "docs_criteria",
    "security": "security_criteria",
}

ALLOWED_SORT_KEYS = frozenset(SORT_COLUMNS)

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

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
    return ProblemError(
        status_code=409, code=code, detail=detail, title="Conflict"
    )


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def consultation_etag(consultation: Consultation) -> str:
    """Strong validator over the persisted consultation version."""
    return f'"{fingerprint(["consultation", str(consultation.id), consultation.updated_at.isoformat()])}"'


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """A persisted consultation plus whether it was served from an idempotent replay."""

    consultation: Consultation
    replayed: bool


def _encode_cursor(sort_key: str, descending: bool, value, consultation_id: UUID) -> str:
    payload = {
        "k": sort_key,
        "d": descending,
        "v": value.isoformat() if isinstance(value, datetime) else value,
        "id": str(consultation_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str, sort_key: str, descending: bool) -> tuple:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        if payload["k"] != sort_key or payload["d"] is not descending:
            raise ValueError("cursor is bound to a different sort")
        consultation_id = UUID(payload["id"])
        value = payload["v"]
        if sort_key in {"created_at", "updated_at"}:
            value = datetime.fromisoformat(value)
        return value, consultation_id
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


class ConsultationService:
    """Authorization, validation, and persistence for consultation intake."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.consultations = ConsultationRepository(session)
        self.projects = ProjectRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    # -- intake -----------------------------------------------------------

    def submit(
        self,
        context: AuthorizationContext,
        *,
        project_id: UUID,
        origin: str,
        title: str,
        description: str,
        category: str | None = None,
        editor_context: dict | None = None,
        external_references: list | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> IntakeResult:
        self._validate_origin(origin)
        self._validate_category(category)
        self._validate_editor_context(editor_context)
        self._require_project(context.workspace_id, project_id)

        request_fingerprint = fingerprint(
            {
                "project_id": str(project_id),
                "origin": origin,
                "title": title,
                "description": description,
                "category": category,
                "editor_context": editor_context,
                "external_references": external_references or [],
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, CREATE_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
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
            consultation = self.consultations.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                author_id=context.actor_id,
                origin=origin,
                title=title,
                description=description,
                priority=DEFAULT_PRIORITY,
                category=category,
                editor_context=editor_context,
                external_references=external_references,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="consultation.created",
                entity_type="consultation",
                entity_id=consultation.id,
                actor_id=context.actor_id,
                snapshot={
                    "consultation_id": str(consultation.id),
                    "project_id": str(project_id),
                    "origin": origin,
                    "status": consultation.status,
                    "category": category,
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"consultation_id": str(consultation.id)},
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
        return IntakeResult(consultation=consultation, replayed=False)

    # -- reads ------------------------------------------------------------

    def get(
        self, context: AuthorizationContext, consultation_id: UUID
    ) -> Consultation:
        consultation = self.consultations.get(
            workspace_id=context.workspace_id, consultation_id=consultation_id
        )
        if consultation is None:
            raise _not_found()
        return consultation

    def list_page(
        self,
        context: AuthorizationContext,
        *,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        sort: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[Consultation], str | None]:
        self._validate_category(category)
        self._validate_priority(priority)
        if status is not None and status not in CONSULTATION_STATUS_VALUES:
            raise _validation("Unknown consultation status filter.")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        sort_key, descending = _parse_sort(sort)
        after = (
            _decode_cursor(cursor, sort_key, descending) if cursor is not None else None
        )
        rows = self.consultations.list_for_workspace(
            workspace_id=context.workspace_id,
            status=status,
            category=category,
            priority=priority,
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

    # -- triage -----------------------------------------------------------

    def triage(
        self,
        context: AuthorizationContext,
        consultation_id: UUID,
        *,
        category: str,
        priority: str,
        triage_notes: str,
        criteria: dict,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> IntakeResult:
        self._validate_category(category, required=True)
        self._validate_priority(priority, required=True)
        self._validate_triage_criteria(category, criteria)

        request_fingerprint = fingerprint(
            {
                "consultation_id": str(consultation_id),
                "category": category,
                "priority": priority,
                "triage_notes": triage_notes,
                "criteria": criteria,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id, TRIAGE_OPERATION, idempotency_key, request_fingerprint
            )
            if replay is not None:
                return replay

        try:
            consultation = self.consultations.get_for_update(
                workspace_id=context.workspace_id, consultation_id=consultation_id
            )
            if consultation is None:
                raise _not_found()
            if if_match is not None and if_match != consultation_etag(consultation):
                raise _precondition_failed()
            if consultation.status not in TRIAGE_START_STATUSES:
                raise _conflict(
                    "The consultation is not in a state that can be triaged.",
                    code="INVALID_STATE",
                )
            record = (
                self.idempotency.reserve(
                    workspace_id=context.workspace_id,
                    operation=TRIAGE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                )
                if idempotency_key is not None
                else None
            )
            self.consultations.apply_triage(
                consultation,
                category=category,
                priority=priority,
                status="triaging",
                triage_notes=triage_notes,
                triage_criteria=criteria,
                triaged_by=context.actor_id,
                triaged_at=_now(),
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="consultation.triaged",
                entity_type="consultation",
                entity_id=consultation.id,
                actor_id=context.actor_id,
                snapshot={
                    "consultation_id": str(consultation.id),
                    "category": category,
                    "priority": priority,
                    "status": "triaging",
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=200,
                    response_body={"consultation_id": str(consultation.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    TRIAGE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return IntakeResult(consultation=consultation, replayed=False)

    # -- internals --------------------------------------------------------

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> IntakeResult | None:
        """Return a stored consultation for a replayed key, without side effects."""
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
        consultation_id = (
            stored.response_body.get("consultation_id")
            if stored.response_body
            else None
        )
        if consultation_id is None:
            return None
        consultation = self.consultations.get(
            workspace_id=stored.workspace_id, consultation_id=UUID(consultation_id)
        )
        if consultation is None:
            return None
        return IntakeResult(consultation=consultation, replayed=True)

    @staticmethod
    def _validate_origin(origin: str) -> None:
        if origin not in ORIGIN_VALUES:
            raise _validation("Unknown consultation origin.")

    @staticmethod
    def _validate_category(category: str | None, *, required: bool = False) -> None:
        if category is None:
            if required:
                raise _validation("A triage category is required.")
            return
        if category not in TRIAGE_CATEGORY_VALUES:
            raise _validation("Unknown triage category.")

    @staticmethod
    def _validate_priority(priority: str | None, *, required: bool = False) -> None:
        if priority is None:
            if required:
                raise _validation("A priority is required.")
            return
        if priority not in PRIORITY_VALUES:
            raise _validation("Unknown priority.")

    @staticmethod
    def _validate_editor_context(editor_context: dict | None) -> None:
        if editor_context is None:
            return
        required = {
            "repository",
            "branch",
            "commit_sha",
            "file_path",
            "line_start",
            "line_end",
            "consent_granted",
        }
        if not required <= set(editor_context):
            raise _validation("Editor context is incomplete.")
        if editor_context.get("consent_granted") is not True:
            raise _validation(
                "Editor context requires explicit developer consent.",
                status_code=422,
            )

    @staticmethod
    def _validate_triage_criteria(category: str, criteria: dict) -> None:
        expected = CRITERIA_FIELD_FOR_CATEGORY[category]
        provided = {key for key, value in criteria.items() if value is not None}
        if provided != {expected}:
            raise _validation(
                "Triage criteria must match the selected category.",
                status_code=422,
            )

    def _require_project(self, workspace_id: UUID, project_id: UUID) -> None:
        if self.projects.get(workspace_id=workspace_id, project_id=project_id) is None:
            raise _not_found()
