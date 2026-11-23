from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


# Tables that must be converted into TimescaleDB hypertables.
# Each entry: (table_name, time_column).
_HYPERTABLES: list[tuple[str, str]] = [
    ("sensor_readings", "timestamp"),
    ("alarm_decisions", "timestamp"),
]

class Database:
    """Thin wrapper around a SQLAlchemy engine and a session factory."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._engine = create_engine(
            url,
            echo=echo,
            future=True,
            pool_pre_ping=True,   # transparently recovers from dropped connections
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            class_=Session,
        )

    # Schema management
    def init_schema(self) -> None:
        """Create tables (idempotent) and ensure hypertables exist."""
        # Import models so they register on Base.metadata. Lazy import to
        # avoid a circular dependency: models import Base from this module.
        from .model import alarm as _alarm  # noqa: F401
        from .model import sensor as _sensor  # noqa: F401

        Base.metadata.create_all(self._engine)
        self._ensure_hypertables()
        print("database schema ready")

    def _ensure_hypertables(self) -> None:
        with self._engine.begin() as conn:
            for table, time_col in _HYPERTABLES:
                conn.execute(text(
                    f"SELECT create_hypertable('{table}', '{time_col}', "
                    f"if_not_exists => TRUE, migrate_data => TRUE)"
                ))
        print("hypertables ensured: %s" + str([t for t, _ in _HYPERTABLES]))

    # Session management
    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session and manage commit/rollback/close in one place."""
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
