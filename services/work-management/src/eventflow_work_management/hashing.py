"""Deterministic hashing helpers for audit snapshots and idempotency keys."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    """Return the lowercase hex SHA-256 digest of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint(payload: Any) -> str:
    """Return the SHA-256 fingerprint of a canonical JSON payload."""
    return sha256_hex(canonical_json(payload))
