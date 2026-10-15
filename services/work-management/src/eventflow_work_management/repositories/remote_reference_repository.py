"""Remote integration reference repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventflow_work_management.models import RemoteIntegrationReference
from eventflow_work_management.repositories.base import Repository


class RemoteReferenceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def link(
        self,
        *,
        workspace_id: UUID,
        provider: str,
        installation_id: str,
        remote_resource_type: str,
        remote_resource_id: str,
        entity_type: str,
        entity_id: UUID,
        url: str | None = None,
    ) -> RemoteIntegrationReference:
        reference = RemoteIntegrationReference(
            id=uuid4(),
            workspace_id=workspace_id,
            provider=provider,
            installation_id=installation_id,
            remote_resource_type=remote_resource_type,
            remote_resource_id=remote_resource_id,
            entity_type=entity_type,
            entity_id=entity_id,
            url=url,
        )
        self._session.add(reference)
        self._session.commit()
        return reference

    def find(
        self,
        *,
        provider: str,
        installation_id: str,
        remote_resource_type: str,
        remote_resource_id: str,
    ) -> RemoteIntegrationReference | None:
        statement = select(RemoteIntegrationReference).where(
            RemoteIntegrationReference.provider == provider,
            RemoteIntegrationReference.installation_id == installation_id,
            RemoteIntegrationReference.remote_resource_type == remote_resource_type,
            RemoteIntegrationReference.remote_resource_id == remote_resource_id,
        )
        return self._session.execute(statement).scalar_one_or_none()
