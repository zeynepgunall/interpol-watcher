"""Fetcher ile web servisi arasındaki entegrasyon katmanı."""
import logging
import threading
import time
from datetime import timedelta

import pika

from shared.message import decode as _decode
from shared.utils import utcnow_naive
from .config import WebConfig
from .minio_storage import MinioStorage
from .models import Notice, create_session_factory, get_session, ALARM_WINDOW_SECONDS
from .notice_service import NoticeService, UpsertOutcome
from .photo import download_photo

logger = logging.getLogger(__name__)

_SWEEPER_INTERVAL = 15


class QueueConsumer:

    def __init__(self, config: WebConfig, on_change=None) -> None:
        self._config = config
        self._on_change = on_change
        self._session_factory = create_session_factory(config)

        # MinIO storage
        self._minio = MinioStorage(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            bucket=config.minio_bucket,
            secure=config.minio_secure,
            public_url=config.minio_public_url,
        )

        self._notice_service = NoticeService(
            self._session_factory,
            interpol_base_url=config.interpol_base_url,
            minio=self._minio,
        )

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
        payload = _decode(body)
        result = self._notice_service.upsert(payload)
        if result.outcome is UpsertOutcome.SKIPPED:
            logger.warning("Mesaj atlandı — entity_id yok: %s", payload)
        elif result.outcome is UpsertOutcome.ERROR:
            logger.error("Kayıt hatası %s: %s", result.entity_id, result.error)
        else:
            photo_url = payload.get("photo_url")
            if photo_url and result.entity_id:
                # MinIO varsa oraya yükle, yoksa local'e indir
                if self._minio and self._minio.enabled:
                    obj_name = self._minio.object_name_for(result.entity_id)
                    if not self._minio.object_exists(obj_name):
                        try:
                            import requests as _req
                            resp = _req.get(photo_url, timeout=15)
                            if resp.status_code == 200 and len(resp.content) > 100:
                                self._minio.upload_bytes(obj_name, resp.content)
                                logger.info("Kapak fotoğrafı MinIO'ya yüklendi: %s", result.entity_id)
                        except Exception as exc:
                            logger.warning("Kapak fotoğrafı yüklenemedi (%s): %s", result.entity_id, exc)
                            download_photo(result.entity_id, photo_url)
                else:
                    download_photo(result.entity_id, photo_url)

            if self._on_change is not None:
                try:
                    self._on_change(result.outcome.name)
                except Exception as exc:
                    logger.warning("SSE bildirim hatası: %s", exc)

    def start_in_thread(self) -> None:
        threading.Thread(target=self._consume_forever, daemon=True).start()
        threading.Thread(target=self._sweeper_forever, daemon=True).start()
        if self._config.detail_backfill_enabled:
            threading.Thread(target=self._backfill_details_forever, daemon=True).start()
        logger.info(
            "Consumer threadleri baslatildi; sweeper=%ss alarm_window=%ss",
            _SWEEPER_INTERVAL,
            ALARM_WINDOW_SECONDS,
        )

    def _sweeper_forever(self) -> None:
        while True:
            time.sleep(_SWEEPER_INTERVAL)
            try:
                self._sweep_expired_alarms()
            except Exception as exc:
                logger.warning("Sweeper hatası: %s", exc)

    def _sweep_expired_alarms(self) -> None:
        expiry_limit = utcnow_naive() - timedelta(seconds=ALARM_WINDOW_SECONDS)
        with get_session(self._session_factory) as session:
            try:
                affected = (
                    session.query(Notice)
                    .filter(Notice.is_updated.is_(True), Notice.updated_at <= expiry_limit)
                    .update({Notice.is_updated: False})
                )
                session.commit()
                if affected:
                    logger.info("Sweeper: %d alarm temizlendi", affected)
                    if self._on_change is not None:
                        self._on_change("SWEPT")
            except Exception as exc:
                session.rollback()
                logger.warning("Sweeper DB hatası: %s", exc)

    def _consume_forever(self) -> None:
        logger.info(
            "RabbitMQ consumer başlatılıyor: %s:%s queue=%s",
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
                logger.info("RabbitMQ bağlantısı kuruldu, mesajlar dinleniyor.")
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
                logger.warning(
                    "RabbitMQ bağlantı hatası: %s — %d sn sonra tekrar denenecek",
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    def _backfill_details_forever(self) -> None:
        service = NoticeService(
            self._session_factory,
            interpol_base_url=self._config.interpol_base_url,
            minio=self._minio,
        )
        batch_size = max(1, self._config.detail_backfill_batch_size)
        idle_seconds = max(5.0, self._config.detail_backfill_idle_seconds)

        while True:
            try:
                filled = service.backfill_missing_details(
                    limit=batch_size,
                    request_delay_seconds=self._config.detail_request_delay_seconds,
                )
                if filled and self._on_change is not None:
                    self._on_change("DETAIL_BACKFILLED")
                if filled < batch_size:
                    time.sleep(idle_seconds)
            except Exception as exc:
                logger.warning("Detail backfill hatasi: %s", exc)
                time.sleep(idle_seconds)