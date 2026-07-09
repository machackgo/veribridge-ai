"""Beam Link service — dynamic revocable short links for the Passport handoff.

The Beam Card QR (and every future handoff surface: Wallet passes, NFC cards,
career-fair event links) encodes a short link ``{app}/b/{code}`` instead of the
public Passport URL. The code resolves through :func:`resolve_beam_code`, which
is the ONLY thing that decides where a scan goes:

    1. code exists
    2. link status is ``active``
    3. link is not past ``expires_at`` (lazily stamped ``expired``)
    4. the target passport row still exists
    5. the target passport is still published

Only then does the caller get the live public Passport path. Every failure mode
collapses into the same generic "inactive" error — an invalid, revoked, expired,
or unpublished-target code NEVER reveals whether it once existed, whose it was,
or why it stopped working.

Codes are minted with ``secrets.token_urlsafe`` (~96 bits, 16 URL-safe chars):
unguessable, collision-checked, never sequential, never derived from internal
ids. Revoking or rotating a link invalidates every printed/screenshotted copy
of the old QR at scan time, without touching the Passport or any evidence.

Storage follows the repo's dual persistence pattern: a plain ``dict`` in tests
/ dev fallback, the Supabase service-role client otherwise (RLS keeps anonymous
clients out of the table entirely — see migration 055).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.vbr_work_passport_service import _get_passport_by_user

logger = logging.getLogger(__name__)

_LINKS_TABLE = "beam_links"
_EVENTS_TABLE = "beam_link_events"

# 12 bytes -> 16 URL-safe base64 chars (~96 bits of entropy). The spec floor is
# 10 chars / "preferably 12+"; 16 keeps the QR tiny while making enumeration
# infeasible.
_CODE_BYTES = 12
_CODE_MIN_LENGTH = 12
_CODE_GENERATION_ATTEMPTS = 8

_ALLOWED_EVENT_TYPES = {"created", "opened", "rotated", "revoked", "expired_hit"}

_EVENT_TAG_MAX_LENGTH = 64

__all__ = [
    "create_or_reuse_beam_link",
    "rotate_beam_link",
    "revoke_beam_link",
    "resolve_beam_code",
    "classify_user_agent",
    "referrer_host",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


# ── Persistence helpers (dict + Supabase) ────────────────────────────────────


def _get_link_by_code(db: Any, code: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_LINKS_TABLE, {}).values()
                if row.get("code") == code
            ),
            None,
        )

    result = db.table(_LINKS_TABLE).select("*").eq("code", code).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_link_by_id(db: Any, link_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.setdefault(_LINKS_TABLE, {}).get(str(link_id))

    result = db.table(_LINKS_TABLE).select("*").eq("id", link_id).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_active_link_for_user(db: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_LINKS_TABLE, {}).values()
                if str(row.get("user_id")) == str(user_id) and row.get("status") == "active"
            ),
            None,
        )

    result = (
        db.table(_LINKS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _code_exists(db: Any, code: str) -> bool:
    return _get_link_by_code(db, code) is not None


def _insert_link(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        db.setdefault(_LINKS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_LINKS_TABLE).insert(row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else row


def _update_link(db: Any, link_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_LINKS_TABLE, {}).get(str(link_id))
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_LINKS_TABLE).update(updates).eq("id", link_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _log_event(
    db: Any,
    beam_link_id: str,
    event_type: str,
    *,
    user_agent_class: str | None = None,
    referrer_host_value: str | None = None,
) -> None:
    """Append one coarse, privacy-safe audit event. Never raises to the caller
    — a failed audit write must not break a live scan or an owner action."""
    if event_type not in _ALLOWED_EVENT_TYPES:  # defence in depth
        return
    row = {
        "id": str(uuid4()),
        "beam_link_id": str(beam_link_id),
        "event_type": event_type,
        "user_agent_class": user_agent_class,
        "referrer_host": referrer_host_value,
        "created_at": _now_iso(),
    }
    try:
        if isinstance(db, dict):
            db.setdefault(_EVENTS_TABLE, {})[row["id"]] = row
        else:
            db.table(_EVENTS_TABLE).insert(row).execute()
    except Exception:
        logger.warning("[Beam] Failed to log %s event for link %s", event_type, beam_link_id)


# ── Coarse, privacy-safe request metadata ────────────────────────────────────


def classify_user_agent(user_agent: str | None) -> str:
    """Reduce a raw User-Agent header to a coarse class. The raw string is
    never stored — this is the ONLY thing that reaches the audit trail."""
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if any(token in ua for token in ("bot", "crawler", "spider", "curl", "wget", "python-requests")):
        return "bot"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if any(token in ua for token in ("iphone", "android", "mobile")):
        return "mobile"
    if any(token in ua for token in ("macintosh", "windows", "x11", "linux")):
        return "desktop"
    return "other"


def referrer_host(referrer: str | None) -> str | None:
    """Keep only the referrer's host — never the path, query, or fragment."""
    if not referrer:
        return None
    try:
        from urllib.parse import urlparse

        host = urlparse(referrer).hostname
        return host or None
    except Exception:
        return None


