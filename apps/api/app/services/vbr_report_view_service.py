"""Privacy-conscious view tracking for the public VBR project report.

Records one row per recruiter open of ``/vbr/report/{token}`` into
``vbr_project_report_views`` (migration 060). Only coarse categories are
stored — never the referrer URL, IP address, or raw user-agent string.

Tracking is strictly best-effort: the caller (the public view endpoint)
treats *any* persistence failure as a no-op so analytics can never block or
break report access.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.config import settings

_VIEWS_TABLE = "vbr_project_report_views"

_ALLOWED_SOURCES = {"direct", "recruiter_open", "recruiter_scan"}
_DEDUPE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

_MOBILE_UA_MARKERS = ("mobile", "android", "iphone", "ipad", "ipod")
_BOT_UA_MARKERS = ("bot", "crawler", "spider", "curl/", "wget/", "python-requests")


def normalize_view_source(source: Any) -> str:
    """Collapse the client-declared arrival source onto the closed enum."""
    if isinstance(source, str) and source.strip().lower() in _ALLOWED_SOURCES:
        return source.strip().lower()
    return "unknown"


def normalize_dedupe_key(key: Any) -> str | None:
    """Accept only an opaque URL-safe key; anything else is treated as absent."""
    if isinstance(key, str) and _DEDUPE_KEY_RE.match(key):
        return key
    return None


def classify_referrer(referrer: Any) -> str:
    """Coarse referrer category: internal app origin, external, or none."""
    if not isinstance(referrer, str) or not referrer.strip():
        return "none"
    try:
        parts = urlsplit(referrer.strip())
    except ValueError:
        return "external"
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "external"
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    known = {o.strip().lower().rstrip("/") for o in settings.cors_origins if o.strip()}
    known.add(settings.frontend_url.strip().lower().rstrip("/"))
    known.add(settings.public_app_url.strip().lower().rstrip("/"))
    return "internal" if origin in known else "external"


def classify_user_agent(user_agent: Any) -> str:
    """Coarse device class from the User-Agent header; the raw string is dropped."""
    if not isinstance(user_agent, str) or not user_agent.strip():
        return "unknown"
    lowered = user_agent.lower()
    if any(marker in lowered for marker in _BOT_UA_MARKERS):
        return "bot"
    if any(marker in lowered for marker in _MOBILE_UA_MARKERS):
        return "mobile"
    return "desktop"


def record_public_report_view(
    db: Any,
    project_id: str,
    *,
    source: Any = None,
    dedupe_key: Any = None,
    referrer: Any = None,
    user_agent: Any = None,
) -> bool:
    """Insert one view event for an already-resolved published project.

    Returns True when a new row was recorded, False when the event was
    deduplicated. Persistence errors propagate — the endpoint catches them so
    tracking failures never surface to the recruiter.
    """
    row = {
        "id": str(uuid4()),
        "project_id": project_id,
        "source": normalize_view_source(source),
        "referrer_category": classify_referrer(referrer),
        "ua_class": classify_user_agent(user_agent),
        "dedupe_key": normalize_dedupe_key(dedupe_key),
    }

    if isinstance(db, dict):
        table = db.setdefault(_VIEWS_TABLE, {})
        if row["dedupe_key"] is not None and any(
            existing.get("project_id") == project_id
            and existing.get("dedupe_key") == row["dedupe_key"]
            for existing in table.values()
        ):
            return False
        table[row["id"]] = row
        return True

    if row["dedupe_key"] is not None:
        existing = (
            db.table(_VIEWS_TABLE)
            .select("id")
            .eq("project_id", project_id)
            .eq("dedupe_key", row["dedupe_key"])
            .limit(1)
            .execute()
        )
        if getattr(existing, "data", []) or []:
            return False

    db.table(_VIEWS_TABLE).insert(row).execute()
    return True


__all__ = [
    "classify_referrer",
    "classify_user_agent",
    "normalize_dedupe_key",
    "normalize_view_source",
    "record_public_report_view",
]
