"""Interpol Red Notice kayıtlarının veritabanı persistance katmanı."""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable

import requests
from sqlalchemy.orm import Session

from shared.utils import utcnow_naive
from .models import Notice, NoticeChange
from .minio_storage import MinioStorage

logger = logging.getLogger(__name__)

_WARMUP_URLS = (
    "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
)
_DETAIL_RETRY_SLEEPS = (3.0, 7.0, 15.0)


class UpsertOutcome(Enum):
    INSERTED = auto()
    UPDATED = auto()
    UNCHANGED = auto()
    SKIPPED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class UpsertResult:
    outcome: UpsertOutcome
    entity_id: str | None = None
    error: str | None = None

    @property
    def is_alarm(self) -> bool:
        return self.outcome is UpsertOutcome.UPDATED


# Queue/payload üzerinden güncellenebilen alanlar.
_UPSERT_FIELDS = (
    "name",
    "forename",
    "date_of_birth",
    "nationality",
    "all_nationalities",
    "arrest_warrant",
    "photo_url",
    "charges",
    "charge_translation",
    "issuing_countries",
    "place_of_birth",
    "country_of_birth_id",
    "sex_id",
    "height",
    "weight",
    "eyes_colors_id",
    "hairs_id",
    "languages_spoken",
    "distinguishing_marks",
    "image_urls",
)

# Payload içindeki bu alanlardan herhangi biri değişirse alarm üret.
_TRACKED_FIELDS = _UPSERT_FIELDS

