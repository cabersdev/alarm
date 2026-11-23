"""Database configuration for the MCC time-series store."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


_HYPERTABLES: list[tuple[str, str]] = [
    ("sensor_readings", "timestamp"),
    ("alarm_decisions", "timestamp"),
]


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._engine = create_engine(url, echo=echo, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, class_=Session,
        )

    def init_schema(self) -> None:
        from .model import alarm as _alarm  # noqa: F401
        from .model import sensor as _sensor  # noqa: F401

        Base.metadata.create_all(self._engine)
        self._ensure_hypertables()
        log.info("database schema ready")

    def _ensure_hypertables(self) -> None:
        with self._engine.begin() as conn:
            for table, time_col in _HYPERTABLES:
                conn.execute(text(
                    f"SELECT create_hypertable('{table}', '{time_col}', "
                    f"if_not_exists => TRUE, migrate_data => TRUE)"
                ))
        log.info("hypertables ensured: %s", [t for t, _ in _HYPERTABLES])

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()