"""Recruiter Search & Discovery V1 (migration 066).

The searchable candidate projection and the deterministic search engine over
it. This is the second candidate-acquisition path (alongside QR / shared
link); results converge into the SAME public passport (``/p/{slug}``) and the
SAME idempotent Save Candidate connection model (migration 065).

PRIVACY MODEL — the load-bearing invariant:
  A candidate's index row is derived exclusively from the OUTPUT of
  :func:`vbr_work_passport_service.build_public_passport` — the one
  disclosure-enforced, scrubbed, fail-closed projection already served
  publicly at ``/p/{slug}``. Search therefore can never surface anything a
  recruiter could not already see on the candidate's public Work Passport:

    * no published passport → no row (refresh deletes it; failures delete,
      never leave a stale row — fail closed);
    * hidden projects / skills / sources never reach the projection because
      ``build_public_passport`` already removed them;
    * at query time the service re-checks ``vbr_work_passports.is_published``
      AND the candidate's live ``disclosure_version`` in batch; any row that
      is unpublished or behind the live policy version is excluded (fail
      closed) — a disclosure change can hide data before the refresh lands,
      never the other way around.

RANKING — deterministic and explainable, per-query relevance only:
  * evidence-backed passport skills outrank claimed project technologies,
    which outrank headline/profile prose;
  * qualitative status strengthens a match (Demonstrated > Supporting);
  * small bonuses when a MATCHED skill is backed by GitHub / live-site /
    defense evidence — relevance of THIS match, never a universal candidate
    quality score;
  * ties break on matched-verified-skill count, then newest publication,
    then slug — fully deterministic.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests). The
ranking implementation is pure Python and identical in both modes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.serialization import make_json_safe
from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    INTENT_CANDIDATE_SEARCH,
    INTENT_EVIDENCE_SEARCH,
    INTENT_PROJECT_SEARCH,
    PLACE_ALIASES,
    describe_group,
    parse_recruiter_query,
)
from app.services.recruiter_search_taxonomy import (
    concept_display,
    expansion_terms,
    satisfies,
)
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

_INDEX_TABLE = "recruiter_search_index"
_EVENTS_TABLE = "recruiter_search_events"
_PASSPORTS_TABLE = "vbr_work_passports"
_POLICIES_TABLE = "passport_disclosure_policies"
_EXCLUSIONS_TABLE = "recruiter_discovery_exclusions"

# ── Query / pagination limits ────────────────────────────────────────────────

MAX_QUERY_LENGTH = 320
MAX_PAGE_SIZE = 20
DEFAULT_PAGE_SIZE = 10
MAX_PAGE = 50
# Upper bound on candidate rows pulled for in-service ranking. Far above the
# current published population; revisit (move ranking into SQL) before it binds.
_MAX_CANDIDATE_POOL = 400
_MAX_MATCHED_REASONS = 8
_MAX_RESULT_SKILLS = 6
_MAX_RESULT_PROJECTS = 3
_MAX_PROJECT_SUMMARY_CHARS = 280
# Evidence Discovery: per-skill proof refs / trace previews kept in the index
# row (compact — titles, paths, closed labels, sanitized summaries only).
_MAX_SKILL_PROOF_PROJECTS = 4
_MAX_SKILL_PROOF_TRACES = 3

# ── Evidence vocabulary (must mirror vbr_work_passport_service labels) ───────

_SRC_GITHUB = "GitHub Proof"
_SRC_DOCUMENT = "Document Proof"
_SRC_WEBSITE = "Website Proof"
_SRC_DEFENSE = "Project Defense"
_SRC_VIDEO = "Video Evidence"

# Closed filter vocabulary → how the flag is derived from the public projection.
EVIDENCE_FILTERS = ("github", "live_site", "documents", "project_defense", "video")

AVAILABILITY_VALUES = (
    "seeking_internship",
    "seeking_full_time",
    "open_to_opportunities",
)
_AVAILABILITY_BY_LABEL = {
    "Seeking internship": "seeking_internship",
    "Seeking full-time roles": "seeking_full_time",
    "Open to opportunities": "open_to_opportunities",
}

# ── Deterministic ranking weights (per distinct matched query term) ──────────

_WEIGHT_SKILL = 5.0
_WEIGHT_NAME = 3.0
_WEIGHT_TECHNOLOGY = 2.5
_WEIGHT_HEADLINE = 2.0
_WEIGHT_PROJECT = 1.5
_WEIGHT_EDUCATION = 1.25
_WEIGHT_LOCATION = 1.0
# Qualitative status strengthens a skill match (never surfaced as a number).
_STATUS_BONUS = {
    "Demonstrated": 1.0,
    "Partially demonstrated": 0.6,
    "Evidence observed": 0.4,
    "Supporting evidence": 0.2,
}
# Evidence-provenance bonus for a MATCHED skill only (capped): a skill backed
# by real artifacts is a stronger answer to the query than prose.
_EVIDENCE_BONUS = {
    _SRC_GITHUB: 0.5,
    _SRC_WEBSITE: 0.5,
    _SRC_DEFENSE: 0.25,
    _SRC_VIDEO: 0.25,
    _SRC_DOCUMENT: 0.25,
}
_EVIDENCE_BONUS_CAP = 1.0

_STATUS_ORDER = {
    "Demonstrated": 0,
    "Partially demonstrated": 1,
    "Evidence observed": 2,
    "Supporting evidence": 3,
    "Needs review": 4,
    "Not assessed": 5,
}

# Minimal, closed stopword list — kept tiny so real technology terms are
# never dropped.
_STOPWORDS = {
    "a", "an", "and", "are", "for", "in", "is", "of", "or", "the", "to",
    "who", "with", "have", "has",
}

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokenize_query(q: Any) -> list[str]:
    """Deterministic query tokenization: lowercase, keep +/#/. so terms like
    c++, c#, .net survive; drop stopwords and 1-char noise (but keep 1-char
    tokens containing a symbol, e.g. 'c' is dropped, 'c++' is kept)."""
    text = str(q or "").strip().lower()[:MAX_QUERY_LENGTH]
    terms: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        token = raw.strip(".")
        if not token or token in _STOPWORDS:
            continue
        if len(token) < 2 and not any(ch in token for ch in "+#"):
            continue
        if token not in terms:
            terms.append(token)
    return terms


# ── Storage helpers (dual-mode) ──────────────────────────────────────────────


def _is_transient_transport_error(exc: Exception) -> bool:
    """The process-wide Supabase client shares ONE sync httpx transport;
    concurrent requests racing it surface ``httpx.ReadError: [Errno 11/35]
    Resource temporarily unavailable`` (see db/supabase.py). Those are safe
    to retry once on a fresh client."""
    text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
    return any(
        marker in text
        for marker in (
            "httpx.", "httpcore.", "ReadError", "WriteError",
            "Resource temporarily unavailable", "ConnectionTerminated",
            "RemoteProtocolError", "ConnectError",
        )
    )


def _read_with_transient_retry(db: Any, fn: Any) -> Any:
    """Run a read against ``db``; on a transient transport race, retry ONCE
    on a fresh service-role client. Search is a pure read surface, so the
    retry is always safe."""
    if isinstance(db, dict):
        return fn(db)
    try:
        return fn(db)
    except Exception as exc:
        if not _is_transient_transport_error(exc):
            raise
        logger.warning(
            "search read hit a transient transport error; retrying on a "
            "fresh client: %s", exc,
        )
        from app.db.supabase import create_service_role_client

        return fn(create_service_role_client())


def _index_rows(db: Any) -> dict[str, dict[str, Any]]:
    return db.setdefault(_INDEX_TABLE, {})


def _delete_index_row(db: Any, user_id: str) -> None:
    if isinstance(db, dict):
        table = _index_rows(db)
        stale = [k for k, r in table.items() if str(r.get("user_id")) == str(user_id)]
        for key in stale:
            del table[key]
        return
    db.table(_INDEX_TABLE).delete().eq("user_id", user_id).execute()


def _upsert_index_row(db: Any, row: dict[str, Any]) -> None:
    if isinstance(db, dict):
        table = _index_rows(db)
        stale = [
            k for k, r in table.items() if str(r.get("user_id")) == str(row["user_id"])
        ]
        for key in stale:
            del table[key]
        table[str(row["user_id"])] = row
        return
    db.table(_INDEX_TABLE).upsert(
        make_json_safe(row), on_conflict="user_id"
    ).execute()


def _excluded_user_ids(db: Any, user_ids: list[str]) -> set[str]:
    """Subset of ``user_ids`` present in the discovery-exclusions table.

    Exclusions (migration 067) are the durable guard that keeps positively
    identified QA / demo / fixture accounts out of recruiter discovery even
    if their passports are ever re-published. Empty on any environment where
    the table has no rows — a no-op for every genuine candidate.
    """
    if not user_ids:
        return set()
    if isinstance(db, dict):
        table = db.setdefault(_EXCLUSIONS_TABLE, {})
        wanted = {str(u) for u in user_ids}
        return {
            str(r.get("user_id"))
            for r in table.values()
            if str(r.get("user_id")) in wanted
        }
    try:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_EXCLUSIONS_TABLE)
            .select("user_id")
            .in_("user_id", user_ids)
            .execute(),
        )
    except Exception as exc:
        # An absent table means the environment simply has no exclusions
        # provisioned (migration 067 not applied) — that is a valid state,
        # not an error; anything else propagates.
        if "PGRST205" in str(exc) or "Could not find the table" in str(exc):
            logger.warning("discovery-exclusions table missing — treating as empty")
            return set()
        raise
    return {str(r.get("user_id")) for r in (getattr(result, "data", []) or [])}


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
    result = (
        db.table(_PASSPORTS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _published_passports(db: Any) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        return [
            r
            for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
            if r.get("is_published")
        ]
    result = (
        db.table(_PASSPORTS_TABLE)
        .select("id, user_id, public_slug, is_published, published_at")
        .eq("is_published", True)
        .execute()
    )
    return list(getattr(result, "data", []) or [])


def _live_publication_map(db: Any, user_ids: list[str]) -> dict[str, bool]:
    """user_id → live ``is_published`` for the given candidates (one query)."""
    if not user_ids:
        return {}
    if isinstance(db, dict):
        out: dict[str, bool] = {}
        for row in db.setdefault(_PASSPORTS_TABLE, {}).values():
            uid = str(row.get("user_id"))
            if uid in user_ids or uid in set(user_ids):
                out[uid] = bool(row.get("is_published"))
        return out
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_PASSPORTS_TABLE)
        .select("user_id, is_published")
        .in_("user_id", user_ids)
        .execute(),
    )
    return {
        str(r.get("user_id")): bool(r.get("is_published"))
        for r in (getattr(result, "data", []) or [])
    }


def _live_disclosure_versions(db: Any, user_ids: list[str]) -> dict[str, int]:
    """user_id → live disclosure_version (one query; absent policy row → 1)."""
    if not user_ids:
        return {}
    if isinstance(db, dict):
        out: dict[str, int] = {}
        for row in db.setdefault(_POLICIES_TABLE, {}).values():
            uid = str(row.get("user_id"))
            if uid in set(user_ids):
                out[uid] = int(row.get("disclosure_version") or 1)
        return out
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_POLICIES_TABLE)
        .select("user_id, disclosure_version")
        .in_("user_id", user_ids)
        .execute(),
    )
    return {
        str(r.get("user_id")): int(r.get("disclosure_version") or 1)
        for r in (getattr(result, "data", []) or [])
    }


# ── Candidate projection (public passport output → index row) ────────────────


def _truncate(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value[:limit]


def _join_text(parts: list[Any]) -> str:
    seen: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        if value and value not in seen:
            seen.append(value)
    return " ".join(seen)


def _identity_placeholder(value: Any, placeholder: str) -> str | None:
    """Public builder placeholders are presentation, not data — don't index them."""
    text = str(value or "").strip()
    if not text or text == placeholder:
        return None
    return text


