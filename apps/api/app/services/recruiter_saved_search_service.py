"""Recruiter Saved Searches — persisted search intent + evidence-aware
discovery over time (migration 070).

A Saved Search is a recruiter search persisted as STRUCTURE: the canonical
requirement plan (``recruiter_requirement_plan`` — the exact shape Hiring
Briefs persist, UNTRUSTED on every load) plus a small closed ``filters``
shape mirroring the explicit chips ``search_candidates`` already accepts.
No third requirement system exists.

Discovery model (the honest contract):

  * Results are ALWAYS computed live by the existing engine
    (``search_candidates`` — fail-closed triple, deterministic, no scores).
    Persistence exists ONLY to answer "what is new / changed since I last
    reviewed": one ``recruiter_saved_search_matches`` row per
    (saved_search, candidate), created/updated/deleted by the deterministic
    reconciliation in :func:`evaluate_saved_search`.
  * Match rows exist ONLY for EXACT matches (every hard requirement
    satisfied by published evidence). Close matches render live but are
    never tracked — no thresholds, no scores. A plan with zero hard
    requirements is savable but untracked, and says so.
  * Match rows store per-requirement content FINGERPRINTS of the
    deterministic evaluation output — hashes, axis keys and timestamps
    ONLY, never prose, identity, or evidence content. Every explanation is
    reconstructed live from the plan + current published evidence.
  * Evaluation is LAZY, on recruiter reads: always on detail open (active
    searches), on list open when stale (≥ EVALUATION_TTL_MINUTES), and at
    creation (baseline — nothing is "new" at the moment of saving). Paused
    searches are never reconciled. There is no background runner; index
    freshness remains publication-driven (documented limitation).
  * Candidates who unpublish, change disclosure, get excluded, or stop
    satisfying the plan have their row DELETED (fail-closed removal);
    re-appearing later is honestly new again.

Isolation: the API runs with the service role (RLS bypassed), so every
read/write here filters by ``recruiter_user_id`` in application code.
Foreign saved searches are indistinguishable from missing ones.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    describe_group,
)
from app.services.recruiter_requirement_plan import (
    requirements_view,
    sanitize_plan,
)
from app.services.recruiter_search_service import (
    AVAILABILITY_VALUES,
    EVIDENCE_FILTERS,
    MAX_PAGE_SIZE,
    MAX_QUERY_LENGTH,
    _read_with_transient_retry,
    parse_recruiter_query,
    record_search_event,
    search_candidates,
)
from app.services.recruiter_search_taxonomy import concept_display
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

_SEARCHES_TABLE = "recruiter_saved_searches"
_MATCHES_TABLE = "recruiter_saved_search_matches"
_INDEX_TABLE = "recruiter_search_index"

# Must stay in sync with the CHECK constraints in migration 070.
SAVED_SEARCH_STATUSES = ("active", "paused")
MATCH_EVENTS = ("new_match", "evidence_updated")

MAX_SAVED_SEARCHES = 20
MAX_SAVED_SEARCH_NAME = 120
EVALUATION_TTL_MINUTES = 5
MAX_MATCH_ROWS = 200
_MAX_FILTER_SKILLS = 10
_MAX_FILTER_TERM = 60


class SavedSearchNotFound(Exception):
    """Saved-search id does not exist for this recruiter (foreign == missing)."""


class SavedSearchError(Exception):
    """Recruiter-facing saved-search input problem (maps to 400/404)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _match_key(saved_search_id: str, student_user_id: str) -> str:
    return f"{saved_search_id}:{student_user_id}"


# ── Closed filters shape (UNTRUSTED on every load, like the plan) ────────────


