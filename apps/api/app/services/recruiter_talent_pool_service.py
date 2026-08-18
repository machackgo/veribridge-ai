"""Recruiter talent pools — minimal recruiter-isolated grouping (migration 068).

A pool is a private label a recruiter puts on a set of saved candidates
("AI Engineer — Fall 2026"). V2 keeps this deliberately small: create, list,
delete, add/remove members, and feed the members into comparison. Members
are keyed by the student's stable user id (identity survives passport
re-publishing), and membership is NEVER visible to the candidate or to any
other recruiter — enforced app-level here (service role) and by RLS.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.recruiter_search_service import _read_with_transient_retry

logger = logging.getLogger(__name__)

_POOLS_TABLE = "recruiter_talent_pools"
_MEMBERS_TABLE = "recruiter_talent_pool_members"
_CONNECTIONS_TABLE = "recruiter_candidate_connections"

MAX_POOL_NAME_LENGTH = 80
MAX_POOLS_PER_RECRUITER = 50


class PoolError(Exception):
    """Recruiter-facing pool input problem (maps to 400/422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PoolNotFound(Exception):
    """Missing OR another recruiter's pool — indistinguishable."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pool_rows(db: Any) -> dict[str, dict[str, Any]]:
    return db.setdefault(_POOLS_TABLE, {})


def _member_rows(db: Any) -> dict[str, dict[str, Any]]:
    return db.setdefault(_MEMBERS_TABLE, {})


def _own_pools(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in _pool_rows(db).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_POOLS_TABLE)
            .select("*")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("created_at", desc=True)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)


def _own_pool(db: Any, recruiter_user_id: str, pool_id: str) -> dict[str, Any]:
    if isinstance(db, dict):
        row = _pool_rows(db).get(str(pool_id or ""))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            raise PoolNotFound(pool_id)
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
    if not rows:
        raise PoolNotFound(pool_id)
    return rows[0]


def _members_for_pools(db: Any, pool_ids: list[str]) -> dict[str, list[str]]:
    """pool_id → ordered member student user ids (added_at asc)."""
    if not pool_ids:
        return {}
    if isinstance(db, dict):
        rows = [
            r
            for r in _member_rows(db).values()
            if str(r.get("pool_id")) in {str(p) for p in pool_ids}
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_MEMBERS_TABLE)
            .select("*")
            .in_("pool_id", pool_ids)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    rows.sort(key=lambda r: str(r.get("added_at") or ""))
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(str(row.get("pool_id")), []).append(
            str(row.get("student_user_id"))
        )
    return out


def _pool_view(row: dict[str, Any], member_ids: list[str]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "name": str(row.get("name") or ""),
        "member_user_ids": member_ids,
        "member_count": len(member_ids),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ── Public API ───────────────────────────────────────────────────────────────


def create_pool(db: Any, recruiter_user_id: str, name: Any) -> dict[str, Any]:
    """Create a pool; re-creating an existing name returns the existing pool
    (idempotent, mirroring Save Candidate)."""
    cleaned = " ".join(str(name or "").split())[:MAX_POOL_NAME_LENGTH]
    if not cleaned:
        raise PoolError("pool_name_required", "Give the pool a name.")

    existing_pools = _own_pools(db, recruiter_user_id)
    match = next(
        (p for p in existing_pools if str(p.get("name") or "") == cleaned), None
    )
    if match is not None:
        members = _members_for_pools(db, [str(match["id"])])
        return _pool_view(match, members.get(str(match["id"]), []))
    if len(existing_pools) >= MAX_POOLS_PER_RECRUITER:
        raise PoolError(
            "too_many_pools",
            f"You can have up to {MAX_POOLS_PER_RECRUITER} talent pools.",
        )

    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "name": cleaned,
        "created_at": now,
        "updated_at": now,
    }
    if isinstance(db, dict):
        _pool_rows(db)[row["id"]] = row
    else:
        try:
            db.table(_POOLS_TABLE).insert(make_json_safe(row)).execute()
        except Exception:
            # Two tabs racing the same create: unique (recruiter, name)
            # rejects the loser — recover by re-reading the winner.
            match = next(
                (
                    p
                    for p in _own_pools(db, recruiter_user_id)
                    if str(p.get("name") or "") == cleaned
                ),
                None,
            )
            if match is None:
                raise
            members = _members_for_pools(db, [str(match["id"])])
            return _pool_view(match, members.get(str(match["id"]), []))
    return _pool_view(row, [])


def list_pools(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    pools = _own_pools(db, recruiter_user_id)
    members = _members_for_pools(db, [str(p["id"]) for p in pools])
    return [_pool_view(p, members.get(str(p["id"]), [])) for p in pools]


def delete_pool(db: Any, recruiter_user_id: str, pool_id: str) -> bool:
    """Delete the caller's OWN pool (members cascade). False for missing or
    foreign pools (indistinguishable)."""
    try:
        _own_pool(db, recruiter_user_id, pool_id)
    except PoolNotFound:
        return False
    if isinstance(db, dict):
        _pool_rows(db).pop(str(pool_id), None)
        stale = [
            k
            for k, r in _member_rows(db).items()
            if str(r.get("pool_id")) == str(pool_id)
        ]
        for key in stale:
            del _member_rows(db)[key]
        return True
    # DB-level cascade removes members.
    db.table(_POOLS_TABLE).delete().eq("id", pool_id).eq(
        "recruiter_user_id", recruiter_user_id
    ).execute()
    return True


def _own_connection_student_id(
    db: Any, recruiter_user_id: str, connection_id: str
) -> str | None:
    if isinstance(db, dict):
        row = db.setdefault(_CONNECTIONS_TABLE, {}).get(str(connection_id or ""))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return None
        return str(row.get("student_user_id"))
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_CONNECTIONS_TABLE)
        .select("student_user_id")
        .eq("id", connection_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return str(rows[0].get("student_user_id")) if rows else None


def add_member(
    db: Any, recruiter_user_id: str, pool_id: str, connection_id: str
) -> dict[str, Any]:
    """Add one of the caller's OWN saved candidates to their OWN pool
    (idempotent). Membership is by student user id, resolved through the
    connection so a recruiter can only ever pool candidates they saved."""
    pool = _own_pool(db, recruiter_user_id, pool_id)
    student_user_id = _own_connection_student_id(db, recruiter_user_id, connection_id)
    if student_user_id is None:
        raise PoolError(
            "candidate_not_found", "This saved candidate was not found."
        )

    member_key = f"{pool['id']}:{student_user_id}"
    row = {
        "pool_id": str(pool["id"]),
        "student_user_id": student_user_id,
        "added_at": _now_iso(),
    }
    if isinstance(db, dict):
        _member_rows(db).setdefault(member_key, row)
    else:
        try:
            db.table(_MEMBERS_TABLE).insert(make_json_safe(row)).execute()
        except Exception:
            # Composite PK rejects a repeat add — idempotent by design.
            existing = _members_for_pools(db, [str(pool["id"])]).get(
                str(pool["id"]), []
            )
            if student_user_id not in existing:
                raise
    members = _members_for_pools(db, [str(pool["id"])])
    return _pool_view(pool, members.get(str(pool["id"]), []))


def remove_member(
    db: Any, recruiter_user_id: str, pool_id: str, student_user_id: str
) -> dict[str, Any]:
    """Remove a member from the caller's OWN pool. Removing an absent member
    is a no-op (idempotent)."""
    pool = _own_pool(db, recruiter_user_id, pool_id)
    if isinstance(db, dict):
        _member_rows(db).pop(f"{pool['id']}:{student_user_id}", None)
    else:
        db.table(_MEMBERS_TABLE).delete().eq("pool_id", pool_id).eq(
            "student_user_id", student_user_id
        ).execute()
    members = _members_for_pools(db, [str(pool["id"])])
    return _pool_view(pool, members.get(str(pool["id"]), []))


__all__ = [
    "MAX_POOL_NAME_LENGTH",
    "PoolError",
    "PoolNotFound",
    "add_member",
    "create_pool",
    "delete_pool",
    "list_pools",
    "remove_member",
]