def build_index_row(
    passport_row: dict[str, Any], public: dict[str, Any]
) -> dict[str, Any]:
    """Project ``build_public_passport`` output into one compact index row.

    Pure function (unit-testable). Everything here is ALREADY public: the
    input is the exact payload served at ``/p/{slug}``.
    """
    identity = public.get("identity") or {}
    top_skills = public.get("top_skills") or []
    projects = public.get("featured_projects") or []

    skills_compact: list[dict[str, Any]] = []
    for entry in top_skills:
        name = str(entry.get("skill") or "").strip()
        if not name:
            continue
        # Per-skill proof refs + safe trace previews (Evidence Discovery).
        # Everything here comes from the SAME public projection — project
        # titles, published report paths, closed proof-type labels, and the
        # already-sanitized public trace summaries served at /p/{slug}.
        proof_projects = [
            {
                "title": _truncate(ref.get("project_title"), 160),
                "public_report_path": str(ref.get("public_report_path") or ""),
                "skill_status": str(ref.get("skill_status") or "Not assessed"),
                "proof_types": [
                    str(t) for t in (ref.get("supporting_proof_types") or [])
                ][:6],
            }
            for ref in (entry.get("projects") or [])[:_MAX_SKILL_PROOF_PROJECTS]
            if ref.get("public_report_path")
        ]
        traces = []
        for trace in (entry.get("evidence_traces") or [])[:_MAX_SKILL_PROOF_TRACES]:
            public_url = trace.get("public_url")
            traces.append(
                {
                    "source_type": _truncate(trace.get("source_type"), 40),
                    "source_title": _truncate(trace.get("source_title"), 120),
                    "summary": _truncate(trace.get("safe_summary"), 220),
                    # Already gated upstream by is_safe_public_url + the
                    # public-safety scrub; index only openable public links.
                    "public_url": str(public_url)
                    if public_url and trace.get("is_publicly_openable")
                    else None,
                }
            )
        skills_compact.append(
            {
                "skill": name,
                "skill_slug": str(entry.get("skill_slug") or skill_slug(name)),
                "category": str(entry.get("category") or ""),
                "status": str(entry.get("status") or "Not assessed"),
                "evidence_sources": [
                    str(s) for s in (entry.get("evidence_sources") or [])
                ],
                "aliases": [str(a) for a in (entry.get("aliases") or [])][:6],
                "projects": proof_projects,
                "traces": traces,
            }
        )

    projects_compact: list[dict[str, Any]] = []
    flags = {key: False for key in EVIDENCE_FILTERS}
    for proj in projects:
        sources = [str(s) for s in (proj.get("evidence_sources") or [])]
        if _SRC_GITHUB in sources:
            flags["github"] = True
        if _SRC_DOCUMENT in sources:
            flags["documents"] = True
        if _SRC_DEFENSE in sources:
            flags["project_defense"] = True
        if _SRC_VIDEO in sources:
            flags["video"] = True
        if proj.get("live_url"):
            flags["live_site"] = True
        projects_compact.append(
            {
                "title": _truncate(proj.get("project_title"), 160),
                "summary": _truncate(proj.get("project_summary"), _MAX_PROJECT_SUMMARY_CHARS),
                "technologies": [
                    str(t) for t in (proj.get("claimed_skills") or [])
                ][:16],
                "evidence_sources": sources,
                "public_report_path": str(proj.get("public_report_path") or ""),
                "has_live_url": bool(proj.get("live_url")),
                "has_github_repo": bool(proj.get("github_repo_url")),
            }
        )

    display_name = _identity_placeholder(
        identity.get("display_name"), "Verified candidate profile"
    )
    headline = _identity_placeholder(identity.get("headline"), "Verified Work Passport")
    availability_label = str(identity.get("availability_label") or "").strip() or None
    availability = _AVAILABILITY_BY_LABEL.get(availability_label or "")
    role_areas = [str(r) for r in (identity.get("role_areas") or [])]
    institution = str(identity.get("institution") or "").strip() or None
    degree = str(identity.get("degree") or "").strip() or None
    graduation_year = identity.get("graduation_year")
    location = str(identity.get("location") or "").strip() or None

    text_skills = _join_text(
        [s["skill"] for s in skills_compact]
        + [alias for s in skills_compact for alias in s["aliases"]]
    )
    text_profile = _join_text(
        [display_name, headline, availability_label]
        + role_areas
        + [str(identity.get("bio") or "")]
        + [tech for p in projects_compact for tech in p["technologies"]]
    )
    text_projects = _join_text(
        [p["title"] for p in projects_compact]
        + [p["summary"] for p in projects_compact]
    )
    text_meta = _join_text(
        [
            institution,
            degree,
            str(identity.get("program") or ""),
            str(identity.get("education_summary") or ""),
            location,
            str(graduation_year or ""),
        ]
    )

    return {
        "user_id": str(passport_row.get("user_id")),
        "passport_id": str(passport_row.get("id")),
        "public_slug": str(passport_row.get("public_slug") or ""),
        "display_name": display_name,
        "headline": headline,
        "location": location,
        "availability": availability,
        "availability_label": availability_label,
        "institution": institution,
        "degree": degree,
        "graduation_year": graduation_year
        if isinstance(graduation_year, int)
        else None,
        "role_areas": role_areas,
        "skills": skills_compact,
        "projects": projects_compact,
        "evidence_flags": flags,
        "skill_count": len(skills_compact),
        "project_count": len(projects_compact),
        "text_skills": text_skills,
        "text_profile": text_profile,
        "text_projects": text_projects,
        "text_meta": text_meta,
        "search_text": _join_text(
            [text_skills, text_profile, text_projects, text_meta]
        ).lower(),
        "disclosure_version": int(public.get("disclosure_version") or 1),
        "passport_published_at": passport_row.get("published_at"),
        "projected_at": _now_iso(),
    }


