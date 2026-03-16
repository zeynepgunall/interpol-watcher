"""
Mevcut notice kayıtlarındaki image_urls'leri Interpol'den indirip MinIO'ya yükler
ve DB'deki image_urls kolonunu MinIO URL'leriyle günceller.

Kullanım (container içinde):
    python /app/migrate_images_to_minio.py

Ortam değişkenleri docker-compose.yml'den otomatik okunur.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time

import psycopg2
import requests
from minio import Minio
from minio.error import S3Error
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# DB
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "interpol_db")
DB_USER = os.getenv("DB_USER", "interpol")
DB_PASS = os.getenv("DB_PASS", "interpol123")

# MinIO
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY",  "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY",  "minioadmin")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",      "interpol-photos")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL",  "http://localhost:9000")
MINIO_SECURE     = os.getenv("MINIO_SECURE", "false").lower() == "true"

_REQUEST_DELAY   = 1.2
_CONSECUTIVE_403_LIMIT = 5
_BAN_PAUSE_SECONDS = 300
_PROGRESS_INTERVAL = 100

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Dest": "image",
}


def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASS,
    )


def get_notices_with_interpol_images(conn) -> list[tuple[str, str]]:
    """image_urls içinde Interpol URL'i olan kayıtları çeker."""
    cur = conn.cursor()
    cur.execute("""
        SELECT entity_id, image_urls
        FROM notices
        WHERE image_urls IS NOT NULL
          AND image_urls != '[]'
          AND image_urls LIKE '%interpol.int%'
    """)
    rows = cur.fetchall()
    cur.close()
    logger.info("Interpol URL'i olan %d kayıt bulundu", len(rows))
    return rows


def update_image_urls(conn, entity_id: str, new_urls: list[str]) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE notices SET image_urls = %s WHERE entity_id = %s",
        (json.dumps(new_urls), entity_id)
    )
    conn.commit()
    cur.close()


def ensure_bucket(client: Minio) -> None:
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
        logger.info("Bucket oluşturuldu: %s", MINIO_BUCKET)
    policy = f'''{{
        "Version": "2012-10-17",
        "Statement": [{{
            "Effect": "Allow",
            "Principal": {{"AWS": ["*"]}},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::{MINIO_BUCKET}/*"]
        }}]
    }}'''
    client.set_bucket_policy(MINIO_BUCKET, policy)


def migrate():
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )
    ensure_bucket(minio_client)

    conn = get_db_conn()
    rows = get_notices_with_interpol_images(conn)
    total = len(rows)

    session = requests.Session()
    session.headers.update(_HEADERS)

    # Warmup
    try:
        session.get("https://www.interpol.int/", timeout=15)
        time.sleep(random.uniform(2.0, 4.0))
        logger.info("Warmup tamamlandı")
    except Exception as e:
        logger.warning("Warmup hatası: %s", e)

    uploaded = 0
    skipped = 0
    failed = 0
    consecutive_403 = 0

    for i, (entity_id, image_urls_json) in enumerate(rows, 1):
        try:
            urls = json.loads(image_urls_json)
        except Exception:
            continue

        new_urls = []
        changed = False

        for idx, url in enumerate(urls):
            # Zaten MinIO URL'i ise atla
            if MINIO_ENDPOINT.split(":")[0] in url or "localhost:9000" in url or "minio" in url:
                new_urls.append(url)
                skipped += 1
                continue

            # Object adı: 2025_102375.jpg veya 2025_102375_1.jpg
            obj_name = entity_id.replace("/", "_") + (f"_{idx}" if idx > 0 else "") + ".jpg"

            # MinIO'da zaten varsa URL'i güncelle
            try:
                minio_client.stat_object(MINIO_BUCKET, obj_name)
                minio_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{obj_name}"
                new_urls.append(minio_url)
                skipped += 1
                changed = True
                continue
            except S3Error:
                pass

            # İndir ve yükle
            try:
                resp = session.get(url, timeout=15)

                if resp.status_code == 200 and len(resp.content) > 100:
                    minio_client.put_object(
                        MINIO_BUCKET, obj_name,
                        BytesIO(resp.content), len(resp.content),
                        content_type="image/jpeg"
                    )
                    minio_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{obj_name}"
                    new_urls.append(minio_url)
                    uploaded += 1
                    consecutive_403 = 0
                    changed = True

                elif resp.status_code == 403:
                    consecutive_403 += 1
                    new_urls.append(url)  # Orijinal URL'i koru
                    failed += 1
                    logger.warning("[%d/%d] 403 — %s (ardışık: %d)", i, total, entity_id, consecutive_403)

                    if consecutive_403 >= _CONSECUTIVE_403_LIMIT:
                        logger.warning("%d ardışık 403 — %d dk bekleniyor...", _CONSECUTIVE_403_LIMIT, _BAN_PAUSE_SECONDS // 60)
                        time.sleep(_BAN_PAUSE_SECONDS)
                        consecutive_403 = 0
                        session = requests.Session()
                        session.headers.update(_HEADERS)
                        session.get("https://www.interpol.int/", timeout=15)
                        time.sleep(random.uniform(3.0, 6.0))
                else:
                    new_urls.append(url)
                    failed += 1

            except Exception as e:
                new_urls.append(url)
                failed += 1
                logger.warning("Hata (%s, %s): %s", entity_id, obj_name, e)

            time.sleep(_REQUEST_DELAY + random.uniform(0.2, 0.6))

        # DB'yi güncelle
        if changed and new_urls:
            update_image_urls(conn, entity_id, new_urls)

        if (i % _PROGRESS_INTERVAL == 0):
            logger.info("İlerleme: %d/%d kayıt işlendi | yüklenen=%d atlanan=%d başarısız=%d",
                        i, total, uploaded, skipped, failed)

    conn.close()
    logger.info("=" * 60)
    logger.info("TAMAMLANDI: toplam=%d | yüklenen=%d | atlanan=%d | başarısız=%d",
                total, uploaded, skipped, failed)


if __name__ == "__main__":
    migrate()