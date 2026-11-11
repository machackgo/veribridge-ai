"""Privacy-conscious view tracking for the public VBR project report.

Records one row per recruiter open of ``/vbr/report/{token}`` into
``vbr_project_report_views`` (migration 060). Only coarse categories are
stored — never the referrer URL, IP address, or raw user-agent string.

Tracking is strictly best-effort: the caller (the public view endpoint)
treats *any* persistence failure as a no-op so analytics can never block or
break report access.

Because the endpoint is unauthenticated, inserts are capped per project per
UTC day (``settings.public_report_view_daily_cap``). The client-supplied
dedupe key is attacker-chosen, so it only collapses honest rerenders; the
daily cap is what bounds the table growth a token holder can cause.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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


def _utc_day_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_viewed_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _views_today(db: Any, project_id: str, day_start: datetime) -> int:
    """Rows already recorded for ``project_id`` since ``day_start`` (UTC)."""
    if isinstance(db, dict):
        count = 0
        for existing in db.setdefault(_VIEWS_TABLE, {}).values():
            if existing.get("project_id") != project_id:
                continue
            viewed_at = _parse_viewed_at(existing.get("viewed_at"))
            # Rows without a parseable timestamp count against the cap
            # (fail closed rather than let them escape it).
            if viewed_at is None or viewed_at >= day_start:
                count += 1
        return count

    result = (
        db.table(_VIEWS_TABLE)
        .select("id", count="exact")
        .eq("project_id", project_id)
        .gte("viewed_at", day_start.isoformat())
        .limit(1)
        .execute()
    )
    count = getattr(result, "count", None)
    if not isinstance(count, int):
        # Unknown count: fail closed so the cap can never be silently bypassed.
        raise RuntimeError("view count unavailable")
    return count


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
    deduplicated or the project's daily cap is reached. Persistence errors
    propagate — the endpoint catches them so tracking failures never surface
    to the recruiter.
    """
    cap = int(settings.public_report_view_daily_cap)
    if cap <= 0:
        return False
    row = {
        "id": str(uuid4()),
        "project_id": project_id,
        "source": normalize_view_source(source),
        "referrer_category": classify_referrer(referrer),
        "ua_class": classify_user_agent(user_agent),
        "dedupe_key": normalize_dedupe_key(dedupe_key),
    }
    day_start = _utc_day_start()

    if isinstance(db, dict):
        table = db.setdefault(_VIEWS_TABLE, {})
        if row["dedupe_key"] is not None and any(
            existing.get("project_id") == project_id
            and existing.get("dedupe_key") == row["dedupe_key"]
            for existing in table.values()
        ):
            return False
        if _views_today(db, project_id, day_start) >= cap:
            return False
        # Dict mode has no column default; mirror ``viewed_at default now()``.
        table[row["id"]] = {**row, "viewed_at": datetime.now(UTC).isoformat()}
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

    if _views_today(db, project_id, day_start) >= cap:
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
