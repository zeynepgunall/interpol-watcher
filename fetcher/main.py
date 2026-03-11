"""Fetcher giriş noktası: Config'i yüklüyor,Interpol API'den veri çeker ve RabbitMQ'ya yazar."""
import logging
import time

from .config import FetcherConfig
from .interpol_client import InterpolClient, RedNotice
from .queue_publisher import QueuePublisher

logger = logging.getLogger(__name__)

_DEFAULT_RESULT_COUNT = 160


class FetchOrchestrator:
    """Periyodik fetch-publish döngüsü.Fetcher servisinin ana akışını yönetir.Tarama moduna karar verir."""

    def __init__(
        self,
        config: FetcherConfig,
        client: InterpolClient,
        publisher: QueuePublisher,
    ) -> None:
        self._config = config
        self._client = client
        self._publisher = publisher

    def run_forever(self) -> None:
        """Ana döngü: veri çek → kuyruğa yaz → bekle → tekrarla."""
        logger.info("Interpol fetcher döngüsü başlatılıyor.")
        logger.info("Base URL       : %s", self._config.interpol_base_url)
        logger.info("Fetch interval : %s s", self._config.fetch_interval_seconds)

        while True:
            try:
                notices = self._fetch_cycle()
                if notices:
                    logger.info("%d notice çekildi, RabbitMQ'ya yazılıyor.", len(notices))
                    self._publisher.publish_notices(notices)
                else:
                    logger.info("Fetch döngüsü tamamlandı (streaming veya boş).")
            except Exception as exc:
                logger.exception("Fetch/publish döngüsünde hata: %s", exc)

            time.sleep(self._config.fetch_interval_seconds)

    def _fetch_cycle(self) -> list[RedNotice]:
        """Hangi tarama modunun çalışacağına karar verir """
        if self._config.fetch_all:
            logger.info("TÜM Red Notice'ler taranıyor (tam tarama, streaming)...")
            self._client.fetch_all_red_notices(
                request_delay=self._config.request_delay_seconds,
                on_new=self._publisher.publish_notices,   # anlık publish 
                state_file=self._config.state_file_path,
            ) 

        if self._config.fetch_extended:
            logger.info("GENİŞLETİLMİŞ Red Notice taraması (çoklu pass, streaming)...")
            self._client.fetch_extended_red_notices(
                request_delay=self._config.request_delay_seconds,
                enable_pass_age_0_9=self._config.enable_pass_age_0_9,
                enable_pass_in_pk_1yr=self._config.enable_pass_in_pk_1yr,
                very_high_nationalities_1yr=self._config.very_high_nationalities_1yr,
                age_1yr_min=self._config.age_1yr_min,
                age_1yr_max=self._config.age_1yr_max,
                state_file=self._config.state_file_path,
                on_new=self._publisher.publish_notices,
            )

        if self._config.fetch_all or self._config.fetch_extended:
            return []

        logger.info("Son Red Notice'ler çekiliyor (~%d kayıt)...", _DEFAULT_RESULT_COUNT)
        return self._client.fetch_red_notices(result_per_page=_DEFAULT_RESULT_COUNT) #daha basit modda tarama yapar, sonuçları topluca döndürür.


def _configure_logging() -> None:
    """Root logger'ı INFO seviyesinde yapılandırır."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    ) #logging ayarlarını yapar.


def run_forever() -> None:
    """Giriş noktası: config oku, bağımlılıkları oluştur, döngüyü başlat."""
    _configure_logging()
    config = FetcherConfig.from_env()
    client = InterpolClient(config.interpol_base_url)
    publisher = QueuePublisher(config)
    FetchOrchestrator(config, client, publisher).run_forever()
#Önce config’i ve bağımlılıkları oluşturuyor, ardından orchestrator’ı başlatıyor.

if __name__ == "__main__":
    run_forever()
