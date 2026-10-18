"""Approval repository: transactional, idempotent proposal decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Approval, BoardCard, Proposal, WorkItem
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.base import Repository
from eventflow_work_management.repositories.board_repository import BoardCardRepository
from eventflow_work_management.repositories.errors import (
    AlreadyDecided,
    EntityNotFound,
    IdempotencyConflict,
    RepositoryError,
    VersionMismatch,
)
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.work_item_repository import (
    WorkItemRepository,
)

DECIDE_OPERATION = "proposal.decide"


@dataclass(frozen=True)
class BoardPlacement:
    """Where an approved WorkItem's card is placed on the board."""

    board_id: UUID
    column_id: str
    rank: str


_DECISION_TO_PROPOSAL_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
}


@dataclass(frozen=True)
class DecisionResult:
    """Outcome of a decide call.

    ``work_item`` and ``board_card`` are always populated for an ``approved``
    decision (created atomically with the Approval) and are ``None`` otherwise.
    """

    approval: Approval
    replayed: bool
    work_item: WorkItem | None = None
    board_card: BoardCard | None = None


def _proposal_snapshot(proposal: Proposal) -> dict:
    """Immutable snapshot of the proposal state that was decided."""
    return {
        "proposal_id": str(proposal.id),
        "version": proposal.version,
        "status": proposal.status,
        "title": proposal.title,
        "category": proposal.category,
        "priority": proposal.priority,
        "acceptance_criteria": proposal.acceptance_criteria,
    }


