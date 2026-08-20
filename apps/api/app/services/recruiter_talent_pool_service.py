"""Recruiter Talent Pools — reusable candidate collections (migration 070).

A Talent Pool is a recruiter-owned, role-independent organizing label
("AI / ML Early Talent", "Fall 2026 Career Fair Prospects") on top of the
V3/V4 Hiring Brief stack. Design rules enforced here:

  * A pool never copies candidate data. Membership is keyed by the stable
    ``student_user_id``; identity is resolved live through the SAME
    consented projection as the workspace listing
    (``recruiter_connection_service._candidate_summary``) and evidence
    context through the SAME fail-closed triple as comparison
    (``live_valid_index_rows``) — a candidate who unpublishes goes dark in
    every pool immediately.
  * Membership is idempotent by construction (composite PK mirrored here
    by the ``pool_id:student_user_id`` dict key) and a candidate may
    belong to many pools.
  * Pools never auto-link to Hiring Briefs; both directions are explicit
    recruiter actions. Deleting a pool never touches connections, briefs,
    or public evidence.

Isolation: the API runs with the service role (RLS bypassed), so every
read/write here filters by ``recruiter_user_id`` in application code —
that filter is the real boundary between recruiters. Foreign pools and
membership rows are indistinguishable from missing ones.

Privacy: pools, membership and notes are recruiter-private workflow data —
never written to any index, public projection, or candidate-facing
surface. Analytics record counts and recruiter-authored text only.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.recruiter_comparison_service import (
    _own_connection_rows,
    _published_passports_by_slugs,
    live_valid_index_rows,
)
from app.services.recruiter_connection_service import _candidate_summary
from app.services.recruiter_search_service import (
    _read_with_transient_retry,
    record_search_event,
)

logger = logging.getLogger(__name__)

_POOLS_TABLE = "recruiter_talent_pools"
_POOL_CANDIDATES_TABLE = "recruiter_talent_pool_candidates"
_BRIEFS_TABLE = "recruiter_hiring_briefs"
_BRIEF_CANDIDATES_TABLE = "recruiter_hiring_brief_candidates"

# Must stay in sync with the CHECK constraints in migration 070.
POOL_STATUSES = ("active", "archived")
# Superset of recruiter_connection_service.CONNECTION_SOURCES (065) plus
# 'saved_search' — how a candidate entered THIS pool.
POOL_CANDIDATE_SOURCES = {
    "qr_scan",
    "shared_link",
    "search",
    "role_match",
    "direct",
    "saved_search",
}
_DEFAULT_SOURCE = "direct"

MAX_TALENT_POOLS = 40
MAX_POOL_CANDIDATES = 200
MAX_POOL_NAME = 120
MAX_POOL_DESCRIPTION = 600
MAX_NOTE_LENGTH = 4000
_MAX_TOP_SKILLS = 6


class PoolNotFound(Exception):
    """Pool id does not exist for this recruiter (foreign == missing)."""


class PoolError(Exception):
    """Recruiter-facing pool input problem (maps to 400/404)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pool_key(pool_id: str, student_user_id: str) -> str:
    return f"{pool_id}:{student_user_id}"


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _pool_row(db: Any, recruiter_user_id: str, pool_id: str) -> dict[str, Any] | None:
    pool_id = str(pool_id or "").strip()
    if not pool_id:
        return None
    if isinstance(db, dict):
        row = db.setdefault(_POOLS_TABLE, {}).get(pool_id)
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return None
        return row
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_POOLS_TABLE)
        .select("*")
        .eq("id", pool_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _list_pool_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_POOLS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_POOLS_TABLE)
            .select("*")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("updated_at", desc=True)
            .limit(MAX_TALENT_POOLS)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[
        :MAX_TALENT_POOLS
    ]


def _insert_pool(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_POOLS_TABLE, {})[row["id"]] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_POOLS_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_pool_row(
    db: Any, recruiter_user_id: str, pool_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_POOLS_TABLE, {}).get(str(pool_id))
        if row is not None and str(row.get("recruiter_user_id")) == str(
            recruiter_user_id
        ):
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_POOLS_TABLE)
        .update(make_json_safe(updates))
        .eq("id", pool_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )


