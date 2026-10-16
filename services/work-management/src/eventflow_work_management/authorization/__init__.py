"""Action-level RBAC for the Work Management bounded context (Issue #9)."""

from __future__ import annotations

from eventflow_work_management.authorization.policy import (
    ADMINISTRATOR_ROLES,
    ALL_ROLES,
    Action,
    assignable_roles,
    can_administer,
    can_assign_role,
    can_modify_membership,
    is_known_role,
    permissions_for,
    role_has_permission,
)
from eventflow_work_management.authorization.service import (
    AuthorizationContext,
    AuthorizationService,
)

__all__ = [
    "ADMINISTRATOR_ROLES",
    "ALL_ROLES",
    "Action",
    "AuthorizationContext",
    "AuthorizationService",
    "assignable_roles",
    "can_administer",
    "can_assign_role",
    "can_modify_membership",
    "is_known_role",
    "permissions_for",
    "role_has_permission",
]
