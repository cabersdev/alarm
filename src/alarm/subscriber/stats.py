from __future__ import annotations

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from ..schema.sensor import SensorReading
from ..service.stats import StatsService

import logging
log = logging.getLogger(__name__)
class StatsSubscriber:
    def __init__(
        self,
        client: mqtt.Client,
        topic: str,
        service: StatsService,
        *,
        qos: int = 0,
    ) -> None:
        self._client = client
        self._topic = topic
        self._service = service
        self._qos = qos

        client.message_callback_add(topic, self._on_message)
        client.subscribe(topic, qos=qos)
        log.info(f"stats subscriber listening on {topic} (qos={qos})")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        try:
            reading = SensorReading.model_validate_json(msg.payload)
        except ValidationError as exc:
            log.error(f"invalid SensorReading on {msg.topic}: {exc}")
            return

        try:
            self._service.on_sample(reading)
        except Exception:
            # A crash inside the service must not take down the callback thread.
            log.exception("StatsService failed on reading seq=%d", reading.sequence)

    def cleanup(self) -> None:
        """Detach the callback and unsubscribe (call on shutdown)."""
        self._client.message_callback_remove(self._topic)
        self._client.unsubscribe(self._topic)