"""RabbitMQ üzerinden gönderilen mesajın formatını standart hale getiriyor."""
from __future__ import annotations

import json

# Kuyruk mesajında yer alan alanlar
FIELDS: tuple[str, ...] = (
    "entity_id",
    "name",
    "forename",
    "date_of_birth",
    "nationality",
    "all_nationalities",
    "arrest_warrant",
    "photo_url",
)


def encode(data: dict) -> bytes:
    """Notice dict'ini UTF-8 JSON byte'larına serialize eder.Sonra rabbitmq'ya publish ediyor."""
    return json.dumps(data).encode("utf-8")


def decode(raw: bytes) -> dict:
    """UTF-8 JSON byte'larını notice dict'ine deserialize eder."""
    return json.loads(raw.decode("utf-8"))
