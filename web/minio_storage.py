"""MinIO object storage yardımcı modülü — fotoğraf yükleme ve URL üretme."""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from minio import Minio
    from minio.error import S3Error
    _MINIO_AVAILABLE = True
except ImportError:
    _MINIO_AVAILABLE = False
    logger.warning("minio paketi yüklü değil, MinIO devre dışı.")


class MinioStorage:
    """MinIO bağlantısını yönetir, fotoğraf yükler ve public URL döner."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "interpol-photos",
        secure: bool = False,
        public_url: Optional[str] = None,
    ) -> None:
        self.bucket = bucket
        self.public_url = (public_url or f"http://{endpoint}").rstrip("/")
        self._enabled = _MINIO_AVAILABLE and bool(endpoint and access_key and secret_key)

        if self._enabled:
            self._client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
            self._ensure_bucket()
        else:
            self._client = None

    def _ensure_bucket(self) -> None:
        """Bucket yoksa oluşturur ve public okuma politikası atar."""
        try:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
                logger.info("MinIO bucket oluşturuldu: %s", self.bucket)

            # Public okuma politikası
            policy = f'''{{
                "Version": "2012-10-17",
                "Statement": [{{
                    "Effect": "Allow",
                    "Principal": {{"AWS": ["*"]}},
                    "Action": ["s3:GetObject"],
                    "Resource": ["arn:aws:s3:::{self.bucket}/*"]
                }}]
            }}'''
            self._client.set_bucket_policy(self.bucket, policy)
        except Exception as exc:
            logger.error("MinIO bucket hatası: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def upload_bytes(self, object_name: str, data: bytes, content_type: str = "image/jpeg") -> bool:
        """Byte verisini MinIO'ya yükler. Başarılı ise True döner."""
        if not self._enabled:
            return False
        try:
            self._client.put_object(
                self.bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return True
        except S3Error as exc:
            logger.error("MinIO yükleme hatası (%s): %s", object_name, exc)
            return False

    def upload_file(self, object_name: str, file_path: str, content_type: str = "image/jpeg") -> bool:
        """Dosyayı MinIO'ya yükler."""
        if not self._enabled:
            return False
        try:
            self._client.fput_object(self.bucket, object_name, file_path, content_type=content_type)
            return True
        except S3Error as exc:
            logger.error("MinIO dosya yükleme hatası (%s): %s", object_name, exc)
            return False

    def object_exists(self, object_name: str) -> bool:
        """Nesne MinIO'da var mı kontrol eder."""
        if not self._enabled:
            return False
        try:
            self._client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False

    def public_photo_url(self, entity_id: str) -> str:
        """entity_id için MinIO public URL döner."""
        object_name = entity_id.replace("/", "_") + ".jpg"
        return f"{self.public_url}/{self.bucket}/{object_name}"

    def object_name_for(self, entity_id: str) -> str:
        """entity_id için MinIO nesne adı döner."""
        return entity_id.replace("/", "_") + ".jpg"