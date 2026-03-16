"""Interpol public API HTTP istemcisi — Red Notice verilerini çeker.
- Fetcher API'den veri çekmek için InterpolClient'ı kullanır.
- fetch_extended_red_notices(): ek filtre kombinasyonlarıyla daha derin veri çekimi sağlar.
- İstekler arasında rastgele gecikmeler uygular, 403 ban durumlarında session'ı sıfırlar ve kademeli bekleme yapar.
- _collect_pages(): API'yi sayfa sayfa gezerek notice'leri toplar. Sonsuz pagination döngüsünü algılar ve önler.
- ScanStateManager: Pass ilerlemesini JSON dosyasına kaydeder. Fetcher yeniden başladığında kaldığı yerden devam eder."""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Callable

import requests

from .notice import RedNotice
from .passes import extended_passes, full_scan_passes
from .scan_state import ScanStateManager

logger = logging.getLogger(__name__)

_WARMUP_URLS = [
    "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
    "https://www.interpol.int/",
]
_MAX_RETRIES = 3
_RETRY_SLEEPS = (5.0, 15.0, 30.0)
_API_PATH = "/notices/v1/red"
_BAN_BACKOFF = [600, 1200, 1800]
_RESULTS_PER_PAGE = 100


class InterpolClient:
    """Interpol public API üzerinden Red Notice verilerini çeken HTTP istemcisi."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session() 
        self._ban_count = 0
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
        """Interpol sitesine normal bir ziyaret simüle ederek session cookie alınır(bot algılamasını azaltır)."""
        if self._warmed_up:
            return
        time.sleep(random.uniform(2.0, 5.0))
        for url in _WARMUP_URLS:
            try:
                resp = self._session.get(url, headers=self._headers(), timeout=20)
                logger.info("Warmup %s → %d", url, resp.status_code)
                if resp.status_code == 200:
                    self._warmed_up = True
                    time.sleep(random.uniform(3.0, 6.0))
                    return
                time.sleep(random.uniform(1.0, 3.0))
            except Exception as exc:
                logger.warning("Warmup hatası (%s): %s", url, exc)
        self._warmed_up = True

    def _reset_session(self) -> None:
        """403 ban sonrası session'ı sıfırlar ve kademeli bekleme uygular."""
        idx = min(self._ban_count, len(_BAN_BACKOFF) - 1)
        wait = _BAN_BACKOFF[idx]
        self._ban_count += 1
        logger.warning("403 alındı (ban #%d); session sıfırlanıyor, %d dk bekleniyor", self._ban_count, wait // 60)
        self._session = requests.Session()
        self._warmed_up = False
        time.sleep(wait)
        self._warmup()
        time.sleep(random.uniform(10.0, 20.0))

    def _get(self, params: dict[str, Any]) -> tuple[bool, Any, int]:
        """API çağrılarını yapıyor ve başarısız istekleri retry mekanizmasıyla tekrar deniyor."""
        url = f"{self.base_url}{_API_PATH}"
        headers = {
            **self._headers(json=True),
            "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 403:
                self._reset_session()
                return False, None, 403
            if resp.status_code == 200:
                self._ban_count = 0
                return True, resp.json(), 200
            return False, None, resp.status_code
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.error("Bağlantı hatası: %s → %s", url, exc)
            return False, None, -1
        except Exception as exc:
            logger.error("Beklenmeyen hata: %s → %s", url, exc)
            return False, None, -1

    def _get_with_retry(self, params: dict[str, Any]) -> tuple[bool, Any, int]:
        """Başarısız istekleri retry mekanizmasıyla tekrar dener."""
        for attempt in range(1, _MAX_RETRIES + 1):
            ok, data, status = self._get(params)
            if ok:
                return ok, data, status
            if status == 404:
                return False, None, 404
            if attempt < _MAX_RETRIES:
                sleep = random.uniform(5.0, 15.0) if status == 403 else _RETRY_SLEEPS[attempt - 1]
                logger.warning("Deneme %d başarısız (status=%d); %.1fs sonra tekrar", attempt, status, sleep)
                time.sleep(sleep)
        return False, None, -1


    def fetch_red_notices(self, result_per_page: int = 20) -> list[RedNotice]:
    
        self._warmup()
        ok, data, _ = self._get({"resultPerPage": result_per_page})
        if not ok or not data:
            raise RuntimeError(f"Red Notice verisi çekilemedi: {self.base_url}")
        notices = [RedNotice.from_api_item(i) for i in self._extract(data)]
        logger.info("%d notice çekildi", len(notices))
        return notices



    def fetch_all_red_notices(
        self,
        request_delay: float = 1.5,
        on_new: Callable[[list[RedNotice]], None] | None = None,
        state_file: str = "/data/scan_state.json",
    ) -> list[RedNotice]:
        """Tüm Red Notice'leri çoklu pass ile tarar (streaming modda)."""
        self._warmup()
        seen: dict[str, RedNotice] = {}
        state = ScanStateManager(state_file)
        for label, param_list in full_scan_passes():
            self._run_pass(label, param_list, seen, request_delay, state=state, on_new=on_new)
        logger.info("Tam tarama tamamlandı: %d benzersiz notice", len(seen))
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
        on_new: Callable[[list[RedNotice]], None] | None = None,
    ) -> list[RedNotice]:
        """Genişletilmiş tarama: ek filtre kombinasyonlarıyla daha derin veri çekimi."""
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
            self._run_pass(label, param_list, seen, request_delay, state=state, on_new=on_new)
        logger.info("Genişletilmiş tarama tamamlandı: %d benzersiz notice", len(seen))
        return list(seen.values())

    """_run_pass() tek bir scan passini yöneten orchestration fonksiyonu. Parametre kombinasyonlarını tek tek çalıştırıyor, gerekiyorsa kaldığı yerden devam ediyor, _collect_pages() ile sayfaları topluyor ve ilerlemeyi state dosyasına kaydediyor."""
    def _run_pass(
        self,
        label: str,
        param_list: list[dict[str, Any]],
        seen: dict[str, RedNotice],
        request_delay: float,
        state: ScanStateManager | None = None, 
        on_new: Callable[[list[RedNotice]], None] | None = None,
    ) -> None:
        """Tek bir pass'ı çalıştırır. Crash-safe state yönetimi(ScanStateManager kullanarak)(kaldığı yerden devam etmesini sağlıyor.) ile kaldığı yerden devam eder."""
        if state and state.is_pass_done(label):
            logger.info("Pass '%s' atlanıyor (zaten tamamlanmış)", label)
            return
        m = re.match(r"Pass\s+(\w+)", label)
        pass_id = m.group(1) if m else label
        total = len(param_list)
        resume = state.get_resume_idx(label) if state else 0
        logger.info("Pass %s başlıyor (%d kombinasyon)", pass_id, total)
        for idx, params in enumerate(param_list):
            if idx < resume:
                continue
            if state and idx % 50 == 0:
                state.mark_query_progress(label, idx)
            self._collect_pages(seen, params, request_delay, pass_id=pass_id, combo=f"{idx + 1}/{total}", on_new=on_new)
        if state:
            state.mark_pass_done(label)
        logger.info("Pass %s tamamlandı (toplam benzersiz: %d)", pass_id, len(seen))

        """API'yi sayfa sayfa gezerek notice'leri toplar. Sonsuz pagination döngüsünü algılar ve önler."""
    def _collect_pages(
        self,
        seen: dict[str, RedNotice],
        extra: dict[str, Any],
        delay: float,
        pass_id: str = "",
        combo: str = "",
        on_new: Callable[[list[RedNotice]], None] | None = None,
    ) -> None:
        """Sayfalanmış API yanıtlarını toplar. Döngü algılaması ile sonsuz pagination'ı önler."""
        page = 1
        prev_ids: frozenset | None = None
        identical = 0

        while True:
            params = {"resultPerPage": _RESULTS_PER_PAGE, "page": page, **extra}
            ok, data, _ = self._get_with_retry(params)
            if not ok or not data:
                break

            items = self._extract(data)
            if not items:
                break

            # Sonsuz pagination döngüsünü algıla
            page_ids = frozenset(i.get("entity_id", "") for i in items if i.get("entity_id"))
            if prev_ids is not None and page_ids == prev_ids:
                identical += 1
                if identical >= 2:
                    logger.warning("Pagination döngüsü algılandı (sayfa %d), durduruluyor", page)
                    break
            else:
                identical = 0
            prev_ids = page_ids

            new_batch: list[RedNotice] = []
            for item in items:
                notice = RedNotice.from_api_item(item)
                if notice.entity_id and notice.entity_id not in seen:
                    seen[notice.entity_id] = notice
                    new_batch.append(notice)

            if on_new and new_batch:
                on_new(new_batch)

            if "next" not in data.get("_links", {}):
                break

            page += 1
            if delay > 0:
                time.sleep(delay + random.uniform(0.5, delay * 0.5))

    @staticmethod
    def _extract(data: Any) -> list[dict[str, Any]]:
        """API yanıtından notice listesini çıkarır (farklı response formatlarını destekler)."""
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
