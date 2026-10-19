"""Deterministic, server-authoritative board-card ranking (Issue #8).

Ranks are opaque ordering keys over the alphabet ``[0-9A-Za-z]`` (a subset of the
persisted ``^[0-9a-zA-Z_-]+$`` constraint). Two ranks compare lexicographically;
a new rank is always computed *between* the neighbours of the requested position
so the API is the sole authority over stored ordering and repeated inserts never
collide.

The algorithm is a lexicographic fractional index: inserting between ``a`` and
``b`` returns the shortest string ``m`` with ``a < m < b``. Keys generated here
never end in the minimum digit, which guarantees a valid predecessor always
exists and keeps key growth slow.
"""

from __future__ import annotations

import bisect

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(ALPHABET)
_INDEX = {character: position for position, character in enumerate(ALPHABET)}
_MID = ALPHABET[_BASE // 2]
RANK_MAX_LENGTH = 64
# A safety bound for the equal-prefix walk; inputs are always distinct.
_MAX_DIGITS = RANK_MAX_LENGTH + 8


class RankSpaceExhausted(Exception):
    """No rank can be produced within the persisted length bound."""


def _digits(value: str) -> list[int]:
    return [_INDEX[character] for character in value]


def _string(digits: list[int]) -> str:
    return "".join(ALPHABET[digit] for digit in digits)


def first_rank() -> str:
    """The seed rank for the first card in an empty column."""
    return _MID


def rank_after(previous: str) -> str:
    """Return the shortest rank strictly greater than ``previous``."""
    for position in range(len(previous) - 1, -1, -1):
        digit = _INDEX[previous[position]]
        if digit < _BASE - 1:
            return previous[:position] + ALPHABET[digit + 1]
    return previous + _MID


def rank_before(following: str) -> str:
    """Return a rank strictly less than ``following``."""
    for position, character in enumerate(following):
        digit = _INDEX[character]
        if digit > 0:
            return following[:position] + ALPHABET[digit - 1] + _MID
    raise RankSpaceExhausted("no rank exists before the minimum key")


def _midpoint(low: str, high: str) -> str:
    """Return a rank ``m`` with ``low < m < high``."""
    result: list[int] = []
    position = 0
    while position < _MAX_DIGITS:
        low_digit = _INDEX[low[position]] if position < len(low) else 0
        high_digit = _INDEX[high[position]] if position < len(high) else 0
        if low_digit == high_digit:
            result.append(low_digit)
            position += 1
            continue
        if high_digit - low_digit >= 2:
            result.append((low_digit + high_digit) // 2)
            return _string(result)
        # The digits are adjacent: take the low digit and exceed the low tail.
        result.append(low_digit)
        if position + 1 < len(low):
            result.extend(_digits(low[position + 1 :]))
        result.append(_BASE // 2)
        return _string(result)
    raise RankSpaceExhausted("no rank exists between the supplied neighbours")


def rank_between(previous: str | None, following: str | None) -> str:
    """Return a rank strictly between the neighbours (``None`` is an open end)."""
    if previous is None and following is None:
        rank = first_rank()
    elif previous is None:
        rank = rank_before(following)  # type: ignore[arg-type]
    elif following is None:
        rank = rank_after(previous)
    else:
        rank = _midpoint(previous, following)
    if len(rank) > RANK_MAX_LENGTH:
        raise RankSpaceExhausted("the computed rank exceeds the persisted bound")
    return rank


def rank_for_position(siblings: list[str], target_rank: str) -> str:
    """Return a rank placing a card at ``target_rank`` among sorted ``siblings``.

    ``siblings`` are the other cards' ranks in the destination column, sorted
    ascending. The new card is placed immediately before the first sibling whose
    rank is greater than or equal to ``target_rank``.
    """
    index = bisect.bisect_left(siblings, target_rank)
    previous = siblings[index - 1] if index > 0 else None
    following = siblings[index] if index < len(siblings) else None
    return rank_between(previous, following)


def parse_rank_value(rank: str) -> list[int]:
    """Expose the decoded rank digits (used by tests)."""
    return _digits(rank)
