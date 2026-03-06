"""Database persistence for Interpol red notices."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto

from sqlalchemy.orm import Session
from .models import Notice

logger = logging.getLogger(__name__)


class UpsertOutcome(Enum):
    INSERTED  = auto()   # Yeni kayıt eklendi
    UPDATED   = auto()   # Mevcut kayıtta gerçek değişiklik var → alarm!
    UNCHANGED = auto()   # Kayıt zaten güncel, değişiklik yok → alarm temizlenir
    SKIPPED   = auto()   # entity_id eksik
    ERROR     = auto()   # Beklenmedik hata


@dataclass(frozen=True)
class UpsertResult:
    outcome: UpsertOutcome
    entity_id: str | None = None
    error: str | None = None

    @property
    def is_alarm(self) -> bool:
        """Sonuç UPDATED ise True döner — bu bir alarm (mevcut kaydın güncellenmesi) demektir."""
        return self.outcome is UpsertOutcome.UPDATED


# Hangi alanlar değişirse gerçek güncelleme sayılır
_TRACKED_FIELDS = ("name", "forename", "date_of_birth", "nationality", "arrest_warrant")


class NoticeService:
    """Persists Interpol notices to the database. Session factory is injected for testability."""

    def __init__(self, session_factory):
        """Dışarıdan session factory alır; böylece test ve prod farklı DB kullanabilir."""
        self.session_factory = session_factory

    def upsert(self, payload: dict) -> UpsertResult:
        """Insert or update a notice. Returns an UpsertResult describing what happened."""
        entity_id = payload.get("entity_id")

        if not entity_id:
            logger.warning("Missing entity_id, skipping: %s", payload)
            return UpsertResult(outcome=UpsertOutcome.SKIPPED)

        session: Session = self.session_factory()
        try:
            result = self._save_notice(session, entity_id, payload)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            logger.error("DB error (entity_id=%s): %s", entity_id, e)
            return UpsertResult(outcome=UpsertOutcome.ERROR, entity_id=entity_id, error=str(e))
        finally:
            session.close()

    def _save_notice(self, session: Session, entity_id: str, payload: dict) -> UpsertResult:
        """
        - DB'de yoksa → INSERT (is_updated=False)
        - DB'de varsa ve bir alan değiştiyse → UPDATE + is_updated=True (ALARM)
        - DB'de varsa ama hiçbir şey değişmediyse → is_updated=False (alarm temizlenir)
        """
        existing = session.query(Notice).filter(Notice.entity_id == entity_id).one_or_none()

        # ── YENİ KAYIT ──────────────────────────────────────────────────────────
        if existing is None:
            notice = Notice(
                entity_id=entity_id,
                name=payload.get("name"),
                forename=payload.get("forename"),
                date_of_birth=payload.get("date_of_birth"),
                nationality=payload.get("nationality"),
                all_nationalities=payload.get("all_nationalities"),
                arrest_warrant=payload.get("arrest_warrant"),
                photo_url=payload.get("photo_url"),
                is_updated=False,
            )
            session.add(notice)
            logger.info("Inserted: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id=entity_id)

        # ── MEVCUT KAYIT — gerçekten bir şey değişti mi? ────────────────────────
        changed = self._detect_changes(existing, payload)

        if not changed:
            # Hiçbir şey değişmedi → önceki alarm varsa temizle
            if existing.is_updated:
                existing.is_updated = False
                logger.info("Alarm cleared (no change): %s", entity_id)
            # photo_url DB'de boşsa ama payload'da varsa güncelle
            new_photo = payload.get("photo_url")
            if new_photo and not existing.photo_url:
                existing.photo_url = new_photo
                logger.info("Photo URL backfilled: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.UNCHANGED, entity_id=entity_id)

        # Gerçek değişiklik var → güncelle ve alarm ver
        existing.name              = payload.get("name")
        existing.forename          = payload.get("forename")
        existing.date_of_birth     = payload.get("date_of_birth")
        existing.nationality       = payload.get("nationality")
        existing.all_nationalities = payload.get("all_nationalities")
        existing.arrest_warrant    = payload.get("arrest_warrant")
        existing.is_updated        = True
        existing.updated_at        = datetime.now(timezone.utc).replace(tzinfo=None)

        if payload.get("photo_url"):
            existing.photo_url = payload.get("photo_url")

        logger.info("Updated (alarm) %s | changed: %s", entity_id, changed)
        return UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id=entity_id)

    def _detect_changes(self, existing: Notice, payload: dict) -> list[str]:
        """
        Takip edilen alanlarda fark var mı kontrol eder.
        None ve boş string'i eşit sayar (API tutarsızlıklarına karşı).
        Döner: değişen alan adları listesi — boşsa değişiklik yok demektir.
        """
        changed = []
        for field in _TRACKED_FIELDS:
            old = getattr(existing, field)
            new = payload.get(field)
            # Normalize: None ve "" aynı kabul edilir
            old_norm = old.strip() if isinstance(old, str) else old
            new_norm = new.strip() if isinstance(new, str) else new
            if old_norm != new_norm:
                changed.append(field)
        return changed