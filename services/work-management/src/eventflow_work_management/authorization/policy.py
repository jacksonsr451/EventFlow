"""Pure, side-effect-free Work Management RBAC policy (Issue #9).

The policy answers three questions and nothing else:

* May a role perform an action inside one workspace?
* May a role be assigned by an actor holding another role?
* May an actor modify a specific membership (protecting the owner seat)?

It never reads the database. Every decision is a deterministic function of its
arguments, so the matrix can be unit-tested exhaustively and audited in one
place. Enforcement (membership resolution, row locking, HTTP mapping) lives in
``eventflow_work_management.authorization.service``.
"""

from __future__ import annotations

from enum import Enum

from eventflow_work_management.models.enums import WORKSPACE_ROLE_VALUES

ALL_ROLES: frozenset[str] = frozenset(WORKSPACE_ROLE_VALUES)


class Action(str, Enum):
    """Action-level permissions; authorization is evaluated per action."""

    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"

    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"

    MEMBERSHIP_READ = "membership:read"
    MEMBERSHIP_INVITE = "membership:invite"
    MEMBERSHIP_UPDATE_ROLE = "membership:update_role"
    MEMBERSHIP_REVOKE = "membership:revoke"
    MEMBERSHIP_TRANSFER_OWNERSHIP = "membership:transfer_ownership"

    CONSULTATION_READ = "consultation:read"
    CONSULTATION_CREATE = "consultation:create"
    CONSULTATION_UPDATE = "consultation:update"
    CONSULTATION_SUBMIT = "consultation:submit"
    CONSULTATION_TRIAGE = "consultation:triage"

    ATTACHMENT_READ = "attachment:read"
    ATTACHMENT_UPLOAD = "attachment:upload"
    ATTACHMENT_DELETE = "attachment:delete"
    EVIDENCE_READ = "evidence:read"
    EVIDENCE_CREATE = "evidence:create"
    HISTORY_READ = "history:read"

    COMMENT_READ = "comment:read"
    COMMENT_CREATE = "comment:create"
    COMMENT_DELETE = "comment:delete"

    PROPOSAL_READ = "proposal:read"
    PROPOSAL_CREATE = "proposal:create"
    PROPOSAL_UPDATE = "proposal:update"
    PROPOSAL_SUBMIT = "proposal:submit"
    PROPOSAL_DUPLICATE = "proposal:duplicate"
    APPROVAL_DECIDE = "approval:decide"

    WORK_ITEM_READ = "work_item:read"
    WORK_ITEM_UPDATE = "work_item:update"
    BOARD_READ = "board:read"
    BOARD_MANAGE = "board:manage"

    PROJECT_REPOSITORY_READ = "project_repository:read"
    PROJECT_REPOSITORY_CREATE = "project_repository:create"
    PROJECT_REPOSITORY_UPDATE = "project_repository:update"
    PROJECT_REPOSITORY_UNLINK = "project_repository:unlink"

    TRIAGE_CONFIGURATION_READ = "triage_configuration:read"
    TRIAGE_CONFIGURATION_MANAGE = "triage_configuration:manage"
    TRIAGE_TEMPLATE_READ = "triage_template:read"
    TRIAGE_TEMPLATE_MANAGE = "triage_template:manage"

    PRIORITY_OVERRIDE = "work_item:override_priority"
    SLA_POLICY_READ = "sla_policy:read"
    SLA_POLICY_MANAGE = "sla_policy:manage"
    SLA_READ = "sla:read"
    DEPENDENCY_READ = "dependency:read"
    DEPENDENCY_MANAGE = "dependency:manage"
    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_PREFERENCE_MANAGE = "notification:manage_preferences"


_READ_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.WORKSPACE_READ,
        Action.PROJECT_READ,
        Action.MEMBERSHIP_READ,
        Action.CONSULTATION_READ,
        Action.ATTACHMENT_READ,
        Action.EVIDENCE_READ,
        Action.HISTORY_READ,
        Action.COMMENT_READ,
        Action.PROPOSAL_READ,
        Action.WORK_ITEM_READ,
        Action.BOARD_READ,
        Action.PROJECT_REPOSITORY_READ,
        Action.TRIAGE_CONFIGURATION_READ,
        Action.TRIAGE_TEMPLATE_READ,
        Action.SLA_POLICY_READ,
        Action.SLA_READ,
        Action.DEPENDENCY_READ,
        Action.NOTIFICATION_READ,
    }
)

