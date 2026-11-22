from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

class SensorReadingRow(Base):
    __tablename__ = "sensor_readings"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False,
    )
    sensor_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, nullable=False,
    )
    sequence: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, nullable=False,
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="bar")

    def __repr__(self) -> str:
        return (
            f"SensorReadingRow(ts={self.timestamp!r}, sensor_id={self.sensor_id!r}, "
            f"seq={self.sequence}, value={self.value})"
        )