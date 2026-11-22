from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AlarmDecisionRow(Base):
    __tablename__ = "alarm_decisions"

    # Composite PK includes timestamp for TimescaleDB partitioning.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False,
    )
    sensor_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, nullable=False,
    )
    window_seq: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, nullable=False,
    )

    # State machine
    state: Mapped[str] = mapped_column(String(8), nullable=False)           # ON / OFF
    previous_state: Mapped[str] = mapped_column(String(8), nullable=False)
    transition: Mapped[str] = mapped_column(String(16), nullable=False)
    test_rejected: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Configuration that drove the decision
    correction_method: Mapped[str] = mapped_column(String(16), nullable=False)
    persistence_n: Mapped[int] = mapped_column(nullable=False)
    hysteresis: Mapped[float] = mapped_column(Float, nullable=False)

    # Streaks
    streak_reject: Mapped[int] = mapped_column(nullable=False)
    streak_below: Mapped[int] = mapped_column(nullable=False)

    # Denormalized statistics (nullable: initial OFF has no window)
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    std: Mapped[float | None] = mapped_column(Float, nullable=True)
    lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value_adj: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)   # = stats.mu0

    def __repr__(self) -> str:
        return (
            f"AlarmDecisionRow(ts={self.timestamp!r}, state={self.state!r}, "
            f"transition={self.transition!r}, window_seq={self.window_seq})"
        )