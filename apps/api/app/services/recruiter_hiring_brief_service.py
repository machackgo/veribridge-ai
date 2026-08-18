"""Recruiter Hiring Briefs — persistence + role workspace (migration 068).

The Hiring Brief is the recruiter-owned source of truth for one hiring
need: the recruiter defines the role ONCE (raw role text and/or edited
requirement chips → the canonical plan owned by
``recruiter_requirement_plan``) and the same brief then powers search,
candidate association, comparison, and ROLE-SCOPED shortlisting:

  * the brief IS the role's candidate pool — one
    ``recruiter_hiring_brief_candidates`` row per (brief, student), keyed by
    the student's STABLE user id, carrying the role-scoped review status
    (saved | reviewing | shortlisted | archived) and a recruiter-private,
    role-specific note. A candidate shortlisted for one brief is
    deliberately NOT shortlisted anywhere else.
  * comparison is a LIVE VIEW over the brief's plan and pool
    (``recruiter_comparison_service.evaluate_matrix``) — nothing here
    stores an evidence snapshot, so unpublished evidence can never be
    served stale.
  * brief-scoped search drives ``search_candidates`` with the brief's
    stored plan (optionally overlaid with a temporary refinement) instead
    of free text, and annotates results with pool membership.

Isolation: the API runs with the service role (RLS bypassed), so every
read/write here filters by ``recruiter_user_id`` in application code —
that filter is the real boundary between recruiters. Foreign briefs and
pool rows are indistinguishable from missing ones.

Privacy: briefs, plans, statuses and notes are recruiter-private workflow
data — never written to any index, embedding, public projection, or
candidate-facing surface. Candidate identity in views reuses the SAME
consented public projection as the workspace listing.

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
    MAX_COMPARE_CANDIDATES,
    ComparisonError,
    _index_rows_by_user_ids,
    _own_connection_rows,
    _published_passports_by_slugs,
    evaluate_candidate_summary,
    evaluate_matrix,
    live_valid_index_rows,
    resolve_candidate_user_ids,
)
from app.services.recruiter_connection_service import _candidate_summary
from app.services.recruiter_requirement_plan import (
    merge_refinement,
    plan_from_requirements,
    requirements_view,
    sanitize_plan,
)
from app.services.recruiter_search_service import (
    _read_with_transient_retry,
    search_candidates,
)

logger = logging.getLogger(__name__)

_BRIEFS_TABLE = "recruiter_hiring_briefs"
_BRIEF_CANDIDATES_TABLE = "recruiter_hiring_brief_candidates"

# Must stay in sync with the CHECK constraints in migration 068.
BRIEF_STATUSES = ("draft", "active", "paused", "closed")
BRIEF_CANDIDATE_STATUSES = ("saved", "reviewing", "shortlisted", "archived")

MAX_TITLE_LENGTH = 120
MAX_NOTE_LENGTH = 2000
MAX_LIST_BRIEFS = 100
MAX_BRIEF_CANDIDATES = 100


class BriefNotFound(Exception):
    """Brief id does not exist for this recruiter (foreign == missing)."""


class BriefError(Exception):
    """Recruiter-facing brief input problem (maps to 400/404)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pool_key(brief_id: str, student_user_id: str) -> str:
    return f"{brief_id}:{student_user_id}"


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _brief_row(db: Any, recruiter_user_id: str, brief_id: str) -> dict[str, Any] | None:
    brief_id = str(brief_id or "").strip()
    if not brief_id:
        return None
    if isinstance(db, dict):
        row = db.setdefault(_BRIEFS_TABLE, {}).get(brief_id)
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return None
        return row
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEFS_TABLE)
        .select("*")
        .eq("id", brief_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _list_brief_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_BRIEFS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_BRIEFS_TABLE)
            .select("*")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("updated_at", desc=True)
            .limit(MAX_LIST_BRIEFS)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[
        :MAX_LIST_BRIEFS
    ]


def _insert_brief(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_BRIEFS_TABLE, {})[row["id"]] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEFS_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_brief_row(
    db: Any, recruiter_user_id: str, brief_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_BRIEFS_TABLE, {}).get(str(brief_id))
        if row is not None and str(row.get("recruiter_user_id")) == str(
            recruiter_user_id
        ):
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEFS_TABLE)
        .update(make_json_safe(updates))
        .eq("id", brief_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )


