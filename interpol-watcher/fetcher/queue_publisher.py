"""
queue_publisher.py - RabbitMQ kuyruğuna mesaj yayınlar.
Bağlantı kopması durumunda tekrar bağlanmayı dener.
"""

import json
import logging
import time
import pika
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class QueuePublisher:
    """
    RabbitMQ'ya mesaj gönderen sınıf.
    
    Attributes:
        host (str): RabbitMQ sunucu adresi
        port (int): RabbitMQ port numarası
        user (str): Kullanıcı adı
        password (str): Şifre
        queue_name (str): Mesajların yazılacağı kuyruk adı
    """

    def __init__(self, host: str, port: int, user: str, password: str, queue_name: str):
        self.host = host
        self.port = port
        self.queue_name = queue_name
        # Kimlik doğrulama bilgileri
        self.credentials = pika.PlainCredentials(user, password)
        self.connection = None
        self.channel = None

    def connect(self, retries: int = 5, delay: int = 5) -> bool:
        """
        RabbitMQ'ya bağlanır. Başarısız olursa tekrar dener.
        
        Args:
            retries: Maksimum deneme sayısı
            delay: Denemeler arası bekleme süresi (saniye)
            
        Returns:
            bool: Bağlantı başarılıysa True, değilse False
        """
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"RabbitMQ'ya bağlanılıyor... (Deneme {attempt}/{retries})")
                
                connection_params = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    credentials=self.credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300
                )
                self.connection = pika.BlockingConnection(connection_params)
                self.channel = self.connection.channel()

                # Kuyruk yoksa oluştur; varsa olduğu gibi kullan
                # durable=True: RabbitMQ yeniden başlasa bile kuyruk silinmez
                self.channel.queue_declare(queue=self.queue_name, durable=True)
                
                logger.info("RabbitMQ bağlantısı başarılı.")
                return True

            except pika.exceptions.AMQPConnectionError as e:
                logger.warning(f"Bağlantı kurulamadı: {e}. {delay} saniye bekleniyor...")
                time.sleep(delay)

        logger.error("RabbitMQ'ya bağlanılamadı. Tüm denemeler başarısız.")
        return False

    def publish_batch(self, notices: List[Dict[str, Any]]) -> int:
        """
        Bir liste veriyi kuyruğa toplu olarak gönderir.
        
        Args:
            notices: Kuyruğa yazılacak kişi listesi
            
        Returns:
            int: Başarıyla gönderilen mesaj sayısı
        """
        if not self._ensure_connected():
            return 0

        sent_count = 0
        for notice in notices:
            try:
                self.channel.basic_publish(
                    exchange="",
                    routing_key=self.queue_name,
                    body=json.dumps(notice, ensure_ascii=False),
                    properties=pika.BasicProperties(
                        delivery_mode=2  # Mesaj kalıcı olsun (disk'e yazılsın)
                    )
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Mesaj gönderilemedi: {e}")

        logger.info(f"{sent_count}/{len(notices)} mesaj kuyruğa yazıldı.")
        return sent_count

    def _ensure_connected(self) -> bool:
        """Bağlantı yoksa veya kopmuşsa yeniden bağlanmayı dener."""
        if self.connection and not self.connection.is_closed:
            return True
        logger.warning("Bağlantı kopmuş, yeniden bağlanılıyor...")
        return self.connect()

    def close(self):
        """Bağlantıyı düzgünce kapatır."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
            logger.info("RabbitMQ bağlantısı kapatıldı.")
