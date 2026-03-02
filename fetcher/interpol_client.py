from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests
logger = logging.getLogger(__name__)


@dataclass
class RedNotice:
    entity_id: str
    name: str | None
    forename: str | None
    date_of_birth: str | None
    nationality: str | None          # birincil uyruk (nationalities[0])
    all_nationalities: str | None    # tüm uyruklar virgülle ayrılmış, örn. "DE,TR"
    arrest_warrant: str | None
    thumbnail_url: str | None = None  # Interpol API _links.thumbnail.href

    @classmethod
    def from_api_item(cls, item: Dict[str, Any]) -> "RedNotice":
        # nationalities is an array in the real API response
        nationalities = item.get("nationalities") or []
        nationality = nationalities[0] if nationalities else item.get("nationality")
        all_nat = ",".join(nationalities) if nationalities else nationality or ""

        # entity_id uses slash format in API ("1993/27493") but path uses dash ("1993-27493")
        entity_id = item.get("entity_id") or item.get("id", "")

        arrest_warrants = item.get("arrest_warrants")
        arrest_warrant = (
            arrest_warrants[0].get("charge") if isinstance(arrest_warrants, list) and arrest_warrants else None
        )

        # Extract thumbnail URL from HATEOAS links if Interpol provides it
        thumbnail_url = (
            item.get("_links", {}).get("thumbnail", {}).get("href")
            or item.get("_links", {}).get("self", {}).get("href")  # fallback: derive later from entity_id
        )
        # Normalise: keep only if it looks like an actual thumbnail href
        if thumbnail_url and "/thumbnail" not in thumbnail_url:
            thumbnail_url = None

        return cls(
            entity_id=entity_id,
            name=item.get("name"),
            forename=item.get("forename"),
            date_of_birth=item.get("date_of_birth"),
            nationality=nationality,
            all_nationalities=all_nat or None,
            arrest_warrant=arrest_warrant,
            thumbnail_url=thumbnail_url,
        )


class ScanStateManager:
    """
    Pass ilerlemesini JSON dosyasına kaydeder — fetcher yeniden başlarsa kaldığı yerden devam eder.
    Dosya: /data/scan_state.json (docker volume'da kalıcı).
    """

    def __init__(self, state_file: str) -> None:
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"completed_passes": [], "current_pass": None, "current_query_idx": 0}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_file)
        except OSError as exc:
            logger.warning("State file write failed: %s", exc)

    def is_pass_done(self, pass_name: str) -> bool:
        return pass_name in self._state["completed_passes"]

    def get_resume_idx(self, pass_name: str) -> int:
        """Aynı pass yarıda kalmışsa kaldığı sorgu indexinden devam et."""
        if self._state.get("current_pass") == pass_name:
            return self._state.get("current_query_idx", 0)
        return 0

    def mark_query_progress(self, pass_name: str, query_idx: int) -> None:
        self._state["current_pass"] = pass_name
        self._state["current_query_idx"] = query_idx
        self._save()

    def mark_pass_done(self, pass_name: str) -> None:
        if pass_name not in self._state["completed_passes"]:
            self._state["completed_passes"].append(pass_name)
        self._state["current_pass"] = None
        self._state["current_query_idx"] = 0
        self._save()
        logger.info("STATE | pass '%s' marked done — saved to %s", pass_name, self.state_file)

    def reset(self) -> None:
        """Tüm state'i sıfırla (yeni tam tarama)."""
        self._state = {"completed_passes": [], "current_pass": None, "current_query_idx": 0}
        self._save()


@dataclass
class PassContext:
    """
    Immutable context for a single sweep pass.
    Created ONCE at pass start; combo_total never changes after initialisation.
    Passed down through _fetch_pages_into so every log line carries the same
    pass_id / combo_total without re-computing them.
    """
    pass_id: str        # "13", "A", "B", "19b", …
    name: str           # full label, e.g. "Pass 13 — F+nat+arrestWarrant"
    combo_total: int    # FIXED at pass start, never mutated
    state_file: str = "<none>"


