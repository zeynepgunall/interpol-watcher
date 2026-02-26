"""
main.py - Container A giriş noktası.
Belirli aralıklarla Interpol API'den veri çeker ve RabbitMQ'ya gönderir.
"""

import logging
import time
import signal
import sys

from config import Config
from interpol_client import InterpolClient
from queue_publisher import QueuePublisher

# Loglama ayarları
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class FetcherApp:
    """
    Ana uygulama sınıfı.
    InterpolClient ve QueuePublisher'ı koordine eder.
    """

    def __init__(self):
        self.config = Config()
        self.running = True

        self.client = InterpolClient(
            api_url=self.config.INTERPOL_API_URL,
            page=self.config.INTERPOL_PAGE,
            result_per_page=self.config.INTERPOL_RESULT_PER_PAGE
        )

        self.publisher = QueuePublisher(
            host=self.config.RABBITMQ_HOST,
            port=self.config.RABBITMQ_PORT,
            user=self.config.RABBITMQ_USER,
            password=self.config.RABBITMQ_PASS,
            queue_name=self.config.QUEUE_NAME
        )

        # SIGTERM ve SIGINT sinyallerini yakala (docker stop için)
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        """Uygulama durdurulduğunda temiz kapanış yapar."""
        logger.info("Kapatma sinyali alındı. Uygulama durduruluyor...")
        self.running = False
        self.publisher.close()
        sys.exit(0)

    def run(self):
        """Ana döngü: veri çek → kuyruğa yaz → bekle → tekrarla."""
        logger.info("Fetcher uygulaması başlatıldı.")
        logger.info(f"API: {self.config.INTERPOL_API_URL}")
        logger.info(f"Çekme aralığı: {self.config.FETCH_INTERVAL} saniye")

        # Önce RabbitMQ'ya bağlan
        if not self.publisher.connect():
            logger.critical("RabbitMQ bağlantısı kurulamadı. Uygulama sonlandırılıyor.")
            sys.exit(1)

        while self.running:
            logger.info("--- Yeni döngü başladı ---")

            # 1. Interpol'den veri çek
            raw_notices = self.client.fetch_red_notices()

            if raw_notices:
                # 2. Her kaydı temiz formata dönüştür
                parsed_notices = [
                    self.client.parse_notice(notice) for notice in raw_notices
                ]

                # 3. RabbitMQ'ya gönder
                self.publisher.publish_batch(parsed_notices)
            else:
                logger.warning("Veri çekilemedi, bir sonraki döngüde tekrar denenecek.")

            # 4. Bir sonraki döngüye kadar bekle
            logger.info(f"Sonraki çekim {self.config.FETCH_INTERVAL} saniye sonra...")
            time.sleep(self.config.FETCH_INTERVAL)


if __name__ == "__main__":
    app = FetcherApp()
    app.run()
