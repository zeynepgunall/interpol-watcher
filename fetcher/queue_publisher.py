import logging
import time
from typing import Iterable

import pika

from shared.message import encode as _encode
from .config import FetcherConfig
from .interpol_client import RedNotice

logger = logging.getLogger(__name__)


class QueuePublisher:
    """RedNotice listelerini RabbitMQ kuyruğuna JSON olarak gönderir."""

    def __init__(self, config: FetcherConfig) -> None:
        """Publisher'a FetcherConfig enjekte eder; bağlantı bilgileri config'den alınır."""
        self._config = config

    def _connection_parameters(self) -> pika.ConnectionParameters:
        """Config'deki host/port/user/password bilgilerinden pika bağlantı parametreleri üretir."""
        credentials = pika.PlainCredentials(
            self._config.rabbitmq_user, self._config.rabbitmq_password
        )
        return pika.ConnectionParameters(
            host=self._config.rabbitmq_host,
            port=self._config.rabbitmq_port,
            credentials=credentials,
        )

    def _connect_with_retry(self, retries: int = 10, delay: int = 5) -> pika.BlockingConnection:
        """RabbitMQ'ya bağlanmayı dener; başarısız olursa belirtilen sayıda tekrar dener."""
        for attempt in range(1, retries + 1):
            try:
                return pika.BlockingConnection(self._connection_parameters())
            except Exception as exc:
                logger.warning("RabbitMQ not ready (attempt %d/%d): %s — retrying in %ds", attempt, retries, exc, delay)
                if attempt == retries:
                    raise
                time.sleep(delay)

    def publish_notices(self, notices: Iterable[RedNotice]) -> None:
        """Notice listesini JSON'a serialize edip RabbitMQ kuyruğuna persistent mesaj olarak basar."""
        if not notices:
            return

        connection = self._connect_with_retry()
        channel = connection.channel()
        channel.queue_declare(queue=self._config.rabbitmq_queue_name, durable=True)

        for notice in notices:
            payload = _encode(notice.__dict__)
            channel.basic_publish(
                exchange="",
                routing_key=self._config.rabbitmq_queue_name,
                body=payload,
                properties=pika.BasicProperties(delivery_mode=2),
            )

        connection.close()

