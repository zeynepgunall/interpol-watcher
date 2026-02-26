"""
config.py - Webserver ortam değişkenlerini yönetir.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Webserver konfigürasyonu."""

    # RabbitMQ
    RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
    RABBITMQ_PORT: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "admin")
    RABBITMQ_PASS: str = os.getenv("RABBITMQ_PASS", "admin123")
    QUEUE_NAME: str = os.getenv("QUEUE_NAME", "interpol_red_notices")

    # Flask
    FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "interpol-watcher-secret-2024")

    # Veritabanı
    DB_PATH: str = os.getenv("DB_PATH", "/app/data/interpol.db")