class NoticeService:
    def __init__(
        self,
        session_factory,
        interpol_base_url: str = "https://ws-public.interpol.int",
        minio: MinioStorage | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.interpol_base_url = interpol_base_url.rstrip("/")
        self._minio = minio
        self._session = requests.Session()
        self._warmed_up = False

    def upsert(self, payload: dict) -> UpsertResult:
        entity_id = payload.get("entity_id")
        if not entity_id:
            logger.warning("entity_id eksik, mesaj atlandı: %s", payload)
            return UpsertResult(outcome=UpsertOutcome.SKIPPED)

        session: Session = self.session_factory()
        try:
            result = self._save_notice(session, entity_id, payload)
            session.commit()
            if result.outcome in (
                UpsertOutcome.INSERTED,
                UpsertOutcome.UNCHANGED,
                UpsertOutcome.UPDATED,
            ):
                self._maybe_fetch_detail(session, entity_id)
            return result
        except Exception as e:
            session.rollback()
            logger.error("DB hatası (entity_id=%s): %s", entity_id, e)
            return UpsertResult(outcome=UpsertOutcome.ERROR, entity_id=entity_id, error=str(e))
        finally:
            session.close()

    def backfill_missing_details(self, limit: int = 25, request_delay_seconds: float = 1.0) -> int:
        entity_ids = self._get_missing_detail_entity_ids(limit)
        if not entity_ids:
            return 0

        filled = 0
        for index, entity_id in enumerate(entity_ids, start=1):
            session: Session = self.session_factory()
            try:
                self._maybe_fetch_detail(session, entity_id)
                notice = session.query(Notice).filter(Notice.entity_id == entity_id).one_or_none()
                if notice is not None and notice.detail_fetched_at is not None:
                    filled += 1
            except Exception as exc:
                session.rollback()
                logger.error("Backfill hatası (entity_id=%s): %s", entity_id, exc)
            finally:
                session.close()

            if request_delay_seconds > 0 and index < len(entity_ids):
                time.sleep(request_delay_seconds)

        logger.info("Detay backfill batch tamamlandı: %d/%d", filled, len(entity_ids))
        return filled

    def _get_missing_detail_entity_ids(self, limit: int) -> list[str]:
        session: Session = self.session_factory()
        try:
            rows: Iterable[tuple[str]] = (
                session.query(Notice.entity_id)
                .filter(Notice.detail_fetched_at.is_(None))
                .order_by(Notice.created_at.asc(), Notice.id.asc())
                .limit(limit)
                .all()
            )
            return [entity_id for (entity_id,) in rows]
        finally:
            session.close()

    def _save_notice(self, session: Session, entity_id: str, payload: dict) -> UpsertResult:
        existing = session.query(Notice).filter(Notice.entity_id == entity_id).one_or_none()

        if existing is None:
            notice_data = {"entity_id": entity_id, "is_updated": False}
            for field in _UPSERT_FIELDS:
                if field in payload:
                    notice_data[field] = self._coerce_payload_value(field, payload.get(field))
            notice = Notice(**notice_data)
            session.add(notice)
            logger.info("Yeni kayıt: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id=entity_id)

        changed = self._detect_changes(existing, payload)

        if not changed:
            if existing.is_updated:
                existing.is_updated = False
                logger.info("Alarm temizlendi (değişiklik yok): %s", entity_id)
            new_photo = payload.get("photo_url")
            if new_photo and not existing.photo_url:
                existing.photo_url = new_photo
                logger.info("Fotoğraf URL eklendi: %s", entity_id)
            return UpsertResult(outcome=UpsertOutcome.UNCHANGED, entity_id=entity_id)

        # Değişiklikleri notice_changes tablosuna kaydet
        for field in changed:
            old_val = getattr(existing, field)
            new_val = self._coerce_payload_value(field, payload.get(field))
            change = NoticeChange(
                entity_id=entity_id,
                field_name=field,
                old_value=self._stringify_change_value(old_val),
                new_value=self._stringify_change_value(new_val),
                changed_at=utcnow_naive(),
            )
            session.add(change)

        # Alanları güncelle
        for field in _UPSERT_FIELDS:
            if field in payload:
                setattr(existing, field, self._coerce_payload_value(field, payload.get(field)))
        existing.is_updated = True
        existing.updated_at = utcnow_naive()

        logger.info("Güncelleme (alarm) %s | değişen: %s", entity_id, changed)
        return UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id=entity_id)

    # ------------------------------------------------------------------
    # Detay çekme
    # ------------------------------------------------------------------

    def _maybe_fetch_detail(self, session: Session, entity_id: str) -> None:
        notice = session.query(Notice).filter(Notice.entity_id == entity_id).one_or_none()
        if notice is None or notice.detail_fetched_at is not None:
            return
        self._fetch_and_apply_detail(session, notice)
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Detay kaydedilemedi (entity_id=%s): %s", entity_id, e)

    def _fetch_and_apply_detail(self, session: Session, notice: Notice) -> None:
        entity_id = notice.entity_id
        url_id = entity_id.replace("/", "-")
        base = self.interpol_base_url

        detail = self._get_json(f"{base}/notices/v1/red/{url_id}")
        if not detail:
            return

        warrants = detail.get("arrest_warrants") or []
        charges = " | ".join(w["charge"] for w in warrants if w.get("charge"))
        issuing_countries = ",".join(w["issuing_country_id"] for w in warrants if w.get("issuing_country_id"))
        first_translation = next(
            (w["charge_translation"] for w in warrants if w.get("charge_translation")), None
        )

        images_data = self._get_json(f"{base}/notices/v1/red/{url_id}/images")
        image_urls: list[str] = []
        if images_data:
            for i, img in enumerate(images_data.get("_embedded", {}).get("images", [])):
                href = img.get("_links", {}).get("self", {}).get("href")
                if not href:
                    continue
                # MinIO varsa fotoğrafı indir ve yükle
                if self._minio and self._minio.enabled:
                    obj_name = entity_id.replace("/", "_") + (f"_{i}" if i > 0 else "") + ".jpg"
                    if not self._minio.object_exists(obj_name):
                        try:
                            resp = self._session.get(href, timeout=15, headers=self._image_headers())
                            if resp.status_code == 200 and len(resp.content) > 100:
                                self._minio.upload_bytes(obj_name, resp.content)
                                minio_url = f"{self._minio.public_url}/{self._minio.bucket}/{obj_name}"
                                image_urls.append(minio_url)
                                logger.debug("MinIO'ya yüklendi: %s", obj_name)
                            else:
                                image_urls.append(href)
                        except Exception as exc:
                            logger.warning("Fotoğraf indirilemedi (%s): %s", href, exc)
                            image_urls.append(href)
                    else:
                        minio_url = f"{self._minio.public_url}/{self._minio.bucket}/{obj_name}"
                        image_urls.append(minio_url)
                else:
                    image_urls.append(href)

        notice.charges               = charges or None
        notice.issuing_countries     = issuing_countries or None
        notice.charge_translation    = first_translation
        notice.place_of_birth        = detail.get("place_of_birth")
        notice.country_of_birth_id   = detail.get("country_of_birth_id")
        notice.sex_id                = detail.get("sex_id")
        notice.height                = detail.get("height")
        notice.weight                = detail.get("weight")
        notice.eyes_colors_id        = ",".join(detail.get("eyes_colors_id") or []) or None
        notice.hairs_id              = ",".join(detail.get("hairs_id") or []) or None
        notice.languages_spoken      = ",".join(detail.get("languages_spoken_ids") or []) or None
        notice.distinguishing_marks  = detail.get("distinguishing_marks")
        notice.image_urls            = json.dumps(image_urls)
        notice.detail_fetched_at     = utcnow_naive()

        logger.info("Detay cekildi: %s (%d fotograf)", entity_id, len(image_urls))

    def _get_json(self, url: str) -> dict | None:
        self._warmup()
        for attempt, sleep_seconds in enumerate((*_DETAIL_RETRY_SLEEPS, None), start=1):
            try:
                response = self._session.get(url, timeout=20, headers=self._json_headers())
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 403:
                    logger.warning("Detay API %s -> HTTP 403", url)
                    self._reset_session()
                else:
                    logger.warning("Detay API %s -> HTTP %s", url, response.status_code)
            except Exception as exc:
                logger.warning("Detay API istegi basarisiz %s: %s", url, exc)

            if sleep_seconds is None:
                break
            logger.info("Detay istegi tekrar denenecek: %s (deneme=%d, %.1fs sonra)", url, attempt, sleep_seconds)
            time.sleep(sleep_seconds)
        return None

    def _headers(self, *, json_response: bool = False) -> dict[str, str]:
        accept = "application/json" if json_response else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }

    def _json_headers(self) -> dict[str, str]:
        return {
            **self._headers(json_response=True),
            "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }

    def _image_headers(self) -> dict[str, str]:
        return {
            **self._headers(),
            "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Dest": "image",
        }

    def _warmup(self) -> None:
        if self._warmed_up:
            return
        time.sleep(random.uniform(1.0, 2.5))
        for warmup_url in _WARMUP_URLS:
            try:
                response = self._session.get(warmup_url, headers=self._headers(), timeout=20)
                logger.info("Detail warmup %s -> HTTP %s", warmup_url, response.status_code)
                if response.status_code == 200:
                    self._warmed_up = True
                    time.sleep(random.uniform(1.0, 2.5))
                    return
            except Exception as exc:
                logger.warning("Detail warmup basarisiz %s: %s", warmup_url, exc)
        self._warmed_up = True

    def _reset_session(self) -> None:
        self._session = requests.Session()
        self._warmed_up = False
        time.sleep(random.uniform(2.0, 4.0))
        self._warmup()

    @staticmethod
    def _detect_changes(existing: Notice, payload: dict) -> list[str]:
        changed = []
        for field in _TRACKED_FIELDS:
            if field not in payload:
                continue
            old = getattr(existing, field)
            new = NoticeService._coerce_payload_value(field, payload.get(field))
            old_norm = NoticeService._normalize_change_value(old)
            new_norm = NoticeService._normalize_change_value(new)
            if old_norm != new_norm:
                changed.append(field)
        return changed

    @staticmethod
    def _coerce_payload_value(field: str, value):
        if field == "image_urls" and value is not None and not isinstance(value, str):
            return json.dumps(value)
        return value

    @staticmethod
    def _normalize_change_value(value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple, dict)):
            return json.dumps(value, sort_keys=True, ensure_ascii=False)
        return value

    @staticmethod
    def _stringify_change_value(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
