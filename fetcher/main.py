import logging
import time

from .config import FetcherConfig
from .interpol_client import InterpolClient, RedNotice
from .queue_publisher import QueuePublisher

logger = logging.getLogger(__name__)


class FetchOrchestrator:
    """
    Orchestrates the periodic fetch-and-publish cycle for Interpol red notices.

    All dependencies (config, client, publisher) are injected via the
    constructor to keep the class fully testable without real network or
    RabbitMQ connections.
    """

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
        """
        Main loop: fetch → publish → sleep → repeat.

        Errors within a cycle are caught and logged; the loop never
        terminates on its own.
        """
        logger.info("Starting Interpol fetcher loop.")
        logger.info("Base URL       : %s", self._config.interpol_base_url)
        logger.info("Fetch interval : %s s", self._config.fetch_interval_seconds)

        while True:
            try:
                notices = self._fetch_cycle()
                logger.info("Fetched %d notices, publishing to RabbitMQ.", len(notices))
                self._publisher.publish_notices(notices)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Error during fetch/publish cycle: %s", exc)

            time.sleep(self._config.fetch_interval_seconds)

    def _fetch_cycle(self) -> list[RedNotice]:
        """Select the correct fetch strategy and return a list of notices."""
        if self._config.use_mock_data:
            logger.info("Mock data enabled; publishing sample notices.")
            return self._mock_notices()

        if self._config.fetch_extended:
            logger.info("Fetching EXTENDED red notices (multi-pass)...")
            return self._client.fetch_extended_red_notices(
                request_delay=self._config.request_delay_seconds,
                enable_pass_age_0_9=self._config.enable_pass_age_0_9,
                enable_pass_in_pk_1yr=self._config.enable_pass_in_pk_1yr,
                very_high_nationalities_1yr=self._config.very_high_nationalities_1yr,
                age_1yr_min=self._config.age_1yr_min,
                age_1yr_max=self._config.age_1yr_max,
                state_file=self._config.state_file_path,
            )

        if self._config.fetch_all:
            logger.info("Fetching ALL red notices (full scan)...")
            return self._client.fetch_all_red_notices()

        logger.info("Fetching latest red notices (~160 records)...")
        return self._client.fetch_red_notices(result_per_page=160)

    @staticmethod
    def _mock_notices() -> list[RedNotice]:
        """Return a small hard-coded dataset for smoke-tests (USE_MOCK_DATA=true)."""
        return [
            RedNotice(
                entity_id="2026/0001",
                name="DOE",
                forename="JANE",
                date_of_birth="1980/01/01",
                nationality="TR",
                all_nationalities="TR",
                arrest_warrant="Fraud",
            ),
            RedNotice(
                entity_id="2026/0002",
                name="SMITH",
                forename="JOHN",
                date_of_birth="1975/05/12",
                nationality="DE",
                all_nationalities="DE",
                arrest_warrant="Cybercrime",
            ),
            RedNotice(
                entity_id="2026/0003",
                name="GARCIA",
                forename=None,
                date_of_birth=None,
                nationality="ES",
                all_nationalities=None,
                arrest_warrant=None,
            ),
        ]


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def run_forever() -> None:
    """
    Module-level convenience wrapper kept for backward compatibility.

    Reads configuration from the environment, wires up dependencies, and
    delegates to FetchOrchestrator.run_forever().
    """
    _configure_logging()
    config = FetcherConfig.from_env()
    client = InterpolClient(config.interpol_base_url)
    publisher = QueuePublisher(config)
    FetchOrchestrator(config, client, publisher).run_forever()


if __name__ == "__main__":
    run_forever()


