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
from eventflow_work_management.models.board import (
    Board,
    BoardCard,
    BoardColumn,
    CardMovement,
)
from eventflow_work_management.models.comment import EntityComment
from eventflow_work_management.models.consultation import Consultation
from eventflow_work_management.models.dependency import WorkItemDependency
from eventflow_work_management.models.entity_attachment import (
    EntityAttachment,
    EntityAttachmentBlob,
)
from eventflow_work_management.models.evidence import ConsultationEvidence
from eventflow_work_management.models.idempotency import IdempotencyRecord
from eventflow_work_management.models.integration import RemoteIntegrationReference
from eventflow_work_management.models.membership import (
    WorkspaceInvitation,
    WorkspaceMembership,
)
from eventflow_work_management.models.notification import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from eventflow_work_management.models.project_repository import (
    ProjectRepositoryLink,
)
from eventflow_work_management.models.proposal import Proposal
from eventflow_work_management.models.proposal_evidence import ProposalEvidence
from eventflow_work_management.models.proposal_revision import ProposalRevision
from eventflow_work_management.models.sla import (
    SlaEvent,
    SlaInstance,
    SlaPauseInterval,
    SlaPolicy,
)
from eventflow_work_management.models.triage import (
    ProjectTriageConfiguration,
    ProjectTriageTemplate,
    ProjectTriageTemplateActivation,
    ProjectTriageTemplateVersion,
)
from eventflow_work_management.models.work_item import WorkItem
from eventflow_work_management.models.workspace import Project, Workspace

__all__ = [
    "Approval",
    "AuthenticationSecurityEvent",
    "AuthenticationSession",
    "AuditRecord",
    "Board",
    "BoardCard",
    "BoardColumn",
    "CardMovement",
    "Consultation",
    "ConsultationAttachment",
    "ConsultationAttachmentBlob",
    "ConsultationEvidence",
    "EntityAttachment",
    "EntityAttachmentBlob",
    "EntityComment",
    "IdempotencyRecord",
    "ExternalIdentity",
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "OIDCLoginTransaction",
    "Project",
    "ProjectRepositoryLink",
    "ProjectTriageConfiguration",
    "ProjectTriageTemplate",
    "ProjectTriageTemplateActivation",
    "ProjectTriageTemplateVersion",
    "Proposal",
    "ProposalEvidence",
    "ProposalRevision",
    "RemoteIntegrationReference",
    "SlaEvent",
    "SlaInstance",
    "SlaPauseInterval",
    "SlaPolicy",
    "WorkItem",
    "WorkItemDependency",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
]
