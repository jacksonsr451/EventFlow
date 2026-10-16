"""Redact query-string credentials from standard Uvicorn access logs."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit


class RedactAccessQueryFilter(logging.Filter):
    """Never emit query strings, which may contain OAuth codes or state."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return True
        args = list(record.args)
        # Uvicorn's access log arguments are client, method, full_path,
        # http_version, status. Do not assume the format beyond that tuple shape.
        if len(args) >= 3 and isinstance(args[2], str):
            parsed = urlsplit(args[2])
            args[2] = parsed.path
            record.args = tuple(args)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactAccessQueryFilter) for item in logger.filters):
        logger.addFilter(RedactAccessQueryFilter())