# ── Code generation ──────────────────────────────────────────────────────────


def _generate_code(db: Any) -> str:
    """Mint a cryptographically random, URL-safe, collision-checked code."""
    for _ in range(_CODE_GENERATION_ATTEMPTS):
        code = secrets.token_urlsafe(_CODE_BYTES)
        if len(code) >= _CODE_MIN_LENGTH and not _code_exists(db, code):
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "beam_code_generation_failed",
            "message": "Could not generate a unique Beam link. Please try again.",
        },
    )


# ── Shared guards / serialization ────────────────────────────────────────────


def _require_published_passport(db: Any, user_id: str) -> dict[str, Any]:
    """A shareable Beam link may only ever point at a PUBLISHED passport."""
    passport = _get_passport_by_user(db, user_id)
    if passport is None or not passport.get("is_published") or not passport.get("public_slug"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "beam_passport_not_published",
                "message": (
                    "Publish your Work Passport first — a Beam link can only "
                    "point at a published public Passport."
                ),
            },
        )
    return passport


def _require_owned_link(db: Any, user_id: str, link_id: str) -> dict[str, Any]:
    """Resolve a link the caller owns. A foreign or unknown id is the SAME 404
    so a caller can never probe whether someone else's link id exists."""
    row = _get_link_by_id(db, link_id)
    if row is None or str(row.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "beam_link_not_found", "message": "Beam link not found."},
        )
    return row


def _link_response(row: dict[str, Any]) -> dict[str, Any]:
    """Owner-facing serialization. Carries the short path + the CURRENT public
    passport path; never another user's data (rows are owner-scoped upstream)."""
    return {
        "id": str(row.get("id") or ""),
        "code": row.get("code") or "",
        "status": row.get("status") or "revoked",
        "short_path": f"/b/{row.get('code')}",
        "public_passport_path": f"/p/{row.get('passport_slug')}",
        "event_tag": row.get("event_tag"),
        "expires_at": row.get("expires_at"),
        "revoked_at": row.get("revoked_at"),
        "created_at": row.get("created_at"),
    }


def _sanitize_event_tag(event_tag: str | None) -> str | None:
    """Optional coarse campaign/event label (e.g. "career-fair-2026"). Kept to a
    short, safe charset so it can never smuggle markup or private text."""
    if not event_tag:
        return None
    cleaned = "".join(ch for ch in event_tag.strip() if ch.isalnum() or ch in "-_ ")
    cleaned = cleaned.strip()[:_EVENT_TAG_MAX_LENGTH]
    return cleaned or None


# ── Owner operations ─────────────────────────────────────────────────────────


def create_or_reuse_beam_link(
    db: Any,
    user_id: str,
    *,
    event_tag: str | None = None,
) -> dict[str, Any]:
    """Return the caller's active Beam link, minting one if none exists.

    Idempotent by design: the same student always beams the same short code
    until they rotate or revoke it, so a printed card / saved screenshot stays
    valid exactly as long as the student wants it to.
    """
    passport = _require_published_passport(db, user_id)

    existing = _get_active_link_for_user(db, user_id)
    if existing is not None:
        # Keep the serialized target on the passport's CURRENT slug (stable in
        # practice, but the passport row is always the source of truth).
        existing = dict(existing, passport_slug=passport.get("public_slug"))
        return _link_response(existing)

    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "code": _generate_code(db),
        "user_id": str(user_id),
        "passport_id": str(passport.get("id")),
        "passport_slug": str(passport.get("public_slug")),
        "status": "active",
        "event_tag": _sanitize_event_tag(event_tag),
        "expires_at": None,
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
    }
    created = _insert_link(db, row)
    _log_event(db, row["id"], "created")
    logger.info("[Beam] Beam link created for user %s", user_id)
    return _link_response(created or row)


