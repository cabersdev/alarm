from __future__ import annotations

import time
from typing import Literal, Optional, Protocol

from ..schema.alarm import AlarmDecision, AlarmState, AlarmTransition
from ..schema.stats import CorrectionMethod, WindowStats

from ..config import load_config

class AlarmPublisher(Protocol):
    def publish(self, decision: AlarmDecision) -> None: ...


class AlarmService:
    """Hysteresis + persistence alarm on top of the t-test decision."""

    cfg = load_config()

    def __init__(
        self,
        publisher: AlarmPublisher,
        *,
        threshold: float = cfg.alarm.threshold,
        hysteresis: float = cfg.alarm.hysteresis,
        persistence_n: int = 3,
        correction_method: CorrectionMethod = cfg.alarm.correction_method,
        sensor_id: str = cfg.sensor.id,
    ) -> None:
        if persistence_n < 1:
            raise ValueError("persistence_n must be >= 1")
        if hysteresis < 0:
            raise ValueError("hysteresis must be >= 0")

        self._publisher = publisher
        self._threshold = threshold
        self._hysteresis = hysteresis
        self._persistence_n = persistence_n
        self._method = correction_method
        self._sensor_id = sensor_id

        self._state: AlarmState = "OFF"
        self._streak_reject = 0
        self._streak_below = 0

    # Public API
    def on_stats(self, window: WindowStats) -> AlarmDecision:
        previous_state = self._state
        rejected = self._is_rejected(window)
        below = window.mean < (self._threshold - self._hysteresis)

        # Update streaks (always track the raw observations)
        self._streak_reject = self._streak_reject + 1 if rejected else 0
        self._streak_below = self._streak_below + 1 if below else 0

        # Apply transitions
        transition: AlarmTransition
        if self._state == "OFF":
            if self._streak_reject >= self._persistence_n:
                self._state = "ON"
                transition = "turn_on"
            else:
                transition = "keep_off"
        else:  # ON
            if self._streak_below >= self._persistence_n:
                self._state = "OFF"
                transition = "turn_off"
            else:
                transition = "keep_on"

        decision = AlarmDecision(
            timestamp=time.time(),
            sensor_id=self._sensor_id,
            state=self._state,
            previous_state=previous_state,
            transition=transition,
            test_rejected=rejected,
            correction_method_used=self._method,
            window_seq=window.window_seq,
            stats=window,
            persistence_n=self._persistence_n,
            hysteresis=self._hysteresis,
            streak_reject=self._streak_reject,
            streak_below=self._streak_below,
        )

        if transition in ("turn_on", "turn_off"):
            print(
                "alarm transition %s at window_seq=%d (lb=%.4f mean=%.4f thr=%.3f)",
                transition, window.window_seq, window.lb, window.mean, self._threshold,
            )

        self._publisher.publish(decision)
        return decision

    def reset(self) -> None:
        self._state = "OFF"
        self._streak_reject = 0
        self._streak_below = 0

    @property
    def state(self) -> AlarmState:
        return self._state

    # Internals
    def _is_rejected(self, w: WindowStats) -> bool:
        """Interpret the corrected p-value under the configured method."""
        if self._method == "raw":
            return w.p_value_raw < w.alpha
        if self._method == "bonferroni":
            return w.p_value_bonferroni < w.alpha
        if self._method == "sidak":
            return w.p_value_sidak < w.alpha
        if self._method == "holm":
            if w.p_value_holm is None:
                raise RuntimeError("Holm p-value not present in WindowStats")
            return w.p_value_holm < w.alpha
        if self._method == "bh":
            if w.p_value_bh is None:
                raise RuntimeError("BH p-value not present in WindowStats")
            return w.p_value_bh < w.alpha
        raise ValueError(f"Unknown correction method: {self._method!r}")