"""Central self-provisioning of the caller's own ``public.users`` row.

Why this exists
---------------
A freshly signed-up Supabase user has an ``auth.users`` row but NO
``public.users`` row (there is no signup endpoint or ``handle_new_user``
trigger creating it), and virtually every student-owned table
(``extension_proof_sessions``, ``github_proof_submissions``, ``student_profiles``,
``proof_artifacts``, ``video_proofs``, ``vbr_projects``, ``beam_links``, …)
foreign-keys ``user_id`` against ``public.users(id)``. Without provisioning, a
fresh user's FIRST write on any of those flows fails with a 23503 FK violation
surfaced as an opaque 500.

This module is the ONE place that closes that gap. Every authenticated
first-write flow goes through :func:`ensure_public_user_for_auth_user` (usually
via the ``get_provisioned_user_id`` dependency in ``app.api.deps``).

Security invariants
-------------------
- Input comes ONLY from a verified Supabase JWT (``sub`` + optional ``email``
  claims). This never accepts a caller-chosen user id.
- It self-provisions the caller's OWN row and nothing else: no fallback user,
  no demo user, no cross-tenant reads or writes.
- Idempotent: an existing row is never modified or overwritten (a row created
  by a future ``handle_new_user`` trigger, or by an earlier request, wins).
- Race-safe: a concurrent insert (another request or a DB trigger) is treated
  as success after a re-check by id.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import (
    SupabaseAPIError,
    SupabaseConnectionError,
    SupabaseFKError,
)

logger = logging.getLogger(__name__)

_USERS = "users"

_FK_MARKERS = ("23503", "foreign key", "foreign-key", "violates foreign key")


def classify_db_error(exc: Exception, op: str, table: str) -> Exception:
    """Map a raw Supabase/httpx error to a typed, safe service exception.

    Never carries a traceback or secrets into the message — only the operation,
    table, and exception class name — so endpoints can surface a clear,
    non-leaky error instead of a generic 500.
    """
    exc_name = type(exc).__name__
    exc_str = str(exc).lower()
    if any(marker in exc_str for marker in _FK_MARKERS):
        return SupabaseFKError(
            f"{op} {table} failed: a required parent row is missing (foreign-key constraint)."
        )
    if isinstance(exc, (ConnectionError, TimeoutError)) or "timed out" in exc_str or "connection" in exc_str:
        return SupabaseConnectionError(f"{op} {table} failed: network error ({exc_name}).")
    return SupabaseAPIError(f"{op} {table} failed: Supabase returned an error ({exc_name}).")


def ensure_public_user_for_auth_user(
    db: Any, user_id: str, email: str | None = None
) -> str:
    """Ensure the authenticated caller's own ``public.users`` row exists.

    ``user_id`` MUST be the verified JWT ``sub`` (it is the canonical app user
    id — ``public.users.id`` mirrors ``auth.users.id``), and ``email`` the
    verified JWT ``email`` claim when available. Returns ``user_id`` so it can
    be used as a pass-through in dependencies.

    A no-op when the row already exists; existing profile fields are never
    touched. Raises a typed ``SupabaseError`` subclass on real DB failures.
    """
    resolved_email = (email or "").strip() or f"{user_id}@users.noreply.veribridge.local"
    new_row = {
        "id": user_id,
        "email": resolved_email,
        "role": "student",
        "status": "active",
    }

    # Dict-mode (unit tests / dev in-memory store).
    if isinstance(db, dict):
        users = db.setdefault(_USERS, {})
        users.setdefault(user_id, dict(new_row))
        return user_id

    try:
        existing = db.table(_USERS).select("id").eq("id", user_id).limit(1).execute()
    except Exception as exc:
        raise classify_db_error(exc, "GET", _USERS) from exc
    if getattr(existing, "data", None):
        return user_id

    try:
        db.table(_USERS).insert(new_row).execute()
        logger.info("Provisioned public.users row for fresh auth user %s", user_id)
    except Exception as exc:
        # A concurrent request (or a DB trigger) may have created the row
        # between the select and the insert. Re-check by id and only surface
        # the error if the row genuinely still does not exist.
        try:
            recheck = db.table(_USERS).select("id").eq("id", user_id).limit(1).execute()
        except Exception:
            recheck = None
        if getattr(recheck, "data", None):
            return user_id
        raise classify_db_error(exc, "INSERT", _USERS) from exc
    return user_id