def refresh_search_projection(db: Any, pipeline_db: Any, user_id: str) -> bool:
    """Rebuild one candidate's search row from the live public projection.

    FAIL CLOSED: any state that is not "actively published and buildable"
    (no passport, unpublished, no slug, projection error, unsafe-scan 404)
    deletes the row. Returns True when a row was written, False otherwise.
    Never raises — callers are owner mutations that must not fail because
    search indexing hiccuped; a deleted row is always the safe outcome.
    """
    uid = str(user_id or "")
    try:
        if uid in _excluded_user_ids(db, [uid]):
            _delete_index_row(db, uid)
            return False
        passport = _passport_by_user(db, uid)
        if (
            passport is None
            or not passport.get("is_published")
            or not passport.get("public_slug")
        ):
            _delete_index_row(db, uid)
            return False
        # Local import: vbr_work_passport_service imports are heavy and this
        # avoids a circular import when the passport service later calls us.
        from app.services.vbr_work_passport_service import build_public_passport

        public = build_public_passport(db, pipeline_db, str(passport["public_slug"]))
        row = build_index_row(passport, public)
        _upsert_index_row(db, row)
        return True
    except Exception:
        logger.warning(
            "search projection refresh failed for user %s — removing index row "
            "(fail closed)",
            uid,
            exc_info=True,
        )
        try:
            _delete_index_row(db, uid)
        except Exception:
            logger.error(
                "search projection cleanup ALSO failed for user %s — row may be "
                "stale until the next rebuild",
                uid,
                exc_info=True,
            )
        return False


def rebuild_search_index(db: Any, pipeline_db: Any) -> dict[str, int]:
    """Rebuild every published candidate's row from source-of-truth data.

    The index is a cache: this is the safe backfill/repair mechanism. Also
    removes rows whose owner no longer has a published passport.
    """
    published = _published_passports(db)
    refreshed = 0
    removed = 0
    for passport in published:
        if refresh_search_projection(db, pipeline_db, str(passport.get("user_id"))):
            refreshed += 1
    published_ids = {str(p.get("user_id")) for p in published}
    # Sweep rows whose owner is no longer published (e.g. deleted accounts).
    if isinstance(db, dict):
        stale_ids = [
            str(r.get("user_id"))
            for r in list(_index_rows(db).values())
            if str(r.get("user_id")) not in published_ids
        ]
    else:
        result = db.table(_INDEX_TABLE).select("user_id").execute()
        stale_ids = [
            str(r.get("user_id"))
            for r in (getattr(result, "data", []) or [])
            if str(r.get("user_id")) not in published_ids
        ]
    for uid in stale_ids:
        _delete_index_row(db, uid)
        removed += 1
    return {"refreshed": refreshed, "removed": removed, "published": len(published)}


