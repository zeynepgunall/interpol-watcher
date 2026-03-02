from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

import requests

from .notice import RedNotice  # noqa: F401 – re-exported for backward compat
from .passes import extended_passes, full_scan_passes
from .scan_state import PassContext, ScanStateManager  # noqa: F401

logger = logging.getLogger(__name__)

_WARMUP_URLS = [
    "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
    "https://www.interpol.int/",
]
_MAX_RETRIES = 3
_RETRY_SLEEPS = (2.0, 5.0, 10.0)
_API_PATH = "/notices/v1/red"


class InterpolClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._warmed_up = False

    def _headers(self, *, json: bool = False) -> dict[str, str]:
        accept = (
            "application/json"
            if json
            else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }

    def _warmup(self) -> None:
        if self._warmed_up:
            return
        for url in _WARMUP_URLS:
            try:
                resp = self._session.get(url, headers=self._headers(), timeout=20)
                if resp.status_code == 200:
                    self._warmed_up = True
                    return
            except Exception as exc:
                logger.warning("Warmup failed for %s: %s", url, exc)
        self._warmed_up = True

    def _reset_session(self) -> None:
        """Drop the current session and re-warm after an IP ban (403)."""
        logger.warning("403 received; resetting session and waiting 5 min")
        self._session = requests.Session()
        self._warmed_up = False
        time.sleep(300)
        self._warmup()
        time.sleep(10)

    def _get(self, params: dict[str, Any]) -> tuple[bool, Any, int]:
        """Single HTTP GET. Returns (ok, data, status)."""
        url = f"{self.base_url}{_API_PATH}"
        headers = {
            **self._headers(json=True),
            "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 403:
                self._reset_session()
                resp = self._session.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 200:
                return True, resp.json(), 200
            return False, None, resp.status_code
        except requests.exceptions.Timeout:
            logger.error("Timeout: %s", url)
            return False, None, -1
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error: %s", exc)
            return False, None, -1
        except Exception as exc:
            logger.error("Unexpected error: %s", exc)
            return False, None, -1

    def _get_with_retry(self, params: dict[str, Any]) -> tuple[bool, Any, int]:
        for attempt in range(1, _MAX_RETRIES + 1):
            ok, data, status = self._get(params)
            if ok:
                return ok, data, status
            if status == 404:
                return False, None, 404
            if attempt < _MAX_RETRIES:
                sleep = _RETRY_SLEEPS[attempt - 1]
                logger.warning("Attempt %d failed (status=%d); retrying in %.1fs", attempt, status, sleep)
                time.sleep(sleep)
        return False, None, -1

    def fetch_red_notices(self, result_per_page: int = 20) -> list[RedNotice]:
        self._warmup()
        ok, data, _ = self._get({"resultPerPage": result_per_page})
        if not ok or not data:
            raise RuntimeError(f"Failed to fetch red notices from {self.base_url}")
        notices = [RedNotice.from_api_item(i) for i in self._extract(data)]
        logger.info("Fetched %d notices", len(notices))
        return notices

    def fetch_all_red_notices(self, request_delay: float = 1.5) -> list[RedNotice]:
        self._warmup()
        seen: dict[str, RedNotice] = {}
        self._collect_pages(seen, {}, request_delay)
        for label, param_list in full_scan_passes():
            self._run_pass(label, param_list, seen, request_delay)
        logger.info("Full scan complete: %d unique notices", len(seen))
        return list(seen.values())

    def fetch_extended_red_notices(
        self,
        request_delay: float = 1.5,
        enable_pass_age_0_9: bool = True,
        enable_pass_in_pk_1yr: bool = True,
        very_high_nationalities_1yr: list[str] | None = None,
        age_1yr_min: int = 10,
        age_1yr_max: int = 99,
        state_file: str = "/data/scan_state.json",
    ) -> list[RedNotice]:
        self._warmup()
        seen: dict[str, RedNotice] = {}
        state = ScanStateManager(state_file)
        passes = extended_passes(
            enable_age_0_9=enable_pass_age_0_9,
            enable_in_pk_1yr=enable_pass_in_pk_1yr,
            nationalities_1yr=very_high_nationalities_1yr,
            age_1yr_min=age_1yr_min,
            age_1yr_max=age_1yr_max,
        )
        for label, param_list in passes:
            self._run_pass(label, param_list, seen, request_delay, state=state)
        logger.info("Extended scan complete: %d unique notices", len(seen))
        return list(seen.values())

    def _run_pass(
        self,
        label: str,
        param_list: list[dict[str, Any]],
        seen: dict[str, RedNotice],
        request_delay: float,
        state: ScanStateManager | None = None,
    ) -> None:
        if state and state.is_pass_done(label):
            logger.info("Skipping pass '%s' (already done)", label)
            return
        m = re.match(r"Pass\s+(\w+)", label)
        pass_id = m.group(1) if m else label
        total = len(param_list)
        resume = state.get_resume_idx(label) if state else 0
        logger.info("Pass %s starting (%d combos)", pass_id, total)
        for idx, params in enumerate(param_list):
            if idx < resume:
                continue
            if state and idx % 50 == 0:
                state.mark_query_progress(label, idx)
            self._collect_pages(seen, params, request_delay, pass_id=pass_id, combo=f"{idx + 1}/{total}")
        if state:
            state.mark_pass_done(label)
        logger.info("Pass %s done (total unique: %d)", pass_id, len(seen))

    def _collect_pages(
        self,
        seen: dict[str, RedNotice],
        extra: dict[str, Any],
        delay: float,
        pass_id: str = "",
        combo: str = "",
    ) -> None:
        """Paginate through all results for a given filter combination."""
        page = 1
        prev_ids: frozenset | None = None
        identical = 0

        while True:
            params = {"resultPerPage": 160, "page": page, **extra}
            ok, data, _ = self._get_with_retry(params)

            if not ok or not data:
                break

            items = self._extract(data)
            if not items:
                break

            page_ids = frozenset(i.get("entity_id", "") for i in items if i.get("entity_id"))
            if prev_ids is not None and page_ids == prev_ids:
                identical += 1
                if identical >= 2:
                    logger.warning("Pagination loop at page %d, stopping", page)
                    break
            else:
                identical = 0
            prev_ids = page_ids

            for item in items:
                notice = RedNotice.from_api_item(item)
                if notice.entity_id and notice.entity_id not in seen:
                    seen[notice.entity_id] = notice

            if "next" not in data.get("_links", {}):
                break

            page += 1
            if delay > 0:
                time.sleep(delay + random.uniform(0.0, delay * 0.15))

    @staticmethod
    def _extract(data: Any) -> list[dict[str, Any]]:
        """Pull the notices list out of whatever structure the API returns."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("_embedded", "embedded", "data", "results", "notices", "items"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):
                    for nested in ("notices", "items", "results", "red_notices"):
                        if isinstance(val.get(nested), list):
                            return val[nested]
        return []

