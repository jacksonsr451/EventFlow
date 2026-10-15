"""Self-contained test helpers (no pytest fixtures or plugins).

Integration tests create a throwaway database, run the Alembic migrations
against it, and drop it afterwards. When no PostgreSQL URL is configured the
tests skip themselves rather than failing.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import testrunner
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = SERVICE_ROOT / "alembic.ini"
MIGRATIONS_DIR = SERVICE_ROOT / "src" / "eventflow_work_management" / "migrations"

TEST_DATABASE_URL_ENV = "EVENTFLOW_TEST_DATABASE_URL"
DATABASE_URL_ENV = "EVENTFLOW_DATABASE_URL"


def require_database_url() -> str:
    """Return the configured admin URL or skip the calling test."""
    url = os.environ.get(TEST_DATABASE_URL_ENV) or os.environ.get(DATABASE_URL_ENV)
    if not url:
        testrunner.skip(
            "no PostgreSQL URL set: configure EVENTFLOW_TEST_DATABASE_URL to run "
            "integration tests"
        )
    return url


def _target_url(admin_url: str, database: str) -> str:
    return make_url(admin_url).set(database=database).render_as_string(
        hide_password=False
    )


def _alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def run_migrations(url: str, revision: str = "head") -> None:
    command.upgrade(_alembic_config(url), revision)


def run_downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(_alembic_config(url), revision)


@contextmanager
def temporary_empty_database(admin_url: str) -> Iterator[tuple[str, Engine]]:
    """Create an empty throwaway database and drop it afterwards."""
    name = f"eventflow_test_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        target = _target_url(admin_url, name)
        engine = create_engine(target, future=True)
        try:
            yield target, engine
        finally:
            engine.dispose()
    finally:
        try:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        finally:
            admin_engine.dispose()


@contextmanager
def temporary_database(admin_url: str) -> Iterator[tuple[str, Engine]]:
    """Create a migrated throwaway database and drop it afterwards."""
    with temporary_empty_database(admin_url) as (target, engine):
        run_migrations(target)
        yield target, engine


@contextmanager
def migrated_engine(admin_url: str) -> Iterator[Engine]:
    """Yield an engine bound to a freshly migrated database."""
    with temporary_database(admin_url) as (_, engine):
        yield engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def unique_slug(prefix: str = "ws") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_key(prefix: str = "PRJ") -> str:
    return f"{prefix[:2].upper()}{uuid.uuid4().hex[:6].upper()}"


def fixed_uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def create_workspace(session: Session, *, name: str = "Acme Inc", slug: str | None = None):
    from eventflow_work_management.models import Workspace

    workspace = Workspace(id=uuid.uuid4(), name=name, slug=slug or unique_slug())
    session.add(workspace)
    session.commit()
    return workspace


def create_project(session: Session, workspace, *, key: str | None = None, name: str = "Payments"):
    from eventflow_work_management.models import Project

    project = Project(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        key=key or unique_key(),
        name=name,
    )
    session.add(project)
    session.commit()
    return project


def create_consultation(
    session: Session,
    workspace,
    project,
    *,
    title: str = "Add CSV export",
    description: str = "Users need CSV export from the dashboard.",
    priority: str = "medium",
    category: str | None = "feature",
    origin: str = "web",
    status: str = "open",
):
    from eventflow_work_management.models import Consultation

    consultation = Consultation(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        author_id=uuid.uuid4(),
        origin=origin,
        title=title,
        description=description,
        category=category,
        priority=priority,
        status=status,
    )
    session.add(consultation)
    session.commit()
    return consultation


def create_proposal(session: Session, workspace, project, consultation, *, version: int = 1):
    from eventflow_work_management.models import Proposal

    proposal = Proposal(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        project_id=project.id,
        consultation_id=consultation.id,
        version=version,
        title="Export proposals",
        technical_description="Implement a streaming CSV export endpoint.",
        scope="Dashboard export control and backend endpoint.",
        justification="Customers requested CSV export.",
        acceptance_criteria=["CSV download works for the current filters"],
        category="feature",
        priority="medium",
        status="in_review",
        proposer_id=uuid.uuid4(),
    )
    session.add(proposal)
    session.commit()
    return proposal
