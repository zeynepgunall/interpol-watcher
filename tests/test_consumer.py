"""
Unit tests for web/consumer.py — QueueConsumer._handle_message logic.

These tests exercise the INSERT / UPDATE / ignore paths without needing
a real RabbitMQ connection.  The QueueConsumer is instantiated with
__new__ so that __init__ (which tries to connect to RabbitMQ) is
intentionally bypassed; only _config and _SessionFactory are set.

Database: in-memory SQLite (configured via conftest.py).
"""

import json

import pytest

from web.config import WebConfig
from web.consumer import QueueConsumer
from web.models import Notice, create_session_factory


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_config() -> WebConfig:
    """Minimal WebConfig pointing at an in-memory SQLite database."""
    return WebConfig(
        rabbitmq_host="localhost",
        rabbitmq_port=5672,
        rabbitmq_queue_name="test_queue",
        rabbitmq_user="guest",
        rabbitmq_password="guest",
        database_url="sqlite:///:memory:",
    )


@pytest.fixture
def session_factory(mem_config: WebConfig):
    """SQLAlchemy session factory backed by an in-memory SQLite database."""
    return create_session_factory(mem_config)


@pytest.fixture
def consumer(mem_config: WebConfig, session_factory):
    """
    QueueConsumer with RabbitMQ bypassed.

    Uses __new__ to skip __init__ entirely, then manually assigns the two
    attributes that _handle_message relies on.
    """
    c = QueueConsumer.__new__(QueueConsumer)
    c._config = mem_config
    c._SessionFactory = session_factory
    return c


def _payload(**overrides) -> bytes:
    """Serialize a notice payload dict to JSON bytes."""
    base = {
        "entity_id": "2024/0001",
        "name": "DOE",
        "forename": "JOHN",
        "date_of_birth": "1985-01-01",
        "nationality": "US",
        "all_nationalities": "US,GB",
        "arrest_warrant": "Fraud",
    }
    base.update(overrides)
    return json.dumps(base).encode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_new_notice_is_inserted(consumer, session_factory):
    """First arrival of an entity_id must INSERT a new Notice row."""
    consumer._handle_message(_payload())

    session = session_factory()
    try:
        notice = (
            session.query(Notice)
            .filter(Notice.entity_id == "2024/0001")
            .one()
        )
        assert notice.name == "DOE"
        assert notice.forename == "JOHN"
        assert notice.nationality == "US"
        assert notice.is_updated is False
    finally:
        session.close()


def test_duplicate_notice_sets_is_updated(consumer, session_factory):
    """Re-arrival of an existing entity_id must set is_updated=True (ALARM)."""
    body = _payload()
    consumer._handle_message(body)   # first arrival → INSERT
    consumer._handle_message(body)   # second arrival → UPDATE + is_updated=True

    session = session_factory()
    try:
        notices = session.query(Notice).all()
        # Must still be exactly ONE row (no duplicate inserts)
        assert len(notices) == 1
        assert notices[0].is_updated is True
    finally:
        session.close()


def test_multiple_unique_notices_inserted(consumer, session_factory):
    """Each unique entity_id gets its own distinct row."""
    consumer._handle_message(_payload(entity_id="2024/0001", name="ALPHA"))
    consumer._handle_message(_payload(entity_id="2024/0002", name="BETA"))
    consumer._handle_message(_payload(entity_id="2024/0003", name="GAMMA"))

    session = session_factory()
    try:
        count = session.query(Notice).count()
        assert count == 3
    finally:
        session.close()


def test_message_without_entity_id_is_ignored(consumer, session_factory):
    """A malformed message with no entity_id must be silently discarded."""
    consumer._handle_message(json.dumps({"name": "NO_ENTITY_ID"}).encode())

    session = session_factory()
    try:
        assert session.query(Notice).count() == 0
    finally:
        session.close()


def test_updated_notice_fields_overwritten(consumer, session_factory):
    """On update, all payload fields must be written to the existing row."""
    consumer._handle_message(_payload(name="OLD_NAME", arrest_warrant="Old charge"))
    consumer._handle_message(_payload(name="NEW_NAME", arrest_warrant="New charge"))

    session = session_factory()
    try:
        notice = (
            session.query(Notice)
            .filter(Notice.entity_id == "2024/0001")
            .one()
        )
        assert notice.name == "NEW_NAME"
        assert notice.arrest_warrant == "New charge"
        assert notice.is_updated is True
    finally:
        session.close()
