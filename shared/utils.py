"""Proje genelinde kullanılan ortak yardımcı fonksiyonlar."""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Timezone bilgisi olmadan UTC zaman damgası döndürür (DB uyumluluğu için)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def safe_filename(entity_id: str) -> str:
    """entity_id içindeki '/' karakterini '-' ile değiştirip .jpg uzantısı ekler."""
    return entity_id.replace("/", "-") + ".jpg"
