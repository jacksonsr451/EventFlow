"""Proposal repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eventflow_work_management.models import Proposal
from eventflow_work_management.repositories.base import Repository
from eventflow_work_management.repositories.errors import EntityNotFound


class ProposalRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def _next_version(self, consultation_id: UUID) -> int:
        statement = select(func.max(Proposal.version)).where(
            Proposal.consultation_id == consultation_id
        )
        current = self._session.execute(statement).scalar_one()
        return (current or 0) + 1

    def create(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        consultation_id: UUID,
        proposer_id: UUID,
        title: str,
        technical_description: str,
        scope: str,
        justification: str,
        acceptance_criteria: list,
        category: str,
        priority: str,
        risks: list | None = None,
        dependencies: list | None = None,
        estimated_hours: float | None = None,
    ) -> Proposal:
        proposal = Proposal(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            consultation_id=consultation_id,
            version=self._next_version(consultation_id),
            title=title,
            technical_description=technical_description,
            scope=scope,
            justification=justification,
            acceptance_criteria=acceptance_criteria,
            category=category,
            priority=priority,
            risks=risks or [],
            dependencies=dependencies or [],
            estimated_hours=estimated_hours,
            proposer_id=proposer_id,
        )
        self._session.add(proposal)
        self._session.commit()
        return proposal

    def get(self, *, workspace_id: UUID, proposal_id: UUID) -> Proposal | None:
        statement = select(Proposal).where(
            Proposal.workspace_id == workspace_id, Proposal.id == proposal_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def submit(self, *, workspace_id: UUID, proposal_id: UUID) -> Proposal:
        proposal = self.get(workspace_id=workspace_id, proposal_id=proposal_id)
        if proposal is None:
            raise EntityNotFound("proposal not found")
        proposal.status = "in_review"
        self._session.commit()
        return proposal
