"""
Unit tests for fetcher/interpol_client.py.

Covers:
- RedNotice.from_api_item: field mapping, nationality array handling, fallbacks
- ScanStateManager: pass state persistence and resume logic
- InterpolClient.fetch_red_notices: HTTP monkeypatched end-to-end parse
"""

import json
import os
import tempfile

import pytest

from fetcher.interpol_client import InterpolClient, RedNotice, ScanStateManager


# ---------------------------------------------------------------------------
# RedNotice.from_api_item
# ---------------------------------------------------------------------------

def test_from_api_item_basic_fields():
    """Standard item with all fields populated must be parsed correctly."""
    item = {
        "entity_id": "2023/9999",
        "name": "SMITH",
        "forename": "ALICE",
        "date_of_birth": "1990-06-15",
        "nationalities": ["GB", "DE"],
        "arrest_warrants": [{"charge": "Money laundering"}],
    }
    notice = RedNotice.from_api_item(item)

    assert notice.entity_id == "2023/9999"
    assert notice.name == "SMITH"
    assert notice.forename == "ALICE"
    assert notice.date_of_birth == "1990-06-15"
    assert notice.nationality == "GB"          # first element
    assert notice.all_nationalities == "GB,DE" # comma-joined
    assert notice.arrest_warrant == "Money laundering"


def test_from_api_item_single_nationality():
    """Single-element nationalities array must not append a trailing comma."""
    item = {
        "entity_id": "2023/0001",
        "nationalities": ["TR"],
        "arrest_warrants": [],
    }
    notice = RedNotice.from_api_item(item)
    assert notice.nationality == "TR"
    assert notice.all_nationalities == "TR"


def test_from_api_item_no_nationalities_falls_back_to_nationality_field():
    """When nationalities is absent, the scalar nationality field is used."""
    item = {
        "entity_id": "2023/0002",
        "nationality": "FR",
        "arrest_warrants": [],
    }
    notice = RedNotice.from_api_item(item)
    assert notice.nationality == "FR"


def test_from_api_item_no_arrest_warrant():
    """An empty arrest_warrants list must result in arrest_warrant=None."""
    item = {"entity_id": "2023/0003", "nationalities": [], "arrest_warrants": []}
    notice = RedNotice.from_api_item(item)
    assert notice.arrest_warrant is None


def test_from_api_item_missing_optional_fields_are_none():
    """Optional fields not in the payload must default to None."""
    notice = RedNotice.from_api_item({"entity_id": "2023/0004"})
    assert notice.name is None
    assert notice.forename is None
    assert notice.date_of_birth is None
    assert notice.arrest_warrant is None


# ---------------------------------------------------------------------------
# ScanStateManager
# ---------------------------------------------------------------------------

@pytest.fixture
def state_file(tmp_path) -> str:
    """Return a path to a temporary state file (not yet created)."""
    return str(tmp_path / "scan_state.json")


def test_new_state_has_no_completed_passes(state_file):
    """Freshly created ScanStateManager must have an empty completed list."""
    mgr = ScanStateManager(state_file)
    assert not mgr.is_pass_done("Pass13")
    assert mgr.get_resume_idx("Pass13") == 0


def test_mark_pass_done_persists(state_file):
    """Marking a pass done must be reflected in a newly loaded manager."""
    mgr = ScanStateManager(state_file)
    mgr.mark_pass_done("Pass13")

    # Re-load from disk
    mgr2 = ScanStateManager(state_file)
    assert mgr2.is_pass_done("Pass13")


def test_resume_idx_returns_saved_value(state_file):
    """mark_query_progress must allow the manager to resume at the saved index."""
    mgr = ScanStateManager(state_file)
    mgr.mark_query_progress("PassA", 42)

    mgr2 = ScanStateManager(state_file)
    assert mgr2.get_resume_idx("PassA") == 42


def test_resume_idx_wrong_pass_returns_zero(state_file):
    """get_resume_idx for a different pass than the saved one must return 0."""
    mgr = ScanStateManager(state_file)
    mgr.mark_query_progress("PassA", 10)
    assert mgr.get_resume_idx("PassB") == 0


def test_reset_clears_all_state(state_file):
    """reset() must erase all completed passes and progress counters."""
    mgr = ScanStateManager(state_file)
    mgr.mark_pass_done("Pass13")
    mgr.mark_query_progress("PassA", 5)
    mgr.reset()

    mgr2 = ScanStateManager(state_file)
    assert not mgr2.is_pass_done("Pass13")
    assert mgr2.get_resume_idx("PassA") == 0


def test_corrupt_state_file_starts_fresh(state_file):
    """A corrupted JSON state file must be silently ignored (fresh state)."""
    with open(state_file, "w") as f:
        f.write("NOT VALID JSON {{{{")

    mgr = ScanStateManager(state_file)
    assert not mgr.is_pass_done("Pass13")
    assert mgr.get_resume_idx("Pass13") == 0


# ---------------------------------------------------------------------------
# InterpolClient.fetch_red_notices (HTTP monkeypatched)
# ---------------------------------------------------------------------------

class DummyResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_red_notices_parses_items(monkeypatch):
    payload = {
        "_embedded": {
            "notices": [
                {
                    "entity_id": "123",
                    "name": "DOE",
                    "forename": "JOHN",
                    "date_of_birth": "1990-01-01",
                    "nationality": "US",
                    "arrest_warrants": [{"charge": "Sample charge"}],
                }
            ]
        }
    }

    def fake_get(self_session, url, params=None, timeout=20, **kwargs):  # noqa: ARG001
        return DummyResponse(payload)

    # InterpolClient uses requests.Session internally, so patch Session.get
    import requests
    monkeypatch.setattr(requests.Session, "get", fake_get)

    client = InterpolClient("https://example.com")
    # Skip warmup (also uses session.get against external URLs)
    client._warmed_up = True

    notices = client.fetch_red_notices()

    assert len(notices) == 1
    notice: RedNotice = notices[0]
    assert notice.entity_id == "123"
    assert notice.name == "DOE"
    assert notice.forename == "JOHN"
    assert notice.arrest_warrant == "Sample charge"

