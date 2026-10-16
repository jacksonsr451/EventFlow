"""Proposal evidence association model (Issue #6).

A proposal may cite the structured evidence already recorded on its
consultation. The join table keeps the association tenant-scoped: both the
proposal and the evidence must belong to the same workspace, so a proposal can
never cite evidence from another tenant.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index, PrimaryKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, CreatedAtMixin


class ProposalEvidence(CreatedAtMixin, Base):
    """Associates a proposal with consultation evidence in the same workspace."""

    __tablename__ = "proposal_evidence"

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["proposals.workspace_id", "proposals.id"],
            name="fk_proposal_evidence_workspace_proposal",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["consultation_evidence.workspace_id", "consultation_evidence.id"],
            name="fk_proposal_evidence_workspace_evidence",
            ondelete="CASCADE",
        ),
        PrimaryKeyConstraint("proposal_id", "evidence_id", name="pk_proposal_evidence"),
        Index("ix_proposal_evidence_workspace_id", "workspace_id"),
        Index("ix_proposal_evidence_evidence_id", "evidence_id"),
    )