# ── Search: matching, ranking, explanations ──────────────────────────────────


def _term_in(term: str, text: Any) -> bool:
    return bool(term) and term in str(text or "").lower()


_LOCATION_WORD_RE = re.compile(r"[a-z]+")


def _canonical_location(text: Any) -> str:
    """Canonicalize a location string for matching.

    Lowercases and expands a TRAILING (or solo) US state abbreviation /
    informal alias to its full name through the parser's PLACE_ALIASES table,
    so a stored profile "Boston, MA" canonicalizes to "boston massachusetts"
    and matches a plan location of "massachusetts" (and still matches
    "boston"). This is profile/plan *location-field* data, never free query
    text, so expanding a trailing two-letter token is safe here — the query
    side keeps its strict context rules in recruiter_query_understanding.
    Only the final token is expanded: mid-string words like the preposition
    "in" must never become Indiana.
    """
    words = _LOCATION_WORD_RE.findall(str(text or "").lower())
    if not words:
        return ""
    last = words[-1]
    expanded = PLACE_ALIASES.get(last)
    if expanded is not None:
        words = words[:-1] + [expanded]
    return " ".join(words)


def _skill_key(name: Any) -> str:
    return skill_slug(str(name or ""))


def _match_candidate(
    row: dict[str, Any], terms: list[str], phrase: str
) -> tuple[float, list[dict[str, Any]], int] | None:
    """Score one candidate against the query terms.

    Returns ``(score, matched_reasons, matched_skill_count)`` or ``None``
    when nothing matches. Deterministic: iteration order follows the stored
    row's own list order; weights are fixed constants.
    """
    skills = row.get("skills") or []
    projects = row.get("projects") or []
    # Canonicalized once per row: lets a lexical "massachusetts" term hit a
    # stored "Boston, MA" (soft signal only — weight unchanged).
    location_canonical = _canonical_location(row.get("location"))
    reasons: list[dict[str, Any]] = []
    score = 0.0
    matched_skill_count = 0
    matched_any = False

    reason_keys: set[tuple[str, str]] = set()

    def add_reason(reason: dict[str, Any]) -> None:
        key = (str(reason.get("type")), str(reason.get("label")).lower())
        if key in reason_keys:
            return
        reason_keys.add(key)
        reasons.append(reason)

    for term in terms:
        best_weight = 0.0
        best_reason: dict[str, Any] | None = None

        # 1. Evidence-backed passport skills (strongest signal).
        for entry in skills:
            name = str(entry.get("skill") or "")
            aliases = [str(a) for a in (entry.get("aliases") or [])]
            if _term_in(term, name) or any(_term_in(term, a) for a in aliases):
                status = str(entry.get("status") or "Not assessed")
                weight = _WEIGHT_SKILL + _STATUS_BONUS.get(status, 0.0)
                bonus = 0.0
                for src in entry.get("evidence_sources") or []:
                    bonus += _EVIDENCE_BONUS.get(str(src), 0.0)
                weight += min(bonus, _EVIDENCE_BONUS_CAP)
                if weight > best_weight:
                    best_weight = weight
                    best_reason = {
                        "type": "skill",
                        "label": name,
                        "term": term,
                        "skill_status": status,
                        "evidence_sources": [
                            str(s) for s in (entry.get("evidence_sources") or [])
                        ],
                    }
                break  # first matching skill in stored order is the anchor

        # 2. Candidate name.
        if best_weight < _WEIGHT_NAME and _term_in(term, row.get("display_name")):
            best_weight = _WEIGHT_NAME
            best_reason = {
                "type": "name",
                "label": str(row.get("display_name") or ""),
                "term": term,
            }

        # 3. Claimed project technologies (claim-level, weaker than evidence).
        if best_weight < _WEIGHT_TECHNOLOGY:
            for proj in projects:
                tech_hit = next(
                    (
                        str(t)
                        for t in (proj.get("technologies") or [])
                        if _term_in(term, t)
                    ),
                    None,
                )
                if tech_hit:
                    best_weight = _WEIGHT_TECHNOLOGY
                    best_reason = {
                        "type": "technology",
                        "label": tech_hit,
                        "term": term,
                        "project_title": str(proj.get("title") or ""),
                    }
                    break

        # 4. Headline / role areas.
        if best_weight < _WEIGHT_HEADLINE:
            if _term_in(term, row.get("headline")):
                best_weight = _WEIGHT_HEADLINE
                best_reason = {
                    "type": "headline",
                    "label": str(row.get("headline") or ""),
                    "term": term,
                }
            else:
                area_hit = next(
                    (
                        str(a)
                        for a in (row.get("role_areas") or [])
                        if _term_in(term, a)
                    ),
                    None,
                )
                if area_hit:
                    best_weight = _WEIGHT_HEADLINE
                    best_reason = {"type": "role_area", "label": area_hit, "term": term}

        # 5. Project titles / summaries.
        if best_weight < _WEIGHT_PROJECT:
            for proj in projects:
                if _term_in(term, proj.get("title")) or _term_in(
                    term, proj.get("summary")
                ):
                    best_weight = _WEIGHT_PROJECT
                    best_reason = {
                        "type": "project",
                        "label": str(proj.get("title") or ""),
                        "term": term,
                    }
                    break

        # 6. Education.
        if best_weight < _WEIGHT_EDUCATION:
            edu = _join_text(
                [row.get("institution"), row.get("degree"), row.get("text_meta")]
            )
            if _term_in(term, edu):
                best_weight = _WEIGHT_EDUCATION
                best_reason = {
                    "type": "education",
                    "label": _join_text([row.get("degree"), row.get("institution")])
                    or edu[:80],
                    "term": term,
                }

        # 7. Location. Raw substring OR alias-canonical form, so a lexical
        # "massachusetts" still hits a stored "Boston, MA".
        if best_weight < _WEIGHT_LOCATION and (
            _term_in(term, row.get("location"))
            or _term_in(term, location_canonical)
        ):
            best_weight = _WEIGHT_LOCATION
            best_reason = {
                "type": "location",
                "label": str(row.get("location") or ""),
                "term": term,
            }

        if best_reason is not None:
            matched_any = True
            score += best_weight
            if best_reason["type"] == "skill":
                matched_skill_count += 1
            add_reason(best_reason)

    # Whole-query phrase equal to a skill name → exact-skill emphasis.
    if phrase:
        for entry in skills:
            if _skill_key(entry.get("skill")) == phrase:
                score += 1.0
                break

    if not matched_any:
        return None
    return score, reasons[:_MAX_MATCHED_REASONS], matched_skill_count


