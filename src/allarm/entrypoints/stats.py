from __future__ import annotations

import argparse
import logging

from ..bootstrap import connect_with_retry, make_client, run_forever, setup_logging
from ..config import load_config
from ..publisher.stats import MqttStatsPublisher
from ..service.stats import StatsService
from ..subscriber.stats import StatsSubscriber

log = logging.getLogger("mcc.stats")


def main() -> int:
    parser = argparse.ArgumentParser(description="MCC statistics service")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config(args.config)

    client = make_client("mcc-stats")
    connect_with_retry(client, cfg.mqtt.broker, cfg.mqtt.port, cfg.mqtt.keepalive)
    client.loop_start()

    # Ground truth available only in simulation: pass mu/sigma of the
    # generator so the downstream evaluation can compute TP/FP/FN/TN.
    if cfg.stats.use_ground_truth:
        mu_true = cfg.sensor.mean
        sigma_true = cfg.sensor.std
    else:
        mu_true, sigma_true = None, None

    service = StatsService(
        publisher=MqttStatsPublisher(client, cfg.stats.topic_stats),
        window_size=cfg.stats.window_size,
        mu0=cfg.stats.mu0,
        alpha=cfg.stats.alpha,
        correction_method=cfg.stats.correction_method,
        p_history_size=cfg.stats.p_history_size,
        sensor_id=cfg.sensor.sensor_id,
        compute_shapiro=cfg.stats.compute_shapiro,
        mu_true=mu_true,
        sigma_true=sigma_true,
    )
    # The subscriber is kept alive by the paho callback registry (it holds
    # a reference to the bound method, which references the instance).
    _subscriber = StatsSubscriber(  # noqa: F841
        client, cfg.sensor.topic_raw, service, qos=0,
    )

    run_forever(client)
    return 0