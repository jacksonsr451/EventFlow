"""Consultation repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import Consultation
from eventflow_work_management.repositories.base import Repository

SORT_COLUMNS = {
    "created_at": Consultation.created_at,
    "updated_at": Consultation.updated_at,
    "priority": Consultation.priority,
    "status": Consultation.status,
}


class ConsultationRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        author_id: UUID,
        origin: str,
        title: str,
        description: str,
        priority: str,
        category: str | None = None,
        assignee_id: UUID | None = None,
        editor_context: dict | None = None,
        external_references: list | None = None,
    ) -> Consultation:
        consultation = Consultation(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            author_id=author_id,
            assignee_id=assignee_id,
            origin=origin,
            title=title,
            description=description,
            category=category,
            priority=priority,
            editor_context=editor_context,
            external_references=external_references or [],
        )
        self._session.add(consultation)
        self._session.commit()
        return consultation

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        author_id: UUID,
        origin: str,
        title: str,
        description: str,
        priority: str = "medium",
        category: str | None = None,
        editor_context: dict | None = None,
        external_references: list | None = None,
    ) -> Consultation:
        """Add a consultation and flush without committing.

        The owning service commits once so intake, its audit record, and any
        idempotency reservation land in a single transaction.
        """
        consultation = Consultation(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            author_id=author_id,
            origin=origin,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status="open",
            editor_context=editor_context,
            external_references=external_references or [],
        )
        self._session.add(consultation)
        self._session.flush()
        return consultation

    def get(self, *, workspace_id: UUID, consultation_id: UUID) -> Consultation | None:
        statement = select(Consultation).where(
            Consultation.workspace_id == workspace_id,
            Consultation.id == consultation_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, consultation_id: UUID
    ) -> Consultation | None:
        statement = (
            select(Consultation)
            .where(
                Consultation.workspace_id == workspace_id,
                Consultation.id == consultation_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_project(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> list[Consultation]:
        statement = (
            select(Consultation)
            .where(
                Consultation.workspace_id == workspace_id,
                Consultation.project_id == project_id,
            )
            .order_by(Consultation.created_at)
        )
        return list(self._session.execute(statement).scalars())

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        sort_key: str = "created_at",
        descending: bool = False,
        limit: int = 50,
        after: tuple[object, UUID] | None = None,
    ) -> list[Consultation]:
        """Return a keyset page ordered by ``sort_key`` with an id tiebreaker."""
        column = SORT_COLUMNS[sort_key]
        statement = select(Consultation).where(Consultation.workspace_id == workspace_id)
        if status is not None:
            statement = statement.where(Consultation.status == status)
        if category is not None:
            statement = statement.where(Consultation.category == category)
        if priority is not None:
            statement = statement.where(Consultation.priority == priority)
        if after is not None:
            value, after_id = after
            comparison = (
                tuple_(column, Consultation.id) < tuple_(value, after_id)
                if descending
                else tuple_(column, Consultation.id) > tuple_(value, after_id)
            )
            statement = statement.where(comparison)
        ordering = column.desc() if descending else column.asc()
        id_ordering = Consultation.id.desc() if descending else Consultation.id.asc()
        statement = statement.order_by(ordering, id_ordering).limit(limit)
        return list(self._session.execute(statement).scalars())

    def apply_triage(
        self,
        consultation: Consultation,
        *,
        category: str,
        priority: str,
        status: str,
        triage_notes: str,
        triage_criteria: dict,
        triaged_by: UUID,
        triaged_at: datetime,
    ) -> None:
        consultation.category = category
        consultation.priority = priority
        consultation.status = status
        consultation.triage_notes = triage_notes
        consultation.triage_criteria = triage_criteria
        consultation.triaged_by = triaged_by
        consultation.triaged_at = triaged_at
        consultation.updated_at = triaged_at
        self._session.flush()
