"""Fetcher servisinin bulduğu RedNotice kayıtlarını RabbitMQ kuyruğuna gönderir."""
import logging
import time
from typing import Iterable

import pika #RabbitMQ bağlantısı Pika kütüphanesi ile kuruluyot

from shared.message import encode as _encode
from .config import FetcherConfig
from .interpol_client import RedNotice

logger = logging.getLogger(__name__)


class QueuePublisher:
    """RedNotice nesnelerini RabbitMQ kuyruğuna JSON olarak gönderir. Fetcher yeni notice bulduğunda publish_notices() çağrılır."""

    def __init__(self, config: FetcherConfig) -> None:
        self._config = config

    """bağlantı bilgileri config'ten geliyor."""
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
        """RabbitMQ hazır olana kadar belirtilen sayıda yeniden bağlanmayı dener."""
        for attempt in range(1, retries + 1):
            try:
                return pika.BlockingConnection(self._connection_parameters())
            except Exception as exc:
                logger.warning("RabbitMQ hazır değil (deneme %d/%d): %s — %ds sonra tekrar", attempt, retries, exc, delay)
                if attempt == retries:
                    raise
                time.sleep(delay)

    def publish_notices(self, notices: Iterable[RedNotice]) -> None:
        """Notice listesini JSON'a serialize edip kuyruğa persistent mesaj olarak basar.
        RabbitMQ'ya bağlanıyor,queue'yi declare ediyor, mesajları publish ediyor ve bağlantıyı kapatıyor.encode işlemi message.py'deki encode fonksiyonunu kullanır."""
        if not notices:
            return

        # "RabbitMQ'ya bağlanır."
        connection = self._connect_with_retry()
        try:
            channel = connection.channel()
            channel.queue_declare(queue=self._config.rabbitmq_queue_name, durable=True) #kuyruğu oluşturur,restart durumunda kaybolmaz.

            for notice in notices:
                payload = _encode(notice.__dict__) #veriyi JSON'a çevirir.
                channel.basic_publdeliveish(
                    exchange="",
                    routing_key=self._config.rabbitmq_queue_name,
                    body=payload,
                    properties=pika.BasicProperties(delivery_mode=2),
                ) #mesajı kuyruğa publish eder,delivery_mode=2 ile mesajın kalıcı olmasını sağlar.
        finally:
            connection.close() #kaynakları temiz tutmak için
