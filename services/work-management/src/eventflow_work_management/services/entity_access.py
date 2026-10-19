"""Resolve a collaboration target from its public collection segment (Issue #29).

Collaboration routes are entity-scoped: a client names a collection and an id.
This module is the single place that maps the public segment onto the canonical
``entity_type`` vocabulary, loads the row inside the caller's workspace, and
returns the project scope used for the composite foreign keys.

An unknown collection and a missing or foreign entity both return ``404`` so a
cross-workspace probe cannot distinguish "unsupported" from "not visible".
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from eventflow_work_management.repositories.board_repository import BoardCardRepository
from eventflow_work_management.repositories.consultation_repository import (
    ConsultationRepository,
)
from eventflow_work_management.repositories.proposal_repository import ProposalRepository
from eventflow_work_management.repositories.work_item_repository import WorkItemRepository
from eventflow_work_management.security.errors import ProblemError

COLLECTION_ENTITY_TYPES: dict[str, str] = {
    "consultations": "consultation",
    "proposals": "proposal",
    "work-items": "work_item",
    "board-cards": "board_card",
}

SUPPORTED_COLLECTIONS = tuple(COLLECTION_ENTITY_TYPES)

_NOT_FOUND = "The requested resource was not found."


def _not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    entity_type: str
    entity_id: UUID
    project_id: UUID


def entity_type_for(collection: str) -> str:
    entity_type = COLLECTION_ENTITY_TYPES.get(collection)
    if entity_type is None:
        # Do not disclose that the collection is unsupported.
        raise _not_found()
    return entity_type


def resolve_entity(
    session: Session,
    *,
    workspace_id: UUID,
    collection: str,
    entity_id: UUID,
    for_attachment: bool = False,
) -> ResolvedEntity:
    """Load the target entity within the workspace or raise a hidden 404.

    Consultations keep their dedicated Issue #4 attachment pipeline, so generic
    attachment routes hide that collection behind the same 404 as an unknown
    one.
    """
    entity_type = entity_type_for(collection)
    if for_attachment and collection == "consultations":
        raise _not_found()

    if collection == "consultations":
        entity = ConsultationRepository(session).get(
            workspace_id=workspace_id, consultation_id=entity_id
        )
    elif collection == "proposals":
        entity = ProposalRepository(session).get(
            workspace_id=workspace_id, proposal_id=entity_id
        )
    elif collection == "work-items":
        entity = WorkItemRepository(session).get(
            workspace_id=workspace_id, work_item_id=entity_id
        )
    else:
        entity = BoardCardRepository(session).get(
            workspace_id=workspace_id, card_id=entity_id
        )

    if entity is None:
        raise _not_found()
    return ResolvedEntity(
        entity_type=entity_type,
        entity_id=entity.id,
        project_id=entity.project_id,
    )
