from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db import Database
from ..model.sensor import SensorReadingRow
from ..schema.sensor import SensorReading

log = logging.getLogger(__name__)


class SensorRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def write(self, reading: SensorReading) -> None:
        row = _to_row(reading)
        with self._db.session() as s:
            s.add(row)

    def write_many(self, readings: list[SensorReading]) -> None:
        if not readings:
            return
        with self._db.session() as s:
            s.add_all([_to_row(r) for r in readings])
        log.debug("persisted %d sensor readings", len(readings))


def _to_row(reading: SensorReading) -> SensorReadingRow:
    return SensorReadingRow(
        timestamp=datetime.fromtimestamp(reading.timestamp, tz=timezone.utc),
        sensor_id=reading.sensor_id,
        sequence=reading.sequence,
        value=reading.value,
        unit=reading.unit,
    )