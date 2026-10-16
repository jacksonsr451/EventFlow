"""Malware scanning boundary for consultation attachments (Issue #4).

The scanner is an injected dependency so the attachment pipeline is fail-closed
by construction: with no scanner configured every upload is reported as
``unknown`` and therefore quarantined. Nothing in this module inspects or trusts
the uploaded bytes; it only classifies the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

CLEAN = "clean"
INFECTED = "infected"
UNKNOWN = "unknown"

SCAN_VERDICT_VALUES = (CLEAN, INFECTED, UNKNOWN)


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The verdict for one scanned object."""

    verdict: str
    detail: str | None = None


class MalwareScanner(Protocol):
    """Structural interface every configured scanner must satisfy."""

    def scan(self, *, content: bytes, content_type: str) -> ScanResult:
        """Return a verdict for the object without raising for a positive match."""
        ...


class UnconfiguredMalwareScanner:
    """Default scanner used when no scanning backend is configured.

    It never reports ``clean``: an unscanned object must never become available.
    """

    def scan(self, *, content: bytes, content_type: str) -> ScanResult:
        return ScanResult(verdict=UNKNOWN, detail="no_scanner_configured")


class StaticMalwareScanner:
    """Deterministic scanner for tests and local development.

    A verdict is chosen by an injected callable so tests can drive clean,
    infected, and unknown outcomes without a real scanning backend.
    """

    def __init__(self, verdict: str, detail: str | None = None) -> None:
        if verdict not in SCAN_VERDICT_VALUES:
            raise ValueError(f"unknown scan verdict: {verdict}")
        self._verdict = verdict
        self._detail = detail

    def scan(self, *, content: bytes, content_type: str) -> ScanResult:
        return ScanResult(verdict=self._verdict, detail=self._detail)