def _sort_result_skills(
    row: dict[str, Any], reasons: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Result-card skills: matched skills first, then strongest status."""
    matched = {
        str(r.get("label", "")).lower() for r in reasons if r.get("type") == "skill"
    }
    entries = list(row.get("skills") or [])
    entries.sort(
        key=lambda s: (
            0 if str(s.get("skill") or "").lower() in matched else 1,
            _STATUS_ORDER.get(str(s.get("status")), 9),
            str(s.get("skill") or ""),
        )
    )
    return [
        {
            "skill": s.get("skill"),
            "status": s.get("status"),
            "evidence_sources": list(s.get("evidence_sources") or []),
            "matched": str(s.get("skill") or "").lower() in matched,
        }
        for s in entries[:_MAX_RESULT_SKILLS]
    ]


def _result_card(
    row: dict[str, Any], evaluation: dict[str, Any]
) -> dict[str, Any]:
    reasons = list(evaluation.get("reasons") or [])
    return {
        "match_type": str(evaluation.get("match_type") or "match"),
        "requirements": list(evaluation.get("requirements") or []),
        "missing_requirements": list(evaluation.get("missing_requirements") or []),
        "public_slug": row.get("public_slug"),
        "display_name": row.get("display_name"),
        "headline": row.get("headline"),
        "location": row.get("location"),
        "availability_label": row.get("availability_label"),
        "institution": row.get("institution"),
        "degree": row.get("degree"),
        "graduation_year": row.get("graduation_year"),
        "role_areas": list(row.get("role_areas") or [])[:4],
        "skills": _sort_result_skills(row, reasons),
        "skill_count": int(row.get("skill_count") or 0),
        "project_count": int(row.get("project_count") or 0),
        "projects": [
            {
                "title": p.get("title"),
                "public_report_path": p.get("public_report_path"),
                "evidence_sources": list(p.get("evidence_sources") or []),
                "has_live_url": bool(p.get("has_live_url")),
            }
            for p in (row.get("projects") or [])[:_MAX_RESULT_PROJECTS]
        ],
        "evidence_flags": dict(row.get("evidence_flags") or {}),
        "matched_reasons": reasons,
        "passport_published_at": row.get("passport_published_at"),
    }


def _fetch_candidate_pool(db: Any, terms: list[str]) -> list[dict[str, Any]]:
    """Pull the bounded candidate pool for ranking.

    Supabase mode prefilters with trigram-accelerated ilike ORs across the
    flat search document when the query has terms; dict mode filters in
    Python with the same predicate. Ranking happens in one shared Python
    implementation either way.
    """
    if isinstance(db, dict):
        rows = list(_index_rows(db).values())
        if terms:
            rows = [
                r
                for r in rows
                if any(term in str(r.get("search_text") or "").lower() for term in terms)
            ]
        return rows[:_MAX_CANDIDATE_POOL]

    def _run(client: Any) -> Any:
        query = client.table(_INDEX_TABLE).select("*")
        if terms:
            # PostgREST or= filter: any term appearing anywhere in the document.
            # Terms are sanitized to [a-z0-9+#.] by tokenize_query; strip the
            # PostgREST reserved chars that could break the filter string.
            ors = ",".join(
                "search_text.ilike.*{}*".format(
                    term.replace(",", "").replace("(", "").replace(")", "")
                )
                for term in terms
            )
            query = query.or_(ors)
        return query.limit(_MAX_CANDIDATE_POOL).execute()

    result = _read_with_transient_retry(db, _run)
    return list(getattr(result, "data", []) or [])


# ── Requirement verification (evidence-grounded, never generative) ──────────
#
# The anti-hallucination contract lives here: a requirement is "satisfied"
# ONLY by an entry that exists in the candidate's indexed PUBLIC projection —
# a passport skill (evidence-backed) or a project technology (claimed on a
# published project). Taxonomy relationships may let a MORE SPECIFIC skill
# satisfy a MORE GENERAL requirement (FastAPI → "API development"), never the
# reverse, and "related" concepts satisfy nothing.

_TIER_SKILL = "skill"
_TIER_TECHNOLOGY = "technology"
# Generic evidence requirement key: "has at least one published project".
_EVIDENCE_REQ_PROJECT = "project"


def _candidate_evidence_map(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Concept slug → strongest public evidence record for this candidate."""
    out: dict[str, dict[str, Any]] = {}

    def better(new: dict[str, Any], old: dict[str, Any] | None) -> bool:
        if old is None:
            return True
        tier_rank = {_TIER_SKILL: 0, _TIER_TECHNOLOGY: 1}
        new_key = (
            tier_rank.get(new["tier"], 9),
            _STATUS_ORDER.get(str(new.get("skill_status")), 9),
        )
        old_key = (
            tier_rank.get(old["tier"], 9),
            _STATUS_ORDER.get(str(old.get("skill_status")), 9),
        )
        return new_key < old_key

    for entry in row.get("skills") or []:
        name = str(entry.get("skill") or "").strip()
        if not name:
            continue
        slug = str(entry.get("skill_slug") or "") or skill_slug(name)
        record = {
            "tier": _TIER_SKILL,
            "label": name,
            "skill_status": str(entry.get("status") or "Not assessed"),
            "evidence_sources": [str(s) for s in (entry.get("evidence_sources") or [])],
            "project_titles": [],
        }
        if better(record, out.get(slug)):
            out[slug] = record

    for proj in row.get("projects") or []:
        title = str(proj.get("title") or "").strip()
        for tech in proj.get("technologies") or []:
            name = str(tech or "").strip()
            if not name:
                continue
            slug = skill_slug(name)
            existing = out.get(slug)
            if existing is not None:
                if title and title not in existing["project_titles"]:
                    existing["project_titles"].append(title)
                continue
            out[slug] = {
                "tier": _TIER_TECHNOLOGY,
                "label": name,
                "skill_status": None,
                "evidence_sources": [str(s) for s in (proj.get("evidence_sources") or [])],
                "project_titles": [title] if title else [],
            }
    return out


def _verify_concept(
    evidence_map: dict[str, dict[str, Any]], group: list[str]
) -> dict[str, Any] | None:
    """Best satisfaction of one requirement group (OR of concept slugs).

    Preference order: evidence-backed skill over claimed technology, direct
    concept over a more-specific descendant, then strongest status.
    """
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, int] | None = None
    tier_rank = {_TIER_SKILL: 0, _TIER_TECHNOLOGY: 1}
    for req in group:
        for ev_slug, record in evidence_map.items():
            if not satisfies(ev_slug, req):
                continue
            direct = ev_slug == req
            key = (
                tier_rank.get(record["tier"], 9),
                0 if direct else 1,
                _STATUS_ORDER.get(str(record.get("skill_status")), 9),
            )
            if best_key is None or key < best_key:
                best_key = key
                best = {**record, "direct": direct, "requirement": req}
    return best


_REQ_WEIGHT = {
    (_TIER_SKILL, True): 5.0,
    (_TIER_SKILL, False): 4.5,
    (_TIER_TECHNOLOGY, True): 2.5,
    (_TIER_TECHNOLOGY, False): 2.2,
}

