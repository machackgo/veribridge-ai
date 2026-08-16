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
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

_INDEX_TABLE = "recruiter_search_index"
_EVENTS_TABLE = "recruiter_search_events"
_PASSPORTS_TABLE = "vbr_work_passports"
_POLICIES_TABLE = "passport_disclosure_policies"

# ── Query / pagination limits ────────────────────────────────────────────────

MAX_QUERY_LENGTH = 200
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

        # 7. Location.
        if best_weight < _WEIGHT_LOCATION and _term_in(term, row.get("location")):
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


def _passes_filters(
    row: dict[str, Any],
    *,
    skills: list[str],
    evidence: list[str],
    availability: str | None,
) -> bool:
    if availability and str(row.get("availability") or "") != availability:
        return False
    flags = row.get("evidence_flags") or {}
    for key in evidence:
        if not flags.get(key):
            return False
    if skills:
        have = {_skill_key(s.get("skill")) for s in (row.get("skills") or [])}
        have |= {
            _skill_key(t)
            for p in (row.get("projects") or [])
            for t in (p.get("technologies") or [])
        }
        for wanted in skills:
            if _skill_key(wanted) not in have:
                return False
    return True


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
    row: dict[str, Any], reasons: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
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


def search_candidates(
    db: Any,
    *,
    q: str | None = None,
    skills: list[str] | None = None,
    evidence: list[str] | None = None,
    availability: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Deterministic recruiter search over the public candidate projection.

    Free text + structured filters; explainable weighted ranking; stable
    pagination. Privacy: pool rows are re-validated against LIVE publication
    state and LIVE disclosure_version in batch — stale rows are excluded.
    """
    terms = tokenize_query(q)
    phrase = _skill_key(str(q or "").strip()) if q else ""
    skills_filter = [s for s in (skills or []) if str(s or "").strip()][:10]
    evidence_filter = [e for e in (evidence or []) if e in EVIDENCE_FILTERS]
    availability_filter = (
        availability if availability in AVAILABILITY_VALUES else None
    )
    page = max(1, min(int(page or 1), MAX_PAGE))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    pool = _fetch_candidate_pool(db, terms)

    # ── Live privacy re-validation (fail closed) ─────────────────────────────
    user_ids = [str(r.get("user_id")) for r in pool]
    published = _live_publication_map(db, user_ids)
    live_versions = _live_disclosure_versions(db, user_ids)
    validated: list[dict[str, Any]] = []
    for row in pool:
        uid = str(row.get("user_id"))
        if not published.get(uid):
            continue  # unpublished (or deleted) since projection — excluded
        if live_versions.get(uid, 1) > int(row.get("disclosure_version") or 1):
            # Disclosure changed after this row was projected: the row may
            # contain since-hidden data. Excluded until the refresh lands.
            continue
        validated.append(row)

    # ── Filter + rank ────────────────────────────────────────────────────────
    scored: list[tuple[float, int, str, str, dict[str, Any], list[dict[str, Any]]]] = []
    for row in validated:
        if not _passes_filters(
            row,
            skills=skills_filter,
            evidence=evidence_filter,
            availability=availability_filter,
        ):
            continue
        if terms:
            match = _match_candidate(row, terms, phrase)
            if match is None:
                continue
            score, reasons, matched_skills = match
        else:
            score, reasons, matched_skills = 0.0, [], 0
        published_at = str(row.get("passport_published_at") or "")
        slug = str(row.get("public_slug") or "")
        scored.append((score, matched_skills, published_at, slug, row, reasons))

    # Deterministic order: score desc, matched skills desc, newest first,
    # slug asc as the total-order tiebreak.
    scored.sort(key=lambda item: (-item[0], -item[1], _desc_str(item[2]), item[3]))

    total = len(scored)
    start = (page - 1) * page_size
    page_items = scored[start : start + page_size]

    return {
        "results": [_result_card(row, reasons) for _, _, _, _, row, reasons in page_items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "query": {
            "q": str(q or "")[:MAX_QUERY_LENGTH],
            "terms": terms,
            "skills": skills_filter,
            "evidence": evidence_filter,
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
