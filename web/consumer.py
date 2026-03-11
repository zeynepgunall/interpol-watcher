"""Fetcher ile web servisi arasındaki entegrasyon katmanı.Fetcher'ın publish  ettiği mesajları kuyruktan okur, DB'ye yazar, UI'a gerçek zamanlı bildirim gönderir."""
import logging
import threading
import time
from datetime import timedelta

import pika

from shared.message import decode as _decode
from shared.utils import utcnow_naive
from .config import WebConfig
from .models import Notice, create_session_factory, get_session, ALARM_WINDOW_SECONDS
from .notice_service import NoticeService, UpsertOutcome
from .photo import download_photo

logger = logging.getLogger(__name__)

_SWEEPER_INTERVAL = 15


class QueueConsumer:
    """"RabbitMQ’dan gelen notice mesajlarını işleyip web katmanına entegre etmek."""

    def __init__(self, config: WebConfig, on_change=None) -> None:
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
        """Gelen mesajı işler"""
        payload = _decode(body) #Mesaj decode edilir.
        result = self._notice_service.upsert(payload) #DB'ye kaydeder, güncelleme varsa is_updated=True yapar ve sonucu döner.
        if result.outcome is UpsertOutcome.SKIPPED:
            logger.warning("Mesaj atlandı — entity_id yok: %s", payload)
        elif result.outcome is UpsertOutcome.ERROR:
            logger.error("Kayıt hatası %s: %s", result.entity_id, result.error)
        else:
            photo_url = payload.get("photo_url")
            if photo_url and result.entity_id:
                download_photo(result.entity_id, photo_url) #fotoğraf indirilirr
            if self._on_change is not None:
                try:
                    self._on_change(result.outcome.name) #SSE ile UI'a bildirim gönderilir
                except Exception as exc:
                    logger.warning("SSE bildirim hatası: %s", exc)

    def start_in_thread(self) -> None:
        """Consumer ve sweeper thread'lerini başlatır.Arka planda sürekli mesaj dinlenir ve alarm temizliği yapılır."""
        threading.Thread(target=self._consume_forever, daemon=True).start()
        threading.Thread(target=self._sweeper_forever, daemon=True).start()
        logger.info(
            _SWEEPER_INTERVAL,
            ALARM_WINDOW_SECONDS,
        )

    def _sweeper_forever(self) -> None:
        """Süresi dolan alarmları periyodik olarak temizler.Amaç:alarm sonsuza kadar aktif kalmasın."""
        while True:
            time.sleep(_SWEEPER_INTERVAL)
            try:
                self._sweep_expired_alarms()
            except Exception as exc:
                logger.warning("Sweeper hatası: %s", exc)

    def _sweep_expired_alarms(self) -> None:
        """Alarm penceresi geçmiş kayıtların is_updated bayrağını sıfırlar."""
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
        """RabbitMQ'ya bağlanır ve mesajları dinler."""
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
                    ch.basic_ack(delivery_tag=method.delivery_tag) #yeni mesaj başarıyla işlendiğimde RabbitMQ'ya tamam deniyor

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
