"""Approval repository: transactional, idempotent proposal decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Approval, Proposal
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.base import Repository
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

DECIDE_OPERATION = "proposal.decide"

_DECISION_TO_PROPOSAL_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
}


@dataclass(frozen=True)
class DecisionResult:
    """Outcome of a decide call."""

    approval: Approval
    replayed: bool


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
    ) -> DecisionResult:
        """Record a decision atomically, replaying retries by idempotency key."""
        if decision not in _DECISION_TO_PROPOSAL_STATUS:
            raise RepositoryError(f"unsupported decision: {decision!r}")

        request_fingerprint = fingerprint(
            {
                "proposal_id": str(proposal_id),
                "proposal_version": proposal_version,
                "decision": decision,
                "justification": justification,
            }
        )

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
        try:
            self._session.flush()
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
            raise AlreadyDecided(
                "a decision already exists for this proposal version"
            ) from exc

        proposal.status = _DECISION_TO_PROPOSAL_STATUS[decision]
        self._audit.append(
            workspace_id=workspace_id,
            action="proposal.decided",
            entity_type="proposal",
            entity_id=proposal_id,
            actor_id=decider_id,
            snapshot={
                "decision": decision,
                "approval_id": str(approval.id),
                "proposal": snapshot,
            },
        )
        self._idempotency.complete(
            record,
            response_status=200,
            response_body={"approval_id": str(approval.id), "decision": decision},
        )
        try:
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
            raise AlreadyDecided(
                "a decision already exists for this proposal version"
            ) from exc
        return DecisionResult(approval=approval, replayed=False)

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
        return DecisionResult(approval=approval, replayed=True)
