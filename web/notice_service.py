"""
web/notice_service.py
---------------------
Service layer for Notice persistence.

Responsibilities:
  - Encapsulate the INSERT / UPDATE (upsert) logic for a single notice payload.
  - Own the alarm-detection rule: any re-arrival of a known entity_id is an alarm.
  - Return a typed result so callers (consumer, run_local, tests) can act on outcome
    without inspecting raw DB state.

This module has NO knowledge of RabbitMQ, HTTP, or Flask.
It only depends on the ORM model and a SQLAlchemy session factory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import Notice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class UpsertOutcome(Enum):
    INSERTED = auto()   # Brand-new entity_id → fresh row
    UPDATED = auto()    # Known entity_id → fields refreshed, alarm raised
    SKIPPED = auto()    # Malformed payload (no entity_id)
    ERROR = auto()      # DB or unexpected failure


@dataclass(frozen=True)
class UpsertResult:
    outcome: UpsertOutcome
    entity_id: str | None = None
    error: str | None = None

    @property
    def is_alarm(self) -> bool:
        return self.outcome is UpsertOutcome.UPDATED


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NoticeService:
    """
    Stateless service that persists notice payloads into the database.

    Depends on a SQLAlchemy session factory (injected via constructor) so it
    can be used in any context: RabbitMQ consumer thread, CLI scripts, tests.

    All public methods are idempotent: calling upsert() with the same payload
    twice produces exactly one DB row (the second call flips is_updated=True).
    """

    def __init__(self, session_factory) -> None:
        self._SessionFactory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, payload: Dict[str, Any]) -> UpsertResult:
        """
        Persist a single notice payload.

        Returns UpsertResult describing what happened.  Never raises —
        exceptions are caught, logged, and returned as UpsertOutcome.ERROR.
        """
        entity_id: str | None = payload.get("entity_id")
        if not entity_id:
            logger.warning("upsert called with payload missing entity_id: %s", payload)
            return UpsertResult(outcome=UpsertOutcome.SKIPPED)

        session: Session = self._SessionFactory()
        try:
            outcome = self._upsert_in_session(session, entity_id, payload)
            session.commit()
            return outcome
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("DB error while upserting %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.ERROR, entity_id=entity_id, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("Unexpected error while upserting %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.ERROR, entity_id=entity_id, error=str(exc))
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upsert_in_session(
        self, session: Session, entity_id: str, payload: Dict[str, Any]
    ) -> UpsertResult:
        """Core upsert — must be called inside an open session."""
        existing: Notice | None = (
            session.query(Notice)
            .filter(Notice.entity_id == entity_id)
            .one_or_none()
        )

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
            logger.info("INSERTED new notice %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id=entity_id)

        # Existing row — update all fields and raise alarm
        existing.name = payload.get("name")
        existing.forename = payload.get("forename")
        existing.date_of_birth = payload.get("date_of_birth")
        existing.nationality = payload.get("nationality")
        existing.all_nationalities = payload.get("all_nationalities")
        existing.arrest_warrant = payload.get("arrest_warrant")
        if payload.get("thumbnail_url"):
            existing.thumbnail_url = payload.get("thumbnail_url")
        existing.is_updated = True
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        logger.info("UPDATED notice %s → ALARM raised", entity_id)
        return UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id=entity_id)
