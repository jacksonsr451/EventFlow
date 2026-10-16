"""Proposal repository (Issue #6).

One row in ``proposals`` is one independent proposal; its ``version`` is the
current revision scoped to that proposal. Content edits append an immutable
snapshot to ``proposal_revisions``. The repository only flushes; the owning
service commits once so a proposal change, its revision, its audit record, and
its idempotency reservation land in a single transaction.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    Proposal,
    ProposalEvidence,
    ProposalRevision,
)
from eventflow_work_management.repositories.base import Repository

SORT_COLUMNS = {
    "created_at": Proposal.created_at,
    "updated_at": Proposal.updated_at,
    "version": Proposal.version,
    "status": Proposal.status,
}

CONTENT_FIELDS = frozenset(
    {
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
)

_SNAPSHOT_FIELDS = (
    "version",
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
    "status",
)


def proposal_snapshot(proposal: Proposal) -> dict:
    """Return the immutable, JSON-safe content snapshot of a proposal."""
    snapshot: dict = {}
    for field in _SNAPSHOT_FIELDS:
        value = getattr(proposal, field)
        if field == "estimated_hours" and value is not None:
            value = float(value)
        snapshot[field] = value
    return snapshot


class ProposalRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
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
        checklist: list | None = None,
        risks: list | None = None,
        dependencies: list | None = None,
        estimated_hours: float | None = None,
        duplicated_from_proposal_id: UUID | None = None,
        summary: str | None = None,
    ) -> Proposal:
        """Create a new proposal at version 1 and record its first revision."""
        proposal = Proposal(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            consultation_id=consultation_id,
            version=1,
            title=title,
            technical_description=technical_description,
            scope=scope,
            justification=justification,
            acceptance_criteria=acceptance_criteria,
            checklist=checklist or [],
            category=category,
            priority=priority,
            risks=risks or [],
            dependencies=dependencies or [],
            estimated_hours=estimated_hours,
            status="draft",
            proposer_id=proposer_id,
            duplicated_from_proposal_id=duplicated_from_proposal_id,
        )
        self._session.add(proposal)
        self._session.flush()
        self.append_revision(proposal, author_id=proposer_id, summary=summary)
        return proposal

    def get(self, *, workspace_id: UUID, proposal_id: UUID) -> Proposal | None:
        statement = select(Proposal).where(
            Proposal.workspace_id == workspace_id, Proposal.id == proposal_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(
        self, *, workspace_id: UUID, proposal_id: UUID
    ) -> Proposal | None:
        statement = (
            select(Proposal)
            .where(
                Proposal.workspace_id == workspace_id,
                Proposal.id == proposal_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_consultation(
        self,
        *,
        workspace_id: UUID,
        consultation_id: UUID,
        sort_key: str = "created_at",
        descending: bool = False,
        limit: int = 50,
        after: tuple[object, UUID] | None = None,
    ) -> list[Proposal]:
        column = SORT_COLUMNS[sort_key]
        statement = select(Proposal).where(
            Proposal.workspace_id == workspace_id,
            Proposal.consultation_id == consultation_id,
        )
        if after is not None:
            value, after_id = after
            comparison = (
                tuple_(column, Proposal.id) < tuple_(value, after_id)
                if descending
                else tuple_(column, Proposal.id) > tuple_(value, after_id)
            )
            statement = statement.where(comparison)
        ordering = column.desc() if descending else column.asc()
        id_ordering = Proposal.id.desc() if descending else Proposal.id.asc()
        statement = statement.order_by(ordering, id_ordering).limit(limit)
        return list(self._session.execute(statement).scalars())

    def count_for_consultation(
        self, *, workspace_id: UUID, consultation_id: UUID
    ) -> int:
        statement = select(func.count()).select_from(Proposal).where(
            Proposal.workspace_id == workspace_id,
            Proposal.consultation_id == consultation_id,
        )
        return int(self._session.execute(statement).scalar_one())

    def update_content(
        self,
        proposal: Proposal,
        *,
        changes: dict[str, object],
        updated_at: datetime,
    ) -> Proposal:
        """Apply a whitelisted content edit, increment the version, and flush."""
        for field, value in changes.items():
            if field not in CONTENT_FIELDS:
                raise ValueError(f"unexpected proposal field: {field}")
            setattr(proposal, field, value)
        proposal.version += 1
        proposal.updated_at = updated_at
        self._session.flush()
        return proposal

    def append_revision(
        self, proposal: Proposal, *, author_id: UUID, summary: str | None = None
    ) -> ProposalRevision:
        revision = ProposalRevision(
            id=uuid4(),
            workspace_id=proposal.workspace_id,
            proposal_id=proposal.id,
            version=proposal.version,
            author_id=author_id,
            summary=summary,
            snapshot=proposal_snapshot(proposal),
        )
        self._session.add(revision)
        self._session.flush()
        return revision

    def set_status(
        self, proposal: Proposal, *, status: str, updated_at: datetime
    ) -> Proposal:
        proposal.status = status
        proposal.updated_at = updated_at
        self._session.flush()
        return proposal

    def supersede(
        self,
        proposal: Proposal,
        *,
        superseded_by_proposal_id: UUID,
        updated_at: datetime,
    ) -> Proposal:
        proposal.status = "superseded"
        proposal.superseded_by_proposal_id = superseded_by_proposal_id
        proposal.updated_at = updated_at
        self._session.flush()
        return proposal

    def list_revisions(
        self,
        *,
        workspace_id: UUID,
        proposal_id: UUID,
        limit: int = 50,
        after_version: int | None = None,
    ) -> list[ProposalRevision]:
        statement = select(ProposalRevision).where(
            ProposalRevision.workspace_id == workspace_id,
            ProposalRevision.proposal_id == proposal_id,
        )
        if after_version is not None:
            statement = statement.where(ProposalRevision.version > after_version)
        statement = statement.order_by(ProposalRevision.version.asc()).limit(limit)
        return list(self._session.execute(statement).scalars())

    def set_evidence(
        self, *, workspace_id: UUID, proposal_id: UUID, evidence_ids: list[UUID]
    ) -> None:
        self._session.execute(
            delete(ProposalEvidence).where(
                ProposalEvidence.workspace_id == workspace_id,
                ProposalEvidence.proposal_id == proposal_id,
            )
        )
        for evidence_id in evidence_ids:
            self._session.add(
                ProposalEvidence(
                    workspace_id=workspace_id,
                    proposal_id=proposal_id,
                    evidence_id=evidence_id,
                )
            )
        self._session.flush()

    def list_evidence_ids(
        self, *, workspace_id: UUID, proposal_id: UUID
    ) -> list[UUID]:
        statement = (
            select(ProposalEvidence.evidence_id)
            .where(
                ProposalEvidence.workspace_id == workspace_id,
                ProposalEvidence.proposal_id == proposal_id,
            )
            .order_by(ProposalEvidence.created_at, ProposalEvidence.evidence_id)
        )
        return list(self._session.execute(statement).scalars())
