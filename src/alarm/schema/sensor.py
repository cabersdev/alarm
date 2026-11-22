"""Schema for the raw pressure readings published by the sensor simulator.

Assumptions (per the task):
- The simulator produces exact iid samples from N(mu, sigma^2).
- No additional measurement noise is added on top of the Gaussian sampling.
- Timestamps are Unix epoch seconds (UTC).
- The unit of measure is explicit, to avoid downstream unit-mismatch bugs.
"""

from __future__ import annotations
from pydantic import BaseModel, Field

ALLOWED_UNITS = {"bar", "mbar", "Pa", "kPa", "MPa", "psi"}

class SensorReading(BaseModel):
    """A single pressure sample as published on the raw topic."""

    timestamp: float = Field(
        ...,
        gt=0,
        description="Unix epoch seconds (UTC) when the sample was generated",
    )
    value: float = Field(
        ...,
        description="Pressure value expressed in `unit`. Exact sample from N(mu, sigma^2).",
    )
    unit: str = Field(
        default="bar",
        description=f"Unit of measure, one of {sorted(ALLOWED_UNITS)}",
    )
    sensor_id: str = Field(
        default="pressure-01",
        description="Identifier of the sensor producing the sample",
    )
    sequence: int | None = Field(
        ...,
        ge=0,
        description="Monotonic counter; used downstream to detect drops",
    )

    def validate_unit(self) -> "SensorReading":
        if self.unit not in ALLOWED_UNITS:
            raise ValueError(
                f"unit must be one of {sorted(ALLOWED_UNITS)}, got {self.unit!r}"
            )
        return self