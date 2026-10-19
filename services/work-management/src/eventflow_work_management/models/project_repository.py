"""Project repository associations (Issue #44).

A repository is identified by the provider's stable repository id within one
provider instance. The URL is normalized metadata, never the identity: the same
repository may be entered as HTTPS or SSH without creating a second row. There
is intentionally no installation id and no credential column here; remote
verification, provider authentication, and synchronization are separate future
concerns.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import (
    Base,
    TimestampMixin,
    check_in,
    check_regex,
)
from eventflow_work_management.models.enums import (
    PROJECT_REPOSITORY_STATUS_VALUES,
    PROJECT_REPOSITORY_VERIFICATION_VALUES,
    REMOTE_PROVIDER_VALUES,
)

INSTANCE_PATTERN = "^[a-z0-9]([a-z0-9.-]{0,253}[a-z0-9])?$"
REMOTE_REPOSITORY_ID_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$"
REPOSITORY_FULL_PATH_PATTERN = "^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$"
DEFAULT_BRANCH_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$"


class ProjectRepositoryLink(TimestampMixin, Base):
    """A project's association with one external GitHub or GitLab repository."""

    __tablename__ = "project_repositories"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_repository_id: Mapped[str] = mapped_column(String(120), nullable=False)
    repository_full_path: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'configured'")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "provider",
            "provider_instance_id",
            "remote_repository_id",
            name="uq_project_repositories_identity",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_project_repositories_workspace_id"
        ),
        CheckConstraint(
            check_in("provider", REMOTE_PROVIDER_VALUES), name="provider_values"
        ),
        CheckConstraint(
            check_in("status", PROJECT_REPOSITORY_STATUS_VALUES),
            name="status_values",
        ),
        CheckConstraint(
            check_in("verification_status", PROJECT_REPOSITORY_VERIFICATION_VALUES),
            name="verification_values",
        ),
        CheckConstraint(
            check_regex("provider_instance_id", INSTANCE_PATTERN),
            name="provider_instance_format",
        ),
        CheckConstraint(
            check_regex("remote_repository_id", REMOTE_REPOSITORY_ID_PATTERN),
            name="remote_repository_id_format",
        ),
        CheckConstraint(
            check_regex("repository_full_path", REPOSITORY_FULL_PATH_PATTERN),
            name="repository_full_path_format",
        ),
        CheckConstraint(
            "canonical_repository_url LIKE 'https://%'",
            name="canonical_url_https",
        ),
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name="display_name_length",
        ),
        CheckConstraint(
            "default_branch IS NULL OR "
            + check_regex("default_branch", DEFAULT_BRANCH_PATTERN),
            name="default_branch_format",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(status = 'inactive') = (deactivated_at IS NOT NULL)",
            name="deactivated_consistency",
        ),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="archived_consistency",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_repositories_workspace_project",
            ondelete="CASCADE",
        ),
        Index("ix_project_repositories_workspace_id", "workspace_id"),
        Index("ix_project_repositories_project_id", "project_id"),
        Index(
            "ix_project_repositories_project_status",
            "workspace_id",
            "project_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_project_repositories_remote_identity",
            "provider",
            "provider_instance_id",
            "remote_repository_id",
        ),
    )
