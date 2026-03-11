"""Web uygulaması yapılandırması — tüm değerler ortam değişkenlerinden okunur."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class WebConfig:
    """Flask web sunucusu ve RabbitMQ bağlantı ayarları."""

    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_queue_name: str
    rabbitmq_user: str
    rabbitmq_password: str
    database_url: str

    @classmethod
    def from_env(cls) -> WebConfig:
        """Ortam değişkenlerinden yapılandırma oluşturur."""
        return cls(
            rabbitmq_host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            rabbitmq_port=int(os.getenv("RABBITMQ_PORT", "5672")),
            rabbitmq_queue_name=os.getenv("RABBITMQ_QUEUE_NAME", "interpol_red_notices"),
            rabbitmq_user=os.getenv("RABBITMQ_USER", "guest"),
            rabbitmq_password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///data/notices.db"),
        )
