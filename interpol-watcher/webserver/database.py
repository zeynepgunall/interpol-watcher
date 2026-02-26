"""
database.py - SQLite veritabanı işlemlerini yönetir.
Kişi kayıtlarını saklar, günceller ve sorgular.
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class Database:
    """
    SQLite veritabanı yönetim sınıfı.
    
    Attributes:
        db_path (str): Veritabanı dosyasının yolu
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize()

    def _get_connection(self) -> sqlite3.Connection:
        """Her işlem için yeni bir bağlantı döner (thread-safe)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Sonuçları dict gibi kullanmak için
        return conn

    def _initialize(self):
        """Tablo yoksa oluşturur."""
        sql = """
        CREATE TABLE IF NOT EXISTS notices (
            entity_id     TEXT PRIMARY KEY,
            name          TEXT,
            forename      TEXT,
            date_of_birth TEXT,
            nationalities TEXT,
            sex_id        TEXT,
            thumbnail     TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        """
        with self._get_connection() as conn:
            conn.execute(sql)
            conn.commit()
        logger.info(f"Veritabanı hazır: {self.db_path}")

    def save_or_update(self, notice: Dict[str, Any]) -> str:
        """
        Kaydı veritabanına ekler veya günceller.
        
        Args:
            notice: Kaydedilecek kişi verisi
            
        Returns:
            str: 'created' yeni kayıt, 'updated' güncelleme, 'error' hata
        """
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entity_id = notice.get("entity_id")

        if not entity_id:
            logger.warning("entity_id boş, kayıt atlandı.")
            return "error"

        try:
            with self._get_connection() as conn:
                # Kayıt var mı?
                existing = conn.execute(
                    "SELECT entity_id FROM notices WHERE entity_id = ?",
                    (entity_id,)
                ).fetchone()

                if existing:
                    # Güncelle
                    conn.execute("""
                        UPDATE notices SET
                            name = ?, forename = ?, date_of_birth = ?,
                            nationalities = ?, sex_id = ?, thumbnail = ?,
                            updated_at = ?
                        WHERE entity_id = ?
                    """, (
                        notice.get("name", ""),
                        notice.get("forename", ""),
                        notice.get("date_of_birth", ""),
                        notice.get("nationalities", ""),
                        notice.get("sex_id", ""),
                        notice.get("thumbnail", ""),
                        now,
                        entity_id
                    ))
                    conn.commit()
                    logger.info(f"Kayıt güncellendi: {entity_id}")
                    return "updated"
                else:
                    # Yeni kayıt ekle
                    conn.execute("""
                        INSERT INTO notices
                            (entity_id, name, forename, date_of_birth,
                             nationalities, sex_id, thumbnail, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entity_id,
                        notice.get("name", ""),
                        notice.get("forename", ""),
                        notice.get("date_of_birth", ""),
                        notice.get("nationalities", ""),
                        notice.get("sex_id", ""),
                        notice.get("thumbnail", ""),
                        now,
                        now
                    ))
                    conn.commit()
                    logger.info(f"Yeni kayıt eklendi: {entity_id}")
                    return "created"

        except sqlite3.Error as e:
            logger.error(f"Veritabanı hatası: {e}")
            return "error"

    def get_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Tüm kayıtları en yeniden en eskiye doğru getirir.
        
        Args:
            limit: Maksimum kayıt sayısı
            
        Returns:
            List[Dict]: Kayıt listesi
        """
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM notices ORDER BY updated_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Veri okuma hatası: {e}")
            return []

    def get_stats(self) -> Dict[str, int]:
        """Toplam kayıt sayısı gibi istatistikleri döner."""
        try:
            with self._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
                return {"total": total}
        except sqlite3.Error as e:
            logger.error(f"İstatistik hatası: {e}")
            return {"total": 0}
