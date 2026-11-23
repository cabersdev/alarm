from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt
from sqlalchemy.exc import OperationalError

from .config import load_config
from .db import Database

log = logging.getLogger("mcc.bootstrap")


# Logging
def setup_logging(*, level: int = logging.INFO) -> None:
    """One log line format, consistent across the three services.

    systemd captures stdout/stderr into journald; the format makes
    `journalctl -u mcc-sensor` readable at a glance.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)-20s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


# MQTT
def make_client(client_id: str) -> mqtt.Client:
    """Create a paho client with clean_session=False.

    Persistent session → the broker remembers subscriptions across reconnects.
    That is essential for the alarm: if it restarts, it must resume receiving
    WindowStats without waiting for a manual re-subscribe. The client_id must
    be stable and unique per service.
    """
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=False,
    )

    def _on_disconnect(c, _ud, _flags, rc, _props):
        log.warning("[%s] MQTT disconnected: %s", client_id, rc)

    client.on_disconnect = _on_disconnect
    return client


def connect_with_retry(
    client: mqtt.Client,
    broker: str,
    port: int,
    keepalive: int,
    *,
    max_attempts: int = 60,
    delay: float = 2.0,
) -> None:
    """Block until the broker accepts the connection, or give up."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            client.connect(broker, port, keepalive)
            log.info("MQTT connected to %s:%d", broker, port)
            return
        except OSError as exc:
            last_exc = exc
            log.warning(
                "MQTT connect %d/%d failed (%s); retrying in %.0fs",
                attempt, max_attempts, exc, delay,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Could not connect to MQTT at {broker}:{port} "
        f"after {max_attempts} attempts"
    ) from last_exc


# Database
def init_db_with_retry(
    config_path: str = "config.toml",
    *,
    max_attempts: int = 60,
    delay: float = 2.0,
) -> Database:
    """Open the DB and create schema (incl. hypertables), with retry."""
    cfg = load_config(config_path)
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            db = Database(url=cfg.database.url, echo=cfg.database.echo)
            db.init_schema()
            log.info("database ready at %s", _mask(cfg.database.url))
            return db
        except OperationalError as exc:
            last_exc = exc
            log.warning(
                "DB init %d/%d failed (%s); retrying in %.0fs",
                attempt, max_attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Could not initialize database after {max_attempts} attempts"
    ) from last_exc


def _mask(url: str) -> str:
    """Hide the password in a SQLAlchemy URL for logging."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, tail = rest.split("@", 1)
        if ":" in creds:
            user, _pw = creds.split(":", 1)
            return f"{scheme}://{user}:***@{tail}"
    return url


# Lifecycle
def run_forever(
    client: mqtt.Client,
    *,
    on_stop: Optional[Callable[[], None]] = None,
) -> None:
    """Block until SIGTERM/SIGINT, then run cleanup and disconnect.

    The MQTT loop runs in a paho thread; the main thread just waits on an
    Event. SIGTERM from `systemctl stop` sets the event, the finally block
    runs cleanup, and the process exits with code 0.
    """
    stop = threading.Event()

    def _handle(signum: int, _frame) -> None:
        log.info("received signal %d, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    try:
        stop.wait()
    finally:
        if on_stop is not None:
            try:
                on_stop()
            except Exception:
                log.exception("error during on_stop cleanup")
        client.loop_stop()
        client.disconnect()
        log.info("shutdown complete")
