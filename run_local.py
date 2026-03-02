"""
run_local.py — RabbitMQ olmadan doğrudan SQLite'a veri çeker.

Kullanım:
    python run_local.py              # tam tarama (fetch_all)
    python run_local.py --fast       # yalnızca ilk sayfa (~160 kayıt, hızlı test)
    python run_local.py --extended   # extended multi-pass tarama
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Proje kök dizinini sys.path'e ekle
sys.path.insert(0, os.path.dirname(__file__))

from fetcher.interpol_client import InterpolClient
from web.config import WebConfig
from web.models import create_session_factory
from web.notice_service import NoticeService, UpsertOutcome

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("run_local")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Interpol fetcher (no RabbitMQ)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", action="store_true", help="Quick fetch: first page only (~160 records)")
    group.add_argument("--extended", action="store_true", help="Extended multi-pass scan")
    args = parser.parse_args()

    os.environ.setdefault("DATABASE_URL", "sqlite:///data/notices.db")
    config = WebConfig.from_env()
    session_factory = create_session_factory(config)
    service = NoticeService(session_factory)

    base_url = os.getenv("INTERPOL_BASE_URL", "https://ws-public.interpol.int")
    client = InterpolClient(base_url)

    # Fetch
    if args.fast:
        logger.info("FAST mode: fetching first page only...")
        notices = client.fetch_red_notices(result_per_page=160)
    elif args.extended:
        logger.info("EXTENDED mode: multi-pass scan starting...")
        notices = client.fetch_extended_red_notices(
            request_delay=1.5,
            state_file="data/scan_state.json",
        )
    else:
        logger.info("FULL SCAN mode: fetching all red notices (this may take a while)...")
        notices = client.fetch_all_red_notices()

    logger.info("Fetched %d notices from Interpol API.", len(notices))

    # Persist via NoticeService (no duplicate upsert logic here)
    inserted = updated = skipped = errors = 0
    for i, rn in enumerate(notices, 1):
        result = service.upsert(rn.__dict__)
        if result.outcome is UpsertOutcome.INSERTED:
            inserted += 1
        elif result.outcome is UpsertOutcome.UPDATED:
            updated += 1
        elif result.outcome is UpsertOutcome.SKIPPED:
            skipped += 1
        else:
            errors += 1

        if i % 100 == 0:
            logger.info("Progress: %d / %d  (inserted=%d, updated=%d, errors=%d)",
                        i, len(notices), inserted, updated, errors)

    logger.info(
        "Done. inserted=%d  updated=%d  skipped=%d  errors=%d  total=%d",
        inserted, updated, skipped, errors, len(notices),
    )
    logger.info("Open http://127.0.0.1:5000 to see the results.")


if __name__ == "__main__":
    main()

