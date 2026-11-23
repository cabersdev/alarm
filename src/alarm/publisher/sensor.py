from __future__ import annotations

import paho.mqtt.client as mqtt

from ..schema.sensor import SensorReading

import logging
log = logging.getLogger(__name__)

class MqttSensorPublisher:
    def __init__(
        self,
        client: mqtt.Client,
        topic: str,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        self._client = client
        self._topic = topic
        self._qos = qos
        self._retain = retain

    def publish(self, reading: SensorReading) -> None:
        payload = reading.model_dump_json()
        info = self._client.publish(self._topic, payload, qos=self._qos, retain=self._retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning(
                f"publish failed on {self._topic} (seq={reading.sequence}): rc={info.rc}"
            )