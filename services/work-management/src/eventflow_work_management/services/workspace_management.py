"""Workspace, project, membership and invitation application services (Issue #9).

Each public method is one unit of work: it authorizes through
``AuthorizationService``, performs a single transactional change, writes an
append-only audit record, and commits exactly once. Membership invariants that
span rows (at least one owner) are serialized with a workspace row lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.policy import (
    Action,
    can_assign_role,
    is_known_role,
)
from eventflow_work_management.authorization.service import (
    AuthorizationContext,
    AuthorizationService,
)
from eventflow_work_management.models.authentication import ExternalIdentity
from eventflow_work_management.models.membership import (
    WorkspaceInvitation,
    WorkspaceMembership,
)
from eventflow_work_management.models.workspace import Project, Workspace
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.invitation_repository import (
    InvitationRepository,
)
from eventflow_work_management.repositories.membership_repository import (
    MembershipRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository,
    WorkspaceRepository,
)
from eventflow_work_management.security.crypto import digest_token, random_url_token
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal

DEFAULT_INVITATION_TTL_SECONDS = 14 * 24 * 60 * 60
MIN_INVITATION_TTL_SECONDS = 5 * 60
MAX_INVITATION_TTL_SECONDS = 30 * 24 * 60 * 60

_NOT_FOUND = "The requested resource was not found."
_FORBIDDEN = "The requested action is not permitted."


def _now() -> datetime:
    return datetime.now(UTC)


def _validation(detail: str) -> ProblemError:
    return ProblemError(
        status_code=400, code="VALIDATION_ERROR", detail=detail, title="Invalid request"
    )


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def _forbidden() -> ProblemError:
    return ProblemError(
        status_code=403, code="FORBIDDEN", detail=_FORBIDDEN, title="Forbidden"
    )


def _conflict(detail: str) -> ProblemError:
    return ProblemError(
        status_code=409, code="CONFLICT", detail=detail, title="Conflict"
    )


@dataclass(frozen=True, slots=True)
class CreatedInvitation:
    """A pending invitation and the one-time bearer token to deliver to the invitee."""

    invitation: WorkspaceInvitation
    token: str


class _Service:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.workspaces = WorkspaceRepository(session)
        self.projects = ProjectRepository(session)
        self.memberships = MembershipRepository(session)
        self.invitations = InvitationRepository(session)
        self.audit = AuditRepository(session)


class WorkspaceService(_Service):
    def create(
        self,
        principal: AuthenticatedPrincipal,
        *,
        name: str,
        slug: str,
        correlation_id: UUID | None = None,
    ) -> Workspace:
        """Create a workspace and its founding owner membership atomically.

        Any authenticated principal may create a workspace; the creator becomes
        its owner. A concurrent duplicate slug loses the race on the unique
        constraint and receives ``409`` rather than a partial workspace.
        """
        if self.workspaces.find_by_slug(slug) is not None:
            raise _conflict("A workspace with this slug already exists.")
        try:
            workspace = self.workspaces.add(name=name, slug=slug)
            self.memberships.add(
                workspace_id=workspace.id,
                user_id=principal.user_id,
                role="owner",
            )
            self.audit.append(
                workspace_id=workspace.id,
                action="workspace.created",
                entity_type="workspace",
                entity_id=workspace.id,
                actor_id=principal.user_id,
                snapshot={"name": name, "slug": slug, "role": "owner"},
                correlation_id=correlation_id,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise _conflict("A workspace with this slug already exists.") from exc
        return workspace

    def list_for(self, principal: AuthenticatedPrincipal) -> list[Workspace]:
        return self.workspaces.list_for_user(principal.user_id)

    def get(self, context: AuthorizationContext) -> Workspace:
        return context.workspace

    def update(
        self,
        context: AuthorizationContext,
        *,
        name: str,
        correlation_id: UUID | None = None,
    ) -> Workspace:
        workspace = context.workspace
        self.workspaces.update_name(workspace, name)
        self.audit.append(
            workspace_id=workspace.id,
            action="workspace.updated",
            entity_type="workspace",
            entity_id=workspace.id,
            actor_id=context.actor_id,
            snapshot={"name": name},
            correlation_id=correlation_id,
        )
        self._session.commit()
        return workspace


class ProjectService(_Service):
    def create(
        self,
        context: AuthorizationContext,
        *,
        key: str,
        name: str,
        description: str | None = None,
        correlation_id: UUID | None = None,
    ) -> Project:
        try:
            project = self.projects.add(
                workspace_id=context.workspace_id,
                key=key,
                name=name,
                description=description,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="project.created",
                entity_type="project",
                entity_id=project.id,
                actor_id=context.actor_id,
                snapshot={"key": key, "name": name},
                correlation_id=correlation_id,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise _conflict("A project with this key already exists.") from exc
        return project

    def list(self, context: AuthorizationContext) -> list[Project]:
        return self.projects.list_for_workspace(context.workspace_id)

    def get(self, context: AuthorizationContext, project_id: UUID) -> Project:
        project = self.projects.get(
            workspace_id=context.workspace_id, project_id=project_id
        )
        if project is None:
            raise _not_found()
        return project

    def update(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
        update_description: bool,
        correlation_id: UUID | None = None,
    ) -> Project:
        project = self.get(context, project_id)
        self.projects.update(
            project,
            name=name,
            description=description,
            update_description=update_description,
        )
        self.audit.append(
            workspace_id=context.workspace_id,
            action="project.updated",
            entity_type="project",
            entity_id=project.id,
            actor_id=context.actor_id,
            snapshot={"name": name, "description": description},
            correlation_id=correlation_id,
        )
        self._session.commit()
        return project


class MembershipService(_Service):
    def list(self, context: AuthorizationContext) -> list[WorkspaceMembership]:
        return self.memberships.list_for_workspace(context.workspace_id)

    def change_role(
        self,
        context: AuthorizationContext,
        membership_id: UUID,
        *,
        role: str,
        correlation_id: UUID | None = None,
    ) -> WorkspaceMembership:
        if not is_known_role(role):
            raise _validation("Unknown role.")
        if not can_assign_role(context.role, role):
            raise _forbidden()
        self.memberships.lock_workspace(context.workspace_id)
        target = self._active_membership(context, membership_id)
        AuthorizationService.require_can_modify_membership(context.role, target.role)
        if target.role == "owner" and role != "owner":
            self._require_another_owner(context.workspace_id)
        previous_role = target.role
        self.memberships.change_role(target, role)
        self.audit.append(
            workspace_id=context.workspace_id,
            action="membership.role_changed",
            entity_type="membership",
            entity_id=target.id,
            actor_id=context.actor_id,
            snapshot={"from": previous_role, "to": role, "user_id": str(target.user_id)},
            correlation_id=correlation_id,
        )
        self._session.commit()
        return target

    def revoke(
        self,
        context: AuthorizationContext,
        membership_id: UUID,
        *,
        reason: str,
        correlation_id: UUID | None = None,
    ) -> WorkspaceMembership:
        self.memberships.lock_workspace(context.workspace_id)
        target = self._active_membership(context, membership_id)
        AuthorizationService.require_can_modify_membership(context.role, target.role)
        if target.role == "owner":
            self._require_another_owner(context.workspace_id)
        self.memberships.revoke(target, reason=reason)
        self.audit.append(
            workspace_id=context.workspace_id,
            action="membership.revoked",
            entity_type="membership",
            entity_id=target.id,
            actor_id=context.actor_id,
            snapshot={"user_id": str(target.user_id), "role": target.role},
            correlation_id=correlation_id,
        )
        self._session.commit()
        return target

    def transfer_ownership(
        self,
        context: AuthorizationContext,
        membership_id: UUID,
        *,
        correlation_id: UUID | None = None,
    ) -> tuple[WorkspaceMembership, WorkspaceMembership]:
        """Make one active member the owner and step the acting owner down to admin."""
        self.memberships.lock_workspace(context.workspace_id)
        if membership_id == context.membership.id:
            raise _validation("Ownership must be transferred to another member.")
        target = self._active_membership(context, membership_id)
        actor = context.membership
        self.memberships.change_role(target, "owner")
        self.memberships.change_role(actor, "admin")
        self.audit.append(
            workspace_id=context.workspace_id,
            action="membership.ownership_transferred",
            entity_type="membership",
            entity_id=target.id,
            actor_id=context.actor_id,
            snapshot={
                "new_owner_membership_id": str(target.id),
                "previous_owner_membership_id": str(actor.id),
            },
            correlation_id=correlation_id,
        )
        self._session.commit()
        return target, actor

    def _active_membership(
        self, context: AuthorizationContext, membership_id: UUID
    ) -> WorkspaceMembership:
        target = self.memberships.get(
            workspace_id=context.workspace_id, membership_id=membership_id
        )
        if target is None or target.state != "active":
            raise _not_found()
        return target

    def _require_another_owner(self, workspace_id: UUID) -> None:
        if self.memberships.count_active_owners(workspace_id) <= 1:
            raise _conflict("A workspace must retain at least one owner.")


class InvitationService(_Service):
    def create(
        self,
        context: AuthorizationContext,
        *,
        invited_user_id: UUID,
        role: str,
        invited_email: str | None = None,
        ttl_seconds: int = DEFAULT_INVITATION_TTL_SECONDS,
        correlation_id: UUID | None = None,
    ) -> CreatedInvitation:
        if not is_known_role(role):
            raise _validation("Unknown role.")
        if not can_assign_role(context.role, role):
            raise _forbidden()
        if not MIN_INVITATION_TTL_SECONDS <= ttl_seconds <= MAX_INVITATION_TTL_SECONDS:
            raise _validation("Invitation lifetime is out of range.")
        invitee = self._session.get(ExternalIdentity, invited_user_id)
        if invitee is None or invitee.disabled_at is not None:
            raise _not_found()
        if (
            self.memberships.find_active(
                workspace_id=context.workspace_id, user_id=invited_user_id
            )
            is not None
        ):
            raise _conflict("The identity is already an active member.")
        if (
            self.invitations.find_pending(
                workspace_id=context.workspace_id, invited_user_id=invited_user_id
            )
            is not None
        ):
            raise _conflict("A pending invitation already exists for this identity.")

        token = random_url_token(32)
        expires_at = _now() + timedelta(seconds=ttl_seconds)
        email = invited_email.lower() if invited_email else None
        try:
            invitation = self.invitations.add(
                workspace_id=context.workspace_id,
                invited_user_id=invited_user_id,
                invited_email=email,
                role=role,
                token_digest=digest_token(token),
                invited_by=context.actor_id,
                expires_at=expires_at,
            )
            self.audit.append(
                workspace_id=context.workspace_id,
                action="membership.invited",
                entity_type="invitation",
                entity_id=invitation.id,
                actor_id=context.actor_id,
                snapshot={
                    "invited_user_id": str(invited_user_id),
                    "role": role,
                    "expires_at": expires_at.isoformat(),
                },
                correlation_id=correlation_id,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise _conflict(
                "A pending invitation already exists for this identity."
            ) from exc
        return CreatedInvitation(invitation=invitation, token=token)

    def list_for(self, context: AuthorizationContext) -> list[WorkspaceInvitation]:
        return self.invitations.list_for_workspace(context.workspace_id)

    def revoke(
        self,
        context: AuthorizationContext,
        invitation_id: UUID,
        *,
        reason: str = "revoked_by_administrator",
        correlation_id: UUID | None = None,
    ) -> WorkspaceInvitation:
        invitation = self.invitations.get(
            workspace_id=context.workspace_id, invitation_id=invitation_id
        )
        if invitation is None:
            raise _not_found()
        if invitation.state != "pending":
            raise _conflict("Only a pending invitation can be revoked.")
        self.invitations.revoke(invitation, reason=reason)
        self.audit.append(
            workspace_id=context.workspace_id,
            action="membership.invitation_revoked",
            entity_type="invitation",
            entity_id=invitation.id,
            actor_id=context.actor_id,
            snapshot={"invited_user_id": str(invitation.invited_user_id)},
            correlation_id=correlation_id,
        )
        self._session.commit()
        return invitation

    def accept(
        self,
        principal: AuthenticatedPrincipal,
        *,
        workspace_id: UUID,
        invitation_id: UUID,
        token: str,
        correlation_id: UUID | None = None,
    ) -> WorkspaceMembership:
        """Accept an invitation and create the membership.

        Authorization is identity-bound: the authenticated principal must be the
        invited identity and must present the exact token digest. A wrong
        identity, unknown token, foreign invitation, or a consumed/withdrawn
        token is indistinguishable from "not found" and returns ``404``; only a
        pending invitation that has passed its expiry returns ``409``.
        """
        if not token:
            raise _validation("An invitation token is required.")
        invitation = self.invitations.get_by_digest_for_update(digest_token(token))
        if (
            invitation is None
            or invitation.id != invitation_id
            or invitation.workspace_id != workspace_id
            or invitation.invited_user_id != principal.user_id
        ):
            raise _not_found()
        if invitation.state in {"accepted", "revoked"}:
            # A consumed or withdrawn token is indistinguishable from an unknown
            # one, so a replay cannot confirm that the token was ever valid.
            raise _not_found()
        if invitation.state == "expired" or (
            invitation.state == "pending" and invitation.expires_at <= _now()
        ):
            if invitation.state == "pending":
                self.invitations.mark_expired(invitation)
                self._session.commit()
            raise _conflict("The invitation has expired.")

        self.memberships.lock_workspace(workspace_id)
        existing = self.memberships.find_active(
            workspace_id=workspace_id, user_id=principal.user_id
        )
        if existing is not None:
            raise _conflict("The identity is already an active member.")
        membership = self.memberships.add(
            workspace_id=workspace_id,
            user_id=principal.user_id,
            role=invitation.role,
            invited_by=invitation.invited_by,
        )
        self.invitations.mark_accepted(invitation)
        self.audit.append(
            workspace_id=workspace_id,
            action="membership.accepted",
            entity_type="membership",
            entity_id=membership.id,
            actor_id=principal.user_id,
            snapshot={"invitation_id": str(invitation.id), "role": invitation.role},
            correlation_id=correlation_id,
        )
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise _conflict("The identity is already an active member.") from exc
        return membership
