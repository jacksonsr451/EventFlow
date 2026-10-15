"""Repositories: the unit of work for each Work Management operation."""

from __future__ import annotations

from eventflow_work_management.repositories.approval_repository import (
    ApprovalRepository,
    DecisionResult,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.board_repository import (
    BoardCardRepository,
    BoardRepository,
)
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
)
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
from eventflow_work_management.repositories.proposal_repository import ProposalRepository
from eventflow_work_management.repositories.remote_reference_repository import (
    RemoteReferenceRepository,
)
from eventflow_work_management.repositories.work_item_repository import WorkItemRepository
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
    WorkspaceRepository,
)

__all__ = [
    "AlreadyDecided",
    "ApprovalRepository",
    "AuditRepository",
    "BoardCardRepository",
    "BoardRepository",
    "ConsultationRepository",
    "DecisionResult",
    "EntityNotFound",
    "IdempotencyConflict",
    "IdempotencyRepository",
    "ProjectRepository",
    "ProposalRepository",
    "RemoteReferenceRepository",
    "RepositoryError",
    "VersionMismatch",
    "WorkItemRepository",
    "WorkspaceRepository",
]
