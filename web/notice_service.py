"""Database persistence for Interpol red notices."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto

from sqlalchemy.orm import Session
from .models import Notice

logger = logging.getLogger(__name__)


class UpsertOutcome(Enum):
    INSERTED = auto()
    UPDATED  = auto()
    SKIPPED  = auto()
    ERROR    = auto()


@dataclass(frozen=True)
class UpsertResult:
    outcome: UpsertOutcome
    entity_id: str | None = None
    error: str | None = None

    @property
    def is_alarm(self) -> bool:
        return self.outcome is UpsertOutcome.UPDATED


class NoticeService:
    """Persists Interpol notices to the database. Session factory is injected for testability."""  

    def __init__(self, session_factory):
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
                thumbnail_url=payload.get("thumbnail_url"),
                is_updated=False,
            )
            session.add(notice)
            logger.info("Inserted: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id=entity_id)

        existing.name              = payload.get("name")
        existing.forename          = payload.get("forename")
        existing.date_of_birth     = payload.get("date_of_birth")
        existing.nationality       = payload.get("nationality")
        existing.all_nationalities = payload.get("all_nationalities")
        existing.arrest_warrant    = payload.get("arrest_warrant")
        existing.is_updated        = True
        existing.updated_at        = datetime.now(timezone.utc).replace(tzinfo=None)

        if payload.get("thumbnail_url"):
            existing.thumbnail_url = payload.get("thumbnail_url")

        logger.info("Updated (alarm): %s", entity_id)
        return UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id=entity_id)