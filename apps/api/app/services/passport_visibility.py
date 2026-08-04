"""Canonical Work Passport visibility checks shared by every public surface.

The single server-side source of truth for a student's Passport visibility is
``vbr_work_passports.is_published`` (see migration 052):

- ``is_published = true``  → 🌍 Public: recruiter-safe published surfaces resolve.
- ``is_published = false`` → 🔒 Private: every public surface tied to the
  candidate must fail closed with a generic 404 (non-disclosure).
- No row at all → the student never published; treated as Private.

Two gate strengths exist because two product generations share the backend:

- ``owner_passport_is_public``: STRICT, for canonical VBR surfaces (public
  project reports and their view tracker, legacy VBR report tokens). A report
  link resolves only while the owner's Passport is explicitly Public, so the
  Passport visibility toggle is a true master switch. Report tokens are never
  cleared by the toggle, which is what makes Private → Public reversible.
- ``owner_passport_blocks_public_access``: SOFT, for the legacy session-based
  passport surface (migration 021). That surface predates the canonical
  Passport and keeps its own ``is_public`` flag for owners who never touched
  the canonical Passport; but once an owner has a canonical Passport row that
  is Private, the legacy surface must go dark too.
- ``owner_has_canonical_passport``: RETIREMENT gate for the same legacy
  surface — any canonical row at all (public OR private) means the owner's
  only public surface is the canonical, disclosure-enforced one, so every
  legacy public route 404s for them.

All helpers fail closed: any lookup error is treated as "not public".
"""

from __future__ import annotations

import logging

from typing import Any

logger = logging.getLogger(__name__)

_PASSPORTS_TABLE = "vbr_work_passports"

__all__ = [
    "owner_passport_is_public",
    "owner_passport_blocks_public_access",
    "owner_has_canonical_passport",
]


def _get_passport_row(db: Any, user_id: str) -> dict[str, Any] | None:
    """Owner's canonical passport row (dict-db fixtures and Supabase alike)."""
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_PASSPORTS_TABLE, {}).values()
                if str(row.get("user_id")) == str(user_id)
            ),
            None,
        )

    result = (
        db.table(_PASSPORTS_TABLE)
        .select("is_published")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def owner_passport_is_public(db: Any, user_id: Any) -> bool:
    """True only when the owner's canonical Passport is explicitly Public.

    Missing owner id, missing passport row, ``is_published = false``, or any
    lookup failure all return False so callers 404 rather than leak.
    """
    if not user_id:
        return False
    try:
        row = _get_passport_row(db, str(user_id))
    except Exception:  # pragma: no cover - defensive: never leak on DB errors
        logger.warning("[Visibility] Passport visibility lookup failed; failing closed.")
        return False
    return bool(isinstance(row, dict) and row.get("is_published"))


def owner_passport_blocks_public_access(db: Any, user_id: Any) -> bool:
    """True when a canonical Passport row exists and is Private.

    Used by the legacy session-passport surface: owners without any canonical
    Passport keep the legacy behavior, but an explicit Private canonical
    Passport blacks out the legacy surface as well. Lookup failures block.
    """
    if not user_id:
        return False
    try:
        row = _get_passport_row(db, str(user_id))
    except Exception:  # pragma: no cover - defensive: never leak on DB errors
        logger.warning("[Visibility] Passport visibility lookup failed; failing closed.")
        return True
    if not isinstance(row, dict):
        return False
    return not bool(row.get("is_published"))


def owner_has_canonical_passport(db: Any, user_id: Any) -> bool:
    """True when ANY canonical Passport row exists for this owner (public or
    private).

    Retires the legacy session-passport surface for canonical-era users: once
    an owner has a canonical ``vbr_work_passports`` row, their ONLY public
    surface is the canonical, disclosure-enforced one — every legacy public
    route returns the standard indistinguishable 404, regardless of the
    canonical row's visibility. Owners who never touched the canonical
    Passport keep the legacy behavior. Lookup failures fail closed (treated
    as "has one", which blocks the legacy surface).
    """
    if not user_id:
        return False
    try:
        row = _get_passport_row(db, str(user_id))
    except Exception:  # pragma: no cover - defensive: never leak on DB errors
        logger.warning("[Visibility] Passport visibility lookup failed; failing closed.")
        return True
    return isinstance(row, dict)
