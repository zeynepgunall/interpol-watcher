"""
consumer.py - RabbitMQ kuyruğunu dinler ve gelen mesajları işler.
Ayrı bir thread'de çalışır, Flask ile eş zamanlı çalışabilir.
"""

import json
import logging
import time
import threading
import pika

logger = logging.getLogger(__name__)


class QueueConsumer:
    """
    RabbitMQ'dan mesaj tüketen sınıf.
    
    Attributes:
        host, port, user, password: RabbitMQ bağlantı bilgileri
        queue_name (str): Dinlenecek kuyruk adı
        db: Database nesnesi (kayıt için)
        socketio: Flask-SocketIO nesnesi (realtime güncelleme için)
    """

    def __init__(self, host: str, port: int, user: str, password: str,
                 queue_name: str, db, socketio):
        self.host = host
        self.port = port
        self.queue_name = queue_name
        self.db = db
        self.socketio = socketio
        self.credentials = pika.PlainCredentials(user, password)
        self.connection = None
        self.channel = None
        self._running = False

    def _on_message(self, channel, method, properties, body):
        """
        Kuyruktan yeni mesaj geldiğinde çağrılır.
        
        Args:
            body: Ham mesaj verisi (JSON bytes)
        """
        try:
            notice = json.loads(body.decode("utf-8"))
            logger.info(f"Mesaj alındı: {notice.get('entity_id', 'bilinmiyor')}")

            # Veritabanına kaydet / güncelle
            result = self.db.save_or_update(notice)

            # Arayüzü Socket.IO ile gerçek zamanlı güncelle
            if result == "created":
                # Yeni kayıt → arayüze gönder
                self.socketio.emit("new_notice", {
                    "notice": notice,
                    "status": "new"
                })
            elif result == "updated":
                # Güncelleme → alarm olarak gönder
                self.socketio.emit("notice_updated", {
                    "notice": notice,
                    "status": "updated"
                })

            # Mesajı başarıyla işlediğimizi RabbitMQ'ya bildir
            channel.basic_ack(delivery_tag=method.delivery_tag)

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse hatası: {e}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.error(f"Mesaj işleme hatası: {e}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    def _connect(self, retries: int = 10, delay: int = 5) -> bool:
        """RabbitMQ'ya bağlanır, başarısız olursa tekrar dener."""
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Consumer RabbitMQ'ya bağlanıyor... ({attempt}/{retries})")
                params = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    credentials=self.credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300
                )
                self.connection = pika.BlockingConnection(params)
                self.channel = self.connection.channel()
                self.channel.queue_declare(queue=self.queue_name, durable=True)
                # Aynı anda 1 mesaj işle (adil dağıtım)
                self.channel.basic_qos(prefetch_count=1)
                self.channel.basic_consume(
                    queue=self.queue_name,
                    on_message_callback=self._on_message
                )
                logger.info("Consumer bağlantısı başarılı.")
                return True
            except pika.exceptions.AMQPConnectionError as e:
                logger.warning(f"Bağlantı kurulamadı: {e}. {delay}s bekleniyor...")
                time.sleep(delay)

        return False

    def start(self):
        """
        Consumer'ı ayrı bir thread'de başlatır.
        Flask'ın çalışmasını engellemez.
        """
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        logger.info("Consumer thread başlatıldı.")

    def _run(self):
        """Thread içinde çalışan ana döngü."""
        self._running = True
        while self._running:
            if self._connect():
                try:
                    logger.info("Kuyruk dinleniyor...")
                    self.channel.start_consuming()
                except pika.exceptions.AMQPConnectionError:
                    logger.warning("Bağlantı kesildi, yeniden bağlanılıyor...")
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"Consumer hatası: {e}")
                    time.sleep(5)
            else:
                logger.error("Bağlantı kurulamadı. 30s sonra tekrar denenecek.")
                time.sleep(30)

    def stop(self):
        """Consumer'ı durdurur."""
        self._running = False
        if self.channel:
            self.channel.stop_consuming()
        if self.connection and not self.connection.is_closed:
            self.connection.close()