class ApprovalRepository(Repository):
    """Records decisions with exactly-once effects for a given key."""

    def __init__(
        self,
        session: Session,
        *,
        audit_repository: AuditRepository | None = None,
        idempotency_repository: IdempotencyRepository | None = None,
    ) -> None:
        super().__init__(session)
        self._audit = audit_repository or AuditRepository(session)
        self._idempotency = idempotency_repository or IdempotencyRepository(session)

    def _existing_approval(
        self, workspace_id: UUID, proposal_id: UUID, proposal_version: int
    ) -> Approval | None:
        statement = select(Approval).where(
            Approval.workspace_id == workspace_id,
            Approval.proposal_id == proposal_id,
            Approval.proposal_version == proposal_version,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def decide(
        self,
        *,
        workspace_id: UUID,
        proposal_id: UUID,
        proposal_version: int,
        decider_id: UUID,
        decision: str,
        justification: str,
        idempotency_key: str,
        placement: BoardPlacement | None = None,
        audit_action: str | None = None,
        request_fingerprint: str | None = None,
        correlation_id: UUID | None = None,
    ) -> DecisionResult:
        """Record a decision atomically, replaying retries by idempotency key.

        When an ``approved`` decision is given a ``placement``, the WorkItem and
        its initial BoardCard are inserted in the same transaction as the
        Approval, the Proposal status change, the audit records and the
        idempotency record. Any failure rolls the entire transaction back, so no
        orphaned WorkItem or BoardCard can survive an incomplete decision.
        """
        if decision not in _DECISION_TO_PROPOSAL_STATUS:
            raise RepositoryError(f"unsupported decision: {decision!r}")

        if request_fingerprint is None:
            request_fingerprint = fingerprint(
                {
                    "proposal_id": str(proposal_id),
                    "proposal_version": proposal_version,
                    "decision": decision,
                    "justification": justification,
                }
            )
        resolved_audit_action = audit_action or "proposal.decided"

        stored = self._idempotency.get(
            workspace_id=workspace_id,
            operation=DECIDE_OPERATION,
            idempotency_key=idempotency_key,
        )
        if stored is not None:
            return self._replay(
                stored, request_fingerprint, workspace_id, proposal_id, proposal_version
            )

        proposal = self._session.get(Proposal, proposal_id)
        if proposal is None or proposal.workspace_id != workspace_id:
            raise EntityNotFound("proposal not found in workspace")
        if proposal.version != proposal_version:
            raise VersionMismatch(
                f"proposal version {proposal.version} does not match {proposal_version}"
            )

        if (
            self._existing_approval(workspace_id, proposal_id, proposal_version)
            is not None
        ):
            replay = self._replay_if_available(
                workspace_id,
                proposal_id,
                proposal_version,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay
            raise AlreadyDecided("a decision already exists for this proposal version")

        try:
            record = self._idempotency.reserve(
                workspace_id=workspace_id,
                operation=DECIDE_OPERATION,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        except IntegrityError as exc:
            self._session.rollback()
            replay = self._replay_if_available(
                workspace_id,
                proposal_id,
                proposal_version,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay
            raise IdempotencyConflict("idempotency key is already in use") from exc

        snapshot = _proposal_snapshot(proposal)
        approval = Approval(
            id=uuid4(),
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            workspace_id=workspace_id,
            decider_id=decider_id,
            decision=decision,
            decision_justification=justification,
            idempotency_key=idempotency_key,
            decided_at=datetime.now(UTC),
            audit_snapshot_hash=fingerprint(snapshot),
        )
        self._session.add(approval)
        work_item: WorkItem | None = None
        board_card: BoardCard | None = None
        try:
            # Flush the Approval now so the WorkItem origin trigger can see the
            # approved decision and the (proposal_id, version) uniqueness is
            # enforced before any downstream row is written.
            self._session.flush()
            proposal.status = _DECISION_TO_PROPOSAL_STATUS[decision]
            proposal.reviewer_id = decider_id
            if decision == "approved" and placement is not None:
                work_item = WorkItemRepository(
                    self._session
                ).build_from_approved_proposal(
                    workspace_id=workspace_id,
                    project_id=proposal.project_id,
                    proposal_id=proposal_id,
                    proposal_version=proposal_version,
                    approval_id=approval.id,
                    title=proposal.title,
                    description=proposal.technical_description,
                    acceptance_criteria=list(proposal.acceptance_criteria),
                    category=proposal.category,
                    priority=proposal.priority,
                )
                board_card = BoardCardRepository(self._session).build_card(
                    workspace_id=workspace_id,
                    board_id=placement.board_id,
                    work_item_id=work_item.id,
                    column_id=placement.column_id,
                    rank=placement.rank,
                    title=proposal.title,
                    priority=proposal.priority,
                    category=proposal.category,
                )
                self._audit.append(
                    workspace_id=workspace_id,
                    action="work_item.created",
                    entity_type="work_item",
                    entity_id=work_item.id,
                    actor_id=decider_id,
                    snapshot={
                        "work_item_id": str(work_item.id),
                        "origin_proposal_id": str(proposal_id),
                        "origin_proposal_version": proposal_version,
                        "origin_approval_id": str(approval.id),
                        "status": work_item.status,
                    },
                    correlation_id=correlation_id,
                )
                self._audit.append(
                    workspace_id=workspace_id,
                    action="board_card.created",
                    entity_type="board_card",
                    entity_id=board_card.id,
                    actor_id=decider_id,
                    snapshot={
                        "card_id": str(board_card.id),
                        "board_id": str(placement.board_id),
                        "column_id": placement.column_id,
                        "work_item_id": str(work_item.id),
                        "rank": board_card.rank,
                    },
                    correlation_id=correlation_id,
                )
            self._audit.append(
                workspace_id=workspace_id,
                action=resolved_audit_action,
                entity_type="proposal",
                entity_id=proposal_id,
                actor_id=decider_id,
                snapshot={
                    "decision": decision,
                    "approval_id": str(approval.id),
                    "proposal": snapshot,
                },
                correlation_id=correlation_id,
            )
            self._idempotency.complete(
                record,
                response_status=200,
                response_body={
                    "approval_id": str(approval.id),
                    "decision": decision,
                    "work_item_id": str(work_item.id) if work_item else None,
                    "board_card_id": str(board_card.id) if board_card else None,
                },
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            replay = self._replay_if_available(
                workspace_id,
                proposal_id,
                proposal_version,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay
            if self._existing_approval(workspace_id, proposal_id, proposal_version):
                raise AlreadyDecided(
                    "a decision already exists for this proposal version"
                ) from exc
            raise RepositoryError(
                "the decision could not be recorded atomically"
            ) from exc
        return DecisionResult(
            approval=approval,
            replayed=False,
            work_item=work_item,
            board_card=board_card,
        )

    def _replay_if_available(
        self,
        workspace_id: UUID,
        proposal_id: UUID,
        proposal_version: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> DecisionResult | None:
        """Return the stored decision for this key when one exists."""
        stored = self._idempotency.get(
            workspace_id=workspace_id,
            operation=DECIDE_OPERATION,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        return self._replay(
            stored, request_fingerprint, workspace_id, proposal_id, proposal_version
        )

    def _replay(
        self,
        stored,
        request_fingerprint: str,
        workspace_id: UUID,
        proposal_id: UUID,
        proposal_version: int,
    ) -> DecisionResult:
        if stored.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key was reused with a different request"
            )
        approval = self._existing_approval(workspace_id, proposal_id, proposal_version)
        if approval is None:
            raise RepositoryError("idempotency record has no matching approval")
        body = stored.response_body or {}
        work_item = (
            self._session.get(WorkItem, UUID(body["work_item_id"]))
            if body.get("work_item_id")
            else None
        )
        board_card = (
            self._session.get(BoardCard, UUID(body["board_card_id"]))
            if body.get("board_card_id")
            else None
        )
        return DecisionResult(
            approval=approval,
            replayed=True,
            work_item=work_item,
            board_card=board_card,
        )
