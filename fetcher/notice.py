"""Red Notice veri modeli — Interpol API yanıtını yapılandırılmış nesneye dönüştürür.
   API'DEN GELEN JSON VERİSİNİ RedNotice nesnesine parse eder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RedNotice:
    """Interpol Red Notice kaydının veri taşıyıcısı."""

    entity_id: str
    name: str | None
    forename: str | None
    date_of_birth: str | None
    nationality: str | None
    all_nationalities: str | None
    arrest_warrant: str | None
    photo_url: str | None = None

    @classmethod
    def from_api_item(cls, item: dict[str, Any]) -> RedNotice:
        """
        Interpol API'den gelen ham JSON'u parse eder.RedNotice nesnesi oluşturuyor.
        """
        nationalities = item.get("nationalities") or []
        nationality = nationalities[0] if nationalities else item.get("nationality")
        all_nat = ",".join(nationalities) if nationalities else nationality or ""

        entity_id = item.get("entity_id") or item.get("id", "")

        arrest_warrants = item.get("arrest_warrants")
        arrest_warrant = (
            arrest_warrants[0].get("charge") 
            if isinstance(arrest_warrants, list) and arrest_warrants
            else None
        )

        # Thumbnail URL'i doğrula: gerçek fotoğraf URL'leri "/images/" içerir
        photo_url = item.get("_links", {}).get("thumbnail", {}).get("href")
        if photo_url and "/images/" not in photo_url:
            photo_url = None

        return cls(
            entity_id=entity_id,
            name=item.get("name"),
            forename=item.get("forename"),
            date_of_birth=item.get("date_of_birth"),
            nationality=nationality,
            all_nationalities=all_nat or None,
            arrest_warrant=arrest_warrant,
            photo_url=photo_url,
        )
