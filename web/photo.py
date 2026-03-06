"""
Fotoğraf indirme ve disk'ten sunma modülü.

Strateji: Fotoğrafları bir kez Interpol'den indirip /data/photos/ klasörüne kaydet.
Sonra Flask /photos/<entity_id> route'u disk'ten serve eder — Interpol'e hiç istek yok.
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable

import requests

logger = logging.getLogger(__name__)

PHOTOS_DIR = Path(os.getenv("PHOTOS_DIR", "/data/photos"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Dest": "image",
}

# Placeholder SVG — fotoğraf yoksa veya indirilemediyse döner
PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200">'
    b'<rect width="300" height="200" fill="#ddd"/>'
    b'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
    b'fill="#888" font-size="16">No Photo</text></svg>'
)


def _safe_filename(entity_id: str) -> str:
    """entity_id → güvenli dosya adı: 2026/12345 → 2026-12345.jpg"""
    return entity_id.replace("/", "-") + ".jpg"


def photo_exists(entity_id: str) -> bool:
    """Fotoğraf disk'te var mı?"""
    return (PHOTOS_DIR / _safe_filename(entity_id)).is_file()


def photo_path(entity_id: str) -> Path:
    """Fotoğrafın disk path'ini döner."""
    return PHOTOS_DIR / _safe_filename(entity_id)


def download_photo(entity_id: str, photo_url: str) -> bool:
    """
    photo_url'den fotoğrafı indirir ve disk'e kaydeder.
    Zaten varsa tekrar indirmez. Başarılıysa True döner.
    """
    if not photo_url:
        return False

    dest = PHOTOS_DIR / _safe_filename(entity_id)
    if dest.is_file():
        return True  # zaten indirilmiş

    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        resp = requests.get(photo_url, headers=_HEADERS, timeout=15)
        if resp.status_code == 200 and resp.content and len(resp.content) > 100:
            dest.write_bytes(resp.content)
            logger.debug("Photo saved: %s → %s", entity_id, dest.name)
            return True
        if resp.status_code == 403:
            logger.debug("Photo 403 (ban): %s", entity_id)
        else:
            logger.debug("Photo download failed: %s → HTTP %s", entity_id, resp.status_code)
        return False
    except Exception as exc:
        logger.warning("Photo download error (%s): %s", entity_id, exc)
        return False


def backfill_photos(
    session_factory: Callable,
    delay: float = 1.0,
) -> None:
    """
    DB'deki tüm notice'leri tarar; photo_url var ama disk'te dosya yoksa indirir.
    Arka plan thread'i olarak çalıştırılır. Ban gelirse hızını düşürür.
    """
    from .models import Notice  # circular-import guard

    logger.info("Photo backfill starting…")
    session = session_factory()
    try:
        rows = (
            session.query(Notice.entity_id, Notice.photo_url)
            .filter(Notice.photo_url.isnot(None), Notice.photo_url != "")
            .all()
        )
    finally:
        session.close()

    total = len(rows)
    downloaded = 0
    skipped = 0
    failed = 0
    consecutive_403 = 0

    for i, (eid, url) in enumerate(rows):
        if photo_exists(eid):
            skipped += 1
            continue

        ok = download_photo(eid, url)
        if ok:
            downloaded += 1
            consecutive_403 = 0
        else:
            failed += 1
            # 403 ban algılama: art arda hatalar → yavaşla
            consecutive_403 += 1
            if consecutive_403 >= 5:
                pause = 300  # 5 dk bekle
                logger.warning(
                    "Backfill: %d consecutive failures, pausing %ds", consecutive_403, pause
                )
                time.sleep(pause)
                consecutive_403 = 0

        # İlerleme logu (her 200 fotoğrafta bir)
        if (downloaded + failed) % 200 == 0 and (downloaded + failed) > 0:
            logger.info(
                "Backfill progress: %d/%d (downloaded=%d, skipped=%d, failed=%d)",
                i + 1, total, downloaded, skipped, failed,
            )

        # İstekler arası bekleme
        time.sleep(delay + random.uniform(0.3, delay * 0.3))

    logger.info(
        "Photo backfill done: total=%d, downloaded=%d, already_existed=%d, failed=%d",
        total, downloaded, skipped, failed,
    )


def start_backfill_thread(session_factory: Callable, delay: float = 1.0) -> None:
    """Backfill'i daemon thread olarak başlatır. Web startup'ında çağrılır."""
    t = threading.Thread(
        target=backfill_photos,
        args=(session_factory, delay),
        daemon=True,
        name="photo-backfill",
    )
    t.start()
    logger.info("Photo backfill thread started (delay=%.1fs)", delay)