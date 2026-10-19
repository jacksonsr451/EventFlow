"""Entity comment application service (Issue #29).

Comments are collaborative annotations, never authoritative state. The service
derives the tenant and author from the verified principal, resolves the target
inside the workspace, and records creation and deletion in the same append-only
audit trail used by the rest of the domain. Deletion is a soft-delete tombstone:
the row and its audit record remain, while the API stops returning the body.

There is deliberately no edit operation. Rewriting a comment would erase the
record of what reviewers actually said.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import ADMINISTRATOR_ROLES
from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import EntityComment
from eventflow_work_management.models.comment import MAX_BODY_LENGTH
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.comment_repository import CommentRepository
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.entity_access import resolve_entity
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)

CREATE_OPERATION = "comment.create"

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

SUPPORTED_SORTS = ("created_at", "-created_at")


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request",
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404,
        code="NOT_FOUND",
        detail="The requested resource was not found.",
        title="Not found",
    )


def _forbidden() -> ProblemError:
    return ProblemError(
        status_code=403,
        code="FORBIDDEN",
        detail="Only the author or a workspace administrator may delete this.",
        title="Forbidden",
    )


def normalize_body(body: str) -> str:
    candidate = body.strip()
    if not candidate:
        raise _validation("The comment body is required.")
    if len(candidate) > MAX_BODY_LENGTH:
        raise ProblemError(
            status_code=422,
            code="VALIDATION_ERROR",
            detail="The comment body is too long.",
            title="Unprocessable entity",
        )
    if any(ord(character) < 32 and character not in "\n\r\t" for character in candidate):
        raise ProblemError(
            status_code=422,
            code="VALIDATION_ERROR",
            detail="The comment body contains unsupported control characters.",
            title="Unprocessable entity",
        )
    return candidate


def comment_etag(comment: EntityComment) -> str:
    """Strong validator; changing the tombstone state changes the ETag."""
    return (
        '"'
        + fingerprint(
            [
                "comment",
                str(comment.id),
                comment.entity_type,
                str(comment.entity_id),
                fingerprint([comment.body]),
                comment.deleted_at.isoformat() if comment.deleted_at else "active",
            ]
        )
        + '"'
    )


@dataclass(frozen=True, slots=True)
class CommentResult:
    comment: EntityComment
    replayed: bool


class CommentService:
    """Authorization, validation, tombstones, audit, and idempotency."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.comments = CommentRepository(session)
        self.audit = AuditRepository(session)
        self.idempotency = IdempotencyRepository(session)

    # -- write ------------------------------------------------------------

    def create(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        body: str,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> CommentResult:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
        )
        normalized = normalize_body(body)
        request_fingerprint = fingerprint(
            {
                "entity_type": entity.entity_type,
                "entity_id": str(entity.entity_id),
                "body": normalized,
            }
        )

        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                entity.entity_type,
                entity.entity_id,
                idempotency_key,
                request_fingerprint,
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
            comment = self.comments.add(
                workspace_id=context.workspace_id,
                project_id=entity.project_id,
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                author_id=context.actor_id,
                body=normalized,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="comment.created",
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                actor_id=context.actor_id,
                snapshot={
                    "comment_id": str(comment.id),
                    "entity_type": entity.entity_type,
                    "entity_id": str(entity.entity_id),
                },
                correlation_id=correlation_id,
            )
            if record is not None:
                self.idempotency.complete(
                    record,
                    response_status=201,
                    response_body={"comment_id": str(comment.id)},
                )
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    entity.entity_type,
                    entity.entity_id,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return replay
            raise
        except ProblemError:
            self._session.rollback()
            raise
        return CommentResult(comment=comment, replayed=False)

    def delete(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        comment_id: UUID,
        correlation_id: UUID | None = None,
    ) -> EntityComment:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
        )
        comment = self._get(
            context.workspace_id, entity.entity_type, entity.entity_id, comment_id
        )
        if (
            comment.author_id != context.actor_id
            and context.role not in ADMINISTRATOR_ROLES
        ):
            raise _forbidden()
        try:
            if comment.deleted_at is not None:
                # Idempotent tombstone: deleting again is a no-op.
                self._session.rollback()
                return comment
            comment = self.comments.soft_delete(
                comment, deleted_by=context.actor_id, deleted_at=datetime.now(UTC)
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="comment.deleted",
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                actor_id=context.actor_id,
                snapshot={
                    "comment_id": str(comment.id),
                    "entity_type": entity.entity_type,
                    "entity_id": str(entity.entity_id),
                },
                correlation_id=correlation_id,
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        return comment

    # -- reads ------------------------------------------------------------

    def get(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        comment_id: UUID,
    ) -> EntityComment:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
        )
        return self._get(
            context.workspace_id, entity.entity_type, entity.entity_id, comment_id
        )

    def list_page(
        self,
        context: AuthorizationContext,
        *,
        collection: str,
        entity_id: UUID,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        sort: str = "created_at",
    ) -> tuple[list[EntityComment], str | None]:
        entity = resolve_entity(
            self._session,
            workspace_id=context.workspace_id,
            collection=collection,
            entity_id=entity_id,
        )
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        normalized_sort = sort.strip() or "created_at"
        if normalized_sort not in SUPPORTED_SORTS:
            raise _validation("The requested sort is not supported.")
        descending = normalized_sort.startswith("-")
        sort_key = normalized_sort.removeprefix("-")

        after = None
        if cursor is not None:
            try:
                payload = decode_cursor(cursor)
                if payload.get("s") != normalized_sort:
                    raise CursorError("cursor bound to a different sort")
                after = (payload["created_at"], payload["id"])
            except (CursorError, KeyError, TypeError, ValueError) as exc:
                raise _validation("The pagination cursor is invalid.") from exc

        rows = self.comments.list_page(
            workspace_id=context.workspace_id,
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
            limit=limit + 1,
            after=after,
            descending=descending,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor(
                {"created_at": last.created_at, "s": normalized_sort}, last.id
            )
        return page, next_cursor

    # -- internals --------------------------------------------------------

    def _get(
        self,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        comment_id: UUID,
    ) -> EntityComment:
        comment = self.comments.get(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            comment_id=comment_id,
        )
        if comment is None:
            raise _not_found()
        return comment

    def _replay(
        self,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> CommentResult | None:
        stored = self.idempotency.get(
            workspace_id=workspace_id,
            operation=CREATE_OPERATION,
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
        comment_id = (
            stored.response_body.get("comment_id") if stored.response_body else None
        )
        if comment_id is None:
            return None
        comment = self.comments.get(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            comment_id=UUID(comment_id),
        )
        if comment is None:
            return None
        return CommentResult(comment=comment, replayed=True)
