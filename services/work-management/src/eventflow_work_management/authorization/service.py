"""Tenant-aware authorization: memberships are resolved then actions evaluated."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import (
    Action,
    can_modify_membership,
    role_has_permission,
)
from eventflow_work_management.models.workspace import Workspace
from eventflow_work_management.models.membership import WorkspaceMembership
from eventflow_work_management.repositories.membership_repository import (
    MembershipRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    WorkspaceRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal

_NOT_FOUND = "The requested resource was not found."
_FORBIDDEN = "The requested action is not permitted."


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """The resolved authority for one request: principal, workspace, membership."""

    principal: AuthenticatedPrincipal
    workspace: Workspace
    membership: WorkspaceMembership

    @property
    def workspace_id(self) -> UUID:
        return self.workspace.id

    @property
    def actor_id(self) -> UUID:
        return self.principal.user_id

    @property
    def role(self) -> str:
        return self.membership.role


class AuthorizationService:
    """Resolves the tenant from the principal, never from the request body.

    Per tenant isolation TI-02/TI-03: a missing workspace, a missing active
    membership, and a foreign resource all return ``404`` so existence is never
    disclosed; ``403`` is reserved for a visible workspace where the caller's
    role lacks the action.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._workspaces = WorkspaceRepository(session)
        self._memberships = MembershipRepository(session)

    def authorize(
        self,
        principal: AuthenticatedPrincipal,
        workspace_id: UUID,
        action: Action,
    ) -> AuthorizationContext:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise self._not_found()
        membership = self._memberships.find_active(
            workspace_id=workspace_id, user_id=principal.user_id
        )
        if membership is None:
            # Not a member of the target workspace: hide its existence entirely.
            raise self._not_found()
        if not role_has_permission(membership.role, action):
            raise self._forbidden()
        return AuthorizationContext(
            principal=principal, workspace=workspace, membership=membership
        )

    @staticmethod
    def require_can_modify_membership(actor_role: str, target_role: str) -> None:
        if not can_modify_membership(actor_role, target_role):
            raise AuthorizationService._forbidden()

    @staticmethod
    def _not_found() -> ProblemError:
        return ProblemError(
            status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
        )

    @staticmethod
    def _forbidden() -> ProblemError:
        return ProblemError(
            status_code=403, code="FORBIDDEN", detail=_FORBIDDEN, title="Forbidden"
        )
