"""Remote integration reference model (GitHub/GitLab identity mapping)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, TimestampMixin, check_in
from eventflow_work_management.models.enums import (
    REMOTE_PROVIDER_VALUES,
    REMOTE_RESOURCE_TYPE_VALUES,
)


class RemoteIntegrationReference(TimestampMixin, Base):
    """Maps an external GitHub/GitLab resource to a Work Management entity.

    The unique key mirrors how external systems identify a resource so webhook
    deliveries are idempotent even when they are redelivered.
    """

    __tablename__ = "remote_integration_references"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    installation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    remote_resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    remote_resource_id: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "installation_id",
            "remote_resource_type",
            "remote_resource_id",
            name="uq_remote_integration_references_resource",
        ),
        CheckConstraint(check_in("provider", REMOTE_PROVIDER_VALUES), name="provider_values"),
        CheckConstraint(
            check_in("remote_resource_type", REMOTE_RESOURCE_TYPE_VALUES),
            name="resource_type_values",
        ),
        CheckConstraint("char_length(installation_id) >= 1", name="installation_id_min_length"),
        CheckConstraint(
            "char_length(remote_resource_id) >= 1", name="remote_resource_id_min_length"
        ),
        CheckConstraint("char_length(entity_type) >= 3", name="entity_type_min_length"),
        Index("ix_remote_integration_references_workspace_id", "workspace_id"),
        Index(
            "ix_remote_integration_references_entity",
            "entity_type",
            "entity_id",
        ),
    )
