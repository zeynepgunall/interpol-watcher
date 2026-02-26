import logging
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Referer": "https://www.interpol.int/",
    "Origin": "https://www.interpol.int",
    # Bazı WAF kontrolleri için:
    "X-Requested-With": "XMLHttpRequest",
}


class InterpolClient:
    def __init__(self, api_url: str, page: int = 1, result_per_page: int = 20):
        self.api_url = api_url
        self.page = page
        self.result_per_page = result_per_page

        # HTTP/2 client
        self.client = httpx.Client(
            http2=True,
            headers=DEFAULT_HEADERS,
            timeout=20.0,
            follow_redirects=True,
        )

    def fetch_red_notices(
        self,
        page: int = 1,
        result_per_page: int = 20,
    ) -> List[Dict[str, Any]]:
        params = {
            "page": page,
            "resultPerPage": result_per_page,
        }

        logger.info("Interpol API request params: %s", params)

        try:
            logger.info("Interpol API'ye istek atılıyor: %s", self.api_url)
            r = self.client.get(self.api_url, params=params)
            r.raise_for_status()

            data = r.json()
            notices = data.get("_embedded", {}).get("notices", [])
            logger.info("%d kayıt başarıyla çekildi.", len(notices))
            return notices

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP hatası: %s - %s",
                e.response.status_code,
                e.response.text[:200],
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Beklenmeyen hata: %s", e)

        return []