"""Canonical recruiter ↔ candidate connection model (migration 065).

A "connection" is the durable, authenticated relationship created when a
recruiter (a real Supabase user) saves a candidate from the candidate's
public Work Passport. It is the single model every acquisition channel
converges into — QR scan, shared link, and later search / role matching —
so the recruiter workspace never has to care how a candidate arrived.

Design rules enforced here:
  * Saves are idempotent. The table carries ``unique (recruiter_user_id,
    student_user_id)``; this service additionally select-first-then-inserts
    and recovers from the unique-violation race by re-reading, so repeated
    clicks can never create duplicates.
  * Saving requires an *actively published* passport; unknown slugs and
    unpublished passports return the same generic not-found signal.
  * Every read/delete is filtered by ``recruiter_user_id`` — the API runs
    with the service role (RLS bypassed), so app-level isolation here is the
    real boundary between recruiters.
  * The workspace listing only ever surfaces the candidate's consented
    public identity (via ``passport_profile_service.public_passport_profile``
    and the passport row's own headline/summary) — never emails, auth ids,
    or any field the student has not opted into showing.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.passport_profile_service import public_passport_profile
from app.services.recruiter_search_service import _read_with_transient_retry

logger = logging.getLogger(__name__)

_CONNECTIONS_TABLE = "recruiter_candidate_connections"
_PASSPORTS_TABLE = "vbr_work_passports"

# Must stay in sync with the CHECK constraint in migration 065.
CONNECTION_SOURCES = {"qr_scan", "shared_link", "search", "role_match", "direct"}
_DEFAULT_SOURCE = "direct"
_MAX_SOURCE_CONTEXT_BYTES = 2048

# Review workflow states — must stay in sync with the CHECK constraint added
# in migration 068. Deliberately minimal: a full ATS pipeline (reviewing /
# contacted / interview) is out of scope for V2.
CONNECTION_STATUSES = ("saved", "shortlisted", "archived")
_DEFAULT_STATUS = "saved"
# Recruiter-PRIVATE note (e.g. shortlist reason). Never exposed on any public
# surface, never indexed, never embedded.
MAX_RECRUITER_NOTE_LENGTH = 2000


class PassportNotFound(Exception):
    """Slug does not resolve to an actively published passport."""


class InvalidConnectionStatus(Exception):
    """Status outside the closed saved/shortlisted/archived vocabulary."""


class ConnectionNotFound(Exception):
    """Missing OR another recruiter's connection — indistinguishable."""


def normalize_connection_source(source: Any) -> str:
    """Collapse the client-declared acquisition source onto the closed enum."""
    if isinstance(source, str) and source.strip().lower() in CONNECTION_SOURCES:
        return source.strip().lower()
    return _DEFAULT_SOURCE


def normalize_source_context(context: Any) -> dict[str, Any]:
    """Accept only a small, JSON-safe dict; anything else becomes ``{}``."""
    if not isinstance(context, dict):
        return {}
    safe = make_json_safe({str(k): v for k, v in context.items()})
    try:
        if len(json.dumps(safe)) > _MAX_SOURCE_CONTEXT_BYTES:
            return {}
    except (TypeError, ValueError):
        return {}
    return safe


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _published_passport_by_slug(db: Any, slug: str) -> dict[str, Any] | None:
    if not slug:
        return None
    if isinstance(db, dict):
        row = next(
            (
                r
                for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
                if r.get("public_slug") == slug
            ),
            None,
        )
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_PASSPORTS_TABLE)
            .select("*")
            .eq("public_slug", slug)
            .limit(1)
            .execute(),
        )
        rows = getattr(result, "data", []) or []
        row = rows[0] if rows else None
    if row is None or not row.get("is_published"):
        return None
    return row


