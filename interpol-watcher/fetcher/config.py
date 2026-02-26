"""
config.py - Ortam değişkenlerini yönetir.
Tüm ayarlar .env dosyasından veya sistem ortam değişkenlerinden okunur.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Uygulama konfigürasyonu - tüm değerler environment'tan alınır."""

    # Interpol API
    INTERPOL_API_URL: str = os.getenv(
        "INTERPOL_API_URL",
        "https://ws-public.interpol.int/notices/v1/red"
    )
    INTERPOL_PAGE: int = int(os.getenv("INTERPOL_PAGE", "1"))
    INTERPOL_RESULT_PER_PAGE: int = int(os.getenv("INTERPOL_RESULT_PER_PAGE", "20"))

    # Fetch aralığı (saniye)
    FETCH_INTERVAL: int = int(os.getenv("FETCH_INTERVAL", "60"))

    # RabbitMQ bağlantı bilgileri
    RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
    RABBITMQ_PORT: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "admin")
    RABBITMQ_PASS: str = os.getenv("RABBITMQ_PASS", "admin123")
    QUEUE_NAME: str = os.getenv("QUEUE_NAME", "interpol_red_notices")
