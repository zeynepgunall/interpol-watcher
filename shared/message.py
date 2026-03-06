"""Canonical schema for the notice payload exchanged via RabbitMQ."""
from __future__ import annotations

import json

# Every field that travels through the queue; both publisher and consumer import this.
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
    """Serialize a notice dict to UTF-8 JSON bytes."""
    return json.dumps(data).encode("utf-8")


def decode(raw: bytes) -> dict:
    """Deserialize UTF-8 JSON bytes to a notice dict."""
    return json.loads(raw.decode("utf-8"))
