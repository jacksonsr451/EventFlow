"""Entity comment repository (Issue #29).

Only flushes; the owning service commits once so a comment, its audit record, and
any idempotency reservation land in one transaction.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import EntityComment
from eventflow_work_management.repositories.base import Repository


class CommentRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        entity_type: str,
        entity_id: UUID,
        author_id: UUID,
        body: str,
    ) -> EntityComment:
        comment = EntityComment(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            author_id=author_id,
            body=body,
        )
        self._session.add(comment)
        self._session.flush()
        return comment

    def get(
        self,
        *,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        comment_id: UUID,
    ) -> EntityComment | None:
        statement = select(EntityComment).where(
            EntityComment.workspace_id == workspace_id,
            EntityComment.entity_type == entity_type,
            EntityComment.entity_id == entity_id,
            EntityComment.id == comment_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        entity_type: str,
        entity_id: UUID,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
        descending: bool = False,
    ) -> list[EntityComment]:
        statement = select(EntityComment).where(
            EntityComment.workspace_id == workspace_id,
            EntityComment.entity_type == entity_type,
            EntityComment.entity_id == entity_id,
        )
        if after is not None:
            created_at, after_id = after
            comparison = (
                tuple_(EntityComment.created_at, EntityComment.id)
                < tuple_(created_at, after_id)
                if descending
                else tuple_(EntityComment.created_at, EntityComment.id)
                > tuple_(created_at, after_id)
            )
            statement = statement.where(comparison)
        ordering = (
            (EntityComment.created_at.desc(), EntityComment.id.desc())
            if descending
            else (EntityComment.created_at, EntityComment.id)
        )
        statement = statement.order_by(*ordering).limit(limit)
        return list(self._session.execute(statement).scalars())

    def soft_delete(
        self, comment: EntityComment, *, deleted_by: UUID, deleted_at: datetime
    ) -> EntityComment:
        comment.deleted_at = deleted_at
        comment.deleted_by = deleted_by
        self._session.flush()
        return comment
