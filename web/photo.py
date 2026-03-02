"""Photo proxy: lazy-warmed requests session + disk-cache with Interpol fallback."""
from __future__ import annotations

import logging
import os

import requests

from .models import Notice

logger = logging.getLogger(__name__)

_INTERPOL_BASE = "https://ws-public.interpol.int"
_DEFAULT_CACHE_DIR = os.getenv("PHOTO_CACHE_DIR", "/data/photos")

_PHOTO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
}


class PhotoProxy:
    """Serves Interpol notice photos via disk cache; fetches on first request."""

    def __init__(self, session_factory, cache_dir: str = _DEFAULT_CACHE_DIR) -> None:
        self._session_factory = session_factory
        self._cache_dir = cache_dir
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update(_PHOTO_HEADERS)
            try:
                s.get("https://www.interpol.int/", timeout=10)
                logger.info("Photo proxy session warmed up")
            except Exception as exc:
                logger.warning("Photo session warmup failed (proceeding anyway): %s", exc)
            self._session = s
        return self._session

    def _thumbnail_url(self, safe: str) -> str:
        """Return stored thumbnail URL from DB, or derive the standard Interpol URL."""
        slash_id = safe.replace("-", "/", 1)  # only the year separator
        db = self._session_factory()
        try:
            notice = db.query(Notice).filter(Notice.entity_id == slash_id).one_or_none()
            if notice and notice.thumbnail_url:
                return notice.thumbnail_url
        finally:
            db.close()
        return f"{_INTERPOL_BASE}/notices/v1/red/{safe}/images/1/thumbnail"

    def get(self, entity_id: str) -> tuple[str | None, int, str | None]:
        """
        Resolve a photo for *entity_id*.

        Returns (cache_path, http_status, content_type).
        status 404 means no photo available.
        """
        safe = entity_id.replace("/", "-").replace("..", "").strip("/")
        cache_path = os.path.join(self._cache_dir, safe + ".jpg")

        if os.path.isfile(cache_path):
            return cache_path, 200, None  # serve straight from cache

        url = self._thumbnail_url(safe)
        try:
            resp = self._get_session().get(url, timeout=15)
            if resp.status_code == 200 and resp.content:
                os.makedirs(self._cache_dir, exist_ok=True)
                with open(cache_path, "wb") as fh:
                    fh.write(resp.content)
                logger.info("Cached photo for %s (%d bytes)", safe, len(resp.content))
                return cache_path, 200, resp.headers.get("Content-Type", "image/jpeg")
            logger.debug("No photo for %s — Interpol returned %d", safe, resp.status_code)
        except Exception as exc:
            logger.warning("Photo fetch failed for %s: %s", safe, exc)

        return None, 404, None
