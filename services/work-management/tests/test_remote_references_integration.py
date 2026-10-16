"""Integration tests for remote integration references."""

from __future__ import annotations

from uuid import uuid4

import testrunner
from eventflow_work_management.repositories import RemoteReferenceRepository
from sqlalchemy.exc import IntegrityError
from support import (
    create_consultation,
    create_project,
    create_workspace,
    migrated_engine,
    require_database_url,
    session_scope,
)


def _resource():
    return {
        "provider": "github",
        "installation_id": "12345678",
        "remote_resource_type": "issue",
        "remote_resource_id": uuid4().hex,
    }


def test_link_and_find_round_trip():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        repository = RemoteReferenceRepository(session)
        resource = _resource()

        repository.link(
            workspace_id=workspace.id,
            entity_type="consultation",
            entity_id=consultation.id,
            url="https://github.com/acme/repo/issues/1",
            **resource,
        )
        found = repository.find(**resource)

        assert found is not None
        assert found.entity_id == consultation.id
        assert found.workspace_id == workspace.id


def test_duplicate_remote_resource_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        repository = RemoteReferenceRepository(session)
        resource = _resource()

        repository.link(
            workspace_id=workspace.id,
            entity_type="consultation",
            entity_id=consultation.id,
            **resource,
        )
        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace.id,
                entity_type="consultation",
                entity_id=uuid4(),
                **resource,
            )
        session.rollback()


def test_invalid_provider_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        project = create_project(session, workspace)
        consultation = create_consultation(session, workspace, project)
        repository = RemoteReferenceRepository(session)
        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace.id,
                provider="bitbucket",
                installation_id="1",
                remote_resource_type="issue",
                remote_resource_id="42",
                entity_type="consultation",
                entity_id=consultation.id,
            )
        session.rollback()


def test_reference_to_unknown_entity_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        repository = RemoteReferenceRepository(session)
        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace.id,
                entity_type="consultation",
                entity_id=uuid4(),
                **_resource(),
            )
        session.rollback()


def test_reference_to_another_workspace_entity_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace_a = create_workspace(session, name="Tenant A")
        workspace_b = create_workspace(session, name="Tenant B")
        project_a = create_project(session, workspace_a)
        consultation_a = create_consultation(session, workspace_a, project_a)
        repository = RemoteReferenceRepository(session)

        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace_b.id,
                entity_type="consultation",
                entity_id=consultation_a.id,
                **_resource(),
            )
        session.rollback()


def test_reference_to_unknown_entity_type_is_allowed():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        repository = RemoteReferenceRepository(session)
        reference = repository.link(
            workspace_id=workspace.id,
            entity_type="external_tracker_item",
            entity_id=uuid4(),
            **_resource(),
        )
        assert reference.id is not None
