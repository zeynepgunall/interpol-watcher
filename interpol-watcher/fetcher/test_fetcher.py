"""
test_fetcher.py - Fetcher bileşenlerinin birim testleri.

Çalıştırmak için:
    cd fetcher
    pip install -r requirements.txt
    python -m pytest test_fetcher.py -v
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# test için path'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interpol_client import InterpolClient


class TestInterpolClient(unittest.TestCase):
    """InterpolClient sınıfının testleri."""

    def setUp(self):
        """Her test öncesi çalışır."""
        self.client = InterpolClient(
            api_url="https://ws-public.interpol.int/notices/v1/red",
            page=1,
            result_per_page=5
        )

    def test_parse_notice_full_data(self):
        """Tam veri ile parse_notice doğru çalışmalı."""
        raw = {
            "entity_id": "2020/12345",
            "name": "DOE",
            "forename": "JOHN",
            "date_of_birth": "1985/01/15",
            "nationalities": ["US", "GB"],
            "sex_id": "M",
            "_links": {
                "thumbnail": {"href": "https://example.com/photo.jpg"}
            }
        }
        result = self.client.parse_notice(raw)

        self.assertEqual(result["entity_id"], "2020/12345")
        self.assertEqual(result["name"], "DOE")
        self.assertEqual(result["forename"], "JOHN")
        self.assertEqual(result["nationalities"], "US, GB")
        self.assertEqual(result["sex_id"], "M")
        self.assertEqual(result["thumbnail"], "https://example.com/photo.jpg")

    def test_parse_notice_missing_fields(self):
        """Eksik alanlar varsayılan değerle doldurulmalı."""
        raw = {"entity_id": "2020/99999"}
        result = self.client.parse_notice(raw)

        self.assertEqual(result["entity_id"], "2020/99999")
        self.assertEqual(result["name"], "")
        self.assertEqual(result["forename"], "")
        self.assertEqual(result["nationalities"], "")

    def test_parse_notice_entity_id_from_link(self):
        """entity_id yoksa link'ten çıkarılmalı."""
        raw = {
            "_links": {
                "self": {"href": "https://api.interpol.int/notices/v1/red/2020/12345"},
                "thumbnail": {"href": ""}
            }
        }
        result = self.client.parse_notice(raw)
        self.assertEqual(result["entity_id"], "12345")

    def test_parse_notice_empty_nationalities(self):
        """Boş uyruk listesi boş string olmalı."""
        raw = {"entity_id": "X", "nationalities": []}
        result = self.client.parse_notice(raw)
        self.assertEqual(result["nationalities"], "")

    @patch("requests.Session.get")
    def test_fetch_returns_notices_on_success(self, mock_get):
        """Başarılı API yanıtında notice listesi dönmeli."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "_embedded": {
                "notices": [
                    {"entity_id": "A1", "name": "TEST"}
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.client.fetch_red_notices()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["entity_id"], "A1")

    @patch("requests.Session.get")
    def test_fetch_returns_empty_on_network_error(self, mock_get):
        """Ağ hatasında boş liste dönmeli, exception fırlatmamalı."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Test hatası")

        result = self.client.fetch_red_notices()
        self.assertEqual(result, [])


class TestConfig(unittest.TestCase):
    """Config sınıfının testleri."""

    def test_default_values(self):
        """Varsayılan değerler doğru olmalı."""
        from config import Config
        self.assertIn("interpol.int", Config.INTERPOL_API_URL)
        self.assertEqual(Config.INTERPOL_PAGE, 1)
        self.assertGreater(Config.FETCH_INTERVAL, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
