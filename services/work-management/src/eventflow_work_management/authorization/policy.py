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
    CONSULTATION_TRIAGE = "consultation:triage"

    PROPOSAL_READ = "proposal:read"
    PROPOSAL_CREATE = "proposal:create"
    PROPOSAL_SUBMIT = "proposal:submit"
    APPROVAL_DECIDE = "approval:decide"

    WORK_ITEM_READ = "work_item:read"
    WORK_ITEM_UPDATE = "work_item:update"
    BOARD_READ = "board:read"
    BOARD_MANAGE = "board:manage"


_READ_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.WORKSPACE_READ,
        Action.PROJECT_READ,
        Action.MEMBERSHIP_READ,
        Action.CONSULTATION_READ,
        Action.PROPOSAL_READ,
        Action.WORK_ITEM_READ,
        Action.BOARD_READ,
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
            Action.CONSULTATION_TRIAGE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.APPROVAL_DECIDE,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
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
            Action.CONSULTATION_TRIAGE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.APPROVAL_DECIDE,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
        }
    ),
    "triager": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.CONSULTATION_TRIAGE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.WORK_ITEM_UPDATE,
        }
    ),
    "approver": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.APPROVAL_DECIDE,
        }
    ),
    "contributor": frozenset(
        {
            Action.CONSULTATION_CREATE,
            Action.PROPOSAL_CREATE,
            Action.PROPOSAL_SUBMIT,
            Action.WORK_ITEM_UPDATE,
            Action.BOARD_MANAGE,
        }
    ),
    "viewer": frozenset(),
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
