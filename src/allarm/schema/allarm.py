"""Schema for the alarm decision.

The alarm consumes WindowStats messages and produces a boolean state (ON/OFF)
with persistence and hysteresis:

- **Turn ON**: the last `persistence_n` windows all reject H0 under the
  configured correction method.
- **Turn OFF**: the last `persistence_n` windows all satisfy the turn-off
  condition: mean < mu0 - hysteresis (hysteresis band on the mean).
- **Otherwise**: keep the previous state (this is the persistence/hysteresis
  mechanism, which decouples the alarm state from the noisy per-window test).

The schema embeds the triggering WindowStats so the decision is fully
auditable.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .stats import CorrectionMethod, WindowStats


AlarmState = Literal["ON", "OFF"]
AlarmTransition = Literal["turn_on", "turn_off", "keep_on", "keep_off"]


class AlarmDecision(BaseModel):
    """The alarm decision produced after processing one WindowStats."""

    # Identity
    timestamp: float = Field(..., gt=0, description="Decision timestamp (epoch seconds)")
    sensor_id: str = Field(default="pressure-01")

    # State machine
    state: AlarmState = Field(..., description="Current alarm state")
    previous_state: AlarmState = Field(..., description="State before this decision")
    transition: AlarmTransition = Field(..., description="Type of transition")

    # Test result that drove the decision
    test_rejected: bool = Field(
        ..., description="Whether the latest window rejected H0 under the chosen correction"
    )
    correction_method_used: CorrectionMethod = Field(
        ..., description="Correction method that produced test_rejected"
    )

    # Persistence / hysteresis context
    persistence_n: int = Field(..., ge=1, description="Consecutive windows required for a transition")
    hysteresis: float = Field(..., ge=0, description="Turn-off band width on the mean")
    streak_reject: int = Field(
        ..., ge=0, le=None,
        description="Consecutive windows (ending with this one) that rejected H0",
    )
    streak_below: int = Field(
        ..., ge=0, le=None,
        description="Consecutive windows (ending with this one) with mean < mu0 - hysteresis",
    )

    # Computed
    @property
    def state_changed(self) -> bool:
        return self.transition in ("turn_on", "turn_off")

    # Consistency validators
    @model_validator(mode="after")
    def _check_consistency(self) -> "AlarmDecision":
        if self.state_changed != (self.state != self.previous_state):
            raise ValueError(
                "transition inconsistent with (state != previous_state): "
                f"transition={self.transition!r}, "
                f"state={self.state!r}, previous={self.previous_state!r}"
            )

        # Turn-on must be preceded by a rejection with enough streak
        if self.transition == "turn_on":
            if not self.test_rejected:
                raise ValueError("turn_on requires test_rejected=True")
            if self.streak_reject < self.persistence_n:
                raise ValueError(
                    f"turn_on requires streak_reject >= persistence_n "
                    f"({self.streak_reject} < {self.persistence_n})"
                )

        # Turn-off must be preceded by enough consecutive "below threshold"
        if self.transition == "turn_off":
            if self.streak_below < self.persistence_n:
                raise ValueError(
                    f"turn_off requires streak_below >= persistence_n "
                    f"({self.streak_below} < {self.persistence_n})"
                )

        # Keep-on: any combination consistent with "still ON, no turn-off condition"
        if self.transition == "keep_on":
            if self.previous_state != "ON" or self.state != "ON":
                raise ValueError("keep_on requires previous_state == state == ON")

        # Keep-off: any combination consistent with "still OFF, no turn-on condition"
        if self.transition == "keep_off":
            if self.previous_state != "OFF" or self.state != "OFF":
                raise ValueError("keep_off requires previous_state == state == OFF")

        return self