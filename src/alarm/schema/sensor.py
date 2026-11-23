"""Schema for the raw pressure readings published by the sensor simulator."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

ALLOWED_UNITS = {"bar", "mbar", "Pa", "kPa", "MPa", "psi"}


class SensorReading(BaseModel):
    timestamp: float = Field(..., gt=0)
    value: float
    unit: str = Field(default="bar")
    sensor_id: str = Field(default="pressure-01")
    sequence: int = Field(..., ge=0)

    model_config = {"frozen": True}

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, v: str) -> str:
        if v not in ALLOWED_UNITS:
            raise ValueError(f"unit must be one of {sorted(ALLOWED_UNITS)}, got {v!r}")
        return v