"""Opaque, sort-bound keyset pagination cursors (Issues #6, #8).

A cursor encodes the last row's sort value(s) plus its id so the next page is a
stable keyset lookup (``x-ordering: stable_keyset_with_resource_id_tiebreaker``).
It is bound to the sort key and direction; reusing it under a different sort is
rejected rather than silently returning wrong pages.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

_DATETIME_KEYS = frozenset({"created_at", "updated_at", "occurred_at", "decided_at"})


class CursorError(ValueError):
    """The supplied cursor is malformed or bound to a different sort."""


def encode_cursor(values: dict[str, object], resource_id: UUID) -> str:
    payload: dict[str, object] = {}
    for key, value in values.items():
        payload[key] = value.isoformat() if isinstance(value, datetime) else value
    payload["id"] = str(resource_id)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, object]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("invalid cursor") from exc
    if not isinstance(payload, dict) or "id" not in payload:
        raise CursorError("invalid cursor")
    decoded: dict[str, object] = {}
    for key, value in payload.items():
        if key == "id":
            decoded[key] = UUID(str(value))
        elif key in _DATETIME_KEYS and isinstance(value, str):
            decoded[key] = datetime.fromisoformat(value)
        elif key in {"k", "d"}:
            decoded[key] = value
        else:
            decoded[key] = value
    return decoded
