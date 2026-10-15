"""Repository base class."""

from __future__ import annotations

from sqlalchemy.orm import Session


class Repository:
    """Base class holding the session that defines the unit of work."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session