def _delete_pool_row(db: Any, recruiter_user_id: str, pool_id: str) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_POOLS_TABLE, {})
        row = table.get(str(pool_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return False
        del table[str(pool_id)]
        # Mirror ON DELETE CASCADE for the membership rows in dict mode.
        members = db.setdefault(_POOL_CANDIDATES_TABLE, {})
        for key in [
            k for k, r in members.items() if str(r.get("pool_id")) == str(pool_id)
        ]:
            del members[key]
        return True
    result = (
        db.table(_POOLS_TABLE)
        .delete()
        .eq("id", pool_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


def _member_rows_for_pool(db: Any, pool_id: str) -> list[dict[str, Any]]:
    """Membership rows for ONE pool. Callers must have resolved the pool
    through ``_pool_row`` first — ownership is enforced there."""
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_POOL_CANDIDATES_TABLE, {}).values()
            if str(r.get("pool_id")) == str(pool_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_POOL_CANDIDATES_TABLE)
            .select("*")
            .eq("pool_id", pool_id)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("added_at") or ""))


def _member_rows_for_pools(db: Any, pool_ids: list[str]) -> list[dict[str, Any]]:
    if not pool_ids:
        return []
    if isinstance(db, dict):
        wanted = {str(p) for p in pool_ids}
        return [
            r
            for r in db.setdefault(_POOL_CANDIDATES_TABLE, {}).values()
            if str(r.get("pool_id")) in wanted
        ]
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_POOL_CANDIDATES_TABLE)
        .select("pool_id, student_user_id")
        .in_("pool_id", pool_ids)
        .execute(),
    )
    return list(getattr(result, "data", []) or [])


def _member_row(db: Any, pool_id: str, student_user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.setdefault(_POOL_CANDIDATES_TABLE, {}).get(
            _pool_key(str(pool_id), str(student_user_id))
        )
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_POOL_CANDIDATES_TABLE)
        .select("*")
        .eq("pool_id", pool_id)
        .eq("student_user_id", student_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _insert_member_row(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_POOL_CANDIDATES_TABLE, {})[
            _pool_key(row["pool_id"], row["student_user_id"])
        ] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_POOL_CANDIDATES_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_member_row(
    db: Any, pool_id: str, student_user_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_POOL_CANDIDATES_TABLE, {}).get(
            _pool_key(str(pool_id), str(student_user_id))
        )
        if row is not None:
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_POOL_CANDIDATES_TABLE)
        .update(make_json_safe(updates))
        .eq("pool_id", pool_id)
        .eq("student_user_id", student_user_id)
        .execute(),
    )


