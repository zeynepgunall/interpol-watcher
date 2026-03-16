"""Web uygulaması yapılandırması — tüm değerler ortam değişkenlerinden okunur."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class WebConfig:
    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_queue_name: str
    rabbitmq_user: str
    rabbitmq_password: str
    database_url: str
    interpol_base_url: str
    # Backfill
    detail_backfill_enabled: bool
    detail_backfill_batch_size: int
    detail_backfill_idle_seconds: float
    detail_request_delay_seconds: float
    # MinIO
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    minio_public_url: str

    @classmethod
    def from_env(cls) -> WebConfig:
        return cls(
            rabbitmq_host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            rabbitmq_port=int(os.getenv("RABBITMQ_PORT", "5672")),
            rabbitmq_queue_name=os.getenv("RABBITMQ_QUEUE_NAME", "interpol_red_notices"),
            rabbitmq_user=os.getenv("RABBITMQ_USER", "guest"),
            rabbitmq_password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/notices.db"),
            interpol_base_url=os.getenv("INTERPOL_BASE_URL", "https://ws-public.interpol.int"),
            detail_backfill_enabled=os.getenv("DETAIL_BACKFILL_ENABLED", "true").lower() == "true",
            detail_backfill_batch_size=int(os.getenv("DETAIL_BACKFILL_BATCH_SIZE", "25")),
            detail_backfill_idle_seconds=float(os.getenv("DETAIL_BACKFILL_IDLE_SECONDS", "30")),
            detail_request_delay_seconds=float(os.getenv("DETAIL_REQUEST_DELAY_SECONDS", "1.5")),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            minio_bucket=os.getenv("MINIO_BUCKET", "interpol-photos"),
            minio_secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
            minio_public_url=os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000"),
        )