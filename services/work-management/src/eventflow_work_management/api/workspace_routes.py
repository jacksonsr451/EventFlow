"""Authenticated workspace, project, membership and invitation routes (Issue #9).

The tenant is always derived from the verified principal and the path locator,
never from a request body. Every mutating route is registered with
``require_csrf`` so cookie-authenticated writes need Origin + CSRF, while
bearer-authenticated callers are unaffected.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from eventflow_work_management.api.dependencies import (
    authenticated_principal,
    correlation_id,
    database_session,
    require_csrf,
)
from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models.membership import WorkspaceInvitation
from eventflow_work_management.models.workspace import Project, Workspace
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.workspace_management import (
    DEFAULT_INVITATION_TTL_SECONDS,
    InvitationService,
    MembershipService,
    ProjectService,
    WorkspaceService,
)

router = APIRouter(tags=["Workspaces"])

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,9}$"

ALL_ROLES_NOTE = (
    "Requires an authenticated principal only; no existing workspace role is "
    "required. The baseline `viewer` token denotes that authenticated tier."
)


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    slug: str = Field(max_length=80, pattern=SLUG_PATTERN)


class UpdateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)


class CreateProjectRequest(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=1)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=1)


class ChangeMemberRoleRequest(BaseModel):
    role: str


class CreateInvitationRequest(BaseModel):
    invited_user_id: UUID
    role: str
    invited_email: str | None = Field(default=None, min_length=3, max_length=320)
    expires_in_seconds: int = Field(
        default=DEFAULT_INVITATION_TTL_SECONDS, ge=300, le=30 * 24 * 60 * 60
    )


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)


def _etag(*parts: object) -> str:
    return f'"{fingerprint(list(parts))}"'


def _workspace_etag(workspace: Workspace) -> str:
    return _etag("workspace", str(workspace.id), workspace.updated_at.isoformat())


def _project_etag(project: Project) -> str:
    return _etag("project", str(project.id), project.updated_at.isoformat())


def _member_etag(membership) -> str:  # noqa: ANN001 - ORM entity
    return _etag("membership", str(membership.id), membership.updated_at.isoformat())


def _invitation_etag(invitation: WorkspaceInvitation) -> str:
    return _etag("invitation", str(invitation.id), invitation.updated_at.isoformat())


def _require_if_match(request: Request, current: str) -> None:
    supplied = request.headers.get("if-match")
    if supplied is not None and supplied != current:
        raise ProblemError(
            status_code=412,
            code="PRECONDITION_FAILED",
            detail="The supplied If-Match validator is stale.",
            title="Precondition failed",
        )


def _workspace_payload(workspace: Workspace) -> dict:
    return {
        "workspace_id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def _project_payload(project: Project) -> dict:
    return {
        "project_id": project.id,
        "workspace_id": project.workspace_id,
        "key": project.key,
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _member_payload(membership) -> dict:  # noqa: ANN001 - ORM entity
    return {
        "membership_id": membership.id,
        "workspace_id": membership.workspace_id,
        "user_id": membership.user_id,
        "role": membership.role,
        "state": membership.state,
        "created_at": membership.created_at,
        "updated_at": membership.updated_at,
    }


def _invitation_payload(invitation: WorkspaceInvitation) -> dict:
    return {
        "invitation_id": invitation.id,
        "workspace_id": invitation.workspace_id,
        "invited_user_id": invitation.invited_user_id,
        "invited_email": invitation.invited_email,
        "role": invitation.role,
        "state": invitation.state,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
        "accepted_at": invitation.accepted_at,
        "revoked_at": invitation.revoked_at,
    }


def _authorize(
    session: Session,
    principal: AuthenticatedPrincipal,
    workspace_id: UUID,
    action: Action,
):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


@router.post("/v1/workspaces", status_code=201)
def create_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    workspace = WorkspaceService(session).create(
        principal,
        name=payload.name,
        slug=payload.slug,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _workspace_etag(workspace)
    response.headers["Location"] = f"/v1/workspaces/{workspace.id}"
    return _workspace_payload(workspace)


@router.get("/v1/workspaces")
def list_workspaces(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    workspaces = WorkspaceService(session).list_for(principal)
    response.headers["ETag"] = _etag(
        "workspaces",
        [str(workspace.id) + workspace.updated_at.isoformat() for workspace in workspaces],
    )
    return [_workspace_payload(workspace) for workspace in workspaces]


@router.get("/v1/workspaces/{workspace_id}")
def get_workspace(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.WORKSPACE_READ)
    response.headers["ETag"] = _workspace_etag(context.workspace)
    return _workspace_payload(context.workspace)


@router.patch("/v1/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: UUID,
    payload: UpdateWorkspaceRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.WORKSPACE_UPDATE)
    _require_if_match(request, _workspace_etag(context.workspace))
    workspace = WorkspaceService(session).update(
        context, name=payload.name, correlation_id=request_correlation_id
    )
    response.headers["ETag"] = _workspace_etag(workspace)
    return _workspace_payload(workspace)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.post("/v1/workspaces/{workspace_id}/projects", status_code=201)
def create_project(
    workspace_id: UUID,
    payload: CreateProjectRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROJECT_CREATE)
    project = ProjectService(session).create(
        context,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _project_etag(project)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/projects/{project.id}"
    )
    return _project_payload(project)


@router.get("/v1/workspaces/{workspace_id}/projects")
def list_projects(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROJECT_READ)
    projects = ProjectService(session).list(context)
    response.headers["ETag"] = _etag(
        "projects",
        [str(project.id) + project.updated_at.isoformat() for project in projects],
    )
    return [_project_payload(project) for project in projects]


@router.get("/v1/workspaces/{workspace_id}/projects/{project_id}")
def get_project(
    workspace_id: UUID,
    project_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.PROJECT_READ)
    project = ProjectService(session).get(context, project_id)
    response.headers["ETag"] = _project_etag(project)
    return _project_payload(project)


@router.patch("/v1/workspaces/{workspace_id}/projects/{project_id}")
def update_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: UpdateProjectRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.PROJECT_UPDATE)
    current = ProjectService(session).get(context, project_id)
    _require_if_match(request, _project_etag(current))
    project = ProjectService(session).update(
        context,
        project_id,
        name=payload.name,
        description=payload.description,
        update_description="description" in payload.model_fields_set,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _project_etag(project)
    return _project_payload(project)


# ---------------------------------------------------------------------------
# Members and roles
# ---------------------------------------------------------------------------


@router.get("/v1/workspaces/{workspace_id}/members")
def list_members(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.MEMBERSHIP_READ)
    members = MembershipService(session).list(context)
    response.headers["ETag"] = _etag(
        "members",
        [
            str(member.id) + member.updated_at.isoformat() + member.role
            for member in members
        ],
    )
    return [_member_payload(member) for member in members]


@router.patch("/v1/workspaces/{workspace_id}/members/{membership_id}")
def change_member_role(
    workspace_id: UUID,
    membership_id: UUID,
    payload: ChangeMemberRoleRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.MEMBERSHIP_UPDATE_ROLE
    )
    membership = MembershipService(session).change_role(
        context,
        membership_id,
        role=payload.role,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _member_etag(membership)
    return _member_payload(membership)


@router.delete("/v1/workspaces/{workspace_id}/members/{membership_id}", status_code=204)
def revoke_member(
    workspace_id: UUID,
    membership_id: UUID,
    response: Response,
    reason: str = "revoked_by_administrator",
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.MEMBERSHIP_REVOKE)
    MembershipService(session).revoke(
        context,
        membership_id,
        reason=reason[:64],
        correlation_id=request_correlation_id,
    )
    response.status_code = 204
    return response


@router.post(
    "/v1/workspaces/{workspace_id}/members/{membership_id}/transfer-ownership"
)
def transfer_ownership(
    workspace_id: UUID,
    membership_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.MEMBERSHIP_TRANSFER_OWNERSHIP
    )
    target, actor = MembershipService(session).transfer_ownership(
        context, membership_id, correlation_id=request_correlation_id
    )
    response.headers["ETag"] = _member_etag(target)
    return {
        "new_owner": _member_payload(target),
        "previous_owner": _member_payload(actor),
    }


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@router.post("/v1/workspaces/{workspace_id}/invitations", status_code=201)
def create_invitation(
    workspace_id: UUID,
    payload: CreateInvitationRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.MEMBERSHIP_INVITE)
    created = InvitationService(session).create(
        context,
        invited_user_id=payload.invited_user_id,
        role=payload.role,
        invited_email=payload.invited_email,
        ttl_seconds=payload.expires_in_seconds,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _invitation_etag(created.invitation)
    response.headers["Location"] = (
        f"/v1/workspaces/{workspace_id}/invitations/{created.invitation.id}"
    )
    return {
        "invitation": _invitation_payload(created.invitation),
        "token": created.token,
    }


@router.get("/v1/workspaces/{workspace_id}/invitations")
def list_invitations(
    workspace_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(session, principal, workspace_id, Action.MEMBERSHIP_READ)
    invitations = InvitationService(session).list_for(context)
    response.headers["ETag"] = _etag(
        "invitations",
        [
            str(invitation.id) + invitation.updated_at.isoformat() + invitation.state
            for invitation in invitations
        ],
    )
    return [_invitation_payload(invitation) for invitation in invitations]


@router.post("/v1/workspaces/{workspace_id}/invitations/{invitation_id}/revoke")
def revoke_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(session, principal, workspace_id, Action.MEMBERSHIP_INVITE)
    invitation = InvitationService(session).revoke(
        context, invitation_id, correlation_id=request_correlation_id
    )
    response.headers["ETag"] = _invitation_etag(invitation)
    return _invitation_payload(invitation)


@router.post(
    "/v1/workspaces/{workspace_id}/invitations/{invitation_id}/accept", status_code=201
)
def accept_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    payload: AcceptInvitationRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    membership = InvitationService(session).accept(
        principal,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
        token=payload.token,
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = _member_etag(membership)
    return _member_payload(membership)
