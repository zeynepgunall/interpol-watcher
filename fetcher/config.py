import os
from dataclasses import dataclass


@dataclass
class FetcherConfig:
    interpol_base_url: str
    fetch_interval_seconds: int
    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_queue_name: str
    rabbitmq_user: str
    rabbitmq_password: str

    @classmethod
    def from_env(cls) -> "FetcherConfig":
        return cls(
            interpol_base_url=os.getenv(
                "INTERPOL_BASE_URL", "https://ws-public.interpol.int"
            ),
            fetch_interval_seconds=int(
                os.getenv("INTERPOL_FETCH_INTERVAL_SECONDS", "300")
            ),
            rabbitmq_host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            rabbitmq_port=int(os.getenv("RABBITMQ_PORT", "5672")),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME", "interpol_red_notices"
            ),
            rabbitmq_user=os.getenv("RABBITMQ_USER", "guest"),
            rabbitmq_password=os.getenv("RABBITMQ_PASSWORD", "guest"),
        )

