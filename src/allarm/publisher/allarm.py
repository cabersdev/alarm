from __future__ import annotations

import logging

import paho.mqtt.client as mqtt

from ..schema.alarm import AlarmDecision

class MqttAlarmPublisher:
    def __init__(
        self,
        client: mqtt.Client,
        topic: str,
        *,
        qos: int = 1,
        retain: bool = True,
        include_stats: bool = False,
    ) -> None:
        self._client = client
        self._topic = topic
        self._qos = qos
        self._retain = retain
        self._include_stats = include_stats

    def publish(self, decision: AlarmDecision) -> None:
        exclude = set() if self._include_stats else {"stats"}
        payload = decision.model_dump_json(exclude=exclude)
        info = self._client.publish(self._topic, payload, qos=self._qos, retain=self._retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(
                f"publish failed on {self._topic} (window_seq={decision.window_seq}, state={decision.state}): rc={info.rc}"
            )