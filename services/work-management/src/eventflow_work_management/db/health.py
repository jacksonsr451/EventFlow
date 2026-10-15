"""Database connectivity health check."""

from __future__ import annotations

from sqlalchemy import Engine, text


def check_database_health(engine: Engine) -> bool:
    """Return ``True`` when the database answers a trivial query."""
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
    return result == 1
