"""Project repository association routes (Issue #44).

Repositories are configured per project inside one workspace. The workspace is
always taken from the verified principal and the path; requests can never
select a different tenant. Creating/updating/unlinking requires
``project_repository:*`` management rights, while reads are workspace-wide.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
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
from eventflow_work_management.models.project_repository import (
    ProjectRepositoryLink,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.services.project_repository_management import (
    ProjectRepositoryService,
    project_repository_etag,
)

router = APIRouter(tags=["Project repositories"])

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
PROVIDER_PATTERN = "^(github|gitlab)$"
STATUS_PATTERN = "^(active|inactive|archived)$"
REMOTE_ID_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$"
FULL_PATH_PATTERN = "^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$"
BRANCH_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$"


class CreateProjectRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=PROVIDER_PATTERN)
    provider_instance_id: str = Field(min_length=1, max_length=255)
    remote_repository_id: str = Field(pattern=REMOTE_ID_PATTERN)
    repository_url: str = Field(min_length=1, max_length=500)
    repository_full_path: str | None = Field(
        default=None, max_length=255, pattern=FULL_PATH_PATTERN
    )
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    default_branch: str | None = Field(default=None, pattern=BRANCH_PATTERN)


class UpdateProjectRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    default_branch: str | None = Field(default=None, pattern=BRANCH_PATTERN)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


def _authorize(
    session: Session,
    principal: AuthenticatedPrincipal,
    workspace_id: UUID,
    action: Action,
):
    return AuthorizationService(session).authorize(principal, workspace_id, action)


def _idempotency_key(request: Request) -> str | None:
    supplied = request.headers.get("idempotency-key")
    if supplied is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.match(supplied):
        raise ProblemError(
            status_code=400,
            code="VALIDATION_ERROR",
            detail="The Idempotency-Key header is malformed.",
            title="Invalid request",
        )
    return supplied


def _collection_etag(workspace_id: UUID, parts: list[str], *extra: object) -> str:
    return '"' + fingerprint([str(workspace_id), parts, *extra]) + '"'


def _payload(link: ProjectRepositoryLink) -> dict:
    return {
        "repository_id": link.id,
        "workspace_id": link.workspace_id,
        "project_id": link.project_id,
        "provider": link.provider,
        "provider_instance_id": link.provider_instance_id,
        "remote_repository_id": link.remote_repository_id,
        "repository_url": link.canonical_repository_url,
        "repository_full_path": link.repository_full_path,
        "display_name": link.display_name,
        "default_branch": link.default_branch,
        "status": link.status,
        "verification_status": link.verification_status,
        "version": link.version,
        "created_by": link.created_by,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "deactivated_at": link.deactivated_at,
        "archived_at": link.archived_at,
    }


def _base_path(workspace_id: UUID, project_id: UUID) -> str:
    return f"/v1/workspaces/{workspace_id}/projects/{project_id}/repositories"


@router.post(
    "/v1/workspaces/{workspace_id}/projects/{project_id}/repositories",
    status_code=201,
)
def create_project_repository(
    workspace_id: UUID,
    project_id: UUID,
    payload: CreateProjectRepositoryRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.PROJECT_REPOSITORY_CREATE
    )
    outcome = ProjectRepositoryService(session).create(
        context,
        project_id,
        provider=payload.provider,
        provider_instance_id=payload.provider_instance_id,
        remote_repository_id=payload.remote_repository_id,
        repository_url=payload.repository_url,
        repository_full_path=payload.repository_full_path,
        display_name=payload.display_name,
        default_branch=payload.default_branch,
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_repository_etag(outcome.link)
    response.headers["Location"] = (
        f"{_base_path(workspace_id, project_id)}/{outcome.link.id}"
    )
    return _payload(outcome.link)


@router.get("/v1/workspaces/{workspace_id}/projects/{project_id}/repositories")
def list_project_repositories(
    workspace_id: UUID,
    project_id: UUID,
    response: Response,
    provider: str | None = Query(default=None, pattern=PROVIDER_PATTERN),
    status: str | None = Query(default=None, pattern=STATUS_PATTERN),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.PROJECT_REPOSITORY_READ
    )
    page, next_cursor = ProjectRepositoryService(session).list_page(
        context,
        project_id,
        provider=provider,
        status=status,
        include_archived=include_archived,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    response.headers["ETag"] = _collection_etag(
        workspace_id,
        [
            f"{link.id}{link.version}{link.updated_at.isoformat()}"
            for link in page
        ],
        next_cursor,
    )
    return {
        "items": [_payload(link) for link in page],
        "page_info": {
            "has_more": next_cursor is not None,
            "next_cursor": next_cursor,
        },
    }


@router.get(
    "/v1/workspaces/{workspace_id}/projects/{project_id}"
    "/repositories/{repository_id}"
)
def get_project_repository(
    workspace_id: UUID,
    project_id: UUID,
    repository_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    session: Session = Depends(database_session),
):
    context = _authorize(
        session, principal, workspace_id, Action.PROJECT_REPOSITORY_READ
    )
    link = ProjectRepositoryService(session).get(
        context, project_id, repository_id
    )
    response.headers["ETag"] = project_repository_etag(link)
    return _payload(link)


@router.patch(
    "/v1/workspaces/{workspace_id}/projects/{project_id}"
    "/repositories/{repository_id}"
)
def update_project_repository(
    workspace_id: UUID,
    project_id: UUID,
    repository_id: UUID,
    payload: UpdateProjectRepositoryRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.PROJECT_REPOSITORY_UPDATE
    )
    outcome = ProjectRepositoryService(session).update(
        context,
        project_id,
        repository_id,
        display_name=payload.display_name,
        default_branch=payload.default_branch,
        update_default_branch="default_branch" in payload.model_fields_set,
        status=payload.status,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.headers["ETag"] = project_repository_etag(outcome.link)
    return _payload(outcome.link)


@router.delete(
    "/v1/workspaces/{workspace_id}/projects/{project_id}"
    "/repositories/{repository_id}",
    status_code=204,
)
def delete_project_repository(
    workspace_id: UUID,
    project_id: UUID,
    repository_id: UUID,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_csrf),
    session: Session = Depends(database_session),
    request_correlation_id: UUID | None = Depends(correlation_id),
):
    context = _authorize(
        session, principal, workspace_id, Action.PROJECT_REPOSITORY_UNLINK
    )
    ProjectRepositoryService(session).unlink(
        context,
        project_id,
        repository_id,
        if_match=request.headers.get("if-match"),
        idempotency_key=_idempotency_key(request),
        correlation_id=request_correlation_id,
    )
    response.status_code = 204
    return response
