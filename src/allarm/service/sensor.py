from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Protocol

import numpy as np

from ..schema.sensor import SensorReading

from ..config import load_config

class SensorPublisher(Protocol):
    """Anything that can publish a SensorReading"""

    def publish(self, reading: SensorReading) -> None: ...

class SensorService:
    """Generate Gaussian samples on a fixed schedule and publish them."""

    cfg = load_config()

    def __init__(
        self,
        publisher: SensorPublisher,
        *,
        mean: float = cfg.sensor.mean,
        std: float = cfg.sensor.std,
        interval: float = cfg.sensor.publish_interval,
        sensor_id: str = cfg.sensor.id,
        unit: str = cfg.sensor.unit,
        rng: Optional[np.random.Generator] = None,
    ) -> None:
        if std <= 0:
            raise ValueError(f"std must be > 0, got {std}")
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")

        self._publisher = publisher
        self._mean = mean
        self._std = std
        self._interval = interval
        self._sensor_id = sensor_id
        self._unit = unit
        # default_rng() without seed -> non-reproducible;
        # pass a seeded one for test porpuse
        self._rng = rng or np.random.default_rng()

        self._sequence = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # Lifecycle
    def start(self) -> None:
        """Blocking run loop; returns when stop() is called."""

        try:
            while not self._stop.is_set():
                reading = self._next_reading()
                self._publisher.publish(reading)
                # wait() returns immediately if stop() is called, unlike time.sleep
                self._stop.wait(self._interval)
        finally:
            print(f"sensor {self._sensor_id} stopped at sequence={self._sequence}")

    def start_in_background(self) -> threading.Thread:
        """Run start() in a daemon thread and return it."""
        self._thread = threading.Thread(
            target=self.start, name=f"sensor-{self._sensor_id}", daemon=True
        )
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # Internals
    def _next_reading(self) -> SensorReading:
        value = float(self._rng.normal(self._mean, self._std))
        reading = SensorReading(
            timestamp=time.time(),
            value=value,
            unit=self._unit,
            sensor_id=self._sensor_id,
            sequence=self._sequence,
        )
        self._sequence += 1
        return reading