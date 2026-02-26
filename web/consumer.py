import json
import logging
import threading
from typing import Any, Dict

import pika
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import WebConfig
from .models import Notice, create_session_factory

logger = logging.getLogger("consumer")


class QueueConsumer:
    def __init__(self, config: WebConfig) -> None:
        self._config = config
        self._SessionFactory = create_session_factory(config)

    def _connection_parameters(self) -> pika.ConnectionParameters:
        credentials = pika.PlainCredentials(
            self._config.rabbitmq_user, self._config.rabbitmq_password
        )
        return pika.ConnectionParameters(
            host=self._config.rabbitmq_host,
            port=self._config.rabbitmq_port,
            credentials=credentials,
        )

    def _handle_message(self, body: bytes) -> None:
        payload: Dict[str, Any] = json.loads(body.decode("utf-8"))
        session: Session = self._SessionFactory()

        try:
            entity_id = payload.get("entity_id")
            if not entity_id:
                logger.warning("Skipping message without entity_id: %s", payload)
                return

            notice: Notice | None = (
                session.query(Notice)
                .filter(Notice.entity_id == entity_id)
                .one_or_none()
            )

            if notice is None:
                notice = Notice(
                    entity_id=entity_id,
                    name=payload.get("name"),
                    forename=payload.get("forename"),
                    date_of_birth=payload.get("date_of_birth"),
                    nationality=payload.get("nationality"),
                    arrest_warrant=payload.get("arrest_warrant"),
                )
                session.add(notice)
                logger.info("Inserted new notice %s", entity_id)
            else:
                # any re-arrival is considered an update and will be shown as alarm
                notice.name = payload.get("name")
                notice.forename = payload.get("forename")
                notice.date_of_birth = payload.get("date_of_birth")
                notice.nationality = payload.get("nationality")
                notice.arrest_warrant = payload.get("arrest_warrant")
                notice.is_updated = True
                logger.info("Updated existing notice %s", entity_id)

            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Database error while handling message.")
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error while handling message.")
        finally:
            session.close()

    def start_in_thread(self) -> None:
        thread = threading.Thread(target=self._consume_forever, daemon=True)
        thread.start()

    def _consume_forever(self) -> None:
        logger.info(
            "Starting RabbitMQ consumer on %s:%s queue=%s",
            self._config.rabbitmq_host,
            self._config.rabbitmq_port,
            self._config.rabbitmq_queue_name,
        )
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

        try:
            channel.start_consuming()
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            channel.stop_consuming()
        finally:
            connection.close()

