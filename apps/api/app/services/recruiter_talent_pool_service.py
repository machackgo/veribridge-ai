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
from uuid import UUID, uuid4

from app.core.serialization import make_json_safe
from app.services.recruiter_comparison_service import (
    MAX_COMPARE_CANDIDATES,
    MIN_COMPARE_CANDIDATES,
    ComparisonError,
    _own_connection_rows,
    _published_passports_by_slugs,
    derive_observed_axis,
    evaluate_matrix,
    live_valid_index_rows,
    resolve_candidate_user_ids,
)
from app.services.recruiter_connection_service import (
    _candidate_summaries,
    _candidate_summary,
)
from app.services.recruiter_query_understanding import parse_recruiter_query
from app.services.recruiter_requirement_plan import requirements_view, sanitize_plan
from app.services.recruiter_search_service import (
    EVIDENCE_FILTERS,
    MAX_QUERY_LENGTH,
    _read_with_transient_retry,
    record_search_event,
    search_candidates,
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

# Must stay in sync with the CHECK constraint in migration 072.
# RECRUITER-PRIVATE workflow stage, scoped to THIS pool — deliberately the
# same shape as recruiter_hiring_brief_candidates.status (068). It is a
# property of the recruiter's process, never of the candidate: it changes no
# evidence, is invisible to the candidate, and does not travel to another
# pool, another brief, or any public surface.
POOL_CANDIDATE_STATUSES = ("review", "shortlisted", "interview", "hold", "pass")
_DEFAULT_STATUS = "review"

_TAGS_TABLE = "recruiter_candidate_tags"
MAX_TAG_LENGTH = 40
MAX_TAGS_PER_CANDIDATE = 12

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


def _addressable_id(db: Any, value: Any) -> str | None:
    """The id to query with, or None when it could not name a row.

    Against Supabase every id here reaches PostgREST as a ``uuid``
    comparison, and Postgres answers a MALFORMED one with an invalid-input
    error rather than an empty result — which surfaced as an unhandled 500
    for a URL like ``/recruiter/pools/not-a-uuid/filter``. Screening the
    shape first keeps the ownership contract intact: a malformed id is
    simply not found, exactly like a well-formed id belonging to someone
    else.

    Dict-backed stores (hermetic tests) have no such typing, so readable
    fixture ids like ``"u-alpha"`` stay valid there.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if isinstance(db, dict):
        return text
    try:
        UUID(text)
    except (ValueError, AttributeError, TypeError):
        return None
    return text


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _pool_row(db: Any, recruiter_user_id: str, pool_id: str) -> dict[str, Any] | None:
    pool_id = _addressable_id(db, pool_id)
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
    # A candidate id also arrives straight from the URL — screen its shape
    # for the same reason _pool_row does (see _addressable_id).
    if _addressable_id(db, student_user_id) is None:
        return None
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
    if _addressable_id(db, student_user_id) is None:
        return False
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


# ── Recruiter-private tags (RECRUITER JUDGEMENT, NEVER EVIDENCE) ─────────────
#
# A tag is the recruiter's own shorthand about a candidate ("Backend",
# "Career Fair", "Follow up"). Scoped to (recruiter, candidate) rather than
# to a pool, because it describes how THIS recruiter thinks about that
# person and should travel with them across every pool they appear in.
#
# Tags are never inferred, never derived from evidence, never written to
# recruiter_search_index or any public projection, and never visible to the
# candidate or to another recruiter. They organize; they do not verify.


def _tag_key(tag: Any) -> str:
    """Identity of a tag: case- and whitespace-insensitive, so "Back End",
    "back end" and "Back  End" are ONE tag rather than three."""
    return " ".join(str(tag or "").strip().lower().split())


def _normalize_tag(tag: Any) -> tuple[str, str] | None:
    """(display, key) for one recruiter-typed tag, or None when it is empty.
    The recruiter's own casing is preserved for display."""
    display = " ".join(str(tag or "").strip().split())[:MAX_TAG_LENGTH]
    key = _tag_key(display)
    if not key:
        return None
    return display, key


def _tag_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        return [
            r
            for r in db.setdefault(_TAGS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_TAGS_TABLE)
        .select("*")
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )
    return list(getattr(result, "data", []) or [])


def _tags_by_candidate(
    db: Any, recruiter_user_id: str, student_user_ids: list[str]
) -> dict[str, list[str]]:
    """{student_user_id → [tag displays]} for the caller's OWN tags, in ONE
    read. Ownership is in the query itself, so another recruiter's tags can
    never appear."""
    wanted = {str(u) for u in student_user_ids if str(u or "").strip()}
    if not wanted:
        return {}
    out: dict[str, list[str]] = {}
    for row in _tag_rows(db, recruiter_user_id):
        uid = str(row.get("student_user_id"))
        if uid in wanted:
            out.setdefault(uid, []).append(str(row.get("tag") or ""))
    return {uid: sorted(tags, key=str.lower) for uid, tags in out.items()}


def _insert_tag_row(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        key = (
            f"{row['recruiter_user_id']}:{row['student_user_id']}:{row['tag_key']}"
        )
        db.setdefault(_TAGS_TABLE, {})[key] = row
        return
    db.table(_TAGS_TABLE).insert(make_json_safe(row)).execute()


def _delete_tag_rows(
    db: Any, recruiter_user_id: str, student_user_id: str, tag_keys: list[str]
) -> None:
    if not tag_keys:
        return
    if isinstance(db, dict):
        store = db.setdefault(_TAGS_TABLE, {})
        for key in tag_keys:
            store.pop(f"{recruiter_user_id}:{student_user_id}:{key}", None)
        return
    (
        db.table(_TAGS_TABLE)
        .delete()
        .eq("recruiter_user_id", recruiter_user_id)
        .eq("student_user_id", student_user_id)
        .in_("tag_key", tag_keys)
        .execute()
    )


def set_candidate_tags(
    db: Any, recruiter_user_id: str, student_user_id: str, tags: Any
) -> list[str]:
    """Replace the caller's tag set for one candidate; returns the stored
    displays. Idempotent: an unchanged set writes nothing."""
    student_user_id = str(student_user_id or "").strip()
    if not student_user_id:
        raise PoolError("candidate_not_found", "Unknown candidate.")

    wanted: dict[str, str] = {}
    for raw in list(tags or [])[: MAX_TAGS_PER_CANDIDATE * 2]:
        normalized = _normalize_tag(raw)
        if normalized is None:
            continue
        display, key = normalized
        wanted.setdefault(key, display)
    if len(wanted) > MAX_TAGS_PER_CANDIDATE:
        raise PoolError(
            "too_many_tags",
            f"Up to {MAX_TAGS_PER_CANDIDATE} tags per candidate.",
        )

    existing = {
        str(r.get("tag_key")): str(r.get("tag") or "")
        for r in _tag_rows(db, recruiter_user_id)
        if str(r.get("student_user_id")) == student_user_id
    }
    _delete_tag_rows(
        db,
        str(recruiter_user_id),
        student_user_id,
        [k for k in existing if k not in wanted],
    )
    for key, display in wanted.items():
        if key in existing:
            continue
        _insert_tag_row(
            db,
            {
                "recruiter_user_id": str(recruiter_user_id),
                "student_user_id": student_user_id,
                "tag": display,
                "tag_key": key,
                "created_at": _now_iso(),
            },
        )
    return sorted(wanted.values(), key=str.lower)


def list_recruiter_tags(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    """The caller's whole private tag vocabulary with usage counts —
    autocomplete + pool filter chips. Never another recruiter's."""
    counts: dict[str, dict[str, Any]] = {}
    for row in _tag_rows(db, recruiter_user_id):
        key = str(row.get("tag_key") or "")
        if not key:
            continue
        entry = counts.setdefault(
            key, {"tag": str(row.get("tag") or ""), "tag_key": key, "candidate_count": 0}
        )
        entry["candidate_count"] += 1
    return sorted(counts.values(), key=lambda e: (-e["candidate_count"], e["tag_key"]))


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


def _status_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """How many pool members sit at each workflow stage. A count of the
    recruiter's own process — not a measure of any candidate."""
    counts = {status: 0 for status in POOL_CANDIDATE_STATUSES}
    for entry in candidates:
        status = str(entry.get("status") or _DEFAULT_STATUS)
        if status in counts:
            counts[status] += 1
    return counts


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
    db: Any,
    row: dict[str, Any],
    *,
    index_row: dict[str, Any] | None,
    identity: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """One pool member card.

    ``identity`` and ``tags`` are passed in by the batched listing paths so a
    pool of N candidates costs a constant number of queries; when omitted
    (single-row paths) they are resolved here.

    The two data domains stay visibly separate in the payload: ``candidate``
    and ``evidence`` are VeriBridge's consented, live, fail-closed evidence
    projection, while ``status``, ``note`` and ``tags`` are this recruiter's
    private judgement and are never derived from — or written back into —
    anything above.
    """
    student_user_id = str(row.get("student_user_id"))
    return {
        "student_user_id": student_user_id,
        "source": str(row.get("source") or _DEFAULT_SOURCE),
        # ── recruiter-private workflow metadata ──
        "status": str(row.get("status") or _DEFAULT_STATUS),
        "note": row.get("note"),
        "tags": list(tags) if tags is not None else [],
        "added_at": row.get("added_at"),
        "updated_at": row.get("updated_at"),
        # ── VeriBridge evidence domain ──
        "candidate": identity
        if identity is not None
        else _candidate_summary(db, student_user_id),
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
            # Honest default: a candidate lands in a pool to be looked at,
            # never pre-judged.
            "status": _DEFAULT_STATUS,
            "note": None,
            "added_at": _now_iso(),
            "updated_at": _now_iso(),
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
    member_ids = [str(r.get("student_user_id")) for r in members]
    # Three batched reads for the whole pool (evidence index, consented
    # identity, recruiter tags) instead of a per-candidate fan-out.
    valid = live_valid_index_rows(db, member_ids)
    identities = _candidate_summaries(db, member_ids)
    tags = _tags_by_candidate(db, recruiter_user_id, member_ids)
    candidates = [
        _member_view(
            db,
            row,
            index_row=valid.get(str(row.get("student_user_id"))),
            identity=identities.get(str(row.get("student_user_id"))),
            tags=tags.get(str(row.get("student_user_id")), []),
        )
        for row in members
    ]
    return {
        "pool": _pool_view(pool, len(members)),
        "candidates": candidates,
        "total": len(candidates),
        "status_counts": _status_counts(candidates),
        "tag_vocabulary": list_recruiter_tags(db, recruiter_user_id),
    }


def update_pool_candidate(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    student_user_id: str,
    *,
    note: Any = ...,
    clear_note: bool = False,
    status: Any = ...,
    tags: Any = ...,
) -> dict[str, Any]:
    """Update one member's RECRUITER-PRIVATE workflow metadata — pool-scoped
    note and status, plus the recruiter's tags for that candidate.
    ``...`` means "leave unchanged".

    None of this touches the candidate's evidence, Work Passport, skill
    verification, Verified Build Reports or any public projection: the write
    targets only recruiter-owned rows, and the response re-reads the evidence
    side live and unchanged.
    """
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
    if status is not ...:
        candidate_status = str(status or "").strip()
        if candidate_status not in POOL_CANDIDATE_STATUSES:
            raise PoolError("invalid_status", "Unknown workflow status.")
        updates["status"] = candidate_status
    if updates:
        updates["updated_at"] = _now_iso()
        _update_member_row(db, str(pool["id"]), str(row["student_user_id"]), updates)

    uid = str(row["student_user_id"])
    stored_tags: list[str] | None = None
    if tags is not ...:
        stored_tags = set_candidate_tags(db, recruiter_user_id, uid, tags)

    refreshed = _member_row(db, str(pool["id"]), uid)
    merged = refreshed or {**row, **updates}
    if stored_tags is None:
        stored_tags = _tags_by_candidate(db, recruiter_user_id, [uid]).get(uid, [])
    return _member_view(
        db,
        merged,
        index_row=live_valid_index_rows(db, [uid]).get(uid),
        tags=stored_tags,
    )


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


# ── Pool-scoped evidence filtering + comparison (V6) ─────────────────────────
#
# Both reuse the recruiter engine wholesale. There is deliberately NO second
# matcher and NO second requirement language: the pool filter runs the same
# deterministic query understanding, the same taxonomy contract (a child
# skill proves a parent requirement, never the reverse; "related" proves
# nothing) and the same fail-closed privacy re-validation as global search,
# only narrowed to this pool's members. Comparison runs the same evidence
# matrix a Hiring Brief runs.


def _pool_member_ids(db: Any, pool: dict[str, Any]) -> list[str]:
    rows = _member_rows_for_pool(db, str(pool["id"]))
    rows = sorted(rows, key=lambda r: str(r.get("added_at") or ""), reverse=True)
    return [str(r.get("student_user_id")) for r in rows]


def filter_pool_candidates(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    *,
    q: Any = None,
    evidence: list[str] | None = None,
    status: Any = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Filter ONE pool's members, by published evidence and/or by the
    recruiter's own workflow metadata.

    Two filter domains, deliberately applied in this order and reported
    separately, because they mean different things:

      1. RECRUITER metadata (``status``, ``tags``) — the recruiter's private
         organization. Applied first, as plain membership predicates.
      2. VeriBridge EVIDENCE (``q``, ``evidence``) — run through the shared
         search engine restricted to the surviving members, so every returned
         candidate is there because their PUBLISHED evidence satisfied the
         requirement, and the reason is reconstructed from that same
         evaluation rather than asserted.

    Honest by construction:
      * a member with no live index row (unpublished / excluded / stale
        disclosure) can never satisfy an evidence requirement, so they drop
        out and are counted in ``unavailable_excluded`` for the UI to say so;
      * terms the parser could not turn into a requirement come back in
        ``interpretation.unrecognized_terms`` — never silently treated as a
        match;
      * no query and no filters returns the pool unchanged, not an empty
        "no results" state;
      * only candidates satisfying EVERY requirement are results. Candidates
        missing at least one come back separately in ``close_candidates``
        with the gap already named, so a near miss is never silently
        promoted into a match.

    INHERITED SEMANTICS worth stating plainly, because it is coarser than a
    recruiter may assume: an evidence requirement is CANDIDATE-level. "machine
    learning with GitHub proof" asks for a candidate who has published machine
    learning evidence AND has published GitHub evidence — it does not require
    that the GitHub proof is what backs the machine learning. This is the
    shipped V1.5 contract that global search, Hiring Briefs, Saved Searches
    and comparison all evaluate, and changing it here would fork the engine.
    It is not fabrication (both facts are published and inspectable), but it
    IS a coarse reading, so ``interpretation`` returns exactly what was
    executed and the UI shows it back to the recruiter rather than leaving
    them to assume a tighter binding.
    """
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)

    query_text = str(q or "").strip()[:MAX_QUERY_LENGTH]
    evidence_gate = [e for e in (evidence or []) if e in EVIDENCE_FILTERS]
    status_filter = str(status or "").strip() or None
    if status_filter and status_filter not in POOL_CANDIDATE_STATUSES:
        raise PoolError("invalid_status", "Unknown workflow status.")
    tag_keys = {k for k in (_tag_key(t) for t in (tags or [])) if k}

    members = _member_rows_for_pool(db, str(pool["id"]))
    members = sorted(members, key=lambda r: str(r.get("added_at") or ""), reverse=True)
    member_ids = [str(r.get("student_user_id")) for r in members]
    total_members = len(members)

    # ── 1. recruiter-private predicates ──
    if status_filter:
        members = [
            r for r in members if str(r.get("status") or _DEFAULT_STATUS) == status_filter
        ]
    tags_by_candidate = _tags_by_candidate(db, recruiter_user_id, member_ids)
    if tag_keys:
        members = [
            r
            for r in members
            if tag_keys
            <= {
                _tag_key(t)
                for t in tags_by_candidate.get(str(r.get("student_user_id")), [])
            }
        ]

    surviving_ids = [str(r.get("student_user_id")) for r in members]

    # ── 2. evidence predicates, through the shared engine ──
    matches: dict[str, dict[str, Any]] = {}
    interpretation: dict[str, Any] | None = None
    unavailable_excluded = 0
    evidence_filtered = bool(query_text or evidence_gate)

    if evidence_filtered and surviving_ids:
        # sanitize_plan forces candidate_search intent, so a phrase the
        # classifier would treat as global evidence discovery ("show me proof
        # of FastAPI") stays a POOL-SCOPED candidate filter and can never
        # reach outside this pool.
        plan = sanitize_plan(parse_recruiter_query(query_text)) if query_text else None
        result = search_candidates(
            db,
            q=query_text or None,
            evidence=evidence_gate,
            plan=plan,
            page=1,
            page_size=MAX_POOL_CANDIDATES,
            restrict_user_ids=surviving_ids,
        )
        interpretation = result.get("interpretation")
        # Result cards are keyed by public_slug (the engine deliberately does
        # not emit stable user ids into search payloads), so map back through
        # the live index rows we already have to hold.
        live_rows = live_valid_index_rows(db, surviving_ids)
        uid_by_slug = {
            str(row.get("public_slug") or ""): uid
            for uid, row in live_rows.items()
            if str(row.get("public_slug") or "")
        }
        for card in result.get("results") or []:
            uid = uid_by_slug.get(str(card.get("public_slug") or ""))
            if uid:
                matches[uid] = card
        unavailable_excluded = len([u for u in surviving_ids if u not in live_rows])
        members = [r for r in members if str(r.get("student_user_id")) in matches]

    # ── 3. build the same pool cards the workspace shows ──
    kept_ids = [str(r.get("student_user_id")) for r in members]
    valid = live_valid_index_rows(db, kept_ids)
    identities = _candidate_summaries(db, kept_ids)
    candidates = []
    for row in members:
        uid = str(row.get("student_user_id"))
        view = _member_view(
            db,
            row,
            index_row=valid.get(uid),
            identity=identities.get(uid),
            tags=tags_by_candidate.get(uid, []),
        )
        card = matches.get(uid)
        # WHY this candidate matched — reconstructed from the deterministic
        # evaluation, so every reason is inspectable evidence, never prose.
        view["match"] = (
            {
                "match_type": str(card.get("match_type") or "match"),
                "requirements": list(card.get("requirements") or []),
                "missing_requirements": list(card.get("missing_requirements") or []),
                "matched_reasons": list(card.get("matched_reasons") or []),
                # Proof entry points for the matched skills, straight from the
                # public projection: the recruiter can open the evidence that
                # put this candidate in the result.
                "skills": list(card.get("skills") or []),
                "projects": list(card.get("projects") or []),
            }
            if card is not None
            else None
        )
        candidates.append(view)

    # A filter must mean what it says. The engine classifies a candidate who
    # satisfies EVERY requirement as "exact" and one missing at least one as
    # "close"; only exact matches are results. Close ones are returned in
    # their own list, with what they are missing already named, so the
    # recruiter can widen deliberately — a near miss is never silently
    # promoted into a match, and an honest empty result beats a padded one.
    close: list[dict[str, Any]] = []
    if evidence_filtered:
        exact: list[dict[str, Any]] = []
        for view in candidates:
            match_type = str((view.get("match") or {}).get("match_type") or "match")
            (close if match_type == "close" else exact).append(view)
        candidates = exact

    _record_pool_event(
        db, str(recruiter_user_id), "filter", count=len(candidates)
    )
    return {
        "pool": _pool_view(pool, total_members),
        "candidates": candidates,
        "total": len(candidates),
        "close_candidates": close,
        "close_total": len(close),
        "pool_total": total_members,
        "status_counts": _status_counts(candidates),
        "tag_vocabulary": list_recruiter_tags(db, recruiter_user_id),
        "filters": {
            "q": query_text,
            "evidence": evidence_gate,
            "status": status_filter,
            "tags": sorted({t for t in (tags or []) if _tag_key(t)}, key=str.lower),
        },
        "interpretation": interpretation,
        "unavailable_excluded": unavailable_excluded,
    }


def pool_comparison(
    db: Any,
    recruiter_user_id: str,
    pool_id: str,
    *,
    candidate_user_ids: list[str],
    q: Any = None,
) -> dict[str, Any]:
    """The requirement x candidate evidence matrix for 2-5 pool members.

    A pool owns no requirement plan (unlike a Hiring Brief it is
    role-independent), so the axis comes from one of two honest places:

      * ``q`` given -> the recruiter's own words, parsed by the SAME query
        understanding the pool filter and global search use;
      * no ``q`` -> the union of skills the SELECTED CANDIDATES have
        themselves published evidence for (``derive_observed_axis``). Those
        rows are facts about the corpus, marked ``origin=observed``, and are
        never counted or described as things the recruiter required.

    Comparison never hides a selected candidate and never ranks them: cells
    carry the closed evidence-state vocabulary plus the provenance needed to
    walk skill -> project -> proof, and columns report transparent counts.
    """
    pool = _pool_row(db, recruiter_user_id, pool_id)
    if pool is None:
        raise PoolNotFound(pool_id)

    member_ids = set(_pool_member_ids(db, pool))
    ordered = resolve_candidate_user_ids(
        db,
        str(recruiter_user_id),
        candidate_user_ids=[str(u) for u in (candidate_user_ids or [])],
        allowed_user_ids=member_ids,
        scope_noun="Talent Pool",
    )

    query_text = str(q or "").strip()[:MAX_QUERY_LENGTH]
    plan = sanitize_plan(parse_recruiter_query(query_text)) if query_text else {}
    extra_axis = None
    if not query_text:
        extra_axis = derive_observed_axis(
            list(live_valid_index_rows(db, ordered).values())
        )

    matrix = evaluate_matrix(
        db,
        recruiter_user_id=str(recruiter_user_id),
        candidate_user_ids=ordered,
        plan=plan,
        extra_axis=extra_axis,
    )

    # Annotate each column with THIS pool's recruiter-private workflow state
    # so the recruiter can act (shortlist, note) without leaving comparison.
    # Kept in its own key: it is never mixed into evidence cells or counts.
    member_rows = {
        str(r.get("student_user_id")): r
        for r in _member_rows_for_pool(db, str(pool["id"]))
    }
    tags = _tags_by_candidate(db, recruiter_user_id, ordered)
    for column in matrix.get("columns") or []:
        uid = str(column.get("user_id"))
        row = member_rows.get(uid) or {}
        column["pool_status"] = str(row.get("status") or _DEFAULT_STATUS)
        column["pool_note"] = row.get("note")
        column["tags"] = tags.get(uid, [])

    _record_pool_event(
        db, str(recruiter_user_id), "comparison", count=len(ordered)
    )
    return {
        "pool": _pool_view(pool, len(member_ids)),
        "matrix": matrix,
        "query": query_text or None,
        "requirements_view": requirements_view(sanitize_plan(plan)),
    }


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
    "MAX_TAGS_PER_CANDIDATE",
    "MAX_TAG_LENGTH",
    "MAX_POOL_CANDIDATES",
    "MAX_POOL_DESCRIPTION",
    "MAX_POOL_NAME",
    "MAX_TALENT_POOLS",
    "POOL_CANDIDATE_SOURCES",
    "POOL_CANDIDATE_STATUSES",
    "POOL_STATUSES",
    "PoolError",
    "PoolNotFound",
    "add_pool_candidates",
    "create_pool",
    "delete_pool",
    "filter_pool_candidates",
    "get_pool",
    "list_recruiter_tags",
    "list_pool_candidates",
    "list_pools",
    "pool_comparison",
    "pool_memberships",
    "remove_pool_candidate",
    "set_candidate_tags",
    "update_pool",
    "update_pool_candidate",
]
