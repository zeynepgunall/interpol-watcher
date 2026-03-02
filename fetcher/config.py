import os
from dataclasses import dataclass


def _bool_env(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "y"}


def _csv_env(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default).strip()
    return [v.strip().upper() for v in raw.split(",") if v.strip()]


@dataclass
class FetcherConfig:
    interpol_base_url: str
    fetch_interval_seconds: int
    use_mock_data: bool
    fetch_all: bool
    fetch_extended: bool
    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_queue_name: str
    rabbitmq_user: str
    rabbitmq_password: str

    enable_pass_age_0_9: bool
    enable_pass_in_pk_1yr: bool
    very_high_nationalities_1yr: list[str]
    age_1yr_min: int
    age_1yr_max: int
    request_delay_seconds: float
    state_file_path: str

    @classmethod
    def from_env(cls) -> "FetcherConfig":
        return cls(
            interpol_base_url=os.getenv("INTERPOL_BASE_URL", "https://ws-public.interpol.int"),
            fetch_interval_seconds=int(os.getenv("INTERPOL_FETCH_INTERVAL_SECONDS", "300")),
            use_mock_data=_bool_env("INTERPOL_USE_MOCK_DATA", "false"),
            fetch_all=_bool_env("INTERPOL_FETCH_ALL", "true"),
            fetch_extended=_bool_env("INTERPOL_FETCH_EXTENDED", "false"),
            rabbitmq_host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            rabbitmq_port=int(os.getenv("RABBITMQ_PORT", "5672")),
            rabbitmq_queue_name=os.getenv("RABBITMQ_QUEUE_NAME", "interpol_red_notices"),
            rabbitmq_user=os.getenv("RABBITMQ_USER", "guest"),
            rabbitmq_password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            enable_pass_age_0_9=_bool_env("ENABLE_PASS_AGE_0_9", "true"),
            enable_pass_in_pk_1yr=_bool_env("ENABLE_PASS_IN_PK_1YR", "true"),
            very_high_nationalities_1yr=_csv_env("VERY_HIGH_NATIONALITIES_1YR", "IN,PK"),
            age_1yr_min=int(os.getenv("AGE_1YR_MIN", "10")),
            age_1yr_max=int(os.getenv("AGE_1YR_MAX", "99")),
            request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "1.5")),
            state_file_path=os.getenv("STATE_FILE_PATH", "/data/scan_state.json"),
        )

