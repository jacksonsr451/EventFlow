"""Add project triage configuration, templates and historical snapshots (#41).

Additive-only migration:

* project-owned configuration, templates, immutable template versions and one
  activation row per project/category;
* nullable consultation columns that pin the effective template version and the
  validation snapshot applied at triage time.

Existing consultations keep ``NULL`` template columns and continue to use the
baseline category contract.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_project_triage_configuration"
down_revision = "0011_priority_sla_dependencies"
branch_labels = None
depends_on = None

_CATEGORIES = "category IN ('bug', 'feature', 'chore', 'docs', 'security')"
_TEMPLATE_STATUS = "status IN ('active', 'deprecated', 'archived')"
_VERSION_STATUS = "status IN ('draft', 'published', 'deprecated', 'archived')"


def upgrade() -> None:
    op.create_table(
        "project_triage_configurations",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "required_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "workflow_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_configurations_workspace_project",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            name="uq_project_triage_configurations_workspace_project",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_project_triage_configurations_workspace_id"
        ),
        sa.CheckConstraint("version >= 1", name="ck_project_triage_configurations_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(required_fields) = 'object'",
            name="ck_project_triage_configurations_required_fields_is_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(custom_fields) = 'array'",
            name="ck_project_triage_configurations_custom_fields_is_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(workflow_rules) = 'object'",
            name="ck_project_triage_configurations_workflow_rules_is_object",
        ),
    )
    op.create_index(
        "ix_project_triage_configurations_project_id",
        "project_triage_configurations",
        ["project_id"],
    )

    op.create_table(
        "project_triage_templates",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_templates_workspace_project",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "key",
            name="uq_project_triage_templates_scope_key",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_project_triage_templates_scope_id",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_project_triage_templates_workspace_id"
        ),
        sa.CheckConstraint(_CATEGORIES, name="ck_project_triage_templates_category_values"),
        sa.CheckConstraint(
            _TEMPLATE_STATUS, name="ck_project_triage_templates_status_values"
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9-]{1,63}$'",
            name="ck_project_triage_templates_key_format",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120",
            name="ck_project_triage_templates_name_length",
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 2000",
            name="ck_project_triage_templates_description_length",
        ),
    )
    op.create_index(
        "ix_project_triage_templates_project_category",
        "project_triage_templates",
        ["project_id", "category"],
    )

    op.create_table(
        "project_triage_template_versions",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("published_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_id"],
            [
                "project_triage_templates.workspace_id",
                "project_triage_templates.project_id",
                "project_triage_templates.id",
            ],
            name="fk_project_triage_template_versions_scope_template",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "template_id",
            "version",
            name="uq_project_triage_template_versions_scope_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "id",
            name="uq_project_triage_template_versions_scope_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_project_triage_template_versions_workspace_id",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_project_triage_template_versions_version_positive"
        ),
        sa.CheckConstraint(
            _VERSION_STATUS, name="ck_project_triage_template_versions_status_values"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(definition) = 'object'",
            name="ck_project_triage_template_versions_definition_is_object",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR published_at IS NOT NULL",
            name="ck_project_triage_template_versions_published_at_consistency",
        ),
        sa.CheckConstraint(
            "(published_at IS NULL) = (published_by IS NULL)",
            name="ck_project_triage_template_versions_published_actor_consistency",
        ),
    )
    op.create_index(
        "ix_project_triage_template_versions_template",
        "project_triage_template_versions",
        ["project_id", "template_id", "version"],
    )

    op.create_table(
        "project_triage_template_activations",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("template_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("template_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("activated_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_triage_template_activations_workspace_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_id"],
            [
                "project_triage_templates.workspace_id",
                "project_triage_templates.project_id",
                "project_triage_templates.id",
            ],
            name="fk_project_triage_template_activations_scope_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "template_version_id"],
            [
                "project_triage_template_versions.workspace_id",
                "project_triage_template_versions.project_id",
                "project_triage_template_versions.id",
            ],
            name="fk_project_triage_template_activations_scope_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "category",
            name="uq_project_triage_template_activations_scope_category",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_project_triage_template_activations_workspace_id",
        ),
        sa.CheckConstraint(
            _CATEGORIES, name="ck_project_triage_template_activations_category_values"
        ),
    )
    op.create_index(
        "ix_project_triage_template_activations_project",
        "project_triage_template_activations",
        ["project_id", "category"],
    )

    op.add_column(
        "consultations",
        sa.Column("triage_template_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("triage_template_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("triage_template_schema_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("triage_template_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "consultations",
        sa.Column("triage_custom_fields", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_consultations_triage_template_version_positive",
        "consultations",
        "triage_template_version IS NULL OR triage_template_version >= 1",
    )
    op.create_check_constraint(
        "ck_consultations_triage_template_schema_version_positive",
        "consultations",
        "triage_template_schema_version IS NULL OR triage_template_schema_version >= 1",
    )
    op.create_check_constraint(
        "ck_consultations_triage_template_snapshot_is_object",
        "consultations",
        "triage_template_snapshot IS NULL OR "
        "jsonb_typeof(triage_template_snapshot) = 'object'",
    )
    op.create_check_constraint(
        "ck_consultations_triage_custom_fields_is_object",
        "consultations",
        "triage_custom_fields IS NULL OR jsonb_typeof(triage_custom_fields) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_consultations_triage_custom_fields_is_object",
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        "ck_consultations_triage_template_snapshot_is_object",
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        "ck_consultations_triage_template_schema_version_positive",
        "consultations",
        type_="check",
    )
    op.drop_constraint(
        "ck_consultations_triage_template_version_positive",
        "consultations",
        type_="check",
    )
    op.drop_column("consultations", "triage_custom_fields")
    op.drop_column("consultations", "triage_template_snapshot")
    op.drop_column("consultations", "triage_template_schema_version")
    op.drop_column("consultations", "triage_template_version")
    op.drop_column("consultations", "triage_template_id")

    op.drop_index(
        "ix_project_triage_template_activations_project",
        table_name="project_triage_template_activations",
    )
    op.drop_table("project_triage_template_activations")
    op.drop_index(
        "ix_project_triage_template_versions_template",
        table_name="project_triage_template_versions",
    )
    op.drop_table("project_triage_template_versions")
    op.drop_index(
        "ix_project_triage_templates_project_category",
        table_name="project_triage_templates",
    )
    op.drop_table("project_triage_templates")
    op.drop_index(
        "ix_project_triage_configurations_project_id",
        table_name="project_triage_configurations",
    )
    op.drop_table("project_triage_configurations")
