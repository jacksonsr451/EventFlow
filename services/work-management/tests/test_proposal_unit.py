"""Unit tests for the proposal service helpers (Issue #6).

No database is required. These tests pin the normalization, pagination, and
entity-tag behaviour that the ProposalService relies on so the wire contract
cannot drift from enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import testrunner
from eventflow_work_management.models import Proposal
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.proposal import (
    ProposalService,
    _decode_cursor,
    _decode_revision_cursor,
    _encode_cursor,
    _encode_revision_cursor,
    _parse_sort,
    proposal_etag,
)


def _rejected(callable_) -> ProblemError:
    with testrunner.raises(ProblemError) as caught:
        callable_()
    assert caught.value.code == "VALIDATION_ERROR"
    return caught.value


def test_checklist_normalization_assigns_stable_item_ids():
    normalized = ProposalService._normalize_checklist(
        [{"text": "Add streaming writer"}, {"text": "Add tests", "done": True}]
    )
    assert [item["text"] for item in normalized] == [
        "Add streaming writer",
        "Add tests",
    ]
    assert normalized[1]["done"] is True
    for item in normalized:
        UUID(item["item_id"])


def test_checklist_preserves_supplied_item_id_and_rejects_duplicates():
    item_id = uuid4()
    normalized = ProposalService._normalize_checklist(
        [{"item_id": str(item_id), "text": "Keep me"}]
    )
    assert normalized[0]["item_id"] == str(item_id)

    _rejected(
        lambda: ProposalService._normalize_checklist(
            [
                {"item_id": str(item_id), "text": "First"},
                {"item_id": str(item_id), "text": "Second"},
            ]
        )
    )
    _rejected(
        lambda: ProposalService._normalize_checklist(
            [{"text": "Extra", "unexpected": True}]
        )
    )


def test_dependencies_must_be_unique_and_non_empty():
    assert ProposalService._normalize_dependencies(["ISSUE-1", "ISSUE-2"]) == [
        "ISSUE-1",
        "ISSUE-2",
    ]
    _rejected(
        lambda: ProposalService._normalize_dependencies(["ISSUE-1", "ISSUE-1"])
    )
    _rejected(lambda: ProposalService._normalize_dependencies([""]))


def test_estimated_hours_are_bounded():
    assert ProposalService._normalize_estimated_hours(8) == 8.0
    assert ProposalService._normalize_estimated_hours(None) is None
    _rejected(lambda: ProposalService._normalize_estimated_hours(0.1))
    _rejected(lambda: ProposalService._normalize_estimated_hours(10_000))
    _rejected(lambda: ProposalService._normalize_estimated_hours(True))


def test_evidence_identifiers_are_deduplicated_and_validated():
    evidence_id = uuid4()
    assert ProposalService._normalize_evidence_ids([str(evidence_id)]) == [evidence_id]
    _rejected(
        lambda: ProposalService._normalize_evidence_ids(
            [str(evidence_id), str(evidence_id)]
        )
    )
    _rejected(lambda: ProposalService._normalize_evidence_ids(["not-a-uuid"]))


def test_sort_parsing_defaults_and_rejects_unknown_keys():
    assert _parse_sort(None) == ("created_at", False)
    assert _parse_sort("version") == ("version", False)
    assert _parse_sort("-updated_at") == ("updated_at", True)
    _rejected(lambda: _parse_sort("unknown"))


def test_cursor_round_trip_is_bound_to_sort():
    proposal_id = uuid4()
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    cursor = _encode_cursor("created_at", False, moment, proposal_id)
    value, decoded_id = _decode_cursor(cursor, "created_at", False)
    assert value == moment
    assert decoded_id == proposal_id

    # A cursor minted for one sort cannot be replayed against another.
    _rejected(lambda: _decode_cursor(cursor, "updated_at", False))
    _rejected(lambda: _decode_cursor("not-base64", "created_at", False))


def test_revision_cursor_round_trip():
    cursor = _encode_revision_cursor(3)
    assert _decode_revision_cursor(cursor) == 3
    _rejected(lambda: _decode_revision_cursor("not-base64"))


def test_proposal_etag_tracks_the_revision():
    proposal = Proposal(
        id=uuid4(),
        version=1,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    first = proposal_etag(proposal)
    assert first.startswith('"') and first.endswith('"')

    proposal.version = 2
    assert proposal_etag(proposal) != first