def _delete_member_row(db: Any, pool_id: str, student_user_id: str) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_POOL_CANDIDATES_TABLE, {})
        key = _pool_key(str(pool_id), str(student_user_id))
        if key not in table:
            return False
        del table[key]
        return True
    result = (
        db.table(_POOL_CANDIDATES_TABLE)
        .delete()
        .eq("pool_id", pool_id)
        .eq("student_user_id", student_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


# ── Views ────────────────────────────────────────────────────────────────────


def _pool_view(row: dict[str, Any], candidate_count: int) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "name": str(row.get("name") or "Untitled pool"),
        "description": row.get("description"),
        "status": str(row.get("status") or "active"),
        "candidate_count": candidate_count,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _evidence_context(index_row: dict[str, Any]) -> dict[str, Any]:
    """Light, live evidence context from the fail-closed index row — public
    projection data only (the same payload served at /p/{slug})."""
    return {
        "skill_count": int(index_row.get("skill_count") or 0),
        "project_count": int(index_row.get("project_count") or 0),
        "evidence_flags": {
            str(k): bool(v)
            for k, v in (index_row.get("evidence_flags") or {}).items()
        },
        "top_skills": [
            str(s.get("skill") or "")
            for s in (index_row.get("skills") or [])[:_MAX_TOP_SKILLS]
            if str(s.get("skill") or "").strip()
        ],
        "public_slug": str(index_row.get("public_slug") or "") or None,
    }


def _member_view(
    db: Any, row: dict[str, Any], *, index_row: dict[str, Any] | None
) -> dict[str, Any]:
    student_user_id = str(row.get("student_user_id"))
    return {
        "student_user_id": student_user_id,
        "source": str(row.get("source") or _DEFAULT_SOURCE),
        "note": row.get("note"),
        "added_at": row.get("added_at"),
        "candidate": _candidate_summary(db, student_user_id),
        # None when the candidate is not live (unpublished / excluded /
        # stale disclosure) — the identity card then carries the
        # "no longer published" treatment; evidence never survives stale.
        "evidence": _evidence_context(index_row) if index_row is not None else None,
    }


def _record_pool_event(
    db: Any, recruiter_user_id: str, action: str, *, count: int, name: Any = None
) -> None:
    """Coarse, privacy-safe analytics: counts + the recruiter's own pool
    name only — never notes or candidate identity."""
    record_search_event(
        db,
        recruiter_user_id=recruiter_user_id,
        q=str(name or "") or None,
        filters={"pool": action},
        result_count=count,
    )


# ── Pool CRUD ────────────────────────────────────────────────────────────────


def create_pool(
    db: Any,
    recruiter_user_id: str,
    *,
    name: Any,
    description: Any = None,
) -> dict[str, Any]:
    cleaned = str(name or "").strip()[:MAX_POOL_NAME]
    if not cleaned:
        raise PoolError("invalid_name", "Give the Talent Pool a name.")
    if len(_list_pool_rows(db, recruiter_user_id)) >= MAX_TALENT_POOLS:
        raise PoolError(
            "too_many_pools",
            f"You can keep up to {MAX_TALENT_POOLS} Talent Pools.",
        )
    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "name": cleaned,
        "description": str(description or "").strip()[:MAX_POOL_DESCRIPTION] or None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    _insert_pool(db, row)
    _record_pool_event(db, str(recruiter_user_id), "created", count=0, name=cleaned)
    return _pool_view(row, 0)


def list_pools(db: Any, recruiter_user_id: str) -> dict[str, Any]:
    """The recruiter's pools, most recently updated first, with transparent
    candidate counts (one batched membership read — no N+1)."""
    rows = _list_pool_rows(db, recruiter_user_id)
    members = _member_rows_for_pools(db, [str(r.get("id")) for r in rows])
    counts: dict[str, int] = {}
    for entry in members:
        pid = str(entry.get("pool_id"))
        counts[pid] = counts.get(pid, 0) + 1
    pools = [_pool_view(row, counts.get(str(row.get("id")), 0)) for row in rows]
    return {"pools": pools, "total": len(pools)}


def get_pool(db: Any, recruiter_user_id: str, pool_id: str) -> dict[str, Any]:
    row = _pool_row(db, recruiter_user_id, pool_id)
    if row is None:
        raise PoolNotFound(pool_id)
    return _pool_view(row, len(_member_rows_for_pool(db, str(row["id"]))))


def update_pool(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    *,
    name: Any = ...,
    description: Any = ...,
    clear_description: bool = False,
    status: Any = ...,
) -> dict[str, Any]:
    """Partial update; ``...`` means "leave unchanged"."""
    row = _pool_row(db, recruiter_user_id, pool_id)
    if row is None:
        raise PoolNotFound(pool_id)

    updates: dict[str, Any] = {"updated_at": _now_iso()}
    if name is not ...:
        cleaned = str(name or "").strip()[:MAX_POOL_NAME]
        if not cleaned:
            raise PoolError("invalid_name", "Give the Talent Pool a name.")
        updates["name"] = cleaned
    if clear_description:
        updates["description"] = None
    elif description is not ...:
        updates["description"] = (
            str(description or "").strip()[:MAX_POOL_DESCRIPTION] or None
        )
    if status is not ...:
        if status not in POOL_STATUSES:
            raise PoolError("invalid_status", "Unknown pool status.")
        updates["status"] = status

    _update_pool_row(db, recruiter_user_id, str(row["id"]), updates)
    refreshed = _pool_row(db, recruiter_user_id, str(row["id"]))
    merged = refreshed or {**row, **updates}
    _record_pool_event(
        db, str(recruiter_user_id), "updated", count=0, name=merged.get("name")
    )
    return _pool_view(merged, len(_member_rows_for_pool(db, str(row["id"]))))


def delete_pool(db: Any, recruiter_user_id: str, pool_id: str) -> bool:
    """Delete one of the caller's OWN pools (membership cascades). Never
    touches connections, briefs, or public evidence. Returns False when the
    id does not exist or is another recruiter's (indistinguishable)."""
    deleted = _delete_pool_row(db, recruiter_user_id, str(pool_id or ""))
    if deleted:
        _record_pool_event(db, str(recruiter_user_id), "deleted", count=0)
    return deleted


# ── Membership ───────────────────────────────────────────────────────────────


def _visible_student_ids(db: Any, recruiter_user_id: str) -> set[str]:
    """Student ids already visible to this recruiter: own connections plus
    members of the recruiter's OWN pools and briefs. A raw user id from a
    client is only ever accepted against this whitelist."""
    visible = {
        str(r.get("student_user_id"))
        for r in _own_connection_rows(db, recruiter_user_id)
    }
    own_pool_ids = [
        str(r.get("id")) for r in _list_pool_rows(db, recruiter_user_id)
    ]
    for entry in _member_rows_for_pools(db, own_pool_ids):
        visible.add(str(entry.get("student_user_id")))

    if isinstance(db, dict):
        own_brief_ids = {
            str(r.get("id"))
            for r in db.setdefault(_BRIEFS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        }
        for r in db.setdefault(_BRIEF_CANDIDATES_TABLE, {}).values():
            if str(r.get("brief_id")) in own_brief_ids:
                visible.add(str(r.get("student_user_id")))
        return visible

    briefs = _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEFS_TABLE)
        .select("id")
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )
    brief_ids = [str(r.get("id")) for r in (getattr(briefs, "data", []) or [])]
    if brief_ids:
        rows = _read_with_transient_retry(
            db,
            lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
            .select("student_user_id")
            .in_("brief_id", brief_ids)
            .execute(),
        )
        for r in getattr(rows, "data", []) or []:
            visible.add(str(r.get("student_user_id")))
    return visible


def add_pool_candidates(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    *,
    candidate_slugs: list[str] | None = None,
    connection_ids: list[str] | None = None,
    student_user_ids: list[str] | None = None,
    source: Any = _DEFAULT_SOURCE,
) -> dict[str, Any]:
    """Idempotently add candidates to the pool. Candidates resolve exactly
    like brief-pool adds: actively published slugs and/or the recruiter's
    OWN connections. ``student_user_ids`` (used by the saved-search flow)
    are accepted ONLY when the id is already visible to this recruiter —
    a raw user id is never trusted on its own."""
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)
    if source not in POOL_CANDIDATE_SOURCES:
        raise PoolError("invalid_source", "Unknown candidate source.")

    ordered: list[str] = []
    if connection_ids:
        own = {str(r.get("id")): r for r in _own_connection_rows(db, recruiter_user_id)}
        for cid in connection_ids:
            row = own.get(str(cid or "").strip())
            if row is None:
                raise PoolError(
                    "candidate_not_found",
                    "One of the selected saved candidates was not found.",
                )
            uid = str(row.get("student_user_id"))
            if uid not in ordered:
                ordered.append(uid)
    if candidate_slugs:
        cleaned = [str(s or "").strip() for s in candidate_slugs if str(s or "").strip()]
        by_slug = _published_passports_by_slugs(db, cleaned)
        for slug in cleaned:
            passport = by_slug.get(slug)
            if passport is None:
                raise PoolError(
                    "candidate_not_found",
                    "One of the selected candidates is not available.",
                )
            uid = str(passport.get("user_id"))
            if uid not in ordered:
                ordered.append(uid)
    if student_user_ids:
        visible = _visible_student_ids(db, recruiter_user_id)
        for raw in student_user_ids:
            uid = str(raw or "").strip()
            if not uid or uid not in visible:
                raise PoolError(
                    "candidate_not_found",
                    "One of the selected candidates is not available.",
                )
            if uid not in ordered:
                ordered.append(uid)
    if not ordered:
        raise PoolError("no_candidates", "Select at least one candidate to add.")

    existing = _member_rows_for_pool(db, str(pool["id"]))
    existing_ids = {str(r.get("student_user_id")) for r in existing}
    if len(existing_ids | set(ordered)) > MAX_POOL_CANDIDATES:
        raise PoolError(
            "pool_full",
            f"A Talent Pool can hold up to {MAX_POOL_CANDIDATES} candidates.",
        )

    added = 0
    already = 0
    for uid in ordered:
        if uid in existing_ids:
            already += 1
            continue
        row = {
            "pool_id": str(pool["id"]),
            "student_user_id": uid,
            "source": str(source),
            "note": None,
            "added_at": _now_iso(),
        }
        try:
            _insert_member_row(db, row)
            added += 1
        except Exception:
            # Two tabs racing the same add: the (pool_id, student_user_id)
            # primary key rejects the loser — the candidate is in the pool
            # either way, so recover as "already in pool".
            if _member_row(db, str(pool["id"]), uid) is None:
                raise
            already += 1
        existing_ids.add(uid)

    _update_pool_row(
        db, recruiter_user_id, str(pool["id"]), {"updated_at": _now_iso()}
    )
    _record_pool_event(db, str(recruiter_user_id), "candidates_added", count=added)
    detail = list_pool_candidates(db, recruiter_user_id, str(pool["id"]))
    wanted = set(ordered)
    return {
        "added": added,
        "already_in_pool": already,
        "candidates": [
            v for v in detail["candidates"] if v["student_user_id"] in wanted
        ],
    }


