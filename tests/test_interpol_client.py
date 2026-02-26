from fetcher.interpol_client import InterpolClient, RedNotice


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

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

    def fake_get(url, params=None, timeout=20):  # noqa: D401, ARG001
        return DummyResponse(payload)

    import requests

    monkeypatch.setattr(requests, "get", fake_get)

    client = InterpolClient("https://example.com")
    notices = client.fetch_red_notices()

    assert len(notices) == 1
    notice: RedNotice = notices[0]
    assert notice.entity_id == "123"
    assert notice.name == "DOE"
    assert notice.forename == "JOHN"
    assert notice.arrest_warrant == "Sample charge"

