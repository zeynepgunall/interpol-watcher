import logging
import time

from .config import FetcherConfig
from .interpol_client import InterpolClient, RedNotice
from .queue_publisher import QueuePublisher


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fetcher")


def build_mock_notices() -> list[RedNotice]:
    """
    Return a small list of fake RedNotice objects for local development.

    Activated when USE_MOCK_DATA=true in the environment — never hit the
    real Interpol API, useful for UI/pipeline smoke-tests without network.
    """
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


def run_forever() -> None:
    """
    Main fetch-and-publish loop.

    Reads configuration from environment, selects the appropriate fetch
    strategy (mock / extended multi-pass / full-scan / latest-only), then
    publishes each batch to RabbitMQ.  Sleeps for
    ``config.fetch_interval_seconds`` between cycles.  Errors within a cycle
    are caught and logged so the loop never terminates unexpectedly.
    """
    config = FetcherConfig.from_env()
    client = InterpolClient(config.interpol_base_url)
    publisher = QueuePublisher(config)

    logger.info("Starting Interpol fetcher loop.")
    logger.info("Base URL: %s", config.interpol_base_url)
    logger.info("Fetch interval: %s seconds", config.fetch_interval_seconds)

    while True:
        try:
            if config.use_mock_data:
                logger.info("Mock data enabled; publishing sample notices.")
                notices = build_mock_notices()
            elif config.fetch_extended:
                logger.info("Fetching EXTENDED red notices (passes 13+ with new Pass A/B)...")
                notices = client.fetch_extended_red_notices(
                    request_delay=config.request_delay_seconds,
                    enable_pass_age_0_9=config.enable_pass_age_0_9,
                    enable_pass_in_pk_1yr=config.enable_pass_in_pk_1yr,
                    very_high_nationalities_1yr=config.very_high_nationalities_1yr,
                    age_1yr_min=config.age_1yr_min,
                    age_1yr_max=config.age_1yr_max,
                    state_file=config.state_file_path,
                )
            elif config.fetch_all:
                logger.info("Fetching ALL red notices from Interpol API (full scan)...")
                notices = client.fetch_all_red_notices()
            else:
                logger.info("Fetching latest red notices from Interpol API...")
                notices = client.fetch_red_notices(result_per_page=160)
            logger.info("Fetched %d notices, publishing to RabbitMQ.", len(notices))
            publisher.publish_notices(notices)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error during fetch/publish cycle: %s", exc)

        time.sleep(config.fetch_interval_seconds)


if __name__ == "__main__":
    run_forever()