def list_pool_candidates(
    db: Any, recruiter_user_id: str, pool_id: str
) -> dict[str, Any]:
    """The pool's members, newest first, each with consented public identity
    and light live evidence context (ONE batched fail-closed index read).
    Candidates who are no longer live carry ``evidence: None``."""
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)

    members = _member_rows_for_pool(db, str(pool["id"]))
    members = sorted(members, key=lambda r: str(r.get("added_at") or ""), reverse=True)
    valid = live_valid_index_rows(
        db, [str(r.get("student_user_id")) for r in members]
    )
    candidates = [
        _member_view(db, row, index_row=valid.get(str(row.get("student_user_id"))))
        for row in members
    ]
    return {
        "pool": _pool_view(pool, len(members)),
        "candidates": candidates,
        "total": len(candidates),
    }


def update_pool_candidate(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    student_user_id: str,
    *,
    note: Any = ...,
    clear_note: bool = False,
) -> dict[str, Any]:
    """Update one member's recruiter-private note. ``...`` means "leave
    unchanged"."""
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)
    row = _member_row(db, str(pool["id"]), str(student_user_id or "").strip())
    if row is None:
        raise PoolError(
            "candidate_not_found", "This candidate is not in this Talent Pool."
        )

    updates: dict[str, Any] = {}
    if clear_note:
        updates["note"] = None
    elif note is not ...:
        updates["note"] = str(note or "")[:MAX_NOTE_LENGTH] or None
    if updates:
        _update_member_row(db, str(pool["id"]), str(row["student_user_id"]), updates)

    refreshed = _member_row(db, str(pool["id"]), str(row["student_user_id"]))
    merged = refreshed or {**row, **updates}
    uid = str(merged.get("student_user_id"))
    return _member_view(db, merged, index_row=live_valid_index_rows(db, [uid]).get(uid))


