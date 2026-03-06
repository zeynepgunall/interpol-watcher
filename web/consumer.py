import logging
import threading
import time
from datetime import datetime, timezone, timedelta

import pika

from shared.message import decode as _decode
from .config import WebConfig
from .models import Notice, create_session_factory, ALARM_WINDOW_SECONDS
from .notice_service import NoticeService, UpsertOutcome
from .photo import download_photo

logger = logging.getLogger(__name__)

_SWEEPER_INTERVAL = 15  # kaç saniyede bir temizlik yapılacak


class QueueConsumer:
    """RabbitMQ consumer that deserialises notice messages and delegates persistence to NoticeService."""

    def __init__(self, config: WebConfig, on_change=None) -> None:
        """Config ve isteğe bağlı SSE callback alır; DB session factory ve NoticeService oluşturur."""
        self._config = config
        self._on_change = on_change
        self._session_factory = create_session_factory(config)
        self._notice_service = NoticeService(self._session_factory)

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
        """Gelen mesajı JSON'dan çözer, NoticeService.upsert() ile DB'ye yazar,
        fotoğrafı disk'e indirir, SSE üzerinden tarayıcılara bildirim gönderir."""
        payload = _decode(body)
        result = self._notice_service.upsert(payload)
        if result.outcome is UpsertOutcome.SKIPPED:
            logger.warning("Dropped message — no entity_id: %s", payload)
        elif result.outcome is UpsertOutcome.ERROR:
            logger.error("Failed to persist %s: %s", result.entity_id, result.error)
        else:
            # Fotoğrafı disk'e indir (zaten varsa skip eder)
            photo_url = payload.get("photo_url")
            if photo_url and result.entity_id:
                download_photo(result.entity_id, photo_url)
            if self._on_change is not None:
                try:
                    self._on_change(result.outcome.name)
                except Exception as exc:
                    logger.warning("SSE notify failed: %s", exc)

    def start_in_thread(self) -> None:
        """Consumer ve sweeper'ı arka planda daemon thread olarak başlatır."""
        threading.Thread(target=self._consume_forever, daemon=True).start()
        threading.Thread(target=self._sweeper_forever, daemon=True).start()
        logger.info("Sweeper thread started (interval=%ds, window=%ds)", _SWEEPER_INTERVAL, ALARM_WINDOW_SECONDS)

    # ── SWEEPER ─────────────────────────────────────────────────────────────────

    def _sweeper_forever(self) -> None:
        """
        Her 15 saniyede bir çalışır.
        is_updated=True olan kayıtların updated_at süresi dolmuşsa is_updated=False yapar.
        Böylece alarm geçici olur — 60 saniye sonra otomatik söner.
        """
        while True:
            time.sleep(_SWEEPER_INTERVAL)
            try:
                self._sweep_expired_alarms()
            except Exception as exc:
                logger.warning("Sweeper error: %s", exc)

    def _sweep_expired_alarms(self) -> None:
        expiry_limit = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=ALARM_WINDOW_SECONDS)
        session = self._session_factory()
        try:
            affected = (
                session.query(Notice)
                .filter(Notice.is_updated == True, Notice.updated_at <= expiry_limit)
                .update({Notice.is_updated: False})
            )
            session.commit()
            if affected:
                logger.info("Sweeper: %d alarm temizlendi", affected)
                if self._on_change is not None:
                    self._on_change("SWEPT")
        except Exception as exc:
            session.rollback()
            logger.warning("Sweeper DB error: %s", exc)
        finally:
            session.close()

    # ── CONSUMER ────────────────────────────────────────────────────────────────

    def _consume_forever(self) -> None:
        """Sonsuz döngüde RabbitMQ'ya bağlanır ve mesajları dinler. Bağlantı koparsa exponential backoff ile yeniden dener."""
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

                def callback(ch, method, properties, body):
                    self._handle_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(
                    queue=self._config.rabbitmq_queue_name, on_message_callback=callback
                )
                logger.info("RabbitMQ connection established, consuming messages.")
                retry_delay = 5
                try:
                    channel.start_consuming()
                except KeyboardInterrupt:
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