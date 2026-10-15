"""Engine and session factory construction."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    """Create a PostgreSQL engine for the service.

    ``pool_pre_ping`` revalidates pooled connections so a restarted database
    does not surface as a spurious first-request failure.
    """
    return create_engine(url, echo=echo, pool_pre_ping=True, future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory with explicit transaction control.

    ``expire_on_commit=False`` keeps loaded attributes usable after commit, and
    ``autoflush=False`` prevents accidental partial flushes before a repository
    has finished building an aggregate.
    """
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        future=True,
    )
