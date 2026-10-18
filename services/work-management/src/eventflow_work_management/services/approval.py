"""Proposal review, approval, rejection and revision service (Issue #7).

A decision is the critical gateway where a proposal becomes authoritative
execution work. This service authorizes the actor, pins the decision to an exact
proposal version, rejects stale or self-approvals, and records the decision, its
audit trail, and (on approval) the generated ``WorkItem`` and initial
``BoardCard`` in one transaction.

The route layer performs the role check through ``AuthorizationService`` before
calling here, so an unauthorized decision never reaches a mutation. Idempotency
is durable: the ``Idempotency-Key`` is stored with the decision and a retry
replays the original ``Approval``/``WorkItem``/``BoardCard`` without creating a
second set of rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models import Approval, BoardCard, Proposal, WorkItem
from eventflow_work_management.repositories.approval_repository import (
    DECIDE_OPERATION,
    ApprovalRepository,
    BoardPlacement,
)
from eventflow_work_management.repositories.board_repository import BoardRepository
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
from eventflow_work_management.repositories.proposal_repository import (
    ProposalRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.proposal import proposal_etag

DECISIONS = ("approved", "rejected", "changes_requested")
DECIDABLE_STATUS = "in_review"
INITIAL_COLUMN_ID = "ready"

_NOT_FOUND = "The requested resource was not found."


def decision_fingerprint(
    *,
    workspace_id: UUID,
    proposal_id: UUID,
    proposal_version: int,
    decision: str,
    justification: str,
    target_board_id: UUID | None,
) -> str:
    """Canonical request fingerprint binding one idempotency key to one request."""
    return fingerprint(
        {
            "operation": DECIDE_OPERATION,
            "workspace_id": str(workspace_id),
            "proposal_id": str(proposal_id),
            "proposal_version": proposal_version,
            "decision": decision,
            "justification": justification,
            "target_board_id": str(target_board_id) if target_board_id else None,
        }
    )


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _conflict(detail: str, *, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def _self_approval_disallowed() -> ProblemError:
    return ProblemError(
        status_code=403,
        code="SELF_APPROVAL_DISALLOWED",
        detail="Proposer cannot approve their own proposal.",
        title="Forbidden",
    )


def _idempotency_conflict() -> ProblemError:
    return ProblemError(
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        detail="The idempotency key was reused with a different request.",
        title="Conflict",
    )


@dataclass(frozen=True)
class ApprovalOutcome:
    """The full result of a decision, including any generated downstream work."""

    approval: Approval
    proposal: Proposal
    etag: str
    replayed: bool
    work_item: WorkItem | None = None
    board_card: BoardCard | None = None


class ApprovalService:
    """Authorizes, validates, and records proposal decisions atomically."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._proposals = ProposalRepository(session)
        self._approvals = ApprovalRepository(session)
        self._boards = BoardRepository(session)
        self._idempotency = IdempotencyRepository(session)

    def decide(
        self,
        context: AuthorizationContext,
        proposal_id: UUID,
        *,
        decision: str,
        proposal_version: int,
        justification: str,
        target_board_id: UUID | None = None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ApprovalOutcome:
        if decision not in DECISIONS:
            raise _validation("Unknown approval decision.")
        if not isinstance(justification, str) or len(justification) < 3:
            raise _validation("A decision justification is required.")
        if not isinstance(proposal_version, int) or proposal_version < 1:
            raise _validation("proposal_version must be a positive integer.")
        if idempotency_key is None:
            raise _validation("The Idempotency-Key header is required.")

        request_fingerprint = decision_fingerprint(
            workspace_id=context.workspace_id,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            decision=decision,
            justification=justification,
            target_board_id=target_board_id,
        )

        # Fast idempotent replay before taking the row lock.
        stored = self._idempotency.get(
            workspace_id=context.workspace_id,
            operation=DECIDE_OPERATION,
            idempotency_key=idempotency_key,
        )
        if stored is not None:
            return self._replay(context, stored, request_fingerprint)

        try:
            proposal = self._proposals.get_for_update(
                workspace_id=context.workspace_id, proposal_id=proposal_id
            )
            if proposal is None:
                raise _not_found()
            # Re-check under the lock so a concurrent decision with the same key
            # replays instead of being mistaken for a second, stale decision.
            stored = self._idempotency.get(
                workspace_id=context.workspace_id,
                operation=DECIDE_OPERATION,
                idempotency_key=idempotency_key,
            )
            if stored is not None:
                return self._replay(context, stored, request_fingerprint)
            if if_match is not None and if_match != proposal_etag(proposal):
                raise _precondition_failed()
            if proposal.version != proposal_version:
                raise _conflict(
                    f"Proposal version {proposal_version} is superseded by "
                    f"version {proposal.version}.",
                    code="STALE_VERSION",
                )
            if proposal.status != DECIDABLE_STATUS:
                raise _conflict(
                    "Only a proposal under review can be decided.",
                    code="INVALID_STATE",
                )
            placement: BoardPlacement | None = None
            if decision == "approved":
                if proposal.proposer_id == context.actor_id:
                    raise _self_approval_disallowed()
                placement = self._placement(context, proposal, target_board_id)
            result = self._approvals.decide(
                workspace_id=context.workspace_id,
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                decider_id=context.actor_id,
                decision=decision,
                justification=justification,
                idempotency_key=idempotency_key,
                placement=placement,
                audit_action=f"proposal.{decision}",
                request_fingerprint=request_fingerprint,
                correlation_id=correlation_id,
            )
        except ProblemError:
            self._session.rollback()
            raise
        except VersionMismatch as exc:
            self._session.rollback()
            raise _conflict(str(exc), code="STALE_VERSION") from exc
        except AlreadyDecided as exc:
            self._session.rollback()
            raise _conflict(
                "A decision already exists for this proposal version.",
                code="ALREADY_DECIDED",
            ) from exc
        except IdempotencyConflict as exc:
            self._session.rollback()
            raise _idempotency_conflict() from exc
        except EntityNotFound as exc:
            self._session.rollback()
            raise _not_found() from exc
        except RepositoryError as exc:
            self._session.rollback()
            raise _conflict("The decision could not be recorded.") from exc

        return ApprovalOutcome(
            approval=result.approval,
            proposal=proposal,
            etag=proposal_etag(proposal),
            replayed=result.replayed,
            work_item=result.work_item,
            board_card=result.board_card,
        )

    # -- internals --------------------------------------------------------

    def _placement(
        self,
        context: AuthorizationContext,
        proposal: Proposal,
        target_board_id: UUID | None,
    ) -> BoardPlacement:
        if target_board_id is None:
            raise _validation("target_board_id is required when approving a proposal.")
        board = self._boards.get(
            workspace_id=context.workspace_id, board_id=target_board_id
        )
        if board is None or board.project_id != proposal.project_id:
            raise _not_found()
        # A random opaque rank keeps the append collision-free under concurrency
        # while matching the persisted rank constraint.
        return BoardPlacement(
            board_id=board.id, column_id=INITIAL_COLUMN_ID, rank=uuid4().hex
        )

    def _replay(
        self,
        context: AuthorizationContext,
        stored,
        request_fingerprint: str,
    ) -> ApprovalOutcome:
        if stored.request_fingerprint != request_fingerprint:
            raise _idempotency_conflict()
        body = stored.response_body or {}
        approval_id = body.get("approval_id")
        if approval_id is None:
            raise _conflict(
                "The original decision response is unavailable.",
                code="INVALID_STATE",
            )
        approval = self._session.get(Approval, UUID(approval_id))
        if approval is None or approval.workspace_id != context.workspace_id:
            raise _conflict(
                "The original decision response is unavailable.",
                code="INVALID_STATE",
            )
        proposal = self._proposals.get(
            workspace_id=context.workspace_id, proposal_id=approval.proposal_id
        )
        if proposal is None:
            raise _not_found()
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
        return ApprovalOutcome(
            approval=approval,
            proposal=proposal,
            etag=proposal_etag(proposal),
            replayed=True,
            work_item=work_item,
            board_card=board_card,
        )
