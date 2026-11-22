from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db import Database
from ..model.alarm import AlarmDecisionRow
from ..schema.alarm import AlarmDecision

log = logging.getLogger(__name__)


class AlarmRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def write(self, decision: AlarmDecision) -> None:
        row = _to_row(decision)
        with self._db.session() as s:
            s.add(row)
        if decision.state_changed:
            log.info(
                "persisted alarm transition %s -> %s (window_seq=%d)",
                decision.previous_state, decision.state, decision.window_seq,
            )


def _to_row(d: AlarmDecision) -> AlarmDecisionRow:
    stats = d.stats  # may be None for the initial OFF published at startup
    return AlarmDecisionRow(
        timestamp=datetime.fromtimestamp(d.timestamp, tz=timezone.utc),
        sensor_id=d.sensor_id,
        window_seq=d.window_seq,
        state=d.state,
        previous_state=d.previous_state,
        transition=d.transition,
        test_rejected=d.test_rejected,
        correction_method=d.correction_method_used,
        persistence_n=d.persistence_n,
        hysteresis=d.hysteresis,
        streak_reject=d.streak_reject,
        streak_below=d.streak_below,
        mean=stats.mean if stats else None,
        std=stats.std if stats else None,
        lb=stats.lb if stats else None,
        p_value_raw=stats.p_value_raw if stats else None,
        p_value_adj=stats.p_value_adj if stats else None,
        threshold=stats.mu0 if stats else None,
    )