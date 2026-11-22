from __future__ import annotations

import argparse
import logging

from ..bootstrap import (
    connect_with_retry, init_db_with_retry, make_client, run_forever, setup_logging,
)
from ..config import load_config
from ..publisher.sensor import MqttSensorPublisher
from ..repository.sensor import SensorRepository
from ..service.sensor import SensorService

log = logging.getLogger("mcc.sensor")


def main() -> int:
    parser = argparse.ArgumentParser(description="MCC sensor simulator service")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config(args.config)

    client = make_client("mcc-sensor")
    connect_with_retry(client, cfg.mqtt.broker, cfg.mqtt.port, cfg.mqtt.keepalive)
    client.loop_start()

    db = init_db_with_retry(args.config)

    service = SensorService(
        publisher=MqttSensorPublisher(client, cfg.sensor.topic_raw),
        repository=SensorRepository(db),
        mean=cfg.sensor.mean,
        std=cfg.sensor.std,
        interval=cfg.sensor.publish_interval,
        sensor_id=cfg.sensor.sensor_id,
        unit=cfg.sensor.unit,
    )
    service.start_in_background()

    def _cleanup() -> None:
        service.stop()
        service.join(timeout=5.0)
        db.dispose()

    run_forever(client, on_stop=_cleanup)
    return 0