def sanitize_filters(filters: Any) -> dict[str, Any]:
    """Force the stored/client ``filters`` jsonb back onto the closed shape
    the engine accepts: bounded skill strings, evidence keys from the
    closed vocabulary, availability from the closed vocabulary."""
    if not isinstance(filters, dict):
        filters = {}
    skills: list[str] = []
    for raw in list(filters.get("skills") or [])[:_MAX_FILTER_SKILLS]:
        term = str(raw or "").strip()[:_MAX_FILTER_TERM]
        if term and term not in skills:
            skills.append(term)
    evidence = [
        k for k in list(filters.get("evidence") or []) if k in EVIDENCE_FILTERS
    ]
    availability = filters.get("availability")
    if availability not in AVAILABILITY_VALUES:
        availability = None
    return {"skills": skills, "evidence": evidence, "availability": availability}


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _search_row(
    db: Any, recruiter_user_id: str, saved_search_id: str
) -> dict[str, Any] | None:
    saved_search_id = str(saved_search_id or "").strip()
    if not saved_search_id:
        return None
    if isinstance(db, dict):
        row = db.setdefault(_SEARCHES_TABLE, {}).get(saved_search_id)
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return None
        return row
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_SEARCHES_TABLE)
        .select("*")
        .eq("id", saved_search_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _list_search_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_SEARCHES_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_SEARCHES_TABLE)
            .select("*")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("updated_at", desc=True)
            .limit(MAX_SAVED_SEARCHES)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[
        :MAX_SAVED_SEARCHES
    ]


def _insert_search(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_SEARCHES_TABLE, {})[row["id"]] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_SEARCHES_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_search_row(
    db: Any, recruiter_user_id: str, saved_search_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_SEARCHES_TABLE, {}).get(str(saved_search_id))
        if row is not None and str(row.get("recruiter_user_id")) == str(
            recruiter_user_id
        ):
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_SEARCHES_TABLE)
        .update(make_json_safe(updates))
        .eq("id", saved_search_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )


def _delete_search_row(
    db: Any, recruiter_user_id: str, saved_search_id: str
) -> bool:
    if isinstance(db, dict):
        table = db.setdefault(_SEARCHES_TABLE, {})
        row = table.get(str(saved_search_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return False
        del table[str(saved_search_id)]
        # Mirror ON DELETE CASCADE for the match rows in dict mode.
        matches = db.setdefault(_MATCHES_TABLE, {})
        for key in [
            k
            for k, r in matches.items()
            if str(r.get("saved_search_id")) == str(saved_search_id)
        ]:
            del matches[key]
        return True
    result = (
        db.table(_SEARCHES_TABLE)
        .delete()
        .eq("id", saved_search_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


def _match_rows(db: Any, saved_search_id: str) -> list[dict[str, Any]]:
    """Match rows for ONE saved search. Callers must have resolved the
    search through ``_search_row`` first — ownership is enforced there."""
    if isinstance(db, dict):
        return [
            r
            for r in db.setdefault(_MATCHES_TABLE, {}).values()
            if str(r.get("saved_search_id")) == str(saved_search_id)
        ]
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_MATCHES_TABLE)
        .select("*")
        .eq("saved_search_id", saved_search_id)
        .execute(),
    )
    return list(getattr(result, "data", []) or [])


def _match_rows_for_searches(
    db: Any, saved_search_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not saved_search_ids:
        return {}
    if isinstance(db, dict):
        rows = [
            r
            for r in db.setdefault(_MATCHES_TABLE, {}).values()
            if str(r.get("saved_search_id")) in {str(s) for s in saved_search_ids}
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_MATCHES_TABLE)
            .select("*")
            .in_("saved_search_id", saved_search_ids)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row.get("saved_search_id")), []).append(row)
    return out


def _insert_match_row(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        db.setdefault(_MATCHES_TABLE, {})[
            _match_key(row["saved_search_id"], row["student_user_id"])
        ] = row
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_MATCHES_TABLE)
        .insert(make_json_safe(row))
        .execute(),
    )


def _update_match_row(
    db: Any, saved_search_id: str, student_user_id: str, updates: dict[str, Any]
) -> None:
    if isinstance(db, dict):
        row = db.setdefault(_MATCHES_TABLE, {}).get(
            _match_key(str(saved_search_id), str(student_user_id))
        )
        if row is not None:
            row.update(updates)
        return
    _read_with_transient_retry(
        db,
        lambda client: client.table(_MATCHES_TABLE)
        .update(make_json_safe(updates))
        .eq("saved_search_id", saved_search_id)
        .eq("student_user_id", student_user_id)
        .execute(),
    )