def _passport_by_user(db: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                r
                for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
                if str(r.get("user_id")) == str(user_id)
            ),
            None,
        )
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_PASSPORTS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _connection_for_pair(
    db: Any, recruiter_user_id: str, student_user_id: str
) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                r
                for r in db.setdefault(_CONNECTIONS_TABLE, {}).values()
                if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
                and str(r.get("student_user_id")) == str(student_user_id)
            ),
            None,
        )
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_CONNECTIONS_TABLE)
        .select("*")
        .eq("recruiter_user_id", recruiter_user_id)
        .eq("student_user_id", student_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _insert_connection(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        db.setdefault(_CONNECTIONS_TABLE, {})[row["id"]] = row
        return row
    # Transient-race retry is safe on this write: the unique
    # (recruiter_user_id, student_user_id) constraint makes a double insert
    # impossible, and save_candidate() already recovers from the resulting
    # unique-violation by re-reading the winner.
    _read_with_transient_retry(
        db,
        lambda client: client.table(_CONNECTIONS_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )
    return row


def _list_connection_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_CONNECTIONS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        # Same transient-transport-race retry as search reads: the workspace
        # listing races other page-load requests through the shared client.
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_CONNECTIONS_TABLE)
            .select("*")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("created_at", desc=True)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)


def _delete_connection_row(db: Any, recruiter_user_id: str, connection_id: str) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_CONNECTIONS_TABLE, {})
        row = table.get(str(connection_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return False
        del table[str(connection_id)]
        return True
    result = (
        db.table(_CONNECTIONS_TABLE)
        .delete()
        .eq("id", connection_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


# ── Public projection of the saved candidate ─────────────────────────────────


def _candidate_summary(db: Any, student_user_id: str) -> dict[str, Any]:
    """Consented public identity for the workspace card. Fail-safe: profile
    lookup errors degrade to the passport row's own fields, never to a crash
    of the whole workspace listing."""
    passport = _passport_by_user(db, student_user_id)
    is_published = bool(passport and passport.get("is_published"))
    slug = (passport or {}).get("public_slug")

    profile: dict[str, Any] = {}
    try:
        profile = public_passport_profile(db, str(student_user_id)) or {}
    except Exception:
        logger.warning(
            "candidate profile projection failed for connection listing",
            exc_info=True,
        )

    display_name = profile.get("preferred_name") or profile.get("full_name")
    return {
        "display_name": display_name,
        "headline": profile.get("headline") or (passport or {}).get("headline"),
        "summary": (passport or {}).get("summary"),
        "availability_label": profile.get("availability_label"),
        "location": profile.get("location"),
        "role_areas": list(profile.get("role_areas") or []),
        # Slug only while published: a candidate who unpublishes stays in the
        # workspace but their passport link goes dark until they re-publish.
        "public_slug": slug if is_published else None,
        "is_published": is_published,
    }


def _connection_view(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "source": str(row.get("source") or _DEFAULT_SOURCE),
        # Pre-068 rows have no status column yet — they are simply "saved".
        "status": str(row.get("status") or _DEFAULT_STATUS),
        "recruiter_note": row.get("recruiter_note"),
        "status_updated_at": row.get("status_updated_at"),
        "created_at": row.get("created_at"),
        "candidate": _candidate_summary(db, str(row.get("student_user_id"))),
    }


# ── Public API ───────────────────────────────────────────────────────────────


def save_candidate(
    db: Any,
    recruiter_user_id: str,
    passport_slug: str,
    *,
    source: Any = None,
    source_context: Any = None,
) -> dict[str, Any]:
    """Idempotently connect ``recruiter_user_id`` to the passport's owner.

    Raises :class:`PassportNotFound` when the slug does not resolve to an
    actively published passport. Returns the connection view plus
    ``already_saved`` so the UI can distinguish first save from a repeat.
    """
    passport = _published_passport_by_slug(db, str(passport_slug or "").strip())
    if passport is None:
        raise PassportNotFound(passport_slug)

    student_user_id = str(passport.get("user_id"))
    existing = _connection_for_pair(db, recruiter_user_id, student_user_id)
    if existing is not None:
        view = _connection_view(db, existing)
        view["already_saved"] = True
        return view

    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "student_user_id": student_user_id,
        "passport_id": str(passport.get("id")),
        "source": normalize_connection_source(source),
        "source_context": normalize_source_context(source_context),
        "created_at": now,
        "updated_at": now,
    }
    try:
        _insert_connection(db, row)
    except Exception:
        # Two tabs racing the same first save: the unique constraint on
        # (recruiter_user_id, student_user_id) rejects the loser — recover by
        # re-reading the winner so the caller still gets a saved state.
        existing = _connection_for_pair(db, recruiter_user_id, student_user_id)
        if existing is None:
            raise
        view = _connection_view(db, existing)
        view["already_saved"] = True
        return view

    view = _connection_view(db, row)
    view["already_saved"] = False
    return view


def list_connections(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    """The recruiter's saved candidates, newest first, public identity only."""
    return [
        _connection_view(db, row)
        for row in _list_connection_rows(db, recruiter_user_id)
    ]


def connection_status(
    db: Any, recruiter_user_id: str, passport_slug: str
) -> dict[str, Any]:
    """Whether this recruiter has already saved the passport's owner.

    Unknown/unpublished slugs report ``saved: false`` rather than erroring —
    the status probe must reveal nothing the public GET does not.
    """
    passport = _published_passport_by_slug(db, str(passport_slug or "").strip())
    if passport is None:
        return {"saved": False, "connection_id": None}
    existing = _connection_for_pair(
        db, recruiter_user_id, str(passport.get("user_id"))
    )
    if existing is None:
        return {"saved": False, "connection_id": None}
    return {"saved": True, "connection_id": str(existing.get("id"))}


def delete_connection(db: Any, recruiter_user_id: str, connection_id: str) -> bool:
    """Remove one of the caller's OWN connections. Returns False when the id
    does not exist or belongs to another recruiter (indistinguishable)."""
    return _delete_connection_row(db, recruiter_user_id, str(connection_id or ""))


def update_connection(
    db: Any,
    recruiter_user_id: str,
    connection_id: str,
    *,
    status: Any = ...,
    recruiter_note: Any = ...,
) -> dict[str, Any]:
    """Update the review status and/or private note of the caller's OWN
    connection (shortlist / archive / back to saved).

    ``...`` (unset) leaves a field untouched; an explicit empty note clears
    it. Raises :class:`InvalidConnectionStatus` outside the closed enum and
    :class:`ConnectionNotFound` for missing/foreign rows (indistinguishable).
    """
    updates: dict[str, Any] = {}

    if status is not ...:
        normalized = str(status or "").strip().lower()
        if normalized not in CONNECTION_STATUSES:
            raise InvalidConnectionStatus(status)
        updates["status"] = normalized
        updates["status_updated_at"] = _now_iso()

    if recruiter_note is not ...:
        if recruiter_note is None:
            updates["recruiter_note"] = None
        else:
            text = str(recruiter_note).strip()[:MAX_RECRUITER_NOTE_LENGTH]
            updates["recruiter_note"] = text or None

    # Ownership check first so a no-op update still 404s on foreign rows.
    existing = None
    if isinstance(db, dict):
        row = db.setdefault(_CONNECTIONS_TABLE, {}).get(str(connection_id or ""))
        if row is not None and str(row.get("recruiter_user_id")) == str(
            recruiter_user_id
        ):
            existing = row
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_CONNECTIONS_TABLE)
            .select("*")
            .eq("id", connection_id)
            .eq("recruiter_user_id", recruiter_user_id)
            .limit(1)
            .execute(),
        )
        rows = getattr(result, "data", []) or []
        existing = rows[0] if rows else None
    if existing is None:
        raise ConnectionNotFound(connection_id)

    if updates:
        updates["updated_at"] = _now_iso()
        if isinstance(db, dict):
            existing.update(updates)
        else:
            db.table(_CONNECTIONS_TABLE).update(make_json_safe(updates)).eq(
                "id", connection_id
            ).eq("recruiter_user_id", recruiter_user_id).execute()
            existing = {**existing, **updates}

    return _connection_view(db, existing)


__all__ = [
    "CONNECTION_SOURCES",
    "CONNECTION_STATUSES",
    "ConnectionNotFound",
    "InvalidConnectionStatus",
    "MAX_RECRUITER_NOTE_LENGTH",
    "PassportNotFound",
    "connection_status",
    "delete_connection",
    "list_connections",
    "normalize_connection_source",
    "normalize_source_context",
    "save_candidate",
    "update_connection",
]
