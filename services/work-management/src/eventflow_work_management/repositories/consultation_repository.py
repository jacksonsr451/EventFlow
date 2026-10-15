"""Consultation repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import Consultation
from eventflow_work_management.repositories.base import Repository


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

    def get(self, *, workspace_id: UUID, consultation_id: UUID) -> Consultation | None:
        statement = select(Consultation).where(
            Consultation.workspace_id == workspace_id,
            Consultation.id == consultation_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_project(self, *, workspace_id: UUID, project_id: UUID) -> list[Consultation]:
        statement = (
            select(Consultation)
            .where(
                Consultation.workspace_id == workspace_id,
                Consultation.project_id == project_id,
            )
            .order_by(Consultation.created_at)
        )
        return list(self._session.execute(statement).scalars())
