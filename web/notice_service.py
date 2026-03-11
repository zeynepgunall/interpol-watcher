"""Interpol Red Notice kayıtlarının veritabanı persistance katmanı."""
"""Gelen mesajın yeni kayıt mı, güncelleme mi, değişmemiş veri mi olduğu belirlenir."""
import logging
from dataclasses import dataclass
from enum import Enum, auto

from sqlalchemy.orm import Session

from shared.utils import utcnow_naive
from .models import Notice

logger = logging.getLogger(__name__)

#veritabanı yazma sonucunu standart hala getiriyor.böylece consumer tarafında kayıt yeni mi güncellendi mi kolayca anlaşılıyor
class UpsertOutcome(Enum): 
    INSERTED = auto()
    UPDATED = auto()
    UNCHANGED = auto()
    SKIPPED = auto()
    ERROR = auto()


@dataclass(frozen=True)
#işlemin sonucunu taşıyan veri yapısı.
class UpsertResult:
    outcome: UpsertOutcome
    entity_id: str | None = None
    error: str | None = None

    @property
    def is_alarm(self) -> bool:
        """UPDATED sonucu alarm anlamına gelir (mevcut kayıt güncellenir)."""
        return self.outcome is UpsertOutcome.UPDATED


# Değişiklik takibi yapılan alanlar — bu alanlardan biri değişirse alarm tetiklenir
_TRACKED_FIELDS = ("name", "forename", "date_of_birth", "nationality", "arrest_warrant")

# Toplu güncelleme yapılacak alanlar (tracked + ek alanlar)
_UPDATE_FIELDS = (*_TRACKED_FIELDS, "all_nationalities")


class NoticeService:
    """Notice kayıtlarını DB'ye ekler veya günceller. Consumer mesajı alıyor ama insert/update kararını ve change detection logic’ini burada yönetilir"""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def upsert(self, payload: dict) -> UpsertResult:
        """Kayıt yoksa ekler, varsa günceller. İşlem sonucunu UpsertResult olarak döndürür."""
        entity_id = payload.get("entity_id")
        if not entity_id:
            logger.warning("entity_id eksik, mesaj atlandı: %s", payload)
            return UpsertResult(outcome=UpsertOutcome.SKIPPED)

        session: Session = self.session_factory() #DB oturumu açılır
        try:
            result = self._save_notice(session, entity_id, payload)
            session.commit() #başarılıysa
            return result
        except Exception as e:
            session.rollback() #hata varsa 
            logger.error("DB hatası (entity_id=%s): %s", entity_id, e)
            return UpsertResult(outcome=UpsertOutcome.ERROR, entity_id=entity_id, error=str(e))
        finally:
            session.close() 

    def _save_notice(self, session: Session, entity_id: str, payload: dict) -> UpsertResult:
        """
        DB'de yoksa INSERT, varsa ve alan değiştiyse UPDATE (alarm), değişmediyse UNCHANGED.
        """
        existing = session.query(Notice).filter(Notice.entity_id == entity_id).one_or_none()

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
            logger.info("Yeni kayıt: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id=entity_id)

        changed = self._detect_changes(existing, payload) #kayıt varsa değişiklik var mı bak

        if not changed:
            if existing.is_updated:
                existing.is_updated = False
                logger.info("Alarm temizlendi (değişiklik yok): %s", entity_id)

            # photo_url boşsa ve yeni veri geliyorsa doldur
            new_photo = payload.get("photo_url")
            if new_photo and not existing.photo_url:
                existing.photo_url = new_photo
                logger.info("Fotoğraf URL eklendi: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.UNCHANGED, entity_id=entity_id)

        # Değişiklik varsa UPDATE+ALARM
        for field in _UPDATE_FIELDS:
            setattr(existing, field, payload.get(field))
        existing.is_updated = True
        existing.updated_at = utcnow_naive()

        if payload.get("photo_url"):
            existing.photo_url = payload["photo_url"]

        logger.info("Güncelleme (alarm) %s | değişen: %s", entity_id, changed)
        return UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id=entity_id)

    @staticmethod
    def _detect_changes(existing: Notice, payload: dict) -> list[str]:
        """
        Takip edilen alanlarda fark olup olmadığını kontrol eder.
        None ve boş string eşit sayılır (API tutarsızlıklarına karşı).
        """
        changed = []
        for field in _TRACKED_FIELDS:
            old = getattr(existing, field)
            new = payload.get(field)
            old_norm = old.strip() if isinstance(old, str) else old
            new_norm = new.strip() if isinstance(new, str) else new
            if old_norm != new_norm:
                changed.append(field)
        return changed
