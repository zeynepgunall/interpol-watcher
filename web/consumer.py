import json
import logging
import threading
import time

import pika

from .config import WebConfig
from .models import create_session_factory
from .notice_service import NoticeService, UpsertOutcome

logger = logging.getLogger(__name__)


class QueueConsumer:
    """
    RabbitMQ consumer that persists incoming red notice messages to the database.

    Runs as a daemon thread inside the web container so it shares the same
    process as the Flask application.

    Business rules (INSERT vs UPDATE / alarm) are fully delegated to
    NoticeService — this class is responsible only for transport: deserialising
    the message, calling the service, and ack-ing the delivery.

    ``on_change`` is an optional callable invoked after every successful
    INSERT or UPDATE so callers (e.g. the SSE endpoint) can push a
    real-time notification to connected browser clients.
    """

    _on_change = None  # class-level default; overridden per-instance in __init__

    def __init__(self, config: WebConfig, on_change=None) -> None:
        self._config = config
        self._on_change = on_change
        session_factory = create_session_factory(config)
        self._notice_service = NoticeService(session_factory)

    def _connection_parameters(self) -> pika.ConnectionParameters:
        """Build pika connection parameters from the current WebConfig."""
        credentials = pika.PlainCredentials(
            self._config.rabbitmq_user, self._config.rabbitmq_password
        )
        return pika.ConnectionParameters(
            host=self._config.rabbitmq_host,
            port=self._config.rabbitmq_port,
            credentials=credentials,
        )

    def _handle_message(self, body: bytes) -> None:
        """
        Deserialise one RabbitMQ message and delegate persistence to NoticeService.

        Idempotent: calling this method twice with the same body produces
        exactly one DB row; the second call sets is_updated=True (alarm).
        After a successful INSERT or UPDATE, notifies SSE clients via on_change.
        """
        payload = json.loads(body.decode("utf-8"))
        result = self._notice_service.upsert(payload)
        if result.outcome is UpsertOutcome.SKIPPED:
            logger.warning("Dropped message — no entity_id: %s", payload)
        elif result.outcome is UpsertOutcome.ERROR:
            logger.error("Failed to persist %s: %s", result.entity_id, result.error)
        elif self._on_change is not None:
            try:
                self._on_change(result.outcome.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SSE notify failed: %s", exc)

    def start_in_thread(self) -> None:
        """Start the consumer loop in a background daemon thread."""
        thread = threading.Thread(target=self._consume_forever, daemon=True)
        thread.start()

    def _consume_forever(self) -> None:
        logger.info(
            "Starting RabbitMQ consumer on %s:%s queue=%s",
            self._config.rabbitmq_host,
            self._config.rabbitmq_port,
            self._config.rabbitmq_queue_name,
        )
        retry_delay = 5
        while True:
            try:
                connection = pika.BlockingConnection(self._connection_parameters())
                channel = connection.channel()
                channel.queue_declare(queue=self._config.rabbitmq_queue_name, durable=True)

                def callback(ch, method, properties, body):  # type: ignore[no-untyped-def]
                    self._handle_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(
                    queue=self._config.rabbitmq_queue_name, on_message_callback=callback
                )

                logger.info("RabbitMQ connection established, consuming messages.")
                retry_delay = 5  # reset on success
                try:
                    channel.start_consuming()
                except KeyboardInterrupt:  # pragma: no cover - manual stop
                    channel.stop_consuming()
                    break
                finally:
                    try:
                        connection.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("RabbitMQ connection failed: %s — retrying in %s s", exc, retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

