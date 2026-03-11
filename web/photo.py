"""Fotoğraf indirme ve disk'ten sunma modülü."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

from shared.utils import safe_filename

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

PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200">'
    b'<rect width="300" height="200" fill="#ddd"/>'
    b'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
    b'fill="#888" font-size="16">No Photo</text></svg>'
)


def photo_exists(entity_id: str) -> bool:
    """Fotoğraf disk'te var mı kontrol eder."""
    return (PHOTOS_DIR / safe_filename(entity_id)).is_file()


def photo_path(entity_id: str) -> Path:
    """Fotoğrafın disk yolunu döndürür."""
    return PHOTOS_DIR / safe_filename(entity_id)


def download_photo(entity_id: str, photo_url: str) -> bool:
    """
    Fotoğrafı Interpol'den indirip disk'e kaydeder.
    Zaten varsa tekrar indirmez. Başarılıysa True döner.
    Not: Interpol çoğu durumda 403 döner; toplu indirme için download_photos.py kullanılır.
    """
    if not photo_url:
        return False

    dest = PHOTOS_DIR / safe_filename(entity_id)
    if dest.is_file():
        return True

    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        resp = requests.get(photo_url, headers=_HEADERS, timeout=15)
        if resp.status_code == 200 and resp.content and len(resp.content) > 100:
            dest.write_bytes(resp.content)
            logger.debug("Fotoğraf kaydedildi: %s → %s", entity_id, dest.name)
            return True
        return False
    except Exception as exc:
        logger.debug("Fotoğraf indirme hatası (%s): %s", entity_id, exc)
        return False
