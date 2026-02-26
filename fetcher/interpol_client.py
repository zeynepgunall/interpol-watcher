from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any

import httpx


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/",
    "Origin": "https://www.interpol.int",
}


@dataclass
class RedNotice:
    entity_id: str
    name: str | None
    forename: str | None
    date_of_birth: str | None
    nationality: str | None
    arrest_warrant: str | None

    @classmethod
    def from_api_item(cls, item: Dict[str, Any]) -> "RedNotice":
        return cls(
            entity_id=item.get("entity_id") or item.get("id", ""),
            name=item.get("name"),
            forename=item.get("forename"),
            date_of_birth=item.get("date_of_birth"),
            nationality=item.get("nationality"),
            arrest_warrant=(item.get("arrest_warrants") or [{}])[0].get(
                "charge", None
            )
            if isinstance(item.get("arrest_warrants"), list)
            else None,
        )


class InterpolClient:
    """
    Minimal client for Interpol public red notice API.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
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
    ) -> List[RedNotice]:
        url = f"{self.base_url}/notices/v1/red"
        params = {"page": page, "resultPerPage": result_per_page}

        request = self.client.build_request("GET", url, params=params)
        response = self.client.send(request)
        response.raise_for_status()

        data = response.json()
        notices: Iterable[dict] = data.get("_embedded", {}).get(
            "notices", []
        )
        return [RedNotice.from_api_item(item) for item in notices]