def _delete_brief_row(db: Any, recruiter_user_id: str, brief_id: str) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_BRIEFS_TABLE, {})
        row = table.get(str(brief_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return False
        del table[str(brief_id)]
        # Mirror ON DELETE CASCADE for the pool rows in dict mode.
        pool = db.setdefault(_BRIEF_CANDIDATES_TABLE, {})
        for key in [
            k for k, r in pool.items() if str(r.get("brief_id")) == str(brief_id)
        ]:
            del pool[key]
        return True
    result = (
        db.table(_BRIEFS_TABLE)
        .delete()
        .eq("id", brief_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


def _pool_rows_for_brief(db: Any, brief_id: str) -> list[dict[str, Any]]:
    """Pool rows for ONE brief. Callers must have resolved the brief through
    ``_brief_row`` first — ownership is enforced there."""
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_BRIEF_CANDIDATES_TABLE, {}).values()
            if str(r.get("brief_id")) == str(brief_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
            .select("*")
            .eq("brief_id", brief_id)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("added_at") or ""))


def _pool_rows_for_briefs(db: Any, brief_ids: list[str]) -> list[dict[str, Any]]:
    if not brief_ids:
        return []
    if isinstance(db, dict):
        wanted = {str(b) for b in brief_ids}
        return [
            r
            for r in db.setdefault(_BRIEF_CANDIDATES_TABLE, {}).values()
            if str(r.get("brief_id")) in wanted
        ]
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
        .select("brief_id, status")
        .in_("brief_id", brief_ids)
        .execute(),
    )
    return list(getattr(result, "data", []) or [])


def _pool_row(db: Any, brief_id: str, student_user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.setdefault(_BRIEF_CANDIDATES_TABLE, {}).get(
            _pool_key(str(brief_id), str(student_user_id))
        )
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
        .select("*")
        .eq("brief_id", brief_id)
        .eq("student_user_id", student_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _insert_pool_row(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_BRIEF_CANDIDATES_TABLE, {})[
            _pool_key(row["brief_id"], row["student_user_id"])
        ] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_pool_row(
    db: Any, brief_id: str, student_user_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_BRIEF_CANDIDATES_TABLE, {}).get(
            _pool_key(str(brief_id), str(student_user_id))
        )
        if row is not None:
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_BRIEF_CANDIDATES_TABLE)
        .update(make_json_safe(updates))
        .eq("brief_id", brief_id)
        .eq("student_user_id", student_user_id)
        .execute(),
    )


def _delete_pool_row(db: Any, brief_id: str, student_user_id: str) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_BRIEF_CANDIDATES_TABLE, {})
        key = _pool_key(str(brief_id), str(student_user_id))
        if key not in table:
            return False
        del table[key]
        return True
    result = (
        db.table(_BRIEF_CANDIDATES_TABLE)
        .delete()
        .eq("brief_id", brief_id)
        .eq("student_user_id", student_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


# ── Views ────────────────────────────────────────────────────────────────────


def _status_counts(pool_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in BRIEF_CANDIDATE_STATUSES}
    for row in pool_rows:
        status = str(row.get("status") or "saved")
        if status in counts:
            counts[status] += 1
    return counts


def default_brief_title(plan: dict[str, Any], role_text: Any) -> str:
    """Deterministic title when the recruiter did not name the brief."""
    role = ((plan.get("role") or {}).get("display") or "").strip()
    if role:
        seniority = ((plan.get("seniority") or {}).get("display") or "").strip()
        return f"{seniority} {role}".strip()[:MAX_TITLE_LENGTH]
    text = " ".join(str(role_text or "").split()).strip()
    if text:
        return (text[:57] + "…") if len(text) > 60 else text
    return "Untitled role"


def brief_view(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    plan = sanitize_plan(row.get("plan"))
    pool = _pool_rows_for_brief(db, str(row.get("id")))
    return {
        "id": str(row.get("id")),
        "title": str(row.get("title") or "Untitled role"),
        "role_text": row.get("role_text"),
        "status": str(row.get("status") or "active"),
        "requirements_view": requirements_view(plan),
        "candidate_count": len(pool),
        "status_counts": _status_counts(pool),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _brief_list_item(
    row: dict[str, Any], pool_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    plan = sanitize_plan(row.get("plan"))
    counts = _status_counts(pool_rows)
    return {
        "id": str(row.get("id")),
        "title": str(row.get("title") or "Untitled role"),
        "role": (plan.get("role") or {}).get("display"),
        "status": str(row.get("status") or "active"),
        "candidate_count": len(pool_rows),
        "shortlisted_count": counts["shortlisted"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _pool_row_view(
    db: Any,
    row: dict[str, Any],
    *,
    connection_id_by_student: dict[str, str],
    evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    student_user_id = str(row.get("student_user_id"))
    return {
        "student_user_id": student_user_id,
        "status": str(row.get("status") or "saved"),
        "note": row.get("note"),
        "connection_id": connection_id_by_student.get(student_user_id),
        "candidate": _candidate_summary(db, student_user_id),
        "evaluation": evaluation,
        "added_at": row.get("added_at"),
        "updated_at": row.get("updated_at"),
    }


# ── Brief CRUD ───────────────────────────────────────────────────────────────


def create_brief(
    db: Any,
    recruiter_user_id: str,
    *,
    plan: dict[str, Any],
    title: Any = None,
    role_text: Any = None,
    status: Any = None,
) -> dict[str, Any]:
    plan = sanitize_plan(plan)
    cleaned_title = str(title or "").strip()[:MAX_TITLE_LENGTH]
    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "title": cleaned_title or default_brief_title(plan, role_text),
        "role_text": str(role_text or "").strip() or None,
        "plan": plan,
        "status": status if status in BRIEF_STATUSES else "active",
        "created_at": now,
        "updated_at": now,
    }
    _insert_brief(db, row)
    return row


def list_briefs(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    """The recruiter's briefs, most recently updated first, with transparent
    pool counts."""
    rows = _list_brief_rows(db, recruiter_user_id)
    pool = _pool_rows_for_briefs(db, [str(r.get("id")) for r in rows])
    by_brief: dict[str, list[dict[str, Any]]] = {}
    for entry in pool:
        by_brief.setdefault(str(entry.get("brief_id")), []).append(entry)
    return [_brief_list_item(row, by_brief.get(str(row.get("id")), [])) for row in rows]


def get_brief(db: Any, recruiter_user_id: str, brief_id: str) -> dict[str, Any]:
    row = _brief_row(db, recruiter_user_id, brief_id)
    if row is None:
        raise BriefNotFound(brief_id)
    return brief_view(db, row)


def update_brief(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    *,
    plan: dict[str, Any] | None = None,
    title: Any = ...,
    role_text: Any = ...,
    status: Any = ...,
) -> dict[str, Any]:
    """Partial update; ``...`` means "leave unchanged". A new ``plan``
    replaces the stored plan (the caller derives it from edited chips or
    re-parsed role text)."""
    row = _brief_row(db, recruiter_user_id, brief_id)
    if row is None:
        raise BriefNotFound(brief_id)

    updates: dict[str, Any] = {"updated_at": _now_iso()}
    if plan is not None:
        updates["plan"] = sanitize_plan(plan)
    if role_text is not ...:
        updates["role_text"] = str(role_text or "").strip() or None
    if title is not ...:
        cleaned = str(title or "").strip()[:MAX_TITLE_LENGTH]
        updates["title"] = cleaned or default_brief_title(
            updates.get("plan", sanitize_plan(row.get("plan"))),
            updates.get("role_text", row.get("role_text")),
        )
    if status is not ...:
        if status not in BRIEF_STATUSES:
            raise BriefError("invalid_status", "Unknown brief status.")
        updates["status"] = status

    _update_brief_row(db, recruiter_user_id, str(row["id"]), updates)
    refreshed = _brief_row(db, recruiter_user_id, str(row["id"]))
    return brief_view(db, refreshed or {**row, **updates})


def delete_brief(db: Any, recruiter_user_id: str, brief_id: str) -> bool:
    """Delete one of the caller's OWN briefs (pool rows cascade). Returns
    False when the id does not exist or is another recruiter's
    (indistinguishable)."""
    return _delete_brief_row(db, recruiter_user_id, str(brief_id or ""))


# ── Role-scoped candidate pool ───────────────────────────────────────────────


def _connection_ids_by_student(db: Any, recruiter_user_id: str) -> dict[str, str]:
    return {
        str(r.get("student_user_id")): str(r.get("id"))
        for r in _own_connection_rows(db, recruiter_user_id)
    }


def add_brief_candidates(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    *,
    connection_ids: list[str] | None = None,
    candidate_slugs: list[str] | None = None,
) -> dict[str, Any]:
    """Idempotently add candidates to the brief's pool with role-scoped
    status ``saved``. Candidates resolve exactly like comparison selection:
    own connections (foreign == missing) and/or actively published slugs."""
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)

    ordered: list[str] = []
    if connection_ids:
        own = {str(r.get("id")): r for r in _own_connection_rows(db, recruiter_user_id)}
        for cid in connection_ids:
            row = own.get(str(cid or "").strip())
            if row is None:
                raise BriefError(
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
                raise BriefError(
                    "candidate_not_found",
                    "One of the selected candidates is not available.",
                )
            uid = str(passport.get("user_id"))
            if uid not in ordered:
                ordered.append(uid)
    if not ordered:
        raise BriefError("no_candidates", "Select at least one candidate to add.")

    existing_pool = _pool_rows_for_brief(db, str(brief["id"]))
    existing_ids = {str(r.get("student_user_id")) for r in existing_pool}
    if len(existing_ids | set(ordered)) > MAX_BRIEF_CANDIDATES:
        raise BriefError(
            "pool_full",
            f"A role can hold up to {MAX_BRIEF_CANDIDATES} candidates.",
        )

    added = 0
    already = 0
    for uid in ordered:
        if uid in existing_ids:
            already += 1
            continue
        now = _now_iso()
        row = {
            "brief_id": str(brief["id"]),
            "student_user_id": uid,
            "status": "saved",
            "note": None,
            "added_at": now,
            "updated_at": now,
        }
        try:
            _insert_pool_row(db, row)
            added += 1
        except Exception:
            # Two tabs racing the same add: the (brief_id, student_user_id)
            # primary key rejects the loser — the candidate is in the pool
            # either way, so recover as "already in brief".
            if _pool_row(db, str(brief["id"]), uid) is None:
                raise
            already += 1
        existing_ids.add(uid)

    _update_brief_row(
        db, recruiter_user_id, str(brief["id"]), {"updated_at": _now_iso()}
    )
    views = list_brief_candidates(db, recruiter_user_id, str(brief["id"]))
    wanted = set(ordered)
    return {
        "added": added,
        "already_in_brief": already,
        "candidates": [
            v for v in views["candidates"] if v["student_user_id"] in wanted
        ],
    }


def list_brief_candidates(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    *,
    with_evaluation: bool = True,
) -> dict[str, Any]:
    """The brief's pool, newest first, each with consented public identity
    and (optionally) a LIVE lightweight evaluation against the brief's
    requirements — unavailable candidates evaluate honestly as such."""
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)

    pool = _pool_rows_for_brief(db, str(brief["id"]))
    pool = sorted(pool, key=lambda r: str(r.get("added_at") or ""), reverse=True)
    connection_ids = _connection_ids_by_student(db, recruiter_user_id)

    evaluations: dict[str, dict[str, Any] | None] = {}
    if with_evaluation and pool:
        plan = sanitize_plan(brief.get("plan"))
        user_ids = [str(r.get("student_user_id")) for r in pool]
        valid = live_valid_index_rows(db, user_ids)
        for uid in user_ids:
            index_row = valid.get(uid)
            if index_row is None:
                evaluations[uid] = {
                    "available": False,
                    "counts": {},
                    "missing_required": [],
                    "missing_preferred": [],
                    "excluded_hits": [],
                }
            else:
                evaluations[uid] = evaluate_candidate_summary(index_row, plan)

    candidates = [
        _pool_row_view(
            db,
            row,
            connection_id_by_student=connection_ids,
            evaluation=evaluations.get(str(row.get("student_user_id")))
            if with_evaluation
            else None,
        )
        for row in pool
    ]
    return {
        "candidates": candidates,
        "total": len(candidates),
        "status_counts": _status_counts(pool),
    }


def update_brief_candidate(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    student_user_id: str,
    *,
    status: Any = ...,
    note: Any = ...,
    clear_note: bool = False,
) -> dict[str, Any]:
    """Partial update of one pool row's ROLE-SCOPED status / private note.
    ``...`` means "leave unchanged"."""
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)
    row = _pool_row(db, str(brief["id"]), str(student_user_id or "").strip())
    if row is None:
        raise BriefError(
            "candidate_not_found", "This candidate is not in this role."
        )

    updates: dict[str, Any] = {"updated_at": _now_iso()}
    if status is not ...:
        if status not in BRIEF_CANDIDATE_STATUSES:
            raise BriefError("invalid_status", "Unknown candidate status.")
        updates["status"] = status
    if clear_note:
        updates["note"] = None
    elif note is not ...:
        updates["note"] = str(note or "")[:MAX_NOTE_LENGTH] or None

    _update_pool_row(db, str(brief["id"]), str(row["student_user_id"]), updates)
    refreshed = _pool_row(db, str(brief["id"]), str(row["student_user_id"]))
    return _pool_row_view(
        db,
        refreshed or {**row, **updates},
        connection_id_by_student=_connection_ids_by_student(db, recruiter_user_id),
        evaluation=None,
    )


def remove_brief_candidate(
    db: Any, recruiter_user_id: str, brief_id: str, student_user_id: str
) -> bool:
    """Remove one candidate from the brief's pool. False when the brief is
    missing/foreign or the candidate is not in it (indistinguishable)."""
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        return False
    return _delete_pool_row(db, str(brief["id"]), str(student_user_id or "").strip())


# ── Comparison (live view over the brief) ────────────────────────────────────


def brief_comparison(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    *,
    candidate_user_ids: list[str] | None = None,
) -> dict[str, Any]:
    """The brief's requirement × candidate evidence matrix, re-evaluated
    from live public evidence on every call.

    ``candidate_user_ids`` selects 2–5 pool members (raw ids are accepted
    ONLY because the brief's own pool whitelists them). When omitted, the
    comparison covers the pool's non-archived candidates in added order,
    capped at the comparison limit.
    """
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)

    pool = _pool_rows_for_brief(db, str(brief["id"]))
    status_by_student = {
        str(r.get("student_user_id")): str(r.get("status") or "saved") for r in pool
    }

    if candidate_user_ids:
        ordered = resolve_candidate_user_ids(
            db,
            str(recruiter_user_id),
            candidate_user_ids=candidate_user_ids,
            allowed_user_ids=set(status_by_student),
        )
    else:
        active = [
            uid
            for uid, status in (
                (str(r.get("student_user_id")), str(r.get("status") or "saved"))
                for r in pool
            )
            if status != "archived"
        ]
        ordered = resolve_candidate_user_ids(
            db,
            str(recruiter_user_id),
            candidate_user_ids=active[:MAX_COMPARE_CANDIDATES],
            allowed_user_ids=set(status_by_student),
        )

    matrix = evaluate_matrix(
        db,
        recruiter_user_id=str(recruiter_user_id),
        candidate_user_ids=ordered,
        plan=sanitize_plan(brief.get("plan")),
    )
    for column in matrix.get("columns") or []:
        column["brief_status"] = status_by_student.get(str(column.get("user_id")))
    return {"brief": _brief_list_item(brief, pool), "matrix": matrix}


# ── Brief-scoped search ──────────────────────────────────────────────────────


def brief_search(
    db: Any,
    recruiter_user_id: str,
    brief_id: str,
    *,
    refine_text: str | None = None,
    availability: str | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, Any]:
    """Search driven by the brief's stored plan instead of free text. A
    ``refine_text`` overlay is TEMPORARY — merged onto a copy of the plan,
    never written back to the brief. Results are annotated with the brief's
    pool membership (``in_brief`` / role-scoped ``brief_status``)."""
    brief = _brief_row(db, recruiter_user_id, brief_id)
    if brief is None:
        raise BriefNotFound(brief_id)

    stored = sanitize_plan(brief.get("plan"))
    plan = (
        merge_refinement(stored, refine_text)
        if str(refine_text or "").strip()
        else stored
    )

    kwargs: dict[str, Any] = {
        "q": str(refine_text or "").strip() or None,
        "availability": availability,
        "page": page,
        "plan": plan,
    }
    if page_size is not None:
        kwargs["page_size"] = page_size
    result = search_candidates(db, **kwargs)

    pool = _pool_rows_for_brief(db, str(brief["id"]))
    status_by_student = {
        str(r.get("student_user_id")): str(r.get("status") or "saved") for r in pool
    }
    slug_status: dict[str, str] = {}
    if status_by_student:
        index_rows = _index_rows_by_user_ids(db, list(status_by_student))
        for uid, row in index_rows.items():
            slug = str(row.get("public_slug") or "")
            if slug:
                slug_status[slug] = status_by_student[uid]
    for card in result.get("results") or []:
        slug = str(card.get("public_slug") or "")
        status = slug_status.get(slug)
        card["in_brief"] = status is not None
        card["brief_status"] = status
    return result


__all__ = [
    "BRIEF_CANDIDATE_STATUSES",
    "BRIEF_STATUSES",
    "BriefError",
    "BriefNotFound",
    "ComparisonError",
    "MAX_BRIEF_CANDIDATES",
    "MAX_NOTE_LENGTH",
    "MAX_TITLE_LENGTH",
    "add_brief_candidates",
    "brief_comparison",
    "brief_search",
    "brief_view",
    "create_brief",
    "default_brief_title",
    "delete_brief",
    "get_brief",
    "list_briefs",
    "list_brief_candidates",
    "plan_from_requirements",
    "remove_brief_candidate",
    "update_brief",
    "update_brief_candidate",
]
