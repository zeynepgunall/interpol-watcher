"""
test_webserver.py - Webserver bileşenlerinin birim testleri.

Çalıştırmak için:
    cd webserver
    pip install -r requirements.txt
    python -m pytest test_webserver.py -v
"""

import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database


class TestDatabase(unittest.TestCase):
    """Database sınıfının testleri."""

    def setUp(self):
        """Her test için geçici bir DB dosyası kullan."""
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db = Database(self.temp_file.name)

    def tearDown(self):
        """Test sonrası geçici dosyayı sil."""
        os.unlink(self.temp_file.name)

    def _sample_notice(self, entity_id="2020/12345"):
        return {
            "entity_id": entity_id,
            "name": "DOE",
            "forename": "JOHN",
            "date_of_birth": "1985/01/15",
            "nationalities": "US",
            "sex_id": "M",
            "thumbnail": ""
        }

    def test_save_new_notice(self):
        """Yeni kayıt 'created' döndürmeli."""
        result = self.db.save_or_update(self._sample_notice())
        self.assertEqual(result, "created")

    def test_update_existing_notice(self):
        """Aynı entity_id ile ikinci kayıt 'updated' döndürmeli."""
        self.db.save_or_update(self._sample_notice())
        result = self.db.save_or_update(self._sample_notice())
        self.assertEqual(result, "updated")

    def test_get_all_returns_saved_records(self):
        """Kaydedilen veriler get_all ile geri alınabilmeli."""
        self.db.save_or_update(self._sample_notice("001"))
        self.db.save_or_update(self._sample_notice("002"))
        records = self.db.get_all()
        self.assertEqual(len(records), 2)

    def test_get_all_empty_database(self):
        """Boş DB'de get_all boş liste dönmeli."""
        records = self.db.get_all()
        self.assertEqual(records, [])

    def test_get_stats_total(self):
        """get_stats toplam kayıt sayısını doğru vermeli."""
        self.db.save_or_update(self._sample_notice("A"))
        self.db.save_or_update(self._sample_notice("B"))
        stats = self.db.get_stats()
        self.assertEqual(stats["total"], 2)

    def test_save_without_entity_id(self):
        """entity_id olmayan kayıt 'error' döndürmeli."""
        result = self.db.save_or_update({"name": "TEST"})
        self.assertEqual(result, "error")

    def test_get_all_order(self):
        """Kayıtlar en yeniden en eskiye sıralı gelmeli."""
        import time
        self.db.save_or_update(self._sample_notice("FIRST"))
        time.sleep(0.01)
        self.db.save_or_update(self._sample_notice("SECOND"))
        records = self.db.get_all()
        # En yeni başta olmalı
        self.assertEqual(records[0]["entity_id"], "SECOND")

    def test_update_changes_value(self):
        """Güncelleme sonrası değer değişmiş olmalı."""
        self.db.save_or_update(self._sample_notice())
        updated = self._sample_notice()
        updated["nationalities"] = "FR"
        self.db.save_or_update(updated)

        records = self.db.get_all()
        self.assertEqual(records[0]["nationalities"], "FR")


class TestConfig(unittest.TestCase):
    """Webserver Config sınıfının testleri."""

    def test_flask_port_is_integer(self):
        from config import Config
        self.assertIsInstance(Config.FLASK_PORT, int)

    def test_rabbitmq_port_is_integer(self):
        from config import Config
        self.assertIsInstance(Config.RABBITMQ_PORT, int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
