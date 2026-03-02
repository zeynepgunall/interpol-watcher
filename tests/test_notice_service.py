"""
Unit tests for web/notice_service.py — NoticeService upsert + alarm logic.

These tests exercise the service layer directly without involving RabbitMQ
or the Flask HTTP layer.  Uses an in-memory SQLite database (configured via
conftest.py).

Test matrix:
  - New entity_id                  → INSERTED, is_updated=False
  - Known entity_id re-arrival     → UPDATED, is_updated=True  (ALARM)
  - Missing entity_id in payload   → SKIPPED
  - Field overwrite on update      → latest values win
  - thumbnail_url only updated if  → present in new payload
  - UpsertResult.is_alarm property → True only on UPDATED
  - Multiple unique payloads       → one row each
"""

import pytest

from web.config import WebConfig
from web.models import Notice, create_session_factory
from web.notice_service import NoticeService, UpsertOutcome, UpsertResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session_factory():
    config = WebConfig(
        rabbitmq_host="localhost",
        rabbitmq_port=5672,
        rabbitmq_queue_name="test",
        rabbitmq_user="guest",
        rabbitmq_password="guest",
        database_url="sqlite:///:memory:",
    )
    return create_session_factory(config)


@pytest.fixture
def service(session_factory) -> NoticeService:
    return NoticeService(session_factory)


def _payload(**overrides) -> dict:
    base = {
        "entity_id": "2024/1111",
        "name": "DOE",
        "forename": "JOHN",
        "date_of_birth": "1985-01-01",
        "nationality": "US",
        "all_nationalities": "US,GB",
        "arrest_warrant": "Fraud",
        "thumbnail_url": "https://example.com/photo.jpg",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# INSERT path
# ---------------------------------------------------------------------------

def test_first_payload_returns_inserted(service):
    result = service.upsert(_payload())
    assert result.outcome is UpsertOutcome.INSERTED
    assert result.entity_id == "2024/1111"
    assert result.is_alarm is False


def test_insert_persists_all_fields(service, session_factory):
    service.upsert(_payload())
    session = session_factory()
    try:
        notice = session.query(Notice).filter(Notice.entity_id == "2024/1111").one()
        assert notice.name == "DOE"
        assert notice.forename == "JOHN"
        assert notice.nationality == "US"
        assert notice.all_nationalities == "US,GB"
        assert notice.arrest_warrant == "Fraud"
        assert notice.is_updated is False
    finally:
        session.close()


def test_multiple_unique_payloads_all_inserted(service, session_factory):
    service.upsert(_payload(entity_id="2024/0001", name="ALPHA"))
    service.upsert(_payload(entity_id="2024/0002", name="BETA"))
    service.upsert(_payload(entity_id="2024/0003", name="GAMMA"))

    session = session_factory()
    try:
        assert session.query(Notice).count() == 3
    finally:
        session.close()


# ---------------------------------------------------------------------------
# UPDATE / ALARM path
# ---------------------------------------------------------------------------

def test_second_arrival_returns_updated(service):
    service.upsert(_payload())
    result = service.upsert(_payload())
    assert result.outcome is UpsertOutcome.UPDATED
    assert result.is_alarm is True


def test_duplicate_produces_single_row(service, session_factory):
    service.upsert(_payload())
    service.upsert(_payload())

    session = session_factory()
    try:
        assert session.query(Notice).count() == 1
    finally:
        session.close()


def test_update_sets_is_updated_true(service, session_factory):
    service.upsert(_payload(name="OLD"))
    service.upsert(_payload(name="NEW"))

    session = session_factory()
    try:
        notice = session.query(Notice).filter(Notice.entity_id == "2024/1111").one()
        assert notice.is_updated is True
        assert notice.name == "NEW"
    finally:
        session.close()


def test_update_overwrites_all_fields(service, session_factory):
    service.upsert(_payload(name="OLD_NAME", arrest_warrant="Old charge"))
    service.upsert(_payload(name="NEW_NAME", arrest_warrant="New charge"))

    session = session_factory()
    try:
        notice = session.query(Notice).filter(Notice.entity_id == "2024/1111").one()
        assert notice.name == "NEW_NAME"
        assert notice.arrest_warrant == "New charge"
    finally:
        session.close()


def test_thumbnail_not_overwritten_if_absent_in_update(service, session_factory):
    """If the update payload has no thumbnail_url, the original value is kept."""
    service.upsert(_payload(thumbnail_url="https://original.com/photo.jpg"))

    payload_no_thumb = _payload()
    del payload_no_thumb["thumbnail_url"]
    service.upsert(payload_no_thumb)

    session = session_factory()
    try:
        notice = session.query(Notice).filter(Notice.entity_id == "2024/1111").one()
        assert notice.thumbnail_url == "https://original.com/photo.jpg"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SKIP path — malformed payloads
# ---------------------------------------------------------------------------

def test_missing_entity_id_returns_skipped(service):
    result = service.upsert({"name": "NO_ENTITY"})
    assert result.outcome is UpsertOutcome.SKIPPED
    assert result.entity_id is None


def test_missing_entity_id_writes_nothing(service, session_factory):
    service.upsert({"name": "NO_ENTITY"})
    session = session_factory()
    try:
        assert session.query(Notice).count() == 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# UpsertResult properties
# ---------------------------------------------------------------------------

def test_upsert_result_is_alarm_false_for_inserted():
    r = UpsertResult(outcome=UpsertOutcome.INSERTED, entity_id="x")
    assert r.is_alarm is False


def test_upsert_result_is_alarm_true_for_updated():
    r = UpsertResult(outcome=UpsertOutcome.UPDATED, entity_id="x")
    assert r.is_alarm is True


def test_upsert_result_is_alarm_false_for_skipped():
    r = UpsertResult(outcome=UpsertOutcome.SKIPPED)
    assert r.is_alarm is False
