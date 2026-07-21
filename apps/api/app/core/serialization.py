"""JSON-safe coercion for Supabase/PostgREST write payloads.

supabase-py sends request bodies through httpx, which calls ``json.dumps()``
without a custom encoder. Raw ``datetime`` / ``date`` / ``UUID`` / ``Decimal``
values in an ``insert``/``upsert``/``update`` payload therefore raise
``TypeError: Object of type datetime is not JSON serializable`` and surface as a
500 to the caller.

Apply :func:`make_json_safe` to any row dict immediately before it is handed to
the Supabase client so every write path is protected uniformly.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def make_json_safe(value: Any) -> Any:
    """Recursively convert non-JSON-serializable values to safe primitives.

    - ``datetime`` / ``date`` -> ISO-8601 string
    - ``UUID`` -> ``str``
    - ``Decimal`` -> ``float``
    - ``dict`` / ``list`` / ``tuple`` -> recursively sanitised

    All other values pass through unchanged.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    return value
