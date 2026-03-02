import json
import logging
import time
from typing import Iterable

import pika

from .config import FetcherConfig
from .interpol_client import RedNotice

logger = logging.getLogger(__name__)


class QueuePublisher:
    def __init__(self, config: FetcherConfig) -> None:
        self._config = config

    def _connection_parameters(self) -> pika.ConnectionParameters:
        credentials = pika.PlainCredentials(
            self._config.rabbitmq_user, self._config.rabbitmq_password
        )
        return pika.ConnectionParameters(
            host=self._config.rabbitmq_host,
            port=self._config.rabbitmq_port,
            credentials=credentials,
        )

    def _connect_with_retry(self, retries: int = 10, delay: int = 5) -> pika.BlockingConnection:
        for attempt in range(1, retries + 1):
            try:
                return pika.BlockingConnection(self._connection_parameters())
            except Exception as exc:
                logger.warning("RabbitMQ not ready (attempt %d/%d): %s — retrying in %ds", attempt, retries, exc, delay)
                if attempt == retries:
                    raise
                time.sleep(delay)

    def publish_notices(self, notices: Iterable[RedNotice]) -> None:
        if not notices:
            return

        connection = self._connect_with_retry()
        channel = connection.channel()
        channel.queue_declare(queue=self._config.rabbitmq_queue_name, durable=True)

        for notice in notices:
            payload = json.dumps(notice.__dict__).encode("utf-8")
            channel.basic_publish(
                exchange="",
                routing_key=self._config.rabbitmq_queue_name,
                body=payload,
                properties=pika.BasicProperties(delivery_mode=2),
            )

        connection.close()