def _delete_match_row(db: Any, saved_search_id: str, student_user_id: str) -> None:
    if isinstance(db, dict):
        db.setdefault(_MATCHES_TABLE, {}).pop(
            _match_key(str(saved_search_id), str(student_user_id)), None
        )
        return
    db.table(_MATCHES_TABLE).delete().eq("saved_search_id", saved_search_id).eq(
        "student_user_id", student_user_id
    ).execute()


def _delete_all_match_rows(db: Any, saved_search_id: str) -> None:
    if isinstance(db, dict):
        matches = db.setdefault(_MATCHES_TABLE, {})
        for key in [
            k
            for k, r in matches.items()
            if str(r.get("saved_search_id")) == str(saved_search_id)
        ]:
            del matches[key]
        return
    db.table(_MATCHES_TABLE).delete().eq(
        "saved_search_id", saved_search_id
    ).execute()


def _user_ids_by_slugs(db: Any, slugs: list[str]) -> dict[str, str]:
    """public_slug → user_id via ONE index read (slug is unique per human)."""
    cleaned = [str(s or "").strip() for s in slugs if str(s or "").strip()]
    if not cleaned:
        return {}
    if isinstance(db, dict):
        wanted = set(cleaned)
        return {
            str(r.get("public_slug")): str(r.get("user_id"))
            for r in db.setdefault(_INDEX_TABLE, {}).values()
            if str(r.get("public_slug")) in wanted
        }
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_INDEX_TABLE)
        .select("user_id, public_slug")
        .in_("public_slug", cleaned)
        .execute(),
    )
    return {
        str(r.get("public_slug")): str(r.get("user_id"))
        for r in (getattr(result, "data", []) or [])
    }


# ── Deterministic fingerprints ───────────────────────────────────────────────

