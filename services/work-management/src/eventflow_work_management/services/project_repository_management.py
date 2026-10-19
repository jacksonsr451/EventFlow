"""Project repository association service (Issue #44).

The service links, lists, reads, updates, deactivates/reactivates, and unlinks
external GitHub/GitLab repositories for a project. It never calls a provider,
never mutates a remote repository, and never stores credentials. Stable
deduplication is enforced by the database unique key on
``(workspace_id, project_id, provider, provider_instance_id,
remote_repository_id)``; the URL is normalized metadata only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eventflow_work_management.authorization.service import AuthorizationContext
from eventflow_work_management.hashing import fingerprint
from eventflow_work_management.models.enums import (
    PROJECT_REPOSITORY_STATUS_VALUES,
    REMOTE_PROVIDER_VALUES,
)
from eventflow_work_management.models.project_repository import (
    INSTANCE_PATTERN,
    ProjectRepositoryLink,
)
from eventflow_work_management.repositories.audit_repository import AuditRepository
from eventflow_work_management.repositories.idempotency_repository import (
    IdempotencyRepository,
)
from eventflow_work_management.repositories.project_repository_link_repository import (
    ProjectRepositoryLinkRepository,
)
from eventflow_work_management.repositories.workspace_repository import (
    ProjectRepository as ProjectRecordRepository,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)

PROJECT_REPOSITORY_CREATE_OPERATION = "project_repository.create"
PROJECT_REPOSITORY_UPDATE_OPERATION = "project_repository.update"
PROJECT_REPOSITORY_UNLINK_OPERATION = "project_repository.unlink"

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
SORT_COLUMNS = frozenset({"created_at", "updated_at", "display_name"})
DEFAULT_SORT = "created_at"
ACTIVE = "active"
INACTIVE = "inactive"
ARCHIVED = "archived"
CONFIGURED = "configured"

_INSTANCE_RE = re.compile(INSTANCE_PATTERN)
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REMOTE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")

_NOT_FOUND = "The requested resource was not found."


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


def _conflict(detail: str, *, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def _precondition_failed() -> ProblemError:
    return ProblemError(
        status_code=412,
        code="PRECONDITION_FAILED",
        detail="The supplied If-Match validator is stale.",
        title="Precondition failed",
    )


def _idempotency_conflict() -> ProblemError:
    return ProblemError(
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        detail="The idempotency key was reused with a different request.",
        title="Conflict",
    )


@dataclass(frozen=True, slots=True)
class NormalizedRepository:
    provider_instance_id: str
    repository_full_path: str
    canonical_repository_url: str


@dataclass(frozen=True, slots=True)
class ProjectRepositoryOutcome:
    link: ProjectRepositoryLink
    replayed: bool = False


def project_repository_etag(link: ProjectRepositoryLink) -> str:
    return (
        '"'
        + fingerprint(
            [
                "project-repository",
                str(link.id),
                link.version,
                link.updated_at.isoformat(),
            ]
        )
        + '"'
    )


def _normalize_instance(value: str) -> str:
    candidate = value.strip().lower().rstrip("/")
    if not candidate or "://" in candidate or "/" in candidate or "@" in candidate:
        raise _validation("The provider instance must be a host name.")
    if not _INSTANCE_RE.match(candidate):
        raise _validation("The provider instance is invalid.")
    return candidate


def _normalize_path(raw_path: str) -> tuple[str, str, list[str]]:
    path = raw_path.strip().strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    if not path:
        raise _validation("The repository URL must include a repository path.")
    parts = path.split("/")
    if len(parts) < 2:
        raise _validation("The repository URL must include an owner and repository.")
    for part in parts:
        if not _SEGMENT_RE.match(part) or part in {".", ".."}:
            raise _validation("The repository path is invalid.")
    full_path = "/".join(parts)
    if len(full_path) > 255:
        raise _validation("The repository path is too long.")
    return full_path, "/".join(parts[:-1]), parts


def normalize_repository_url(
    repository_url: str,
    *,
    provider_instance_id: str | None = None,
    repository_full_path: str | None = None,
) -> NormalizedRepository:
    """Return the canonical HTTPS URL and normalized identity metadata.

    HTTPS and SSH/scp-like forms of the same repository normalize to one URL.
    Userinfo, passwords, ports, query strings, and fragments are rejected rather
    than silently stored.
    """
    raw = repository_url.strip()
    if not raw or len(raw) > 500:
        raise _validation("The repository URL is invalid.")
    if any(character.isspace() or ord(character) < 32 for character in raw):
        raise _validation("The repository URL must not contain whitespace.")
    if "\\" in raw:
        raise _validation("The repository URL is invalid.")

    host: str
    path: str
    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"https", "ssh"}:
            raise _validation("The repository URL must use HTTPS or SSH.")
        if parsed.query or parsed.fragment:
            raise _validation("The repository URL must not carry a query or fragment.")
        try:
            port = parsed.port
        except ValueError as exc:
            raise _validation("The repository URL is invalid.") from exc
        if port is not None:
            raise _validation("The repository URL must not include a port.")
        if parsed.password is not None:
            raise _validation("The repository URL must not contain credentials.")
        if parsed.scheme == "https" and parsed.username is not None:
            raise _validation("The repository URL must not contain credentials.")
        if parsed.scheme == "ssh" and parsed.username not in {None, "git"}:
            raise _validation("The SSH user must be 'git' when supplied.")
        host = parsed.hostname or ""
        path = parsed.path
    elif raw.startswith("git@") and ":" in raw:
        host, path = raw[4:].split(":", 1)
        if "/" in host:
            raise _validation("The repository URL is invalid.")
    else:
        raise _validation("The repository URL must use HTTPS or SSH.")

    normalized_host = host.strip().lower().rstrip(".")
    if not _HOST_RE.match(normalized_host):
        raise _validation("The repository host is invalid.")

    full_path, _, parts = _normalize_path(path)
    if repository_full_path is not None:
        supplied = repository_full_path.strip().strip("/")
        if supplied.lower().endswith(".git"):
            supplied = supplied[:-4]
        if supplied != full_path:
            raise _validation(
                "The repository full path does not match the repository URL."
            )

    if provider_instance_id is not None:
        instance = _normalize_instance(provider_instance_id)
        if instance != normalized_host:
            raise _validation(
                "The provider instance does not match the repository URL host."
            )
    else:
        instance = normalized_host

    return NormalizedRepository(
        provider_instance_id=instance,
        repository_full_path=full_path,
        canonical_repository_url=f"https://{normalized_host}/{full_path}",
    )


def _normalize_display_name(display_name: str | None, parts: list[str]) -> str:
    if display_name is None:
        return parts[-1]
    value = display_name.strip()
    if not (1 <= len(value) <= 200):
        raise _validation("The repository display name must be 1 to 200 characters.")
    if any(ord(character) < 32 for character in value):
        raise _validation("The repository display name contains control characters.")
    return value


def _normalize_branch(default_branch: str | None) -> str | None:
    if default_branch is None:
        return None
    value = default_branch.strip()
    if not value:
        raise _validation("The default branch must not be empty.")
    if (
        not _BRANCH_RE.match(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", ".", ".lock"))
    ):
        raise _validation("The default branch name is invalid.")
    return value


def _parse_sort(
    sort: str | None,
) -> tuple[str, bool]:
    if not sort:
        return DEFAULT_SORT, False
    token = sort.split(",", 1)[0].strip()
    descending = token.startswith("-")
    key = token[1:] if descending else token
    if key not in SORT_COLUMNS:
        raise _validation("The sort parameter is invalid.")
    return key, descending


class _BaseService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._links = ProjectRepositoryLinkRepository(session)
        self._projects = ProjectRecordRepository(session)
        self._audit = AuditRepository(session)
        self._idempotency = IdempotencyRepository(session)

    def _require_project(self, context: AuthorizationContext, project_id: UUID) -> None:
        if (
            self._projects.get(
                workspace_id=context.workspace_id, project_id=project_id
            )
            is None
        ):
            raise _not_found()

    def _replay(
        self,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict | None:
        stored = self._idempotency.get(
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != request_fingerprint:
            raise _idempotency_conflict()
        return stored.response_body or {}

    def _reserve(
        self,
        context: AuthorizationContext,
        operation: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ):
        if idempotency_key is None:
            return None
        return self._idempotency.reserve(
            workspace_id=context.workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def _complete(self, record, status: int, body: dict) -> None:
        if record is not None:
            self._idempotency.complete(record, response_status=status, response_body=body)

    def _replay_after_conflict(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        operation: str,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> ProjectRepositoryOutcome | None:
        if idempotency_key is None:
            return None
        replay = self._replay(
            context.workspace_id, operation, idempotency_key, request_fingerprint
        )
        if replay is None:
            raise _idempotency_conflict()
        return self._replay_link(context, project_id, replay)

    def _replay_link(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        body: dict,
    ) -> ProjectRepositoryOutcome:
        repository_id = body.get("repository_id")
        if repository_id is None:
            raise _conflict(
                "The original repository response is unavailable.",
                code="INVALID_STATE",
            )
        link = self._links.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            repository_id=UUID(str(repository_id)),
        )
        if link is None:
            raise _not_found()
        return ProjectRepositoryOutcome(link=link, replayed=True)


class ProjectRepositoryService(_BaseService):
    def create(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        provider: str,
        provider_instance_id: str,
        remote_repository_id: str,
        repository_url: str,
        repository_full_path: str | None = None,
        display_name: str | None = None,
        default_branch: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProjectRepositoryOutcome:
        self._require_project(context, project_id)
        if provider not in REMOTE_PROVIDER_VALUES:
            raise _validation("Unknown repository provider.")
        remote_id = remote_repository_id.strip()
        if not _REMOTE_ID_RE.match(remote_id):
            raise _validation("The remote repository id is invalid.")
        normalized = normalize_repository_url(
            repository_url,
            provider_instance_id=provider_instance_id,
            repository_full_path=repository_full_path,
        )
        _, _, parts = _normalize_path(normalized.repository_full_path)
        display = _normalize_display_name(display_name, parts)
        branch = _normalize_branch(default_branch)

        request_fingerprint = fingerprint(
            {
                "operation": PROJECT_REPOSITORY_CREATE_OPERATION,
                "project_id": str(project_id),
                "provider": provider,
                "provider_instance_id": normalized.provider_instance_id,
                "remote_repository_id": remote_id,
                "repository_url": normalized.canonical_repository_url,
                "display_name": display,
                "default_branch": branch,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                PROJECT_REPOSITORY_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_link(context, project_id, replay)

        try:
            record = self._reserve(
                context,
                PROJECT_REPOSITORY_CREATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            existing = self._links.find_identity(
                workspace_id=context.workspace_id,
                project_id=project_id,
                provider=provider,
                provider_instance_id=normalized.provider_instance_id,
                remote_repository_id=remote_id,
            )
            if existing is not None:
                raise self._existing_conflict(existing)
            link = self._links.add(
                workspace_id=context.workspace_id,
                project_id=project_id,
                provider=provider,
                provider_instance_id=normalized.provider_instance_id,
                remote_repository_id=remote_id,
                repository_full_path=normalized.repository_full_path,
                canonical_repository_url=normalized.canonical_repository_url,
                display_name=display,
                default_branch=branch,
                created_by=context.actor_id,
            )
            self._audit.append(
                workspace_id=context.workspace_id,
                action="project_repository.linked",
                entity_type="project_repository",
                entity_id=link.id,
                actor_id=context.actor_id,
                snapshot={
                    "repository_id": str(link.id),
                    "project_id": str(project_id),
                    "provider": provider,
                    "provider_instance_id": normalized.provider_instance_id,
                    "remote_repository_id": remote_id,
                    "repository_full_path": normalized.repository_full_path,
                    "status": link.status,
                    "verification_status": link.verification_status,
                },
                correlation_id=correlation_id,
            )
            self._complete(
                record,
                201,
                {"repository_id": str(link.id), "project_id": str(project_id)},
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        except IntegrityError:
            self._session.rollback()
            if idempotency_key is not None:
                replay = self._replay(
                    context.workspace_id,
                    PROJECT_REPOSITORY_CREATE_OPERATION,
                    idempotency_key,
                    request_fingerprint,
                )
                if replay is not None:
                    return self._replay_link(context, project_id, replay)
            existing = self._links.find_identity(
                workspace_id=context.workspace_id,
                project_id=project_id,
                provider=provider,
                provider_instance_id=normalized.provider_instance_id,
                remote_repository_id=remote_id,
            )
            if existing is not None:
                raise self._existing_conflict(existing)
            raise _conflict("The repository association could not be created.")
        return ProjectRepositoryOutcome(link=link)

    def get(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        repository_id: UUID,
    ) -> ProjectRepositoryLink:
        self._require_project(context, project_id)
        link = self._links.get(
            workspace_id=context.workspace_id,
            project_id=project_id,
            repository_id=repository_id,
        )
        if link is None:
            raise _not_found()
        return link

    def list_page(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        *,
        provider: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        sort: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[ProjectRepositoryLink], str | None]:
        self._require_project(context, project_id)
        if provider is not None and provider not in REMOTE_PROVIDER_VALUES:
            raise _validation("Unknown repository provider filter.")
        if status is not None and status not in PROJECT_REPOSITORY_STATUS_VALUES:
            raise _validation("Unknown repository status filter.")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise _validation("The page limit is out of range.")
        sort_key, descending = _parse_sort(sort)
        after: tuple[object, UUID] | None = None
        if cursor is not None:
            try:
                payload = decode_cursor(cursor)
            except CursorError as exc:
                raise _validation("The pagination cursor is invalid.") from exc
            value = payload.get(sort_key)
            after_id = payload.get("id")
            if not isinstance(after_id, UUID):
                raise _validation("The pagination cursor is invalid.")
            after = (value, after_id)
        rows = self._links.list_page(
            workspace_id=context.workspace_id,
            project_id=project_id,
            provider=provider,
            status=status,
            include_archived=include_archived,
            sort_key=sort_key,
            descending=descending,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor({sort_key: getattr(last, sort_key)}, last.id)
        return page, next_cursor

    def update(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        repository_id: UUID,
        *,
        display_name: str | None = None,
        default_branch: str | None = None,
        update_default_branch: bool = False,
        status: str | None = None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProjectRepositoryOutcome:
        if (
            display_name is None
            and not update_default_branch
            and status is None
        ):
            raise _validation("At least one repository field must be provided.")
        if status is not None and status not in {ACTIVE, INACTIVE}:
            raise _validation("Only active or inactive status can be set directly.")
        branch = _normalize_branch(default_branch) if update_default_branch else None
        request_fingerprint = fingerprint(
            {
                "operation": PROJECT_REPOSITORY_UPDATE_OPERATION,
                "project_id": str(project_id),
                "repository_id": str(repository_id),
                "display_name": display_name,
                "default_branch": branch,
                "update_default_branch": update_default_branch,
                "status": status,
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                PROJECT_REPOSITORY_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_link(context, project_id, replay)

        try:
            link = self._links.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                repository_id=repository_id,
            )
            if link is None:
                raise _not_found()
            if if_match is not None and if_match != project_repository_etag(link):
                raise _precondition_failed()
            if link.status == ARCHIVED:
                raise _conflict(
                    "An archived repository association cannot be updated.",
                    code="REPOSITORY_ARCHIVED",
                )
            record = self._reserve(
                context,
                PROJECT_REPOSITORY_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            changed = False
            if display_name is not None:
                value = display_name.strip()
                if not (1 <= len(value) <= 200):
                    raise _validation(
                        "The repository display name must be 1 to 200 characters."
                    )
                if any(ord(character) < 32 for character in value):
                    raise _validation(
                        "The repository display name contains control characters."
                    )
                if link.display_name != value:
                    link.display_name = value
                    changed = True
            if update_default_branch and link.default_branch != branch:
                link.default_branch = branch
                changed = True
            action = "project_repository.updated"
            if status is not None and link.status != status:
                if status == ACTIVE:
                    link.status = ACTIVE
                    link.deactivated_at = None
                    action = "project_repository.reactivated"
                else:
                    link.status = INACTIVE
                    link.deactivated_at = _now()
                    action = "project_repository.deactivated"
                changed = True
            if changed:
                link.updated_at = _now()
                self._links.touch(link)
                self._audit.append(
                    workspace_id=context.workspace_id,
                    action=action,
                    entity_type="project_repository",
                    entity_id=link.id,
                    actor_id=context.actor_id,
                    snapshot={
                        "repository_id": str(link.id),
                        "project_id": str(project_id),
                        "display_name": link.display_name,
                        "default_branch": link.default_branch,
                        "status": link.status,
                        "version": link.version,
                    },
                    correlation_id=correlation_id,
                )
            self._complete(
                record,
                200,
                {"repository_id": str(link.id), "project_id": str(project_id)},
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        except IntegrityError:
            self._session.rollback()
            replay = self._replay_after_conflict(
                context,
                project_id,
                PROJECT_REPOSITORY_UPDATE_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay
            raise
        return ProjectRepositoryOutcome(link=link)

    def unlink(
        self,
        context: AuthorizationContext,
        project_id: UUID,
        repository_id: UUID,
        *,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> ProjectRepositoryOutcome:
        request_fingerprint = fingerprint(
            {
                "operation": PROJECT_REPOSITORY_UNLINK_OPERATION,
                "project_id": str(project_id),
                "repository_id": str(repository_id),
                "if_match": if_match,
            }
        )
        if idempotency_key is not None:
            replay = self._replay(
                context.workspace_id,
                PROJECT_REPOSITORY_UNLINK_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self._replay_link(context, project_id, replay)

        try:
            link = self._links.get_for_update(
                workspace_id=context.workspace_id,
                project_id=project_id,
                repository_id=repository_id,
            )
            if link is None:
                raise _not_found()
            if if_match is not None and if_match != project_repository_etag(link):
                raise _precondition_failed()
            record = self._reserve(
                context,
                PROJECT_REPOSITORY_UNLINK_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if link.status != ARCHIVED:
                link.status = ARCHIVED
                link.archived_at = _now()
                link.deactivated_at = None
                link.updated_at = _now()
                self._links.touch(link)
                self._audit.append(
                    workspace_id=context.workspace_id,
                    action="project_repository.unlinked",
                    entity_type="project_repository",
                    entity_id=link.id,
                    actor_id=context.actor_id,
                    snapshot={
                        "repository_id": str(link.id),
                        "project_id": str(project_id),
                        "provider": link.provider,
                        "provider_instance_id": link.provider_instance_id,
                        "remote_repository_id": link.remote_repository_id,
                        "status": link.status,
                        "version": link.version,
                    },
                    correlation_id=correlation_id,
                )
            self._complete(
                record,
                204,
                {"repository_id": str(link.id), "project_id": str(project_id)},
            )
            self._session.commit()
        except ProblemError:
            self._session.rollback()
            raise
        except IntegrityError:
            self._session.rollback()
            replay = self._replay_after_conflict(
                context,
                project_id,
                PROJECT_REPOSITORY_UNLINK_OPERATION,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return replay
            raise
        return ProjectRepositoryOutcome(link=link)

    @staticmethod
    def _existing_conflict(link: ProjectRepositoryLink) -> ProblemError:
        if link.status == ARCHIVED:
            return _conflict(
                "An archived association already exists for this repository.",
                code="REPOSITORY_ARCHIVED",
            )
        return _conflict(
            "This repository is already associated with the project.",
            code="REPOSITORY_ALREADY_LINKED",
        )