_SENIORITY_KEYWORDS = {
    "intern": ("intern",),
    "entry_level": ("entry", "junior", "new grad", "recent grad", "graduate"),
}


def _evidence_requirement_met(row: dict[str, Any], key: str) -> bool:
    if key == _EVIDENCE_REQ_PROJECT:
        return int(row.get("project_count") or 0) > 0
    flags = row.get("evidence_flags") or {}
    return bool(flags.get(key))


def _context_rows(
    row: dict[str, Any],
    plan: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    """Soft signals (role / seniority / location): explanation + rank boost,
    never hard gates — they live in profile prose, not verified evidence."""
    rows: list[dict[str, Any]] = []
    boost = 0.0
    headline = str(row.get("headline") or "").lower()
    role_areas = [str(a).lower() for a in (row.get("role_areas") or [])]

    role = plan.get("role")
    if role:
        display = str(role.get("display") or "")
        text_hit = display.lower() in headline or any(
            display.lower() in area or area in display.lower() for area in role_areas
        )
        hint_hit = any(
            _verify_concept(evidence_map, [hint]) is not None
            for hint in (role.get("hint_concepts") or [])
        )
        if text_hit or hint_hit:
            boost += 2.0
            rows.append(
                {
                    "kind": "context",
                    "requirement": "role",
                    "display": f"Role: {display}",
                    "required": False,
                    "satisfied": True,
                    "via": None,
                    "matched_label": str(row.get("headline") or "") if text_hit else None,
                    "skill_status": None,
                    "evidence_sources": [],
                    "project_titles": [],
                    "note": "Public Work Passport headline"
                    if text_hit
                    else "Related published evidence",
                }
            )

    seniority = plan.get("seniority")
    if seniority:
        key = str(seniority.get("key") or "")
        availability_label = str(row.get("availability_label") or "").lower()
        hit = False
        if key == "intern" and str(row.get("availability") or "") == "seeking_internship":
            hit = True
        for kw in _SENIORITY_KEYWORDS.get(key, ()):
            if kw in headline or kw in availability_label:
                hit = True
        if hit:
            boost += 1.0
            rows.append(
                {
                    "kind": "context",
                    "requirement": "seniority",
                    "display": f"Seniority: {seniority.get('display')}",
                    "required": False,
                    "satisfied": True,
                    "via": None,
                    "matched_label": row.get("availability_label"),
                    "skill_status": None,
                    "evidence_sources": [],
                    "project_titles": [],
                    "note": None,
                }
            )

    location = plan.get("location")
    # Canonicalize BOTH sides through the shared alias table so a plan
    # location of "massachusetts" matches a stored "Boston, MA" (and
    # "boston" still matches). Substring check on canonical strings only —
    # honesty unchanged: no match, no boost, no row.
    if location and _term_in(
        _canonical_location(location), _canonical_location(row.get("location"))
    ):
        boost += 1.0
        rows.append(
            {
                "kind": "context",
                "requirement": "location",
                "display": f"Location: {str(row.get('location') or '')}",
                "required": False,
                "satisfied": True,
                "via": None,
                "matched_label": row.get("location"),
                "skill_status": None,
                "evidence_sources": [],
                "project_titles": [],
                "note": None,
            }
        )
    return rows, boost


def _evaluate_candidate(
    row: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any] | None:
    """Verify every parsed requirement against this candidate's published
    evidence. Returns the structured evaluation, or None when the candidate
    matches nothing in the plan (or hits an exclusion)."""
    evidence_map = _candidate_evidence_map(row)

    # NOT-constraints: any public evidence for an excluded concept drops the
    # candidate entirely ("machine learning but not computer vision").
    for slug in plan.get("excluded") or []:
        if _verify_concept(evidence_map, [slug]) is not None:
            return None

    requirement_rows: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    score = 0.0
    matched_skill_count = 0
    satisfied_required = 0
    missing_required: list[str] = []

    def concept_row(
        group: list[str], required: bool
    ) -> None:
        nonlocal score, matched_skill_count, satisfied_required
        display = describe_group(group)
        hit = _verify_concept(evidence_map, group)
        if hit is None:
            requirement_rows.append(
                {
                    "kind": "concept",
                    "requirement": group[0],
                    "display": display,
                    "required": required,
                    "satisfied": False,
                    "via": None,
                    "matched_label": None,
                    "skill_status": None,
                    "evidence_sources": [],
                    "project_titles": [],
                    "note": f"No published {display} evidence",
                }
            )
            if required:
                missing_required.append(display)
            return
        weight = _REQ_WEIGHT[(hit["tier"], bool(hit["direct"]))]
        if hit["tier"] == _TIER_SKILL:
            weight += _STATUS_BONUS.get(str(hit.get("skill_status")), 0.0)
            bonus = 0.0
            for src in hit.get("evidence_sources") or []:
                bonus += _EVIDENCE_BONUS.get(str(src), 0.0)
            weight += min(bonus, _EVIDENCE_BONUS_CAP)
            matched_skill_count += 1
        if not required:
            weight *= 0.5
        score += weight
        if required:
            satisfied_required += 1
        note = None
        if not hit["direct"]:
            note = f"Satisfied by {hit['label']} evidence"
        elif hit["tier"] == _TIER_TECHNOLOGY:
            titles = hit.get("project_titles") or []
            note = f"Claimed in {titles[0]}" if titles else "Claimed on a public project"
        requirement_rows.append(
            {
                "kind": "concept",
                "requirement": hit["requirement"],
                "display": display,
                "required": required,
                "satisfied": True,
                "via": hit["tier"],
                "matched_label": hit["label"],
                "skill_status": hit.get("skill_status"),
                "evidence_sources": list(hit.get("evidence_sources") or []),
                "project_titles": list(hit.get("project_titles") or []),
                "note": note,
            }
        )
        reasons.append(
            {
                "type": "skill" if hit["tier"] == _TIER_SKILL else "technology",
                "label": str(hit["label"]),
                "term": display.lower(),
                **(
                    {"skill_status": hit.get("skill_status")}
                    if hit["tier"] == _TIER_SKILL
                    else {
                        "project_title": (hit.get("project_titles") or [""])[0]
                    }
                ),
                **(
                    {"evidence_sources": list(hit.get("evidence_sources") or [])}
                    if hit["tier"] == _TIER_SKILL
                    else {}
                ),
            }
        )

    for group in plan.get("required_groups") or []:
        concept_row(group, required=True)
    for slug in plan.get("preferred") or []:
        concept_row([slug], required=False)

    for key in plan.get("evidence") or []:
        met = _evidence_requirement_met(row, key)
        display = EVIDENCE_REQUIREMENT_DISPLAY.get(key, key)
        requirement_rows.append(
            {
                "kind": "evidence",
                "requirement": key,
                "display": display,
                "required": True,
                "satisfied": met,
                "via": None,
                "matched_label": None,
                "skill_status": None,
                "evidence_sources": [],
                "project_titles": [],
                "note": None if met else f"No published {display.lower()}",
            }
        )
        if met:
            satisfied_required += 1
            score += 1.5
        else:
            missing_required.append(display)

    for key in plan.get("preferred_evidence") or []:
        met = _evidence_requirement_met(row, key)
        display = EVIDENCE_REQUIREMENT_DISPLAY.get(key, key)
        requirement_rows.append(
            {
                "kind": "evidence",
                "requirement": key,
                "display": display,
                "required": False,
                "satisfied": met,
                "via": None,
                "matched_label": None,
                "skill_status": None,
                "evidence_sources": [],
                "project_titles": [],
                "note": None if met else f"Preferred — no published {display.lower()}",
            }
        )
        if met:
            score += 0.75

    context_rows, boost = _context_rows(row, plan, evidence_map)
    requirement_rows.extend(context_rows)
    score += boost

    # Residual free-text terms keep V1 lexical behavior (name, headline,
    # project prose …) — ranking signal only, never a hard requirement.
    residual = [t for t in (plan.get("residual_terms") or []) if t]
    if residual:
        lex = _match_candidate(row, residual, "")
        if lex is not None:
            lex_score, lex_reasons, lex_skills = lex
            score += lex_score
            matched_skill_count += lex_skills
            reasons.extend(lex_reasons)

    hard_total = len(plan.get("required_groups") or []) + len(plan.get("evidence") or [])
    if hard_total > 0:
        if satisfied_required == 0:
            return None  # matches no requirement — noise, not a close match
        match_type = "exact" if not missing_required else "close"
    else:
        # No hard requirements (role/seniority/location/preferred/lexical
        # only): anything that matched a soft signal is simply a match.
        if score <= 0.0:
            return None
        match_type = "match"

    return {
        "match_type": match_type,
        "requirements": requirement_rows,
        "missing_requirements": missing_required,
        "satisfied_required": satisfied_required,
        "score": score,
        "matched_skill_count": matched_skill_count,
        "reasons": reasons[:_MAX_MATCHED_REASONS],
    }


def _plan_interpretation(plan: dict[str, Any]) -> dict[str, Any]:
    """The 'Understood as …' payload shown to the recruiter — exactly what
    the engine executed, so ambiguity is exposed instead of silently guessed."""
    return {
        "mode": str(plan.get("mode") or "lexical"),
        "intent": str(plan.get("intent") or INTENT_CANDIDATE_SEARCH),
        "required": [
            {"display": describe_group(g), "concepts": list(g)}
            for g in (plan.get("required_groups") or [])
        ],
        "preferred": [
            {"display": concept_display(s), "concepts": [s]}
            for s in (plan.get("preferred") or [])
        ],
        "excluded": [
            {"display": concept_display(s), "concepts": [s]}
            for s in (plan.get("excluded") or [])
        ],
        "evidence": [
            {"key": k, "display": EVIDENCE_REQUIREMENT_DISPLAY.get(k, k)}
            for k in (plan.get("evidence") or [])
        ],
        "preferred_evidence": [
            {"key": k, "display": EVIDENCE_REQUIREMENT_DISPLAY.get(k, k)}
            for k in (plan.get("preferred_evidence") or [])
        ],
        "role": (plan.get("role") or {}).get("display"),
        "seniority": (plan.get("seniority") or {}).get("display"),
        "location": plan.get("location"),
        "remote": bool(plan.get("remote")),
        "residual_terms": list(plan.get("residual_terms") or []),
    }


def _retrieval_terms(plan: dict[str, Any]) -> list[str]:
    """Prefilter terms for the candidate pool: every requirement concept's
    expansion (aliases + descendants + related — recall only; verification
    happens after), role hints, and residual lexical terms."""
    terms: list[str] = []

    def add(term: str) -> None:
        t = str(term or "").strip().lower()
        if t and t not in terms:
            terms.append(t)

    for group in plan.get("required_groups") or []:
        for slug in group:
            for t in expansion_terms(slug):
                add(t)
    for slug in plan.get("preferred") or []:
        for t in expansion_terms(slug):
            add(t)
    role = plan.get("role")
    if role:
        add(str(role.get("display") or ""))
        for hint in role.get("hint_concepts") or []:
            for t in expansion_terms(hint):
                add(t)
    for t in plan.get("residual_terms") or []:
        add(t)
    return terms[:60]


def search_candidates(
    db: Any,
    *,
    q: str | None = None,
    skills: list[str] | None = None,
    evidence: list[str] | None = None,
    availability: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recruiter search over the public candidate projection.

    V1.5: the free-text query runs through deterministic recruiter-intent
    understanding (required / preferred / excluded concepts, evidence
    expectations, role/seniority/location signals), every requirement is
    verified against published evidence via the concept taxonomy, and
    results are classified EXACT (all requirements evidenced) vs CLOSE
    (missing at least one, said explicitly). Queries with no recognizable
    intent fall back to V1 lexical matching unchanged. Privacy: pool rows
    are re-validated against LIVE publication state, LIVE disclosure
    version, and the discovery-exclusions table — fail closed.

    V3: ``plan`` lets a Hiring Brief drive the search with its stored
    requirement plan instead of free text. The caller MUST pass a
    sanitize_plan() output; a brief plan always has candidate_search
    intent, so the evidence-discovery branch never triggers for it.
    """
    if plan is None:
        plan = parse_recruiter_query(q)
    else:
        # Defensive copy: this function mutates the plan (filter chips).
        plan = {**plan, "required_groups": [list(g) for g in plan.get("required_groups") or []]}

    # ── Evidence Discovery (V1.6): "show me proof of X" is NOT a candidate
    # search. The intent classifier separates finding people from opening
    # the proof behind a claim; evidence-type filter chips participate as
    # evidence-type gates on the proof itself. ──────────────────────────────
    if str(plan.get("intent")) in (INTENT_EVIDENCE_SEARCH, INTENT_PROJECT_SEARCH):
        from app.services.recruiter_evidence_service import build_evidence_results

        evidence_gate = [e for e in (evidence or []) if e in EVIDENCE_FILTERS]
        payload = build_evidence_results(
            db, plan=plan, extra_evidence_types=evidence_gate
        )
        return {
            "results": [],
            "total": int(payload.get("total_items") or 0),
            "exact_total": 0,
            "close_total": 0,
            "page": 1,
            "page_size": max(
                1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)
            ),
            "has_more": False,
            "interpretation": _plan_interpretation(plan),
            "evidence": payload,
            "query": {
                "q": str(q or "")[:MAX_QUERY_LENGTH],
                "terms": [],
                "skills": [],
                "evidence": evidence_gate,
                "availability": None,
            },
        }

    # Explicit structured params keep their V1 HARD-FILTER contract: a
    # filter chip excludes, full stop. Only natural-language expectations
    # participate in exact-vs-close classification. skills entries become
    # requirement groups whose absence DROPS the candidate (never "close");
    # evidence flags gate directly.
    hard_filter_displays: set[str] = set()
    for raw_skill in (skills or [])[:10]:
        slug = _skill_key(raw_skill)
        if slug and not any(slug in g for g in plan["required_groups"]):
            plan["required_groups"].append([slug])
            hard_filter_displays.add(describe_group([slug]))
    evidence_gate = [e for e in (evidence or []) if e in EVIDENCE_FILTERS]
    if plan["required_groups"]:
        if plan["mode"] in ("browse", "lexical"):
            plan["mode"] = "structured"

    availability_filter = (
        availability if availability in AVAILABILITY_VALUES else None
    )
    page = max(1, min(int(page or 1), MAX_PAGE))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    structured = plan["mode"] == "structured"
    # Lexical fallback matches on the parser's residual terms — recruiter
    # phrasing ("show", "me", "ignore") is already stripped, so it can never
    # substring-match candidate prose the way raw tokens could.
    lexical_terms = (
        [t for t in (plan.get("residual_terms") or []) if t]
        if plan["mode"] != "browse"
        else []
    )
    pool_terms = _retrieval_terms(plan) if structured else lexical_terms
    pool = _fetch_candidate_pool(db, pool_terms)

    # ── Live privacy re-validation (fail closed) ─────────────────────────────
    user_ids = [str(r.get("user_id")) for r in pool]
    published = _live_publication_map(db, user_ids)
    live_versions = _live_disclosure_versions(db, user_ids)
    discovery_excluded = _excluded_user_ids(db, user_ids)
    validated: list[dict[str, Any]] = []
    for row in pool:
        uid = str(row.get("user_id"))
        if uid in discovery_excluded:
            continue  # positively identified QA/demo account — never served
        if not published.get(uid):
            continue  # unpublished (or deleted) since projection — excluded
        if live_versions.get(uid, 1) > int(row.get("disclosure_version") or 1):
            # Disclosure changed after this row was projected: the row may
            # contain since-hidden data. Excluded until the refresh lands.
            continue
        validated.append(row)

    # ── Verify + classify + rank ─────────────────────────────────────────────
    phrase = _skill_key(str(q or "").strip()) if q else ""
    scored: list[
        tuple[int, float, int, int, str, str, dict[str, Any], dict[str, Any]]
    ] = []
    for row in validated:
        if availability_filter and str(row.get("availability") or "") != availability_filter:
            continue
        flags = row.get("evidence_flags") or {}
        if any(not flags.get(k) for k in evidence_gate):
            continue
        if structured:
            evaluation = _evaluate_candidate(row, plan)
            if evaluation is None:
                continue
            if hard_filter_displays and any(
                m in hard_filter_displays
                for m in evaluation["missing_requirements"]
            ):
                continue  # explicit skills filter — absence excludes, never "close"
        elif lexical_terms:
            lex = _match_candidate(row, lexical_terms, phrase)
            if lex is None:
                continue
            lex_score, lex_reasons, lex_skills = lex
            evaluation = {
                "match_type": "match",
                "requirements": [],
                "missing_requirements": [],
                "satisfied_required": 0,
                "score": lex_score,
                "matched_skill_count": lex_skills,
                "reasons": lex_reasons,
            }
        else:
            evaluation = {
                "match_type": "match",
                "requirements": [],
                "missing_requirements": [],
                "satisfied_required": 0,
                "score": 0.0,
                "matched_skill_count": 0,
                "reasons": [],
            }
        type_rank = 0 if evaluation["match_type"] in ("exact", "match") else 1
        published_at = str(row.get("passport_published_at") or "")
        slug = str(row.get("public_slug") or "")
        scored.append(
            (
                type_rank,
                evaluation["score"],
                evaluation["satisfied_required"],
                evaluation["matched_skill_count"],
                published_at,
                slug,
                row,
                evaluation,
            )
        )

    # Deterministic total order: exact before close, then score desc,
    # satisfied requirements desc, matched skills desc, newest first, slug.
    scored.sort(
        key=lambda item: (
            item[0],
            -item[1],
            -item[2],
            -item[3],
            _desc_str(item[4]),
            item[5],
        )
    )

    exact_total = sum(1 for item in scored if item[0] == 0)
    close_total = len(scored) - exact_total
    total = len(scored)
    start = (page - 1) * page_size
    page_items = scored[start : start + page_size]

    return {
        "results": [
            _result_card(row, evaluation) for *_, row, evaluation in page_items
        ],
        "total": total,
        "exact_total": exact_total,
        "close_total": close_total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "interpretation": _plan_interpretation(plan),
        "query": {
            "q": str(q or "")[:MAX_QUERY_LENGTH],
            "terms": lexical_terms,
            "skills": [s for s in (skills or []) if str(s or "").strip()][:10],
            "evidence": [e for e in (evidence or []) if e in EVIDENCE_FILTERS],
            "availability": availability_filter,
        },
    }


def _desc_str(value: str) -> tuple[int, ...]:
    """Sort helper: descending order for an ISO date string inside an
    ascending sort key (missing dates sort last)."""
    if not value:
        return (1,)
    return (0,) + tuple(255 - b for b in value.encode("utf-8", "ignore"))


# ── Observability (coarse, best-effort) ──────────────────────────────────────


def record_search_event(
    db: Any,
    *,
    recruiter_user_id: str | None,
    q: str | None,
    filters: dict[str, Any],
    result_count: int,
) -> None:
    """Best-effort search analytics — never an error surface, never evidence."""
    try:
        row = {
            "recruiter_user_id": str(recruiter_user_id) if recruiter_user_id else None,
            "query_text": str(q or "")[:MAX_QUERY_LENGTH] or None,
            "filters": make_json_safe(
                {k: v for k, v in (filters or {}).items() if v}
            ),
            "result_count": int(result_count),
            "zero_results": int(result_count) == 0,
            "created_at": _now_iso(),
        }
        if isinstance(db, dict):
            from uuid import uuid4

            row["id"] = str(uuid4())
            db.setdefault(_EVENTS_TABLE, {})[row["id"]] = row
            return
        db.table(_EVENTS_TABLE).insert(make_json_safe(row)).execute()
    except Exception:
        logger.warning("search event recording failed", exc_info=True)


__all__ = [
    "AVAILABILITY_VALUES",
    "parse_recruiter_query",
    "DEFAULT_PAGE_SIZE",
    "EVIDENCE_FILTERS",
    "MAX_PAGE",
    "MAX_PAGE_SIZE",
    "MAX_QUERY_LENGTH",
    "build_index_row",
    "rebuild_search_index",
    "record_search_event",
    "refresh_search_projection",
    "search_candidates",
    "tokenize_query",
]