class InterpolClient:
    """
    Robust client for Interpol public red notice API with multiple endpoint strategies.
    """

    # List of endpoint paths to try in order
    ENDPOINT_PATHS = [
        "/notices/v1/red",
    ]

    WARMUP_URLS = [
        "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
        "https://www.interpol.int/",
    ]

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._warmed_up = False
        logger.info(f"Initialized InterpolClient with base URL: {self.base_url}")

    def _build_headers(self, accept_json: bool = False) -> Dict[str, str]:
        """Build request headers with various user agent and accept types."""
        accept = "application/json" if accept_json else "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    def _warmup_session(self) -> None:
        """Visit the Interpol website to obtain cookies before making API requests."""
        if self._warmed_up:
            return
        for url in self.WARMUP_URLS:
            try:
                logger.info(f"Warming up session via: {url}")
                resp = self._session.get(url, headers=self._build_headers(accept_json=False), timeout=20, allow_redirects=True)
                logger.info(f"Warmup response status: {resp.status_code} | cookies: {dict(self._session.cookies)}")
                if resp.status_code == 200:
                    self._warmed_up = True
                    return
            except Exception as e:
                logger.warning(f"Warmup request failed for {url}: {e}")
        logger.warning("Session warmup did not succeed; proceeding anyway.")
        self._warmed_up = True

    # ------------------------------------------------------------------ #
    #  Retry configuration                                                #
    # ------------------------------------------------------------------ #
    _MAX_RETRIES: int = 3
    _RETRY_SLEEPS: tuple = (2.0, 5.0, 10.0)  # sleep seconds per attempt (1-based index)

    def _try_endpoint(self, endpoint_path: str, params: Dict[str, Any]) -> tuple[bool, Any, int, str]:
        """
        Try a single endpoint request.
        Returns (success, data, status_code, error_msg).
        status_code is the HTTP status code, or -1 for network/exception failures.
        Business logic for 403 (session reset + 5-minute back-off) is preserved here.
        """
        url = f"{self.base_url}{endpoint_path}"
        headers = self._build_headers(accept_json=True)
        headers["Referer"] = "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices"
        headers["Sec-Fetch-Site"] = "same-site"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Dest"] = "empty"

        logger.debug("Attempting endpoint: %s | params=%s", url, params)

        try:
            response = self._session.get(url, params=params, headers=headers, timeout=20)

            if response.status_code == 403:
                # Session expired or rate-limited — structured RETRY log before the 5-min back-off
                logger.warning(
                    "RETRY | reason=403 | sleep=300s — resetting session and waiting for IP ban to lift"
                )
                self._session = requests.Session()
                self._warmed_up = False
                time.sleep(300)  # wait 5 minutes for IP ban to lift
                self._warmup_session()
                time.sleep(10)
                response = self._session.get(url, params=params, headers=headers, timeout=20)
                logger.info("Post-403-retry | status=%d", response.status_code)

            if response.status_code == 200:
                try:
                    data = response.json()
                    return True, data, 200, ""
                except ValueError as exc:
                    logger.error("Failed to parse JSON response: %s", exc)
                    return False, None, response.status_code, f"Invalid JSON response: {exc}"
            else:
                try:
                    logger.warning(
                        "Endpoint returned %d. Body: %s", response.status_code, response.text[:500]
                    )
                except Exception:
                    pass
                return False, None, response.status_code, f"HTTP {response.status_code}"

        except requests.exceptions.Timeout:
            logger.error("Timeout connecting to %s", url)
            return False, None, -1, "Timeout"
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error for %s: %s", url, exc)
            return False, None, -1, f"Connection error: {exc}"
        except Exception as exc:
            logger.error("Unexpected error for %s: %s", url, exc)
            return False, None, -1, f"Unexpected error: {exc}"

    def _fetch_with_retry(
        self,
        endpoint_path: str,
        params: Dict[str, Any],
        pass_id: str = "",
        combo_idx: int = 0,
        combo_total: int = 0,
    ) -> tuple[bool, Any, int, int]:
        """
        Wraps _try_endpoint with structured QUERY / RETRY logging.
        Returns (success, data, status_code, latency_ms).

        Log lines emitted:
          QUERY | pass=X | combo=Y/Z | attempt=N | params={...}
          RETRY | pass=X | combo=Y/Z | attempt=N | reason=<msg> | sleep=Xs
        combo_idx and combo_total are display-only; business logic is unchanged.
        """
        combo_str = f"{combo_idx}/{combo_total}" if combo_total else str(combo_idx)
        last_status: int = -1
        last_latency: int = 0

        for attempt in range(1, self._MAX_RETRIES + 1):
            logger.info(
                "QUERY | pass=%s | combo=%s | attempt=%d | params=%s",
                pass_id, combo_str, attempt, params,
            )
            t0 = time.monotonic()
            success, data, status_code, error = self._try_endpoint(endpoint_path, params)
            latency_ms = int((time.monotonic() - t0) * 1000)
            last_status = status_code
            last_latency = latency_ms

            if success:
                return True, data, status_code, latency_ms

            # 404 is definitive — no point retrying
            if status_code == 404:
                logger.warning(
                    "QUERY_SKIP | pass=%s | combo=%s | reason=404 | no retry",
                    pass_id, combo_str,
                )
                break

            if attempt < self._MAX_RETRIES:
                sleep_sec = (
                    self._RETRY_SLEEPS[attempt - 1]
                    if attempt - 1 < len(self._RETRY_SLEEPS)
                    else self._RETRY_SLEEPS[-1]
                )
                reason = error if error else str(status_code) if status_code > 0 else "unknown"
                logger.warning(
                    "RETRY | pass=%s | combo=%s | attempt=%d | reason=%s | sleep=%.1fs",
                    pass_id, combo_str, attempt + 1, reason, sleep_sec,
                )
                time.sleep(sleep_sec)

        return False, None, last_status, last_latency

    def fetch_red_notices(self, result_per_page: int = 20) -> List[RedNotice]:
        """Fetch red notices by trying multiple endpoint strategies."""
        params = {"resultPerPage": result_per_page}

        self._warmup_session()
        
        logger.info(f"Starting red notice fetch (requested: {result_per_page} results)")
        
        # Try each endpoint path
        for endpoint_path in self.ENDPOINT_PATHS:
            success, data, _status, _err = self._try_endpoint(endpoint_path, params)

            if success and data:
                notices_data = self._extract_notices(data)
                if notices_data:
                    notices = [RedNotice.from_api_item(item) for item in notices_data]
                    logger.info("Successfully parsed %d notices from %s", len(notices), endpoint_path)
                    return notices
                else:
                    logger.warning("Endpoint %s returned data but no notices found", endpoint_path)

        # All endpoints failed
        logger.error("All endpoint attempts failed")
        raise Exception(f"Failed to fetch red notices from any endpoint. Base URL: {self.base_url}")

    # ISO 3166-1 alpha-2 country codes
    ALL_NATIONALITIES = [
        "AF","AL","DZ","AD","AO","AG","AR","AM","AU","AT","AZ","BS","BH","BD","BB",
        "BY","BE","BZ","BJ","BT","BO","BA","BW","BR","BN","BG","BF","BI","CV","KH",
        "CM","CA","CF","TD","CL","CN","CO","KM","CG","CD","CR","HR","CU","CY","CZ",
        "DK","DJ","DM","DO","EC","EG","SV","GQ","ER","EE","SZ","ET","FJ","FI","FR",
        "GA","GM","GE","DE","GH","GR","GD","GT","GN","GW","GY","HT","HN","HU","IS",
        "IN","ID","IR","IQ","IE","IL","IT","JM","JP","JO","KZ","KE","KI","KP","KR",
        "KW","KG","LA","LV","LB","LS","LR","LY","LI","LT","LU","MG","MW","MY","MV",
        "ML","MT","MH","MR","MU","MX","FM","MD","MC","MN","ME","MA","MZ","MM","NA",
        "NR","NP","NL","NZ","NI","NE","NG","NO","OM","PK","PW","PA","PG","PY","PE",
        "PH","PL","PT","QA","RO","RU","RW","KN","LC","VC","WS","SM","ST","SA","SN",
        "RS","SC","SL","SG","SK","SI","SB","SO","ZA","SS","ES","LK","SD","SR","SE",
        "CH","SY","TW","TJ","TZ","TH","TL","TG","TO","TT","TN","TR","TM","TV","UG",
        "UA","AE","GB","US","UY","UZ","VU","VE","VN","YE","ZM","ZW",
    ]

    def fetch_all_red_notices(self, request_delay: float = 1.5) -> List[RedNotice]:
        """
        Fetch ALL red notices by combining multiple filter dimensions.
        The public API caps results at 160 per query regardless of total,
        so we sweep across nationality, arrestWarrantCountryId, sexId combos and age ranges.
        """
        self._warmup_session()
        seen: Dict[str, RedNotice] = {}

        def run_pass(label: str, param_list: List[Dict[str, Any]]) -> None:
            import re as _re
            _m = _re.match(r"Pass\s+(\w+)", label)
            pass_id: str = _m.group(1) if _m else label
            combo_total: int = len(param_list)  # fixed for the lifetime of this pass
            logger.info("PASS_START | pass_id=%s | name=%s | combos=%d", pass_id, label, combo_total)
            for idx, params in enumerate(param_list, 1):
                self._fetch_pages_into(
                    seen,
                    extra_params=params,
                    request_delay=request_delay,
                    pass_id=pass_id,
                    combo_idx=idx,
                    combo_total=combo_total,
                )
            logger.info(
                "PASS_DONE | pass_id=%s | name=%s | collected=%d | saved_to=<none>",
                pass_id, label, len(seen),
            )

        # Pass 1: unfiltered
        logger.info("Pass 1 — unfiltered")
        self._fetch_pages_into(seen, extra_params={}, request_delay=request_delay)

        # Pass 2: nationality
        run_pass("Pass 2 — nationality", [{"nationality": n} for n in self.ALL_NATIONALITIES])

        # Pass 3: arrestWarrantCountryId
        run_pass("Pass 3 — arrestWarrantCountryId", [{"arrestWarrantCountryId": c} for c in self.ALL_NATIONALITIES])

        # Pass 4: sexId=M + nationality  (M is 5545 total — too big alone, need sub-filters)
        run_pass("Pass 4 — M+nationality", [{"sexId": "M", "nationality": n} for n in self.ALL_NATIONALITIES])

        # Pass 5: sexId=F + nationality
        run_pass("Pass 5 — F+nationality", [{"sexId": "F", "nationality": n} for n in self.ALL_NATIONALITIES])

        # Pass 6: sexId=M + arrestWarrantCountryId
        run_pass("Pass 6 — M+arrestWarrant", [{"sexId": "M", "arrestWarrantCountryId": c} for c in self.ALL_NATIONALITIES])

        # Pass 7: sexId=F + arrestWarrantCountryId
        run_pass("Pass 7 — F+arrestWarrant", [{"sexId": "F", "arrestWarrantCountryId": c} for c in self.ALL_NATIONALITIES])

        # Pass 8: age ranges × sexId (catch notices with no nationality/warrant country)
        age_ranges = [(i, i + 4) for i in range(10, 100, 5)]
        run_pass("Pass 8 — M+age", [{"sexId": "M", "ageMin": a, "ageMax": b} for a, b in age_ranges])
        run_pass("Pass 9 — F+age", [{"sexId": "F", "ageMin": a, "ageMax": b} for a, b in age_ranges])

        # Pass 10 & 11: drill-down for high-count nationalities (>160 total)
        # RU=3022, SV=783, IN=217, AR=178, PK=174, GT=172 — need age sub-ranges
        HIGH_COUNT_NATIONALITIES = ["RU", "SV", "IN", "AR", "PK", "GT"]
        run_pass("Pass 10 — M+highNat+age", [
            {"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
            for nat in HIGH_COUNT_NATIONALITIES
            for a, b in age_ranges
        ])
        run_pass("Pass 11 — F+highNat+age", [
            {"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
            for nat in HIGH_COUNT_NATIONALITIES
            for a, b in age_ranges
        ])

        # Pass 12: M + each nationality + each arrest warrant country (covers cross-border notices)
        run_pass("Pass 12 — M+nat+arrestWarrant", [
            {"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
            for nat in HIGH_COUNT_NATIONALITIES
            for c in self.ALL_NATIONALITIES
        ])

        # Pass 13: F + highNat + each arrest warrant country (mirror of pass 12 for females)
        run_pass("Pass 13 — F+nat+arrestWarrant", [
            {"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
            for nat in HIGH_COUNT_NATIONALITIES
            for c in self.ALL_NATIONALITIES
        ])

        # Pass 14: M + ALL nationalities × high-count arrest warrant countries
        # (inverse axis: people issued by RU/SV/IN/etc warrant, any nationality)
        run_pass("Pass 14 — M+allNat+highAW", [
            {"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
            for c in HIGH_COUNT_NATIONALITIES
            for nat in self.ALL_NATIONALITIES
        ])

        # Pass 15: F + ALL nationalities × high-count arrest warrant countries
        run_pass("Pass 15 — F+allNat+highAW", [
            {"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
            for c in HIGH_COUNT_NATIONALITIES
            for nat in self.ALL_NATIONALITIES
        ])

        notices = list(seen.values())
        logger.info(f"Total unique red notices fetched: {len(notices)}")
        return notices

    def fetch_extended_red_notices(
        self,
        request_delay: float = 1.5,
        enable_pass_age_0_9: bool = True,
        enable_pass_in_pk_1yr: bool = True,
        very_high_nationalities_1yr: Optional[List[str]] = None,
        age_1yr_min: int = 10,
        age_1yr_max: int = 99,
        state_file: str = "/data/scan_state.json",
    ) -> List[RedNotice]:
        """
        Supplemental passes to recover notices missed by the initial 12-pass scan.
        Runs only new filter combinations, skips passes 1-12.

        Pass 13: F + highNat + arrestWarrantCountryId
        Pass 14: M + ALL nationalities × high arrest-warrant countries
        Pass 15: F + ALL nationalities × high arrest-warrant countries
        Pass 16: M + VERY_HIGH_NAT (RU, SV) + 1-year age ranges
        Pass 17: F + VERY_HIGH_NAT (RU, SV) + 1-year age ranges
        Pass 18: M + VERY_HIGH_NAT + AW + 5yr age
        Pass 19: sexId=U
        Pass 20: age 100-120
        Pass A:  age 0-9  (ENABLE_PASS_AGE_0_9)
        Pass B:  IN/PK + 1yr age (ENABLE_PASS_IN_PK_1YR)
        """
        if very_high_nationalities_1yr is None:
            very_high_nationalities_1yr = ["IN", "PK"]

        self._warmup_session()
        seen: Dict[str, RedNotice] = {}
        state = ScanStateManager(state_file)

        HIGH_COUNT_NATIONALITIES = ["RU", "SV", "IN", "AR", "PK", "GT"]
        VERY_HIGH_NATIONALITIES = ["RU", "SV"]
        age_ranges_5yr = [(i, i + 4) for i in range(10, 100, 5)]
        age_ranges_1yr = [(i, i) for i in range(10, 85)]

        def run_pass(label: str, param_list: List[Dict[str, Any]]) -> None:
            """
            Executes one sweep pass with structured PASS_START / PASS_DONE logging.

            Progress guarantees:
              - combo_total is calculated ONCE here and never changes.
              - combo_idx is incremented ONLY after a successful _fetch_pages_into call.
              - State is checkpointed every 50 combos for crash-safety.
            """
            import re as _re

            if state.is_pass_done(label):
                logger.info("SKIP | pass='%s' zaten tamamlanmis (state file)", label)
                return

            # Extract short pass_id from label, e.g. "Pass 13 — ..." -> "13", "Pass Ab — ..." -> "Ab"
            _m = _re.match(r"Pass\s+(\w+)", label)
            pass_id: str = _m.group(1) if _m else label

            # combo_total is fixed for the lifetime of this pass
            combo_total: int = len(param_list)
            saved_to: str = state.state_file if state.state_file else "<none>"

            logger.info(
                "PASS_START | pass_id=%s | name=%s | combos=%d",
                pass_id, label, combo_total,
            )

            resume_idx = state.get_resume_idx(label)
            if resume_idx > 0:
                logger.info(
                    "RESUME | pass_id=%s | from_combo=%d/%d",
                    pass_id, resume_idx, combo_total,
                )

            for list_idx, params in enumerate(param_list):
                if list_idx < resume_idx:
                    continue  # zaten islendi, atla

                # combo_idx is 1-based for display; updated only after successful processing
                combo_idx: int = list_idx + 1

                # Checkpoint every 50 combos for crash-safety (not a progress indicator)
                if list_idx % 50 == 0:
                    state.mark_query_progress(label, list_idx)

                # _fetch_pages_into now logs QUERY / RESULT / RETRY internally
                stats = self._fetch_pages_into(
                    seen,
                    extra_params=params,
                    request_delay=request_delay,
                    pass_id=pass_id,
                    combo_idx=combo_idx,
                    combo_total=combo_total,
                )

                # Brief per-combo summary after all pages are done
                if stats["new"] or stats["loop"]:
                    logger.info(
                        "COMBO_DONE | pass=%s | combo=%d/%d | pages=%d"
                        " | new=%d | dupes=%d | loop=%s",
                        pass_id, combo_idx, combo_total,
                        stats["pages"], stats["new"], stats["dupes"], stats["loop"],
                    )

            state.mark_pass_done(label)
            logger.info(
                "PASS_DONE | pass_id=%s | name=%s | collected=%d | saved_to=%s",
                pass_id, label, len(seen), saved_to,
            )

        # Pass 13: F + highNat + each arrest warrant country
        run_pass("Pass 13 — F+nat+arrestWarrant", [
            {"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
            for nat in HIGH_COUNT_NATIONALITIES
            for c in self.ALL_NATIONALITIES
        ])

        # Pass 14: M + ALL nationalities × high-count arrest warrant countries
        run_pass("Pass 14 — M+allNat+highAW", [
            {"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
            for c in HIGH_COUNT_NATIONALITIES
            for nat in self.ALL_NATIONALITIES
        ])

        # Pass 15: F + ALL nationalities × high-count arrest warrant countries
        run_pass("Pass 15 — F+allNat+highAW", [
            {"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
            for c in HIGH_COUNT_NATIONALITIES
            for nat in self.ALL_NATIONALITIES
        ])

        # Pass 16: M + VERY_HIGH_NAT + 1-year age ranges
        # RU/SV have so many records that even 5-year age buckets hit 160 cap at peak ages
        run_pass("Pass 16 — M+veryHighNat+1yrAge", [
            {"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
            for nat in VERY_HIGH_NATIONALITIES
            for a, b in age_ranges_1yr
        ])

        # Pass 17: F + VERY_HIGH_NAT + 1-year age ranges
        run_pass("Pass 17 — F+veryHighNat+1yrAge", [
            {"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
            for nat in VERY_HIGH_NATIONALITIES
            for a, b in age_ranges_1yr
        ])

        # Pass 18: M/F + VERY_HIGH_NAT + AW country + 5-year age ranges
        # Triple filter for the densest cells that even 1-year ranges might not clear
        run_pass("Pass 18 — M+veryHighNat+AW+5yrAge", [
            {"sexId": "M", "nationality": nat, "arrestWarrantCountryId": nat, "ageMin": a, "ageMax": b}
            for nat in VERY_HIGH_NATIONALITIES
            for a, b in age_ranges_5yr
        ])

        # Pass 19: sexId=U — notices with unknown/unspecified sex (4 known records)
        run_pass("Pass 19 — sexId=U", [{"sexId": "U"}])
        run_pass("Pass 19b — U+allNat", [{"sexId": "U", "nationality": n} for n in self.ALL_NATIONALITIES])

        # Pass 20: extreme age ranges (100-120) — catches edge cases not in standard age scans
        run_pass("Pass 20 — age100+", [{"ageMin": 100, "ageMax": 120}])
        run_pass("Pass 20b — M+age100+", [{"sexId": "M", "ageMin": 100, "ageMax": 120}])
        run_pass("Pass 20c — F+age100+", [{"sexId": "F", "ageMin": 100, "ageMax": 120}])

        # ------------------------------------------------------------------ #
        #  Pass A — age 0–9 (henüz hiç taranmadı)                            #
        # ------------------------------------------------------------------ #
        if enable_pass_age_0_9:
            run_pass("Pass A — age0-9", [{"ageMin": 0, "ageMax": 9}])
            # Eğer age 0-9 için total > 160 ise sex'e göre bölüp tekrar tara
            run_pass("Pass Ab — M+age0-9", [{"sexId": "M", "ageMin": 0, "ageMax": 9}])
            run_pass("Pass Ab — F+age0-9", [{"sexId": "F", "ageMin": 0, "ageMax": 9}])
            run_pass("Pass Ab — U+age0-9", [{"sexId": "U", "ageMin": 0, "ageMax": 9}])
        else:
            logger.info("SKIP Pass A — ENABLE_PASS_AGE_0_9=false")

        # ------------------------------------------------------------------ #
        #  Pass B — 1 yıllık yaş aralığı: IN, PK (ve VERY_HIGH_NATIONALITIES_1YR)  #
        # ------------------------------------------------------------------ #
        if enable_pass_in_pk_1yr and very_high_nationalities_1yr:
            age_ranges_1yr_b = [(a, a) for a in range(age_1yr_min, age_1yr_max + 1)]
            run_pass(
                f"Pass B — M+{'+'.join(very_high_nationalities_1yr)}+1yrAge",
                [
                    {"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
                    for nat in very_high_nationalities_1yr
                    for a, b in age_ranges_1yr_b
                ],
            )
            run_pass(
                f"Pass B — F+{'+'.join(very_high_nationalities_1yr)}+1yrAge",
                [
                    {"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
                    for nat in very_high_nationalities_1yr
                    for a, b in age_ranges_1yr_b
                ],
            )
        else:
            logger.info("SKIP Pass B — ENABLE_PASS_IN_PK_1YR=false veya liste boş")

        notices = list(seen.values())
        logger.info(f"Extended scan complete. New unique notices found: {len(notices)}")
        return notices

    def _fetch_pages_into(
        self,
        seen: Dict[str, "RedNotice"],
        extra_params: Dict[str, Any],
        request_delay: float = 0.3,
        pass_id: str = "",
        combo_idx: int = 0,
        combo_total: int = 0,
    ) -> Dict[str, Any]:
        """
        Belirli filtre parametreleriyle tüm sayfaları çeker, seen dict'e ekler.
        Döndürür: {pages, new, dupes, loop} istatistik sözlüğü.

        pass_id / combo_idx / combo_total are forwarded to _fetch_with_retry so that
        every QUERY / RETRY / RESULT line carries consistent structured context.

        Döngü tespiti: ardışık iki sayfa aynı entity_id setini döndürürse
        PAGINATION_LOOP logu basılır ve sayfalama durdurulur.
        """
        page = 1
        result_per_page = 160
        pages_fetched = 0
        new_found = 0
        duplicates = 0
        loop_detected = False
        combo_str = f"{combo_idx}/{combo_total}" if combo_total else str(combo_idx)

        prev_page_ids: Optional[frozenset] = None
        consecutive_identical = 0

        while True:
            params = {"resultPerPage": result_per_page, "page": page, **extra_params}

            success, data, status_code, latency_ms = self._fetch_with_retry(
                self.ENDPOINT_PATHS[0],
                params,
                pass_id=pass_id,
                combo_idx=combo_idx,
                combo_total=combo_total,
            )

            if not success or not data:
                logger.warning(
                    "RESULT | pass=%s | combo=%s | page=%d | items=0 | status=%d"
                    " | latency_ms=%d | FAILED",
                    pass_id, combo_str, page, status_code, latency_ms,
                )
                break

            notices_data = self._extract_notices(data)

            logger.info(
                "RESULT | pass=%s | combo=%s | page=%d | items=%d | status=%d | latency_ms=%d",
                pass_id, combo_str, page, len(notices_data), status_code, latency_ms,
            )

            if not notices_data:
                break

            # Döngü tespiti: bu sayfanın ID seti
            page_ids = frozenset(
                item.get("entity_id", "") for item in notices_data if item.get("entity_id")
            )
            if prev_page_ids is not None and page_ids == prev_page_ids:
                consecutive_identical += 1
                if consecutive_identical >= 2:
                    loop_detected = True
                    logger.warning(
                        "PAGINATION_LOOP | pass=%s | combo=%s | page=%d | params=%s"
                        " — sayfalama durduruluyor",
                        pass_id, combo_str, page, extra_params,
                    )
                    break
            else:
                consecutive_identical = 0
            prev_page_ids = page_ids

            for item in notices_data:
                notice = RedNotice.from_api_item(item)
                if notice.entity_id and notice.entity_id not in seen:
                    seen[notice.entity_id] = notice
                    new_found += 1
                else:
                    duplicates += 1

            pages_fetched += 1

            # Sonraki sayfa var mı?
            links = data.get("_links", {}) if isinstance(data, dict) else {}
            if "next" not in links:
                break

            page += 1
            if request_delay > 0:
                # Küçük rastgele jitter — Akamai rate-limit tespitini zorlaştırır
                jitter = random.uniform(0.0, request_delay * 0.15)
                time.sleep(request_delay + jitter)

        return {"pages": pages_fetched, "new": new_found, "dupes": duplicates, "loop": loop_detected}
    
    def _extract_notices(self, data: Any) -> List[Dict[str, Any]]:
        """Extract notices array from various response structures."""
        if isinstance(data, list):
            return data
        
        if isinstance(data, dict):
            # Try common response structures
            for key in ["_embedded", "embedded", "data", "results", "notices", "items"]:
                if key in data:
                    nested = data[key]
                    if isinstance(nested, list):
                        return nested
                    if isinstance(nested, dict):
                        # Try nested structures like {"_embedded": {"notices": [...]}}
                        for nested_key in ["notices", "items", "results", "red_notices"]:
                            if nested_key in nested and isinstance(nested[nested_key], list):
                                return nested[nested_key]
        
        return []