def remove_pool_candidate(
    db: Any, recruiter_user_id: str, pool_id: str, student_user_id: str
) -> bool:
    """Remove one candidate from the pool. False when the pool is missing/
    foreign or the candidate is not in it (indistinguishable)."""
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        return False
    removed = _delete_member_row(
        db, str(pool["id"]), str(student_user_id or "").strip()
    )
    if removed:
        _update_pool_row(
            db, recruiter_user_id, str(pool["id"]), {"updated_at": _now_iso()}
        )
        _record_pool_event(db, str(recruiter_user_id), "candidate_removed", count=1)
    return removed


def pool_memberships(
    db: Any, recruiter_user_id: str, student_user_ids: list[str]
) -> dict[str, list[str]]:
    """{student_user_id → [pool ids]} across the recruiter's OWN pools —
    picker support ("Added ✓"). Foreign pools can never appear because the
    pool list itself is ownership-filtered."""
    wanted = {str(u or "").strip() for u in student_user_ids if str(u or "").strip()}
    if not wanted:
        return {}
    own_pool_ids = [str(r.get("id")) for r in _list_pool_rows(db, recruiter_user_id)]
    out: dict[str, list[str]] = {}
    for entry in _member_rows_for_pools(db, own_pool_ids):
        uid = str(entry.get("student_user_id"))
        if uid in wanted:
            out.setdefault(uid, []).append(str(entry.get("pool_id")))
    return out


__all__ = [
    "MAX_NOTE_LENGTH",
    "MAX_POOL_CANDIDATES",
    "MAX_POOL_DESCRIPTION",
    "MAX_POOL_NAME",
    "MAX_TALENT_POOLS",
    "POOL_CANDIDATE_SOURCES",
    "POOL_STATUSES",
    "PoolError",
    "PoolNotFound",
    "add_pool_candidates",
    "create_pool",
    "delete_pool",
    "get_pool",
    "list_pool_candidates",
    "list_pools",
    "pool_memberships",
    "remove_pool_candidate",
    "update_pool",
    "update_pool_candidate",
]
