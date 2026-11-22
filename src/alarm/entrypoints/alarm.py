from __future__ import annotations

import argparse
import logging
import time

from ..bootstrap import (
    connect_with_retry, init_db_with_retry, make_client, run_forever, setup_logging,
)
from ..config import load_config
from ..publisher.alarm import MqttAlarmPublisher
from ..repository.alarm import AlarmRepository
from ..schema.alarm import AlarmDecision
from ..service.alarm import AlarmService
from ..subscriber.alarm import AlarmSubscriber

log = logging.getLogger("mcc.alarm")


def main() -> int:
    parser = argparse.ArgumentParser(description="MCC alarm service")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config(args.config)

    client = make_client("mcc-alarm")
    connect_with_retry(client, cfg.mqtt.broker, cfg.mqtt.port, cfg.mqtt.keepalive)
    client.loop_start()

    db = init_db_with_retry(args.config)

    publisher = MqttAlarmPublisher(client, cfg.alarm.topic_alarm, retain=True)
    repository = AlarmRepository(db)

    service = AlarmService(
        publisher=publisher,
        repository=repository,
        threshold=cfg.alarm.threshold,
        hysteresis=cfg.alarm.hysteresis,
        persistence_n=cfg.alarm.persistence_n,
        correction_method=cfg.alarm.correction_method,
        sensor_id=cfg.sensor.sensor_id,
    )

    # Override stale retained state. Published, not persisted.
    initial = AlarmDecision(
        timestamp=time.time(),
        sensor_id=cfg.sensor.sensor_id,
        state="OFF",
        previous_state="OFF",
        transition="keep_off",
        test_rejected=False,
        correction_method_used=cfg.alarm.correction_method,
        window_seq=0,
        stats=None,
        persistence_n=cfg.alarm.persistence_n,
        hysteresis=cfg.alarm.hysteresis,
        streak_reject=0,
        streak_below=0,
    )
    publisher.publish(initial)

    _subscriber = AlarmSubscriber(  # noqa: F841
        client, cfg.stats.topic_stats, service, qos=1,
    )

    run_forever(client, on_stop=db.dispose)
    return 0