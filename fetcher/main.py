import logging
import time

from .config import FetcherConfig
from .interpol_client import InterpolClient
from .queue_publisher import QueuePublisher


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fetcher")


def run_forever() -> None:
    config = FetcherConfig.from_env()
    client = InterpolClient(config.interpol_base_url)
    publisher = QueuePublisher(config)

    logger.info("Starting Interpol fetcher loop.")
    logger.info("Base URL: %s", config.interpol_base_url)
    logger.info("Fetch interval: %s seconds", config.fetch_interval_seconds)

    while True:
        try:
            logger.info("Fetching latest red notices from Interpol API...")
            notices = client.fetch_red_notices(page=1, result_per_page=20)
            logger.info("Fetched %d notices, publishing to RabbitMQ.", len(notices))
            publisher.publish_notices(notices)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error during fetch/publish cycle: %s", exc)

        time.sleep(config.fetch_interval_seconds)


if __name__ == "__main__":
    run_forever()

