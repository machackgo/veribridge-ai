"""Privacy-conscious view tracking for the public Work Passport page.

Records one row per open of ``/p/{public_slug}`` into ``vbr_passport_views``
(migration 065), mirroring the public report tracker
(:mod:`app.services.vbr_report_view_service` / migration 060). Only coarse
categories are stored — never the referrer URL, IP address, or raw
user-agent string. ``recruiter_user_id`` is set only when the viewer
presented a valid Supabase session; anonymous views stay anonymous.

Tracking is strictly best-effort: the caller (the public view endpoint)
treats *any* persistence failure as a no-op so analytics can never block or
break passport access.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.services.vbr_report_view_service import (
    classify_referrer,
    classify_user_agent,
    normalize_dedupe_key,
)

_VIEWS_TABLE = "vbr_passport_views"

# Must stay in sync with the CHECK constraint in migration 065.
_ALLOWED_SOURCES = {"direct", "qr_scan", "shared_link"}


def normalize_passport_view_source(source: Any) -> str:
    """Collapse the client-declared arrival source onto the closed enum."""
    if isinstance(source, str) and source.strip().lower() in _ALLOWED_SOURCES:
        return source.strip().lower()
    return "unknown"


def resolve_published_passport_id(db: Any, public_slug: str) -> str | None:
    """Passport id for an actively published slug, else None. Never raises
    for unknown slugs — the view tracker must not be a slug oracle."""
    slug = str(public_slug or "").strip()
    if not slug:
        return None
    if isinstance(db, dict):
        row = next(
            (
                r
                for r in db.setdefault("vbr_work_passports", {}).values()
                if r.get("public_slug") == slug
            ),
            None,
        )
    else:
        result = (
            db.table("vbr_work_passports")
            .select("id, is_published")
            .eq("public_slug", slug)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        row = rows[0] if rows else None
    if row is None or not row.get("is_published"):
        return None
    return str(row.get("id"))


def record_public_passport_view(
    db: Any,
    passport_id: str,
    *,
    source: Any = None,
    dedupe_key: Any = None,
    referrer: Any = None,
    user_agent: Any = None,
    recruiter_user_id: str | None = None,
) -> bool:
    """Insert one view event for an already-resolved published passport.

    Returns True when a new row was recorded, False when the event was
    deduplicated. Persistence errors propagate — the endpoint catches them so
    tracking failures never surface to the viewer.
    """
    row = {
        "id": str(uuid4()),
        "passport_id": passport_id,
        "source": normalize_passport_view_source(source),
        "referrer_category": classify_referrer(referrer),
        "ua_class": classify_user_agent(user_agent),
        "recruiter_user_id": str(recruiter_user_id) if recruiter_user_id else None,
        "dedupe_key": normalize_dedupe_key(dedupe_key),
    }

    if isinstance(db, dict):
        table = db.setdefault(_VIEWS_TABLE, {})
        if row["dedupe_key"] is not None and any(
            existing.get("passport_id") == passport_id
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
            .eq("passport_id", passport_id)
            .eq("dedupe_key", row["dedupe_key"])
            .limit(1)
            .execute()
        )
        if getattr(existing, "data", []) or []:
            return False

    db.table(_VIEWS_TABLE).insert(row).execute()
    return True


__all__ = [
    "normalize_passport_view_source",
    "record_public_passport_view",
    "resolve_published_passport_id",
]
