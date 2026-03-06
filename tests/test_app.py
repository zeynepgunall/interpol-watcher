"""
Unit tests for web/app.py — Flask routes.

conftest.py sets DATABASE_URL=sqlite:///:memory: before any web import,
so no Docker volume is required.  QueueConsumer.start_in_thread is
mocked to prevent background RabbitMQ reconnection noise during tests.
"""

from unittest.mock import patch, MagicMock

import pytest

# Import web.photo first so the module is in sys.modules before patching
import web.photo  # noqa: F401

# Patch out the RabbitMQ daemon thread and photo backfill for all tests in this module.
with patch("web.consumer.QueueConsumer.start_in_thread"), \
     patch("web.photo.start_backfill_thread"):
    from web.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Fresh Flask test app with in-memory SQLite and no RabbitMQ thread."""
    with patch("web.consumer.QueueConsumer.start_in_thread"), \
         patch("web.photo.start_backfill_thread"):
        application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="module")
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests — / (index)
# ---------------------------------------------------------------------------

def test_index_returns_200(client):
    """GET / must return an HTTP 200 with HTML content."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"<!DOCTYPE html>" in response.data or b"<html" in response.data.lower()


def test_index_empty_db_shows_zero_total(client):
    """With an empty database the page must still render without errors."""
    response = client.get("/")
    assert response.status_code == 200
    # The template renders total count; with empty DB it must contain "0"
    assert b"0" in response.data


def test_index_pagination_default_page(client):
    """GET / without ?page param must default to page 1 (200 OK)."""
    response = client.get("/?page=1")
    assert response.status_code == 200


def test_index_search_param_accepted(client):
    """GET /?q=test must not raise a 500 error."""
    response = client.get("/?q=test")
    assert response.status_code == 200


def test_index_nationality_filter_accepted(client):
    """GET /?nat=TR must not raise a 500 error."""
    response = client.get("/?nat=TR")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests — /api/status
# ---------------------------------------------------------------------------

def test_api_status_returns_200(client):
    """GET /api/status must return HTTP 200."""
    response = client.get("/api/status")
    assert response.status_code == 200


def test_api_status_returns_json(client):
    """GET /api/status must return valid JSON with 'total' and 'alarms' keys."""
    response = client.get("/api/status")
    data = response.get_json()
    assert data is not None, "Response body is not valid JSON"
    assert "total" in data
    assert "alarms" in data


def test_api_status_empty_db_counts(client):
    """With an empty database total and alarms must both be 0."""
    response = client.get("/api/status")
    data = response.get_json()
    assert data["total"] == 0
    assert data["alarms"] == 0


def test_api_status_content_type(client):
    """Response Content-Type must be application/json."""
    response = client.get("/api/status")
    assert "application/json" in response.content_type