# The evidence-relevant projection of one requirement evaluation row —
# exactly the fields whose change means "the published evidence behind this
# requirement changed". Prose ``note``/``display`` strings are excluded on
# purpose (reconstructed live, never persisted).
_FINGERPRINT_FIELDS = (
    "kind",
    "requirement",
    "satisfied",
    "via",
    "matched_label",
    "skill_status",
    "evidence_sources",
    "project_titles",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(make_json_safe(value), sort_keys=True, separators=(",", ":"))


def _row_fingerprint(row: dict[str, Any]) -> str:
    projection = {field: row.get(field) for field in _FINGERPRINT_FIELDS}
    return hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()[:16]


def _effective_axis_plan(
    plan: dict[str, Any], filters: dict[str, Any]
) -> dict[str, Any]:
    """The plan as the engine actually executes it: explicit skill filter
    chips become requirement groups exactly the way ``search_candidates``
    appends them, so axis keys align 1:1 with the emitted requirement rows."""
    groups = [list(g) for g in plan.get("required_groups") or []]
    for raw in (filters.get("skills") or [])[:_MAX_FILTER_SKILLS]:
        slug = skill_slug(str(raw or ""))
        if slug and not any(slug in g for g in groups):
            groups.append([slug])
    return {**plan, "required_groups": groups}


def _plan_axis_keys(plan: dict[str, Any]) -> list[str]:
    """Stable axis keys in the exact order the engine emits requirement rows
    (required groups, preferred concepts, required evidence, preferred
    evidence) — the same key format the comparison matrix uses."""
    keys: list[str] = []
    for group in plan.get("required_groups") or []:
        keys.append("concept:" + "|".join(group))
    for slug in plan.get("preferred") or []:
        keys.append(f"concept:{slug}")
    for key in plan.get("evidence") or []:
        keys.append(f"evidence:{key}")
    for key in plan.get("preferred_evidence") or []:
        keys.append(f"evidence:{key}")
    return keys


def _axis_display_map(plan: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in plan.get("required_groups") or []:
        out.setdefault("concept:" + "|".join(group), describe_group(group))
    for slug in plan.get("preferred") or []:
        out.setdefault(f"concept:{slug}", concept_display(slug))
    for key in list(plan.get("evidence") or []) + list(
        plan.get("preferred_evidence") or []
    ):
        out.setdefault(f"evidence:{key}", EVIDENCE_REQUIREMENT_DISPLAY.get(key, key))
    return out


def _card_fingerprints(
    card: dict[str, Any], axis_keys: list[str]
) -> dict[str, str]:
    """{axis key → 16-hex hash} over the card's concept/evidence requirement
    rows. Context rows (soft role/seniority/location signals) are excluded —
    they are never requirements and must not fire change events."""
    rows = [
        r for r in (card.get("requirements") or []) if r.get("kind") != "context"
    ]
    fingerprints: dict[str, str] = {}
    for key, row in zip(axis_keys, rows):
        if key not in fingerprints:
            fingerprints[key] = _row_fingerprint(row)
    return fingerprints


def _overall_fingerprint(fingerprints: dict[str, str]) -> str:
    return hashlib.sha256(
        _canonical_json(dict(sorted(fingerprints.items()))).encode("utf-8")
    ).hexdigest()


def _plan_is_tracked(plan: dict[str, Any]) -> bool:
    """Tracking requires at least one HARD requirement — a pure lexical /
    browse search has no deterministic satisfaction condition to diff."""
    return bool(plan.get("required_groups") or plan.get("evidence"))


# ── Views ────────────────────────────────────────────────────────────────────


def _default_search_name(plan: dict[str, Any], q: Any) -> str:
    role = ((plan.get("role") or {}).get("display") or "").strip()
    if role:
        seniority = ((plan.get("seniority") or {}).get("display") or "").strip()
        return f"{seniority} {role}".strip()[:MAX_SAVED_SEARCH_NAME]
    groups = plan.get("required_groups") or []
    if groups:
        return ", ".join(describe_group(g) for g in groups[:3])[
            :MAX_SAVED_SEARCH_NAME
        ]
    text = " ".join(str(q or "").split()).strip()
    if text:
        return (text[:57] + "…") if len(text) > 60 else text
    return "Untitled search"


def _new_and_updated_counts(
    match_rows: list[dict[str, Any]], last_reviewed_at: Any
) -> tuple[int, int]:
    reviewed = _parse_ts(last_reviewed_at)
    new_count = 0
    updated_count = 0
    for row in match_rows:
        changed = _parse_ts(row.get("last_change_at"))
        is_recent = (
            reviewed is None or (changed is not None and changed > reviewed)
        )
        if not is_recent:
            continue
        if str(row.get("last_event")) == "new_match":
            new_count += 1
        elif str(row.get("last_event")) == "evidence_updated":
            updated_count += 1
    return new_count, updated_count


def _list_item(
    row: dict[str, Any], match_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    plan = sanitize_plan(row.get("plan"))
    status = str(row.get("status") or "active")
    paused = status == "paused"
    new_count, updated_count = _new_and_updated_counts(
        match_rows, row.get("last_reviewed_at")
    )
    return {
        "id": str(row.get("id")),
        "name": str(row.get("name") or "Untitled search"),
        "query_text": row.get("query_text"),
        "status": status,
        "requirements": requirements_view(plan),
        "tracking": _plan_is_tracked(plan),
        # Paused searches are not reconciled, so counts would be stale —
        # they are omitted rather than shown wrong.
        "new_count": None if paused else new_count,
        "updated_count": None if paused else updated_count,
        "match_count": None if paused else len(match_rows),
        "last_evaluated_at": row.get("last_evaluated_at"),
        "last_reviewed_at": row.get("last_reviewed_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _record_saved_search_event(
    db: Any, recruiter_user_id: str, action: str, *, count: int, q: Any = None
) -> None:
    """Coarse, privacy-safe analytics: counts + the recruiter's own query
    text only — never names, annotations, or candidate identity."""
    record_search_event(
        db,
        recruiter_user_id=recruiter_user_id,
        q=str(q or "")[:MAX_QUERY_LENGTH] or None,
        filters={"saved_search": action},
        result_count=count,
    )


# ── Deterministic reconciliation core ────────────────────────────────────────


def _live_exact_cards(
    db: Any, plan: dict[str, Any], filters: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    """Every live EXACT match card (bounded at MAX_MATCH_ROWS), collected by
    paging the real engine — exact results sort first, so paging stops as
    soon as a page yields none. Returns (cards, truncated)."""
    cards: list[dict[str, Any]] = []
    exact_total = 0
    page = 1
    while len(cards) < MAX_MATCH_ROWS:
        res = search_candidates(
            db,
            plan=plan,
            skills=filters.get("skills") or None,
            evidence=filters.get("evidence") or None,
            availability=filters.get("availability"),
            page=page,
            page_size=MAX_PAGE_SIZE,
        )
        exact_total = int(res.get("exact_total") or 0)
        page_exact = [
            c for c in (res.get("results") or []) if c.get("match_type") == "exact"
        ]
        cards.extend(page_exact)
        if (
            not res.get("has_more")
            or not page_exact
            or len(cards) >= min(exact_total, MAX_MATCH_ROWS)
        ):
            break
        page += 1
    truncated = exact_total > MAX_MATCH_ROWS
    if truncated:
        logger.warning(
            "saved-search evaluation truncated at %s of %s exact matches",
            MAX_MATCH_ROWS,
            exact_total,
        )
    return cards[:MAX_MATCH_ROWS], truncated


def evaluate_saved_search(
    db: Any, recruiter_user_id: str, saved_search_row: dict[str, Any]
) -> dict[str, Any]:
    """The deterministic reconciliation pass: diff the live exact-match set
    against the stored match rows.

      absent → insert (new_match); fingerprint changed → update
      (evidence_updated + changed axis keys); unchanged → touch
      last_evaluated_at only (last_change_at NEVER bumps without a real
      change); stored row not in the live exact set → DELETE (fail-closed
      removal — unpublished / excluded / no longer satisfying).

    Pure Python over engine output; identical in dict and Supabase modes.
    """
    saved_search_id = str(saved_search_row.get("id"))
    plan = sanitize_plan(saved_search_row.get("plan"))
    now = _now_iso()

    if not _plan_is_tracked(plan):
        _delete_all_match_rows(db, saved_search_id)
        _update_search_row(
            db, recruiter_user_id, saved_search_id, {"last_evaluated_at": now}
        )
        saved_search_row["last_evaluated_at"] = now
        return {"tracked": False, "truncated": False, "changed": 0}

    filters = sanitize_filters(saved_search_row.get("filters"))
    cards, truncated = _live_exact_cards(db, plan, filters)

    uid_by_slug = _user_ids_by_slugs(
        db, [str(c.get("public_slug") or "") for c in cards]
    )
    axis_keys = _plan_axis_keys(_effective_axis_plan(plan, filters))
    live: dict[str, dict[str, str]] = {}
    for card in cards:
        uid = uid_by_slug.get(str(card.get("public_slug") or ""))
        if not uid:
            continue  # slug no longer resolves — fail closed, skip
        live[uid] = _card_fingerprints(card, axis_keys)

    stored = {str(r.get("student_user_id")): r for r in _match_rows(db, saved_search_id)}
    changed = 0

    for uid, fingerprints in live.items():
        overall = _overall_fingerprint(fingerprints)
        existing = stored.get(uid)
        if existing is None:
            row = {
                "saved_search_id": saved_search_id,
                "student_user_id": uid,
                "requirement_fingerprints": fingerprints,
                "evidence_fingerprint": overall,
                "last_event": "new_match",
                "changed_requirement_keys": [],
                "first_matched_at": now,
                "last_change_at": now,
                "last_evaluated_at": now,
            }
            try:
                _insert_match_row(db, row)
            except Exception:
                # Two requests racing the same evaluation: the composite PK
                # rejects the loser — the row exists either way.
                if not any(
                    str(r.get("student_user_id")) == uid
                    for r in _match_rows(db, saved_search_id)
                ):
                    raise
            changed += 1
            continue
        if str(existing.get("evidence_fingerprint") or "") != overall:
            previous = dict(existing.get("requirement_fingerprints") or {})
            changed_keys = sorted(
                key
                for key, value in fingerprints.items()
                if previous.get(key) != value
            )
            _update_match_row(
                db,
                saved_search_id,
                uid,
                {
                    "requirement_fingerprints": fingerprints,
                    "evidence_fingerprint": overall,
                    "last_event": "evidence_updated",
                    "changed_requirement_keys": changed_keys,
                    "last_change_at": now,
                    "last_evaluated_at": now,
                },
            )
            changed += 1
        else:
            _update_match_row(
                db, saved_search_id, uid, {"last_evaluated_at": now}
            )

    for uid in list(stored):
        if uid not in live:
            _delete_match_row(db, saved_search_id, uid)
            changed += 1

    _update_search_row(
        db, recruiter_user_id, saved_search_id, {"last_evaluated_at": now}
    )
    saved_search_row["last_evaluated_at"] = now
    if changed:
        _record_saved_search_event(
            db,
            str(recruiter_user_id),
            "evaluated",
            count=len(live),
            q=saved_search_row.get("query_text"),
        )
    return {"tracked": True, "truncated": truncated, "changed": changed}


def _is_stale(row: dict[str, Any]) -> bool:
    evaluated = _parse_ts(row.get("last_evaluated_at"))
    if evaluated is None:
        return True
    return datetime.now(timezone.utc) - evaluated > timedelta(
        minutes=EVALUATION_TTL_MINUTES
    )


# ── Saved-search CRUD + results ──────────────────────────────────────────────


def create_saved_search(
    db: Any,
    recruiter_user_id: str,
    *,
    q: Any,
    name: Any = None,
    filters: Any = None,
) -> dict[str, Any]:
    """Persist a search as structure, run the baseline evaluation, and set
    the review boundary AFTER it — the recruiter is looking at these results
    right now, so nothing is "new" at creation."""
    query_text = str(q or "").strip()[:MAX_QUERY_LENGTH]
    if not query_text:
        raise SavedSearchError("invalid_query", "Describe the search to save.")
    if len(_list_search_rows(db, recruiter_user_id)) >= MAX_SAVED_SEARCHES:
        raise SavedSearchError(
            "too_many_saved_searches",
            f"You can keep up to {MAX_SAVED_SEARCHES} saved searches.",
        )
    plan = sanitize_plan(parse_recruiter_query(query_text))
    clean_filters = sanitize_filters(filters)
    cleaned_name = str(name or "").strip()[:MAX_SAVED_SEARCH_NAME]
    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "name": cleaned_name or _default_search_name(plan, query_text),
        "query_text": query_text,
        "plan": plan,
        "filters": clean_filters,
        "status": "active",
        "last_evaluated_at": None,
        "last_reviewed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    _insert_search(db, row)
    evaluate_saved_search(db, str(recruiter_user_id), row)
    baseline = _now_iso()
    _update_search_row(
        db, recruiter_user_id, str(row["id"]), {"last_reviewed_at": baseline}
    )
    row["last_reviewed_at"] = baseline
    _record_saved_search_event(
        db,
        str(recruiter_user_id),
        "created",
        count=len(_match_rows(db, str(row["id"]))),
        q=query_text,
    )
    refreshed = _search_row(db, recruiter_user_id, str(row["id"]))
    return _list_item(refreshed or row, _match_rows(db, str(row["id"])))


def list_saved_searches(db: Any, recruiter_user_id: str) -> dict[str, Any]:
    """The recruiter's saved searches, newest updated first. Stale ACTIVE
    searches (≥ EVALUATION_TTL_MINUTES since last evaluation) are lazily
    re-evaluated first — bounded by MAX_SAVED_SEARCHES."""
    rows = _list_search_rows(db, recruiter_user_id)
    for row in rows:
        if str(row.get("status") or "active") == "active" and _is_stale(row):
            evaluate_saved_search(db, str(recruiter_user_id), row)
    by_search = _match_rows_for_searches(db, [str(r.get("id")) for r in rows])
    items = [
        _list_item(row, by_search.get(str(row.get("id")), [])) for row in rows
    ]
    return {"saved_searches": items, "total": len(items)}


def get_saved_search_results(
    db: Any,
    recruiter_user_id: str,
    saved_search_id: str,
    *,
    page: int = 1,
) -> dict[str, Any]:
    """Detail view: live results (ALWAYS recomputed by the real engine —
    fail-closed) plus per-candidate discovery annotations from the match
    rows. Active searches reconcile first; paused searches show live
    results but are NOT reconciled and carry no annotations (stale badges
    would be dishonest)."""
    row = _search_row(db, recruiter_user_id, saved_search_id)
    if row is None:
        raise SavedSearchNotFound(saved_search_id)

    active = str(row.get("status") or "active") == "active"
    truncated = False
    if active:
        outcome = evaluate_saved_search(db, str(recruiter_user_id), row)
        truncated = bool(outcome.get("truncated"))

    plan = sanitize_plan(row.get("plan"))
    filters = sanitize_filters(row.get("filters"))
    res = search_candidates(
        db,
        plan=plan,
        skills=filters.get("skills") or None,
        evidence=filters.get("evidence") or None,
        availability=filters.get("availability"),
        page=page,
    )

    annotations: dict[str, dict[str, Any]] = {}
    match_rows = _match_rows(db, str(row["id"]))
    if active and match_rows:
        display_by_key = _axis_display_map(_effective_axis_plan(plan, filters))
        reviewed = _parse_ts(row.get("last_reviewed_at"))
        slug_by_uid = {
            uid: slug
            for slug, uid in _user_ids_by_slugs(
                db,
                [str(c.get("public_slug") or "") for c in res.get("results") or []],
            ).items()
        }
        for match in match_rows:
            uid = str(match.get("student_user_id"))
            slug = slug_by_uid.get(uid)
            if not slug:
                continue
            changed = _parse_ts(match.get("last_change_at"))
            recent = reviewed is None or (changed is not None and changed > reviewed)
            event = str(match.get("last_event") or "new_match")
            annotations[slug] = {
                "is_new": recent and event == "new_match",
                "evidence_updated": recent and event == "evidence_updated",
                "changed_requirements": [
                    display_by_key.get(str(k), str(k))
                    for k in (match.get("changed_requirement_keys") or [])
                ]
                if recent and event == "evidence_updated"
                else [],
                "first_matched_at": match.get("first_matched_at"),
            }

    _record_saved_search_event(
        db,
        str(recruiter_user_id),
        "opened",
        count=int(res.get("total") or 0),
        q=row.get("query_text"),
    )
    return {
        "saved_search": _list_item(row, match_rows),
        "results": res.get("results") or [],
        "total": res.get("total") or 0,
        "exact_total": res.get("exact_total") or 0,
        "close_total": res.get("close_total") or 0,
        "page": res.get("page") or page,
        "page_size": res.get("page_size") or 0,
        "has_more": bool(res.get("has_more")),
        "interpretation": res.get("interpretation") or {},
        "annotations": annotations,
        "truncated": truncated,
    }


def update_saved_search(
    db: Any,
    recruiter_user_id: str,
    saved_search_id: str,
    *,
    name: Any = ...,
    status: Any = ...,
    q: Any = ...,
    filters: Any = ...,
) -> dict[str, Any]:
    """Partial update; ``...`` means "leave unchanged". Editing the query or
    filters re-parses/re-sanitizes, WIPES the match rows, re-evaluates, and
    resets the review boundary — a changed search must never fake "new"
    candidates. Resuming a paused search re-evaluates."""
    row = _search_row(db, recruiter_user_id, saved_search_id)
    if row is None:
        raise SavedSearchNotFound(saved_search_id)

    updates: dict[str, Any] = {"updated_at": _now_iso()}
    plan_changed = False
    resumed = False

    if name is not ...:
        cleaned = str(name or "").strip()[:MAX_SAVED_SEARCH_NAME]
        if not cleaned:
            raise SavedSearchError("invalid_name", "Give the saved search a name.")
        updates["name"] = cleaned
    if status is not ...:
        if status not in SAVED_SEARCH_STATUSES:
            raise SavedSearchError("invalid_status", "Unknown saved-search status.")
        previous = str(row.get("status") or "active")
        updates["status"] = status
        if previous == "paused" and status == "active":
            resumed = True
        if previous != status:
            _record_saved_search_event(
                db,
                str(recruiter_user_id),
                "resumed" if status == "active" else "paused",
                count=0,
                q=row.get("query_text"),
            )
    if q is not ...:
        query_text = str(q or "").strip()[:MAX_QUERY_LENGTH]
        if not query_text:
            raise SavedSearchError("invalid_query", "Describe the search to save.")
        updates["query_text"] = query_text
        updates["plan"] = sanitize_plan(parse_recruiter_query(query_text))
        plan_changed = True
    if filters is not ...:
        updates["filters"] = sanitize_filters(filters)
        plan_changed = True

    _update_search_row(db, recruiter_user_id, str(row["id"]), updates)
    merged = _search_row(db, recruiter_user_id, str(row["id"])) or {**row, **updates}

    if plan_changed:
        _delete_all_match_rows(db, str(row["id"]))
        evaluate_saved_search(db, str(recruiter_user_id), merged)
        baseline = _now_iso()
        _update_search_row(
            db, recruiter_user_id, str(row["id"]), {"last_reviewed_at": baseline}
        )
        merged["last_reviewed_at"] = baseline
    elif resumed and str(merged.get("status") or "") == "active":
        evaluate_saved_search(db, str(recruiter_user_id), merged)

    return _list_item(merged, _match_rows(db, str(row["id"])))


def mark_reviewed(
    db: Any, recruiter_user_id: str, saved_search_id: str
) -> dict[str, Any]:
    """Explicit "I've seen these" action: moves the review boundary to now."""
    row = _search_row(db, recruiter_user_id, saved_search_id)
    if row is None:
        raise SavedSearchNotFound(saved_search_id)
    now = _now_iso()
    _update_search_row(
        db, recruiter_user_id, str(row["id"]), {"last_reviewed_at": now}
    )
    row["last_reviewed_at"] = now
    _record_saved_search_event(
        db, str(recruiter_user_id), "reviewed", count=0, q=row.get("query_text")
    )
    return _list_item(row, _match_rows(db, str(row["id"])))


def delete_saved_search(
    db: Any, recruiter_user_id: str, saved_search_id: str
) -> bool:
    """Delete one of the caller's OWN saved searches (match rows cascade).
    Never deletes candidates, connections, pools, or briefs. Returns False
    when the id does not exist or is another recruiter's."""
    deleted = _delete_search_row(db, recruiter_user_id, str(saved_search_id or ""))
    if deleted:
        _record_saved_search_event(db, str(recruiter_user_id), "deleted", count=0)
    return deleted


__all__ = [
    "EVALUATION_TTL_MINUTES",
    "MATCH_EVENTS",
    "MAX_MATCH_ROWS",
    "MAX_SAVED_SEARCHES",
    "MAX_SAVED_SEARCH_NAME",
    "SAVED_SEARCH_STATUSES",
    "SavedSearchError",
    "SavedSearchNotFound",
    "create_saved_search",
    "delete_saved_search",
    "evaluate_saved_search",
    "get_saved_search_results",
    "list_saved_searches",
    "mark_reviewed",
    "sanitize_filters",
    "update_saved_search",
]
