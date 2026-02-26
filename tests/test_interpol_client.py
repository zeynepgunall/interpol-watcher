import httpx

from fetcher.interpol_client import InterpolClient, RedNotice


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

    captured = {}

    def fake_send(self, request):  # noqa: ANN001
        captured["url"] = str(request.url)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    client = InterpolClient("https://example.com")
    notices = client.fetch_red_notices()

    assert len(notices) == 1
    notice: RedNotice = notices[0]
    assert notice.entity_id == "123"
    assert notice.name == "DOE"
    assert notice.forename == "JOHN"
    assert notice.arrest_warrant == "Sample charge"
    assert captured["url"] == (
        "https://example.com/notices/v1/red?page=1&resultPerPage=20"
    )
