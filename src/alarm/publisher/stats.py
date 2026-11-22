from __future__ import annotations

import logging

import paho.mqtt.client as mqtt

from ..schema.stats import WindowStats

class MqttStatsPublisher:
    def __init__(
        self,
        client: mqtt.Client,
        topic: str,
        *,
        qos: int = 1,
        retain: bool = False,
        include_raw_samples: bool = False,
    ) -> None:
        self._client = client
        self._topic = topic
        self._qos = qos
        self._retain = retain
        self._include_raw = include_raw_samples

    def publish(self, stats: WindowStats) -> None:
        exclude = set() if self._include_raw else {"raw_samples"}
        payload = stats.model_dump_json(exclude=exclude)
        info = self._client.publish(self._topic, payload, qos=self._qos, retain=self._retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(
                f"publish failed on {self._topic} (seq={stats.window_seq}): rc={info.rc}"
                )