"""Integration tests for remote integration references."""

from __future__ import annotations

from uuid import uuid4

import testrunner
from sqlalchemy.exc import IntegrityError

from eventflow_work_management.repositories import RemoteReferenceRepository
from support import (
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
        repository = RemoteReferenceRepository(session)
        resource = _resource()
        entity_id = uuid4()

        repository.link(
            workspace_id=workspace.id,
            entity_type="consultation",
            entity_id=entity_id,
            url="https://github.com/acme/repo/issues/1",
            **resource,
        )
        found = repository.find(**resource)

        assert found is not None
        assert found.entity_id == entity_id
        assert found.workspace_id == workspace.id


def test_duplicate_remote_resource_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        repository = RemoteReferenceRepository(session)
        resource = _resource()

        repository.link(
            workspace_id=workspace.id,
            entity_type="consultation",
            entity_id=uuid4(),
            **resource,
        )
        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace.id,
                entity_type="work_item",
                entity_id=uuid4(),
                **resource,
            )
        session.rollback()


def test_invalid_provider_is_rejected():
    admin_url = require_database_url()
    with migrated_engine(admin_url) as engine, session_scope(engine) as session:
        workspace = create_workspace(session)
        repository = RemoteReferenceRepository(session)
        with testrunner.raises(IntegrityError):
            repository.link(
                workspace_id=workspace.id,
                provider="bitbucket",
                installation_id="1",
                remote_resource_type="issue",
                remote_resource_id="42",
                entity_type="consultation",
                entity_id=uuid4(),
            )
        session.rollback()
