"""Project-scoped triage configuration and versioned templates (Issue #41).

The existing differentiated category criteria remain authoritative. These models
only add project-owned requirements on top of that baseline:

* ``ProjectTriageConfiguration`` stores additive required fields, custom field
  definitions and workflow restrictions for one project.
* ``ProjectTriageTemplate`` groups immutable versions for one category.
* ``ProjectTriageTemplateVersion`` is the immutable definition revision. A
  published row is never updated in place; editing creates a new draft.
* ``ProjectTriageTemplateActivation`` points at the single effective published
  version per project/category.

Every row is scoped by ``workspace_id`` and ``project_id`` with composite foreign
keys so cross-workspace and cross-project references are rejected by PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventflow_work_management.db.base import Base, TimestampMixin, check_in
from eventflow_work_management.models.enums import (
    TRIAGE_CATEGORY_VALUES,
    TRIAGE_TEMPLATE_STATUS_VALUES,
    TRIAGE_TEMPLATE_VERSION_STATUS_VALUES,
)

TEMPLATE_KEY_PATTERN = "^[a-z][a-z0-9-]{1,63}$"


class ProjectTriageConfiguration(TimestampMixin, Base):
    """Additive project requirements layered over the category contract."""

    __tablename__ = "project_triage_configurations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    required_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    custom_fields: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    workflow_rules: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_configurations_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            name="uq_project_triage_configurations_workspace_project",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_project_triage_configurations_workspace_id"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "jsonb_typeof(required_fields) = 'object'",
            name="required_fields_is_object",
        ),
        CheckConstraint(
            "jsonb_typeof(custom_fields) = 'array'", name="custom_fields_is_array"
        ),
        CheckConstraint(
            "jsonb_typeof(workflow_rules) = 'object'", name="workflow_rules_is_object"
        ),
        Index("ix_project_triage_configurations_project_id", "project_id"),
    )


class ProjectTriageTemplate(TimestampMixin, Base):
    """A project-scoped, category-specific family of template versions."""

    __tablename__ = "project_triage_templates"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'")
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_templates_workspace_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "key",
            name="uq_project_triage_templates_scope_key",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_project_triage_templates_scope_id",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_project_triage_templates_workspace_id"
        ),
        CheckConstraint(
            check_in("category", TRIAGE_CATEGORY_VALUES), name="category_values"
        ),
        CheckConstraint(
            check_in("status", TRIAGE_TEMPLATE_STATUS_VALUES), name="status_values"
        ),
        CheckConstraint("key ~ '" + TEMPLATE_KEY_PATTERN + "'", name="key_format"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 2000",
            name="description_length",
        ),
        Index("ix_project_triage_templates_project_category", "project_id", "category"),
    )


class ProjectTriageTemplateVersion(TimestampMixin, Base):
    """One immutable definition revision of a project template.

    ``definition`` is a validated declarative document: it never contains
    executable code, SQL, remote references or unbounded regular expressions.
    """

    __tablename__ = "project_triage_template_versions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    template_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'")
    )
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_id"],
            [
                "project_triage_templates.workspace_id",
                "project_triage_templates.project_id",
                "project_triage_templates.id",
            ],
            name="fk_project_triage_template_versions_scope_template",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "template_id",
            "version",
            name="uq_project_triage_template_versions_scope_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_project_triage_template_versions_scope_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_project_triage_template_versions_workspace_id",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            check_in("status", TRIAGE_TEMPLATE_VERSION_STATUS_VALUES),
            name="status_values",
        ),
        CheckConstraint(
            "jsonb_typeof(definition) = 'object'", name="definition_is_object"
        ),
        CheckConstraint(
            "status = 'draft' OR published_at IS NOT NULL",
            name="published_at_consistency",
        ),
        CheckConstraint(
            "(published_at IS NULL) = (published_by IS NULL)",
            name="published_actor_consistency",
        ),
        Index(
            "ix_project_triage_template_versions_template",
            "project_id",
            "template_id",
            "version",
        ),
    )


class ProjectTriageTemplateActivation(Base):
    """The single effective published template version per project/category."""

    __tablename__ = "project_triage_template_activations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    template_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    template_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    activated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_template_activations_workspace_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_id"],
            [
                "project_triage_templates.workspace_id",
                "project_triage_templates.project_id",
                "project_triage_templates.id",
            ],
            name="fk_project_triage_template_activations_scope_template",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_version_id"],
            [
                "project_triage_template_versions.workspace_id",
                "project_triage_template_versions.project_id",
                "project_triage_template_versions.id",
            ],
            name="fk_project_triage_template_activations_scope_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "project_id",
            "category",
            name="uq_project_triage_template_activations_scope_category",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_project_triage_template_activations_workspace_id",
        ),
        CheckConstraint(
            check_in("category", TRIAGE_CATEGORY_VALUES), name="category_values"
        ),
        Index(
            "ix_project_triage_template_activations_project",
            "project_id",
            "category",
        ),
    )
