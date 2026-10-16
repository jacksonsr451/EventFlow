"""SQLAlchemy models for the Work Management bounded context.

Importing this package registers every table on ``Base.metadata``; Alembic and
tests rely on that side effect.
"""

from __future__ import annotations

from eventflow_work_management.models.approval import Approval
from eventflow_work_management.models.attachment import (
    ConsultationAttachment,
    ConsultationAttachmentBlob,
)
from eventflow_work_management.models.authentication import (
    AuthenticationSecurityEvent,
    AuthenticationSession,
    ExternalIdentity,
    OIDCLoginTransaction,
)
from eventflow_work_management.models.audit import AuditRecord
from eventflow_work_management.models.board import Board, BoardCard
from eventflow_work_management.models.consultation import Consultation
from eventflow_work_management.models.evidence import ConsultationEvidence
from eventflow_work_management.models.idempotency import IdempotencyRecord
from eventflow_work_management.models.integration import RemoteIntegrationReference
from eventflow_work_management.models.membership import (
    WorkspaceInvitation,
    WorkspaceMembership,
)
from eventflow_work_management.models.proposal import Proposal
from eventflow_work_management.models.work_item import WorkItem
from eventflow_work_management.models.workspace import Project, Workspace

__all__ = [
    "Approval",
    "AuthenticationSecurityEvent",
    "AuthenticationSession",
    "AuditRecord",
    "Board",
    "BoardCard",
    "Consultation",
    "ConsultationAttachment",
    "ConsultationAttachmentBlob",
    "ConsultationEvidence",
    "IdempotencyRecord",
    "ExternalIdentity",
    "OIDCLoginTransaction",
    "Project",
    "Proposal",
    "RemoteIntegrationReference",
    "WorkItem",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
]
