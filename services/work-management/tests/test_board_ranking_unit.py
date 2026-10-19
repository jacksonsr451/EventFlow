"""Unit tests for deterministic board ranking and lifecycle transitions (Issue #8)."""

from __future__ import annotations

from eventflow_work_management.services.board_ranking import (
    ALPHABET,
    RANK_MAX_LENGTH,
    RankSpaceExhausted,
    rank_after,
    rank_before,
    rank_between,
    rank_for_position,
)
from eventflow_work_management.services.work_item_transitions import (
    TERMINAL_STATUSES,
    is_valid_transition,
)


def _ordered(*ranks: str) -> list[str]:
    return sorted(ranks)


def test_rank_after_is_greater():
    previous = "U"
    for _ in range(50):
        following = rank_after(previous)
        assert previous < following
        assert len(following) <= RANK_MAX_LENGTH
        previous = following


def test_rank_before_is_less():
    following = "z" * 4
    for _ in range(20):
        previous = rank_before(following)
        assert previous < following
        assert len(previous) <= RANK_MAX_LENGTH
        following = previous


def test_midpoint_is_strictly_between():
    for low, high in [("A", "B"), ("A", "C"), ("A0", "A1"), ("A", "A0Z"), ("9", "A")]:
        middle = rank_between(low, high)
        assert low < middle < high, (low, middle, high)


def test_repeated_insertion_at_same_boundary_preserves_order():
    ranks = ["A", "Z"]
    for _ in range(40):
        middle = rank_between("A", ranks[1])
        ranks.insert(1, middle)
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
    assert all(len(rank) <= RANK_MAX_LENGTH for rank in ranks)


def test_rank_between_open_ends():
    assert rank_between(None, None) == ALPHABET[len(ALPHABET) // 2]
    high = rank_between(None, "U")
    assert high < "U"
    low = rank_between("U", None)
    assert low > "U"


def test_rank_for_position_places_card():
    siblings = _ordered("B", "D", "F")
    # Before B
    assert rank_for_position(siblings, "A") < "B"
    # Between B and D
    between = rank_for_position(siblings, "C")
    assert "B" < between < "D"
    # After the last card
    assert rank_for_position(siblings, "z") > "F"


def test_rank_before_minimum_is_exhausted():
    try:
        rank_before("0" * 8)
    except RankSpaceExhausted:
        return
    raise AssertionError("expected RankSpaceExhausted")


def test_transitions_follow_the_lifecycle():
    assert is_valid_transition("ready", "in_progress")
    assert is_valid_transition("in_progress", "in_review")
    assert is_valid_transition("in_review", "done")
    assert is_valid_transition("in_review", "in_progress")
    assert not is_valid_transition("ready", "done")
    assert not is_valid_transition("done", "ready")
    assert not is_valid_transition("cancelled", "in_progress")


def test_same_status_transition_is_a_noop():
    for status in ("ready", "in_progress", "in_review", "blocked", "done", "cancelled"):
        assert is_valid_transition(status, status)


def test_terminal_statuses():
    assert TERMINAL_STATUSES == frozenset({"done", "cancelled"})
