"""Dev-only runner: all three services in one process.

NOT used in production. Each service runs as its own systemd unit there.
"""

from __future__ import annotations

import logging
import threading

from .bootstrap import connect_with_retry, init_db_with_retry, make_client, setup_logging
from .config import load_config
from .publisher.allarm import MqttAlarmPublisher
from .publisher.sensor import MqttSensorPublisher
from .publisher.stats import MqttStatsPublisher
from .repository.allarm import AlarmRepository
from .repository.sensor import SensorRepository
from .service.allarm import AlarmService
from .service.sensor import SensorService
from .service.stats import StatsService
from .subscriber.allarm import AlarmSubscriber
from .subscriber.stats import StatsSubscriber

log = logging.getLogger("mcc.cli")


def main() -> int:
    setup_logging()
    cfg = load_config()

    client = make_client("mcc-dev")
    connect_with_retry(client, cfg.mqtt.broker, cfg.mqtt.port, cfg.mqtt.keepalive)
    client.loop_start()
    db = init_db_with_retry()

    sensor_svc = SensorService(
        MqttSensorPublisher(client, cfg.sensor.topic_raw), SensorRepository(db),
        mean=cfg.sensor.mean, std=cfg.sensor.std,
        interval=cfg.sensor.publish_interval,
        sensor_id=cfg.sensor.sensor_id, unit=cfg.sensor.unit,
    )
    stats_svc = StatsService(
        MqttStatsPublisher(client, cfg.stats.topic_stats),
        window_size=cfg.stats.window_size,
        mu0=cfg.stats.mu0,
        alpha=cfg.stats.alpha,
        correction_method=cfg.stats.correction_method,
        p_history_size=cfg.stats.p_history_size,
        sensor_id=cfg.sensor.sensor_id,
        compute_shapiro=cfg.stats.compute_shapiro,
        mu_true=cfg.sensor.mean if cfg.stats.use_ground_truth else None,
        sigma_true=cfg.sensor.std if cfg.stats.use_ground_truth else None,
    )
    alarm_svc = AlarmService(
        MqttAlarmPublisher(client, cfg.alarm.topic_alarm), AlarmRepository(db),
        threshold=cfg.alarm.threshold, hysteresis=cfg.alarm.hysteresis,
        persistence_n=cfg.alarm.persistence_n,
        correction_method=cfg.alarm.correction_method,
        sensor_id=cfg.sensor.sensor_id,
    )

    StatsSubscriber(client, cfg.sensor.topic_raw, stats_svc, qos=0)
    AlarmSubscriber(client, cfg.stats.topic_stats, alarm_svc, qos=1)

    sensor_thread = sensor_svc.start_in_background()
    log.info("dev stack running (Ctrl+C to stop)")

    try:
        sensor_thread.join()
    except KeyboardInterrupt:
        sensor_svc.stop()
        sensor_thread.join(timeout=5)
    finally:
        client.loop_stop()
        client.disconnect()
        db.dispose()
    return 0