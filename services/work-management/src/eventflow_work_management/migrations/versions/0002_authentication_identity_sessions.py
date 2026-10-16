"""Add OIDC identities, server sessions and security audit events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_auth_sessions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(issuer) BETWEEN 1 AND 512", name=op.f("ck_external_identities_issuer_length")),
        sa.CheckConstraint("char_length(subject) BETWEEN 1 AND 255", name=op.f("ck_external_identities_subject_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identities")),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identities_issuer_subject"),
    )
    op.create_index("ix_external_identities_subject", "external_identities", ["subject"])

    op.create_table(
        "authentication_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("identity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("session_token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("session_token_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_authentication_sessions_token_digest_format")),
        sa.CheckConstraint("csrf_token_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_authentication_sessions_csrf_digest_format")),
        sa.CheckConstraint("idle_expires_at <= absolute_expires_at", name=op.f("ck_authentication_sessions_idle_before_absolute_expiry")),
        sa.CheckConstraint("char_length(client_id) BETWEEN 1 AND 80", name=op.f("ck_authentication_sessions_client_id_length")),
        sa.CheckConstraint("source IN ('web', 'desktop', 'vscode')", name=op.f("ck_authentication_sessions_source_values")),
        sa.CheckConstraint("revoke_reason IS NULL OR char_length(revoke_reason) BETWEEN 1 AND 64", name=op.f("ck_authentication_sessions_revoke_reason_length")),
        sa.ForeignKeyConstraint(["identity_id"], ["external_identities.id"], name=op.f("fk_authentication_sessions_identity_id_external_identities"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authentication_sessions")),
        sa.UniqueConstraint("session_token_digest", name="uq_auth_sessions_token_digest"),
    )
    op.create_index("ix_auth_sessions_identity_id", "authentication_sessions", ["identity_id"])
    op.create_index("ix_auth_sessions_expiry", "authentication_sessions", ["idle_expires_at", "absolute_expires_at"])

    op.create_table(
        "oidc_login_transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("browser_binding_digest", sa.String(length=64), nullable=False),
        sa.Column("nonce_digest", sa.String(length=64), nullable=False),
        sa.Column("verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_oidc_login_transactions_state_digest_format")),
        sa.CheckConstraint("browser_binding_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_oidc_login_transactions_browser_digest_format")),
        sa.CheckConstraint("nonce_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_oidc_login_transactions_nonce_digest_format")),
        sa.CheckConstraint("char_length(redirect_uri) BETWEEN 1 AND 2048", name=op.f("ck_oidc_login_transactions_redirect_uri_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_transactions")),
        sa.UniqueConstraint("state_digest", name="uq_oidc_transactions_state_digest"),
    )
    op.create_index("ix_oidc_transactions_expiry", "oidc_login_transactions", ["expires_at"])

    op.create_table(
        "authentication_security_events",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("subject", sa.String(length=256), nullable=True),
        sa.Column("correlation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event_type IN ('auth.failure', 'auth.success', 'auth.replay_detected', 'session.created', 'session.expired', 'session.revoked', 'auth.refresh_success', 'auth.refresh_failure', 'auth.logout', 'authz.denial', 'credential.revoked')", name=op.f("ck_authentication_security_events_event_type_values")),
        sa.CheckConstraint("severity IN ('info', 'low', 'medium', 'high', 'critical')", name=op.f("ck_authentication_security_events_severity_values")),
        sa.CheckConstraint("outcome IN ('success', 'denied', 'failure')", name=op.f("ck_authentication_security_events_outcome_values")),
        sa.CheckConstraint("actor_type IN ('user', 'service', 'integration', 'system', 'unknown')", name=op.f("ck_authentication_security_events_actor_type_values")),
        sa.CheckConstraint("source IN ('web', 'desktop', 'vscode', 'backend', 'scheduler')", name=op.f("ck_authentication_security_events_source_values")),
        sa.CheckConstraint("actor_id IS NULL OR char_length(actor_id) BETWEEN 1 AND 128", name=op.f("ck_authentication_security_events_actor_id_length")),
        sa.CheckConstraint("subject IS NULL OR char_length(subject) BETWEEN 1 AND 256", name=op.f("ck_authentication_security_events_subject_length")),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f("ck_authentication_security_events_details_object")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authentication_security_events")),
    )
    op.create_index("ix_auth_security_events_occurred_at", "authentication_security_events", ["occurred_at"])
    op.create_index("ix_auth_security_events_type_time", "authentication_security_events", ["event_type", "occurred_at"])

    op.execute(
        """
        CREATE FUNCTION prevent_authentication_security_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'authentication security events are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_authentication_security_events_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON authentication_security_events
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_authentication_security_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_authentication_security_events_immutable ON authentication_security_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_authentication_security_event_mutation()")
    op.drop_index("ix_auth_security_events_type_time", table_name="authentication_security_events")
    op.drop_index("ix_auth_security_events_occurred_at", table_name="authentication_security_events")
    op.drop_table("authentication_security_events")
    op.drop_index("ix_oidc_transactions_expiry", table_name="oidc_login_transactions")
    op.drop_table("oidc_login_transactions")
    op.drop_index("ix_auth_sessions_expiry", table_name="authentication_sessions")
    op.drop_index("ix_auth_sessions_identity_id", table_name="authentication_sessions")
    op.drop_table("authentication_sessions")
    op.drop_index("ix_external_identities_subject", table_name="external_identities")
    op.drop_table("external_identities")
