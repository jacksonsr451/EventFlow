"""Shared hostile-input handling for every attachment surface (Issues #4, #29).

Consultation attachments (Issue #4) and generic entity attachments (Issue #29)
must apply exactly the same validation, content sniffing, size bound, and
fail-closed scan classification. Keeping the pure logic here means there is one
implementation to audit and no behavioral drift between the two tables.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

from eventflow_work_management.security.attachment_scanner import CLEAN, INFECTED
from eventflow_work_management.security.errors import ProblemError

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_FILENAME_LENGTH = 255

AVAILABLE_STATUS = "available"
QUARANTINED_STATUS = "quarantined"
REJECTED_STATUS = "rejected"

MALWARE_REJECTION_REASON = "malware_detected"

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "application/pdf",
        "text/plain",
    }
)

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)

_NOT_FOUND = "The requested resource was not found."


def not_found() -> ProblemError:
    return ProblemError(
        status_code=404, code="NOT_FOUND", detail=_NOT_FOUND, title="Not found"
    )


def validation(detail: str, *, status_code: int = 400) -> ProblemError:
    return ProblemError(
        status_code=status_code,
        code="VALIDATION_ERROR",
        detail=detail,
        title="Invalid request" if status_code == 400 else "Unprocessable entity",
    )


def conflict(detail: str, *, code: str = "CONFLICT") -> ProblemError:
    return ProblemError(status_code=409, code=code, detail=detail, title="Conflict")


def normalize_file_name(file_name: str) -> str:
    candidate = file_name.strip()
    if not candidate:
        raise validation("The file name is required.")
    if len(candidate) > MAX_FILENAME_LENGTH:
        raise validation("The file name is too long.", status_code=422)
    if candidate in {".", ".."}:
        raise validation("The file name is invalid.", status_code=422)
    if any(separator in candidate for separator in ("/", "\\")):
        raise validation("The file name must not contain a path.", status_code=422)
    if any(ord(character) < 32 for character in candidate):
        raise validation(
            "The file name must not contain control characters.", status_code=422
        )
    return candidate


def decode_content(content_base64: str) -> bytes:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise validation("The attachment content is not valid base64.") from exc
    if not data:
        raise validation("The attachment content is empty.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise validation("The attachment exceeds the maximum size.", status_code=422)
    return data


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def detect_content_type(data: bytes, declared: str) -> str | None:
    for signature, content_type in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return content_type
    if declared == "text/plain" and _looks_like_text(data):
        return "text/plain"
    return None


def classify(verdict: str) -> tuple[str, str | None, str]:
    if verdict == CLEAN:
        return AVAILABLE_STATUS, None, "attachment.uploaded"
    if verdict == INFECTED:
        return REJECTED_STATUS, MALWARE_REJECTION_REASON, "attachment.rejected"
    return QUARANTINED_STATUS, None, "attachment.quarantined"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    file_name: str
    content_type: str
    data: bytes
    checksum_sha256: str


def validate_upload(
    *, file_name: str, content_type: str, content_base64: str
) -> ValidatedUpload:
    """Normalize and fully validate an upload before any persistence."""
    normalized_name = normalize_file_name(file_name)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise validation(
            "The attachment content type is not permitted.", status_code=422
        )
    data = decode_content(content_base64)
    detected = detect_content_type(data, content_type)
    if detected is None or detected != content_type:
        raise validation(
            "The attachment content does not match its declared content type.",
            status_code=422,
        )
    return ValidatedUpload(
        file_name=normalized_name,
        content_type=detected,
        data=data,
        checksum_sha256=hashlib.sha256(data).hexdigest(),
    )
