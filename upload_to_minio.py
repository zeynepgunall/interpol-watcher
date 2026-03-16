"""
Mevcut fotoğrafları MinIO'ya toplu yükler.

Kullanım (container içinde):
    python /app/upload_to_minio.py

Ortam değişkenleri docker-compose.yml'den otomatik okunur.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY",  "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY",  "minioadmin")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",      "interpol-photos")
MINIO_SECURE     = os.getenv("MINIO_SECURE", "false").lower() == "true"

PHOTOS_DIR = Path("/data/photos")
_PROGRESS_INTERVAL = 100


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Bucket oluşturuldu: %s", bucket)

    policy = f'''{{
        "Version": "2012-10-17",
        "Statement": [{{
            "Effect": "Allow",
            "Principal": {{"AWS": ["*"]}},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::{bucket}/*"]
        }}]
    }}'''
    client.set_bucket_policy(bucket, policy)
    logger.info("Bucket public politikası ayarlandı: %s", bucket)


def upload_all() -> None:
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )
    ensure_bucket(client, MINIO_BUCKET)

    files = list(PHOTOS_DIR.glob("*.jpg"))
    total = len(files)
    logger.info("Yüklenecek toplam fotoğraf: %d", total)

    uploaded = 0
    skipped = 0
    failed = 0

    for i, photo_path in enumerate(files, 1):
        object_name = photo_path.name  # örn: 2025_102375.jpg

        # Zaten yüklüyse atla
        try:
            client.stat_object(MINIO_BUCKET, object_name)
            skipped += 1
            continue
        except S3Error:
            pass  # Yok, yükle

        try:
            client.fput_object(
                MINIO_BUCKET,
                object_name,
                str(photo_path),
                content_type="image/jpeg",
            )
            uploaded += 1
            if uploaded % _PROGRESS_INTERVAL == 0:
                logger.info("İlerleme: %d/%d yüklendi", uploaded, total - skipped)
        except Exception as exc:
            failed += 1
            logger.warning("Yükleme hatası (%s): %s", photo_path.name, exc)

    logger.info("=" * 50)
    logger.info(
        "TAMAMLANDI: toplam=%d, yüklenen=%d, atlanan=%d, başarısız=%d",
        total, uploaded, skipped, failed,
    )


if __name__ == "__main__":
    upload_all()