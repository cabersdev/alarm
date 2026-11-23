"""Schema for the alarm decision."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .stats import CorrectionMethod, WindowStats


AlarmState = Literal["ON", "OFF"]
AlarmTransition = Literal["turn_on", "turn_off", "keep_on", "keep_off"]


class AlarmDecision(BaseModel):
    timestamp: float = Field(..., gt=0)
    sensor_id: str = Field(default="pressure-01")

    state: AlarmState
    previous_state: AlarmState
    transition: AlarmTransition

    test_rejected: bool
    correction_method_used: CorrectionMethod

    # NEW: allow the initial OFF (no window) and the per-window decision
    window_seq: int = Field(..., ge=-1, description="-1 marks the initial OFF at startup")
    stats: Optional[WindowStats] = Field(
        default=None,
        description="Triggering window; None for the initial OFF",
    )

    persistence_n: int = Field(..., ge=1)
    hysteresis: float = Field(..., ge=0)
    streak_reject: int = Field(..., ge=0)
    streak_below: int = Field(..., ge=0)

    @property
    def state_changed(self) -> bool:
        return self.transition in ("turn_on", "turn_off")

    @property
    def is_initial(self) -> bool:
        return self.window_seq == -1 and self.stats is None

    @model_validator(mode="after")
    def _check_consistency(self) -> "AlarmDecision":
        # Initial OFF is exempt from state-machine validation
        if self.is_initial:
            if self.state != "OFF" or self.previous_state != "OFF":
                raise ValueError("initial decision must have state == previous_state == OFF")
            if self.transition != "keep_off":
                raise ValueError("initial decision must have transition == keep_off")
            return self

        if self.state_changed != (self.state != self.previous_state):
            raise ValueError(
                f"transition inconsistent with (state != previous_state): "
                f"transition={self.transition!r}, state={self.state!r}, "
                f"previous={self.previous_state!r}"
            )

        if self.transition == "turn_on":
            if not self.test_rejected:
                raise ValueError("turn_on requires test_rejected=True")
            if self.streak_reject < self.persistence_n:
                raise ValueError(
                    f"turn_on requires streak_reject >= persistence_n "
                    f"({self.streak_reject} < {self.persistence_n})"
                )

        if self.transition == "turn_off":
            if self.streak_below < self.persistence_n:
                raise ValueError(
                    f"turn_off requires streak_below >= persistence_n "
                    f"({self.streak_below} < {self.persistence_n})"
                )

        if self.transition == "keep_on":
            if self.previous_state != "ON" or self.state != "ON":
                raise ValueError("keep_on requires previous_state == state == ON")

        if self.transition == "keep_off":
            if self.previous_state != "OFF" or self.state != "OFF":
                raise ValueError("keep_off requires previous_state == state == OFF")

        return self