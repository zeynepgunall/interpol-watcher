import logging
import time

from .config import FetcherConfig
from .interpol_client import InterpolClient
from .queue_publisher import QueuePublisher

logger = logging.getLogger(__name__)


class FetchOrchestrator:
    """Periodic fetch-and-publish loop; dependencies injected for testability."""

    def __init__(
        self,
        config: FetcherConfig,
        client: InterpolClient,
        publisher: QueuePublisher,
    ) -> None:
        """Config, API istemcisi ve kuyruk publisher'ı dışarıdan alır (dependency injection)."""
        self._config = config
        self._client = client
        self._publisher = publisher

    def run_forever(self) -> None:
        """Sonsuz döngüde Interpol API'den veri çeker ve RabbitMQ'ya yazar. Her döngü arasında config'deki süre kadar bekler."""
        logger.info("Starting Interpol fetcher loop.")
        logger.info("Base URL       : %s", self._config.interpol_base_url)
        logger.info("Fetch interval : %s s", self._config.fetch_interval_seconds)

        while True:
            try:
                notices = self._fetch_cycle()
                if notices:
                    logger.info("Fetched %d notices, publishing to RabbitMQ.", len(notices))
                    self._publisher.publish_notices(notices)
                else:
                    logger.info("Fetch cycle complete (streaming or empty).")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error during fetch/publish cycle: %s", exc)

            time.sleep(self._config.fetch_interval_seconds)

    def _fetch_cycle(self) -> list:
        """Select the correct fetch strategy and return a list of notices."""
        if self._config.fetch_all:
            logger.info("Fetching ALL red notices (full scan, streaming)...")
            self._client.fetch_all_red_notices(
                request_delay=self._config.request_delay_seconds,
                on_new=self._publisher.publish_notices,
                state_file=self._config.state_file_path,
            )

        if self._config.fetch_extended:
            logger.info("Fetching EXTENDED red notices (multi-pass, streaming)...")
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
            return []  # zaten streaming ile yayınlandı

        logger.info("Fetching latest red notices (~160 records)...")
        return self._client.fetch_red_notices(result_per_page=160)


def _configure_logging() -> None:
    """Root logger'ı INFO seviyesinde ve zaman damgalı formatta yapılandırır."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def run_forever() -> None:
    """Entry point: read config from env, wire dependencies, start the loop."""
    _configure_logging()
    config = FetcherConfig.from_env()
    client = InterpolClient(config.interpol_base_url)
    publisher = QueuePublisher(config)
    FetchOrchestrator(config, client, publisher).run_forever()


if __name__ == "__main__":
    run_forever()
