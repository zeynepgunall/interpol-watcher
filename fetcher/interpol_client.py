from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any

import requests


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

    def fetch_red_notices(self, result_per_page: int = 20) -> List[RedNotice]:
        url = f"{self.base_url}/notices/v1/red"
        params = {"resultPerPage": result_per_page}
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        notices: Iterable[dict] = data.get("_embedded", {}).get(
            "notices", []
        )
        return [RedNotice.from_api_item(item) for item in notices]

