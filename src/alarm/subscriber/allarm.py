from __future__ import annotations

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from ..schema.stats import WindowStats
from ..service.allarm import AlarmService

import logging
log = logging.getLogger(__name__)


class AlarmSubscriber:
    def __init__(
        self,
        client: mqtt.Client,
        topic: str,
        service: AlarmService,
        *,
        qos: int = 1,
    ) -> None:
        self._client = client
        self._topic = topic
        self._service = service
        self._qos = qos

        client.message_callback_add(topic, self._on_message)
        client.subscribe(topic, qos=qos)
        log.info("alarm subscriber listening on %s (qos=%d)", topic, qos)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        try:
            window = WindowStats.model_validate_json(msg.payload)
        except ValidationError as exc:
            log.warning("invalid WindowStats on %s: %s", msg.topic, exc)
            return

        try:
            self._service.on_stats(window)
        except Exception:
            log.exception("AlarmService failed on window_seq=%d", window.window_seq)

    def cleanup(self) -> None:
        self._client.message_callback_remove(self._topic)
        self._client.unsubscribe(self._topic)