_MUTATION_ACTIONS: dict[str, frozenset[Action]] = {
    "owner": frozenset(
        {
            Action.WORKSPACE_UPDATE,
            Action.WORKSPACE_DELETE,
            Action.PROJECT_CREATE,
            Action.PROJECT_UPDATE,
            Action.MEMBERSHIP_INVITE,
            Action.MEMBERSHIP_UPDATE_ROLE,
            Action.MEMBERSHIP_REVOKE,
            Action.MEMBERSHIP_TRANSFER_OWNERSHIP,
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_UPDATE,
            Action.CONSULTATION_SUBMIT,
            Action.CONSULTATION_TRIAGE,
            Action.ATTACHMENT_UPLOAD,
            Action.ATTACHMENT_DELETE,
            Action.EVIDENCE_CREATE,
            Action.COMMENT_CREATE,
            Action.COMMENT_DELETE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.PROPOSAL_UPDATE,
            Action.PROPOSAL_DUPLICATE,
            Action.APPROVAL_DECIDE,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
            Action.PROJECT_REPOSITORY_CREATE,
            Action.PROJECT_REPOSITORY_UPDATE,
            Action.PROJECT_REPOSITORY_UNLINK,
            Action.TRIAGE_CONFIGURATION_MANAGE,
            Action.TRIAGE_TEMPLATE_MANAGE,
            Action.SLA_POLICY_MANAGE,
            Action.PRIORITY_OVERRIDE,
            Action.DEPENDENCY_MANAGE,
            Action.NOTIFICATION_PREFERENCE_MANAGE,
        }
    ),
    "admin": frozenset(
        {
            Action.WORKSPACE_UPDATE,
            Action.PROJECT_CREATE,
            Action.PROJECT_UPDATE,
            Action.MEMBERSHIP_INVITE,
            Action.MEMBERSHIP_UPDATE_ROLE,
            Action.MEMBERSHIP_REVOKE,
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_UPDATE,
            Action.CONSULTATION_SUBMIT,
            Action.CONSULTATION_TRIAGE,
            Action.ATTACHMENT_UPLOAD,
            Action.ATTACHMENT_DELETE,
            Action.EVIDENCE_CREATE,
            Action.COMMENT_CREATE,
            Action.COMMENT_DELETE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.PROPOSAL_UPDATE,
            Action.PROPOSAL_DUPLICATE,
            Action.APPROVAL_DECIDE,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
            Action.PROJECT_REPOSITORY_CREATE,
            Action.PROJECT_REPOSITORY_UPDATE,
            Action.PROJECT_REPOSITORY_UNLINK,
            Action.TRIAGE_CONFIGURATION_MANAGE,
            Action.TRIAGE_TEMPLATE_MANAGE,
            Action.SLA_POLICY_MANAGE,
            Action.PRIORITY_OVERRIDE,
            Action.DEPENDENCY_MANAGE,
            Action.NOTIFICATION_PREFERENCE_MANAGE,
        }
    ),
    "triager": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_UPDATE,
            Action.CONSULTATION_SUBMIT,
            Action.CONSULTATION_TRIAGE,
            Action.ATTACHMENT_UPLOAD,
            Action.ATTACHMENT_DELETE,
            Action.EVIDENCE_CREATE,
            Action.COMMENT_CREATE,
            Action.COMMENT_DELETE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.PROPOSAL_UPDATE,
            Action.PROPOSAL_DUPLICATE,
            Action.WORK_ITEM_UPDATE,
            Action.PRIORITY_OVERRIDE,
            Action.DEPENDENCY_MANAGE,
            Action.NOTIFICATION_PREFERENCE_MANAGE,
        }
    ),
    "approver": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_UPDATE,
            Action.CONSULTATION_SUBMIT,
            Action.ATTACHMENT_UPLOAD,
            Action.ATTACHMENT_DELETE,
            Action.EVIDENCE_CREATE,
            Action.COMMENT_CREATE,
            Action.COMMENT_DELETE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.PROPOSAL_UPDATE,
            Action.PROPOSAL_DUPLICATE,
            Action.APPROVAL_DECIDE,
            Action.NOTIFICATION_PREFERENCE_MANAGE,
        }
    ),
    "contributor": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_UPDATE,
            Action.CONSULTATION_SUBMIT,
            Action.ATTACHMENT_UPLOAD,
            Action.ATTACHMENT_DELETE,
            Action.EVIDENCE_CREATE,
            Action.COMMENT_CREATE,
            Action.COMMENT_DELETE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.PROPOSAL_UPDATE,
            Action.PROPOSAL_DUPLICATE,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
            Action.DEPENDENCY_MANAGE,
            Action.NOTIFICATION_PREFERENCE_MANAGE,
        }
    ),
    "viewer": frozenset({Action.NOTIFICATION_PREFERENCE_MANAGE}),
}

_ROLE_PERMISSIONS: dict[str, frozenset[Action]] = {
    role: _READ_ACTIONS | _MUTATION_ACTIONS.get(role, frozenset())
    for role in ALL_ROLES
}

# An admin may grant every role except owner; only an owner may create another
# owner. This prevents an admin from escalating to owner or creating a peer it
# cannot later remove.
_ASSIGNABLE_ROLES: dict[str, frozenset[str]] = {
    "owner": ALL_ROLES,
    "admin": ALL_ROLES - {"owner"},
    "triager": frozenset(),
    "approver": frozenset(),
    "contributor": frozenset(),
    "viewer": frozenset(),
}

OWNER_ROLE = "owner"
ADMIN_ROLE = "admin"
ADMINISTRATOR_ROLES: frozenset[str] = frozenset({OWNER_ROLE, ADMIN_ROLE})


def is_known_role(role: str) -> bool:
    return role in ALL_ROLES


def permissions_for(role: str) -> frozenset[Action]:
    return _ROLE_PERMISSIONS.get(role, frozenset())


def role_has_permission(role: str, action: Action) -> bool:
    """Deny by default: an unknown role or action yields ``False``."""
    return action in _ROLE_PERMISSIONS.get(role, frozenset())


def can_administer(role: str) -> bool:
    """Whether the role may change memberships or roles at all."""
    return role in ADMINISTRATOR_ROLES


def can_assign_role(actor_role: str, role: str) -> bool:
    return role in _ASSIGNABLE_ROLES.get(actor_role, frozenset())


def can_modify_membership(actor_role: str, target_role: str) -> bool:
    """Whether an actor may revoke, re-role or transfer away a membership.

    Owners may modify any membership. Admins may modify every membership except
    an owner's, so an admin can never demote or remove the owner seat.
    """
    if actor_role == OWNER_ROLE:
        return True
    if actor_role == ADMIN_ROLE:
        return target_role != OWNER_ROLE
    return False


def assignable_roles(actor_role: str) -> frozenset[str]:
    return _ASSIGNABLE_ROLES.get(actor_role, frozenset())