def rotate_beam_link(db: Any, user_id: str, link_id: str) -> dict[str, Any]:
    """Revoke the given link and mint a fresh code in one owner action.

    Every previously shared copy of the OLD code (printed card, screenshot,
    old wallet pass) stops resolving immediately; the new code takes over.
    """
    old = _require_owned_link(db, user_id, link_id)
    passport = _require_published_passport(db, user_id)

    now = _now_iso()
    if old.get("status") == "active":
        _update_link(db, str(old["id"]), {"status": "revoked", "revoked_at": now, "updated_at": now})
    _log_event(db, str(old["id"]), "rotated")

    new_row = {
        "id": str(uuid4()),
        "code": _generate_code(db),
        "user_id": str(user_id),
        "passport_id": str(passport.get("id")),
        "passport_slug": str(passport.get("public_slug")),
        "status": "active",
        "event_tag": old.get("event_tag"),
        "expires_at": None,
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
    }
    created = _insert_link(db, new_row)
    _log_event(db, new_row["id"], "created")
    logger.info("[Beam] Beam link rotated for user %s", user_id)
    return _link_response(created or new_row)


def revoke_beam_link(db: Any, user_id: str, link_id: str) -> dict[str, Any]:
    """Kill a link. Idempotent; the QR shows the safe inactive page from now on."""
    row = _require_owned_link(db, user_id, link_id)
    if row.get("status") == "active":
        now = _now_iso()
        updated = _update_link(
            db, str(row["id"]), {"status": "revoked", "revoked_at": now, "updated_at": now}
        )
        row.update(updated or {"status": "revoked", "revoked_at": now})
        _log_event(db, str(row["id"]), "revoked")
        logger.info("[Beam] Beam link revoked for user %s", user_id)
    return _link_response(row)


# ── Public resolution (the ONLY public read path) ────────────────────────────


def _inactive() -> HTTPException:
    """One generic failure for EVERY invalid scan — unknown, revoked, expired,
    or unpublished-target codes are indistinguishable from the outside, so the
    endpoint can never be used as an oracle for holder identity or link state."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "beam_link_inactive",
            "message": "This Passport link is no longer active.",
        },
    )


def _is_expired(row: dict[str, Any]) -> bool:
    expires_at = row.get("expires_at")
    if not expires_at:
        return False
    try:
        value = expires_at if isinstance(expires_at, datetime) else datetime.fromisoformat(str(expires_at))
    except ValueError:
        return True  # unparseable expiry fails closed
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= _now()


def resolve_beam_code(
    db: Any,
    code: str,
    *,
    user_agent: str | None = None,
    referrer: str | None = None,
) -> dict[str, Any]:
    """Validate a scanned code and return the LIVE public Passport path.

    Validation order (all failures collapse into the same generic inactive
    error — no holder data, no slug, no reason ever leaks on a bad scan):
      1. code exists  2. status active  3. not expired
      4. target passport exists  5. target passport is published
    """
    ua_class = classify_user_agent(user_agent)
    ref_host = referrer_host(referrer)

    if not code or len(code) < _CODE_MIN_LENGTH:
        raise _inactive()

    row = _get_link_by_code(db, code)
    if row is None:
        raise _inactive()

    if row.get("status") != "active":
        _log_event(db, str(row["id"]), "expired_hit", user_agent_class=ua_class, referrer_host_value=ref_host)
        raise _inactive()

    if _is_expired(row):
        # Lazy expiry: stamp the row so owner surfaces show the true state.
        now = _now_iso()
        _update_link(db, str(row["id"]), {"status": "expired", "updated_at": now})
        _log_event(db, str(row["id"]), "expired_hit", user_agent_class=ua_class, referrer_host_value=ref_host)
        raise _inactive()

    # The passport row is the live source of truth for BOTH existence and
    # visibility. An unpublished passport makes the link dormant (not dead):
    # re-publishing restores the same code, matching how unpublish works
    # everywhere else in the product.
    passport = _get_passport_row(db, str(row.get("passport_id") or ""))
    if (
        passport is None
        or not passport.get("is_published")
        or not passport.get("public_slug")
    ):
        _log_event(db, str(row["id"]), "expired_hit", user_agent_class=ua_class, referrer_host_value=ref_host)
        raise _inactive()

    _log_event(db, str(row["id"]), "opened", user_agent_class=ua_class, referrer_host_value=ref_host)
    return {
        "status": "active",
        # CURRENT slug from the live passport row — never the stored snapshot.
        "public_passport_path": f"/p/{passport.get('public_slug')}",
    }


def _get_passport_row(db: Any, passport_id: str) -> dict[str, Any] | None:
    if not passport_id:
        return None
    if isinstance(db, dict):
        return db.setdefault("vbr_work_passports", {}).get(passport_id) or next(
            (
                row
                for row in db.setdefault("vbr_work_passports", {}).values()
                if str(row.get("id")) == str(passport_id)
            ),
            None,
        )

    result = (
        db.table("vbr_work_passports").select("*").eq("id", passport_id).limit(1).execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None
