"""Recruiter candidate comparison + persisted comparison sessions (migration 068).

Evidence-based comparison: the recruiter selects 2–5 saved candidates and a
role brief (natural language and/or edited requirement chips), and gets a
requirement × candidate matrix where every cell is a deterministic evidence
state derived from the SAME machinery as recruiter search:

  * the candidate axis is the recruiter_search_index row — itself derived
    exclusively from the public passport projection (privacy by construction);
  * requirement satisfaction reuses ``_candidate_evidence_map`` /
    ``_verify_concept`` and the taxonomy ``satisfies()`` contract — a child
    skill proves a parent requirement, NEVER the reverse, and "related"
    concepts prove nothing;
  * every load re-runs the live fail-closed triple (discovery exclusions,
    ``is_published``, ``disclosure_version``) — a persisted comparison stores
    NO evidence snapshot, so unpublished evidence can never be served stale.

Cell states are a closed vocabulary, never a score:

  ``proven``       — evidence-backed passport skill satisfies the requirement
  ``claimed``      — only a project-technology claim ("Claimed — not verified
                     evidence"); surfaced but visually distinct from proof
  ``none``         — no published evidence (optionally with RELATED hints,
                     explicitly labeled as not proof)
  ``unavailable``  — the candidate is no longer publicly comparable
                     (unpublished / excluded / stale disclosure)

Transparent counts ("2 of 3 required requirements proven") are allowed;
percentages and opaque composite scores are not.

Persisted sessions (``recruiter_comparisons``) store the recruiter's brief:
title, raw role text, the structured requirement plan (the future Hiring
Brief primitive), and the selected candidates by stable user id. They are
recruiter-isolated at the app level AND by RLS.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.serialization import make_json_safe
from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    MAX_QUERY_LENGTH,
    describe_group,
    parse_recruiter_query,
)

# Closed evidence-phrase vocabulary reused so a manually typed requirement
# like "live deployment" lands on the same evidence key the NL parser uses.
from app.services.recruiter_query_understanding import (  # noqa: F401
    _EVIDENCE_PHRASES as _EVIDENCE_PHRASE_TO_KEY,
)
from app.services.recruiter_search_service import (
    _candidate_evidence_map,
    _evidence_requirement_met,
    _excluded_user_ids,
    _live_disclosure_versions,
    _live_publication_map,
    _read_with_transient_retry,
    _verify_concept,
)
from app.services.recruiter_search_taxonomy import (
    PHRASE_TO_CONCEPT,
    ancestors,
    concept_display,
    related,
)
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

_COMPARISONS_TABLE = "recruiter_comparisons"
_INDEX_TABLE = "recruiter_search_index"
_CONNECTIONS_TABLE = "recruiter_candidate_connections"
_PASSPORTS_TABLE = "vbr_work_passports"

MIN_COMPARE_CANDIDATES = 2
MAX_COMPARE_CANDIDATES = 5
MAX_REQUIREMENT_ROWS = 16
MAX_TITLE_LENGTH = 120
MAX_LIST_COMPARISONS = 50
_MAX_CELL_PROJECTS = 3
_MAX_CELL_TRACES = 2
_MAX_RELATED_HINTS = 2

CELL_PROVEN = "proven"
CELL_CLAIMED = "claimed"
CELL_NONE = "none"
CELL_UNAVAILABLE = "unavailable"


class ComparisonError(Exception):
    """Recruiter-facing comparison input problem (maps to 400/422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ComparisonNotFound(Exception):
    """Missing OR another recruiter's comparison — indistinguishable."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Requirement normalization (manual chips ↔ plan) ──────────────────────────


def _normalize_phrase(term: Any) -> str:
    return " ".join(str(term or "").strip().lower().split())


def normalize_requirement_term(term: Any) -> tuple[str, str] | None:
    """Map one manually entered requirement onto the closed vocabularies.

    Returns ``("evidence", key)`` when the term is an evidence expectation
    ("live deployment", "github proof"), else ``("concept", slug)``.
    Unrecognized concepts still normalize through ``skill_slug`` so the
    matrix can honestly report "no published evidence" for them.
    """
    phrase = _normalize_phrase(term)
    if not phrase:
        return None
    if phrase in _EVIDENCE_PHRASE_TO_KEY:
        return ("evidence", _EVIDENCE_PHRASE_TO_KEY[phrase])
    if phrase in EVIDENCE_REQUIREMENT_DISPLAY:
        return ("evidence", phrase)
    concept = PHRASE_TO_CONCEPT.get(phrase)
    if concept:
        return ("concept", concept)
    # "Fast API" → "fastapi": collapsed spelling often IS the known concept.
    collapsed = phrase.replace(" ", "")
    concept = PHRASE_TO_CONCEPT.get(collapsed)
    if concept:
        return ("concept", concept)
    return ("concept", skill_slug(phrase))


def _concept_slugs(values: Any) -> list[str]:
    """Normalize a client-supplied concept list; drops evidence-key strays."""
    out: list[str] = []
    for value in list(values or [])[: MAX_REQUIREMENT_ROWS * 2]:
        normalized = normalize_requirement_term(value)
        if normalized is None:
            continue
        kind, slug = normalized
        if kind != "concept":
            continue
        if slug and slug not in out:
            out.append(slug)
    return out


def _evidence_keys(values: Any) -> list[str]:
    out: list[str] = []
    for value in list(values or [])[: MAX_REQUIREMENT_ROWS * 2]:
        normalized = normalize_requirement_term(value)
        if normalized is None:
            continue
        _, key = normalized
        if key in EVIDENCE_REQUIREMENT_DISPLAY and key not in out:
            out.append(key)
    return out


def plan_from_requirements(requirements: dict[str, Any]) -> dict[str, Any]:
    """Build the structured plan from the recruiter's EDITED requirement
    chips. Required entries may be a plain term or a list (an OR-group).
    Terms that are actually evidence expectations ("live deployment") are
    routed to the evidence buckets rather than becoming fake concepts."""
    required_groups: list[list[str]] = []
    evidence: list[str] = []
    preferred: list[str] = []
    preferred_evidence: list[str] = []

    def _route(term: Any, *, required: bool, group: list[str] | None) -> None:
        normalized = normalize_requirement_term(term)
        if normalized is None:
            return
        kind, value = normalized
        if kind == "evidence":
            bucket = evidence if required else preferred_evidence
            if value not in bucket:
                bucket.append(value)
            return
        if group is not None:
            if value not in group:
                group.append(value)
        elif required:
            if not any(value in g for g in required_groups):
                required_groups.append([value])
        else:
            if value not in preferred:
                preferred.append(value)

    for entry in list(requirements.get("required") or [])[:MAX_REQUIREMENT_ROWS]:
        if isinstance(entry, (list, tuple)):
            group: list[str] = []
            for term in list(entry)[:6]:
                _route(term, required=True, group=group)
            if group and group not in required_groups:
                required_groups.append(group)
        else:
            _route(entry, required=True, group=None)

    for entry in list(requirements.get("preferred") or [])[:MAX_REQUIREMENT_ROWS]:
        _route(entry, required=False, group=None)

    for key in _evidence_keys(requirements.get("evidence")):
        if key not in evidence:
            evidence.append(key)
    for key in _evidence_keys(requirements.get("preferred_evidence")):
        if key not in evidence and key not in preferred_evidence:
            preferred_evidence.append(key)

    role_display = str(requirements.get("role") or "").strip()[:80] or None
    seniority = requirements.get("seniority")
    seniority_payload = None
    if isinstance(seniority, dict) and seniority.get("key"):
        seniority_payload = {
            "key": str(seniority.get("key")),
            "display": str(seniority.get("display") or seniority.get("key")),
        }
    elif isinstance(seniority, str) and seniority.strip():
        key = seniority.strip().lower().replace(" ", "_").replace("-", "_")
        seniority_payload = {
            "key": key,
            "display": seniority.strip().replace("_", " ").title(),
        }

    location = _normalize_phrase(requirements.get("location"))[:60] or None

    return {
        "raw": "",
        "mode": "structured",
        "intent": "candidate_search",
        "required_groups": required_groups[:MAX_REQUIREMENT_ROWS],
        "preferred": preferred[:MAX_REQUIREMENT_ROWS],
        "excluded": _concept_slugs(requirements.get("excluded")),
        "evidence": evidence,
        "preferred_evidence": preferred_evidence,
        "role": {"display": role_display, "hint_concepts": []} if role_display else None,
        "seniority": seniority_payload,
        "location": location,
        "residual_terms": [],
    }


def plan_from_role_text(role_text: Any) -> dict[str, Any]:
    """Parse a natural-language role brief with the SAME deterministic
    grammar as recruiter search. Comparison always evaluates candidates, so
    the parsed intent is irrelevant here (a brief like "show me who has ML
    proof" still becomes requirements)."""
    plan = parse_recruiter_query(str(role_text or "")[:MAX_QUERY_LENGTH])
    plan["intent"] = "candidate_search"
    return plan


def _sanitize_plan(plan: Any) -> dict[str, Any]:
    """Re-normalize a stored plan (jsonb round-trip / older shape) so the
    engine only ever sees closed-vocabulary slugs and keys."""
    if not isinstance(plan, dict):
        return plan_from_requirements({})
    groups: list[list[str]] = []
    for group in list(plan.get("required_groups") or [])[:MAX_REQUIREMENT_ROWS]:
        if isinstance(group, (list, tuple)):
            slugs = [skill_slug(str(s)) for s in group if str(s or "").strip()]
        else:
            slugs = [skill_slug(str(group))]
        slugs = [s for s in slugs if s]
        if slugs:
            groups.append(slugs[:6])
    return {
        "raw": str(plan.get("raw") or "")[:MAX_QUERY_LENGTH],
        "mode": "structured" if groups or plan.get("evidence") else str(plan.get("mode") or "structured"),
        "intent": "candidate_search",
        "required_groups": groups,
        "preferred": [
            skill_slug(str(s))
            for s in list(plan.get("preferred") or [])[:MAX_REQUIREMENT_ROWS]
            if str(s or "").strip()
        ],
        "excluded": [
            skill_slug(str(s))
            for s in list(plan.get("excluded") or [])[:MAX_REQUIREMENT_ROWS]
            if str(s or "").strip()
        ],
        "evidence": [
            k for k in list(plan.get("evidence") or []) if k in EVIDENCE_REQUIREMENT_DISPLAY
        ],
        "preferred_evidence": [
            k
            for k in list(plan.get("preferred_evidence") or [])
            if k in EVIDENCE_REQUIREMENT_DISPLAY
        ],
        "role": plan.get("role") if isinstance(plan.get("role"), dict) else None,
        "seniority": plan.get("seniority") if isinstance(plan.get("seniority"), dict) else None,
        "location": _normalize_phrase(plan.get("location"))[:60] or None,
        "residual_terms": [
            str(t) for t in list(plan.get("residual_terms") or [])[:12]
        ],
    }


def requirements_view(plan: dict[str, Any]) -> dict[str, Any]:
    """Editable-chips payload: exactly what the engine will evaluate, in a
    shape the UI can edit and post back through ``requirements``."""
    return {
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
        # Terms the parser could not turn into a requirement — surfaced so
        # the recruiter can see what was NOT understood, never silently used.
        "unrecognized_terms": list(plan.get("residual_terms") or []),
    }


# ── Candidate resolution ─────────────────────────────────────────────────────


def _own_connection_rows(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        return [
            r
            for r in db.setdefault(_CONNECTIONS_TABLE, {}).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_CONNECTIONS_TABLE)
        .select("*")
        .eq("recruiter_user_id", recruiter_user_id)
        .execute(),
    )
    return list(getattr(result, "data", []) or [])


def _published_passports_by_slugs(db: Any, slugs: list[str]) -> dict[str, dict[str, Any]]:
    if not slugs:
        return {}
    if isinstance(db, dict):
        return {
            str(r.get("public_slug")): r
            for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
            if r.get("is_published") and str(r.get("public_slug")) in set(slugs)
        }
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_PASSPORTS_TABLE)
        .select("user_id, public_slug, is_published")
        .in_("public_slug", slugs)
        .eq("is_published", True)
        .execute(),
    )
    return {
        str(r.get("public_slug")): r
        for r in (getattr(result, "data", []) or [])
        if r.get("is_published")
    }


def resolve_candidate_user_ids(
    db: Any,
    recruiter_user_id: str,
    *,
    connection_ids: list[str] | None = None,
    candidate_slugs: list[str] | None = None,
) -> list[str]:
    """Resolve the recruiter's selection to stable student user ids.

    ``connection_ids`` must be the caller's OWN connections (foreign ids are
    indistinguishable from missing — same error). ``candidate_slugs`` must be
    actively published passports. One human → one column: duplicates collapse
    by user id, preserving first-selection order.
    """
    ordered: list[str] = []

    if connection_ids:
        own = {str(r.get("id")): r for r in _own_connection_rows(db, recruiter_user_id)}
        for cid in connection_ids:
            row = own.get(str(cid or "").strip())
            if row is None:
                raise ComparisonError(
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
                raise ComparisonError(
                    "candidate_not_found",
                    "One of the selected candidates is not available.",
                )
            uid = str(passport.get("user_id"))
            if uid not in ordered:
                ordered.append(uid)

    if len(ordered) > MAX_COMPARE_CANDIDATES:
        raise ComparisonError(
            "too_many_candidates",
            f"Compare up to {MAX_COMPARE_CANDIDATES} candidates at a time.",
        )
    if len(ordered) < MIN_COMPARE_CANDIDATES:
        raise ComparisonError(
            "too_few_candidates",
            f"Select at least {MIN_COMPARE_CANDIDATES} candidates to compare.",
        )
    return ordered


# ── Matrix evaluation ────────────────────────────────────────────────────────


def _index_rows_by_user_ids(db: Any, user_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not user_ids:
        return {}
    if isinstance(db, dict):
        wanted = {str(u) for u in user_ids}
        return {
            str(r.get("user_id")): r
            for r in db.setdefault(_INDEX_TABLE, {}).values()
            if str(r.get("user_id")) in wanted
        }
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_INDEX_TABLE)
        .select("*")
        .in_("user_id", user_ids)
        .execute(),
    )
    return {
        str(r.get("user_id")): r for r in (getattr(result, "data", []) or [])
    }


def _requirement_axis(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The matrix's requirement rows: required concepts, then required
    evidence, then preferred concepts, then preferred evidence."""
    axis: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(entry: dict[str, Any]) -> None:
        if entry["key"] in seen or len(axis) >= MAX_REQUIREMENT_ROWS:
            return
        seen.add(entry["key"])
        axis.append(entry)

    for group in plan.get("required_groups") or []:
        add(
            {
                "key": "concept:" + "|".join(group),
                "kind": "concept",
                "display": describe_group(group),
                "required": True,
                "concepts": list(group),
            }
        )
    for key in plan.get("evidence") or []:
        add(
            {
                "key": f"evidence:{key}",
                "kind": "evidence",
                "display": EVIDENCE_REQUIREMENT_DISPLAY.get(key, key),
                "required": True,
                "concepts": [key],
            }
        )
    for slug in plan.get("preferred") or []:
        add(
            {
                "key": f"concept:{slug}",
                "kind": "concept",
                "display": concept_display(slug),
                "required": False,
                "concepts": [slug],
            }
        )
    for key in plan.get("preferred_evidence") or []:
        add(
            {
                "key": f"evidence:{key}",
                "kind": "evidence",
                "display": EVIDENCE_REQUIREMENT_DISPLAY.get(key, key),
                "required": False,
                "concepts": [key],
            }
        )
    return axis


def _skill_entry_for(row: dict[str, Any], evidence_slug: str) -> dict[str, Any] | None:
    for entry in row.get("skills") or []:
        slug = str(entry.get("skill_slug") or "") or skill_slug(
            str(entry.get("skill") or "")
        )
        if slug == evidence_slug:
            return entry
    return None


def _proof_refs(row: dict[str, Any], evidence_slug: str) -> dict[str, Any]:
    """Provenance for a proven cell, straight from the indexed public
    projection: the skill report deep link plus compact project/trace refs.
    Nothing here exists outside the public passport."""
    slug = str(row.get("public_slug") or "")
    entry = _skill_entry_for(row, evidence_slug)
    projects = []
    traces = []
    if entry is not None:
        projects = [
            {
                "title": p.get("title"),
                "public_report_path": p.get("public_report_path"),
                "skill_status": p.get("skill_status"),
                "proof_types": list(p.get("proof_types") or []),
            }
            for p in (entry.get("projects") or [])[:_MAX_CELL_PROJECTS]
        ]
        traces = [
            {
                "source_type": t.get("source_type"),
                "source_title": t.get("source_title"),
                "summary": t.get("summary"),
                "public_url": t.get("public_url"),
            }
            for t in (entry.get("traces") or [])[:_MAX_CELL_TRACES]
        ]
    proof_path = (
        f"/p/{slug}/skills/{evidence_slug}" if slug and entry is not None else None
    )
    return {"proof_path": proof_path, "projects": projects, "traces": traces}


def _related_hints(
    evidence_map: dict[str, dict[str, Any]], concepts: list[str]
) -> list[str]:
    """Adjacent published evidence for an unsupported requirement — shown as
    RELATED, never as proof. Covers taxonomy `related` links plus evidence
    for a strict ancestor (more general than what was asked)."""
    hints: list[str] = []
    for req in concepts:
        adjacent = set(related(req)) | set(ancestors(req))
        for ev_slug, record in evidence_map.items():
            if ev_slug in adjacent and record["tier"] == "skill":
                label = str(record.get("label") or "")
                if label and label not in hints:
                    hints.append(label)
    return hints[:_MAX_RELATED_HINTS]


def _empty_cell(state: str, note: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "matched_label": None,
        "skill_status": None,
        "direct": True,
        "evidence_sources": [],
        "project_titles": [],
        "note": note,
        "proof_path": None,
        "projects": [],
        "traces": [],
        "related": [],
    }


def _concept_cell(
    row: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]],
    concepts: list[str],
    display: str,
) -> dict[str, Any]:
    hit = _verify_concept(evidence_map, concepts)
    if hit is None:
        cell = _empty_cell(CELL_NONE, f"No published {display} evidence")
        cell["related"] = _related_hints(evidence_map, concepts)
        return cell

    # _verify_concept records don't carry the winning evidence slug, so
    # recover it from the matched label — the same normalization that built
    # the evidence map keys.
    evidence_slug = skill_slug(str(hit.get("label") or ""))

    if hit["tier"] == "skill":
        note = None
        if not hit["direct"]:
            note = f"Satisfied by {hit['label']} evidence"
        cell = {
            "state": CELL_PROVEN,
            "matched_label": hit.get("label"),
            "skill_status": hit.get("skill_status"),
            "direct": bool(hit.get("direct")),
            "evidence_sources": list(hit.get("evidence_sources") or []),
            "project_titles": list(hit.get("project_titles") or []),
            "note": note,
            "related": [],
        }
        cell.update(_proof_refs(row, evidence_slug))
        return cell

    titles = list(hit.get("project_titles") or [])
    note = f"Claimed in {titles[0]}" if titles else "Claimed on a public project"
    return {
        "state": CELL_CLAIMED,
        "matched_label": hit.get("label"),
        "skill_status": None,
        "direct": bool(hit.get("direct")),
        "evidence_sources": list(hit.get("evidence_sources") or []),
        "project_titles": titles,
        "note": f"{note} — not verified evidence",
        "proof_path": None,
        "projects": [],
        "traces": [],
        "related": [],
    }


def _evidence_cell(row: dict[str, Any], key: str, display: str) -> dict[str, Any]:
    met = _evidence_requirement_met(row, key)
    if not met:
        return _empty_cell(CELL_NONE, f"No published {display.lower()}")
    cell = _empty_cell(CELL_PROVEN)
    cell["matched_label"] = display
    return cell


def _candidate_column(
    row: dict[str, Any], axis: list[dict[str, Any]], plan: dict[str, Any]
) -> dict[str, Any]:
    evidence_map = _candidate_evidence_map(row)
    cells: dict[str, dict[str, Any]] = {}
    counts = {
        "required_proven": 0,
        "required_claimed": 0,
        "required_total": 0,
        "preferred_proven": 0,
        "preferred_claimed": 0,
        "preferred_total": 0,
    }
    missing_required: list[str] = []
    missing_preferred: list[str] = []

    for req in axis:
        if req["kind"] == "concept":
            cell = _concept_cell(row, evidence_map, req["concepts"], req["display"])
        else:
            cell = _evidence_cell(row, req["concepts"][0], req["display"])
        cells[req["key"]] = cell

        bucket = "required" if req["required"] else "preferred"
        counts[f"{bucket}_total"] += 1
        if cell["state"] == CELL_PROVEN:
            counts[f"{bucket}_proven"] += 1
        elif cell["state"] == CELL_CLAIMED:
            counts[f"{bucket}_claimed"] += 1
        else:
            (missing_required if req["required"] else missing_preferred).append(
                req["display"]
            )

    # NOT-constraints: comparison never hides a candidate the recruiter
    # explicitly selected — it flags the conflict honestly instead.
    excluded_hits: list[str] = []
    for slug in plan.get("excluded") or []:
        if _verify_concept(evidence_map, [slug]) is not None:
            excluded_hits.append(concept_display(slug))

    public_slug = str(row.get("public_slug") or "")
    return {
        "user_id": str(row.get("user_id")),
        "available": True,
        "public_slug": public_slug or None,
        "display_name": row.get("display_name"),
        "headline": row.get("headline"),
        "availability_label": row.get("availability_label"),
        "passport_path": f"/p/{public_slug}" if public_slug else None,
        "cells": cells,
        "counts": counts,
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
        "excluded_hits": excluded_hits,
        "unavailable_note": None,
    }


def _unavailable_column(user_id: str, identity: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "user_id": str(user_id),
        "available": False,
        "public_slug": None,
        "display_name": (identity or {}).get("display_name"),
        "headline": None,
        "availability_label": None,
        "passport_path": None,
        "cells": {},
        "counts": {
            "required_proven": 0,
            "required_claimed": 0,
            "required_total": 0,
            "preferred_proven": 0,
            "preferred_claimed": 0,
            "preferred_total": 0,
        },
        "missing_required": [],
        "missing_preferred": [],
        "excluded_hits": [],
        "unavailable_note": "This candidate's evidence is no longer publicly available.",
    }


def _column_summary(column: dict[str, Any]) -> str:
    name = str(column.get("display_name") or "This candidate")
    if not column.get("available"):
        return f"{name}: evidence no longer publicly available."
    counts = column["counts"]
    parts: list[str] = []
    if counts["required_total"]:
        line = (
            f"published evidence for {counts['required_proven']} of "
            f"{counts['required_total']} required requirements"
        )
        if counts["required_claimed"]:
            line += (
                f" (plus {counts['required_claimed']} claimed — not verified)"
            )
        parts.append(line)
    if counts["preferred_total"]:
        parts.append(
            f"{counts['preferred_proven']} of {counts['preferred_total']} preferred"
        )
    if column["missing_required"]:
        parts.append("missing " + ", ".join(column["missing_required"][:4]))
    if column["excluded_hits"]:
        parts.append(
            "has excluded " + ", ".join(column["excluded_hits"][:2]) + " evidence"
        )
    if not parts:
        parts.append("no requirements evaluated")
    return f"{name}: " + "; ".join(parts) + "."


def evaluate_matrix(
    db: Any,
    *,
    recruiter_user_id: str,
    candidate_user_ids: list[str],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic requirement × candidate evidence matrix.

    Re-runs the live fail-closed triple on every call — the matrix can only
    ever show what the candidates' public passports show right now.
    """
    plan = _sanitize_plan(plan)
    ordered = [str(u) for u in candidate_user_ids][:MAX_COMPARE_CANDIDATES]
    axis = _requirement_axis(plan)

    rows = _index_rows_by_user_ids(db, ordered)
    user_ids = list(rows.keys())
    excluded = _excluded_user_ids(db, user_ids) if user_ids else set()
    published = _live_publication_map(db, user_ids) if user_ids else {}
    live_versions = _live_disclosure_versions(db, user_ids) if user_ids else {}

    valid: dict[str, dict[str, Any]] = {}
    for uid, row in rows.items():
        if uid in excluded:
            continue
        if not published.get(uid, False):
            continue
        if live_versions.get(uid, 1) > int(row.get("disclosure_version") or 1):
            continue
        valid[uid] = row

    # Identity fallback for unavailable columns comes from the recruiter's
    # OWN saved-candidate rows (never from the stale index row).
    connection_by_student = {
        str(r.get("student_user_id")): r
        for r in _own_connection_rows(db, recruiter_user_id)
    }

    columns: list[dict[str, Any]] = []
    for uid in ordered:
        row = valid.get(uid)
        if row is None:
            identity = None
            if connection_by_student.get(uid) is not None:
                # The recruiter already sees this candidate's consented
                # identity in their workspace listing — reuse that exact
                # projection (never the stale index row).
                try:
                    from app.services.recruiter_connection_service import (
                        _candidate_summary,
                    )

                    identity = _candidate_summary(db, uid)
                except Exception:
                    identity = None
            columns.append(_unavailable_column(uid, identity))
        else:
            columns.append(_candidate_column(row, axis, plan))

    # Attach the recruiter's own connection id/status so the matrix can
    # shortlist in place. Never another recruiter's data by construction.
    for column in columns:
        conn = connection_by_student.get(column["user_id"])
        column["connection"] = (
            {
                "id": str(conn.get("id")),
                "status": str(conn.get("status") or "saved"),
            }
            if conn is not None
            else None
        )

    coverage = []
    available_columns = [c for c in columns if c.get("available")]
    for req in axis:
        supported = sum(
            1
            for c in available_columns
            if c["cells"].get(req["key"], {}).get("state") == CELL_PROVEN
        )
        claimed = sum(
            1
            for c in available_columns
            if c["cells"].get(req["key"], {}).get("state") == CELL_CLAIMED
        )
        coverage.append(
            {
                "key": req["key"],
                "display": req["display"],
                "required": req["required"],
                "proven_count": supported,
                "claimed_count": claimed,
                "candidate_total": len(available_columns),
            }
        )

    notes: list[str] = []
    for entry in coverage:
        if (
            entry["candidate_total"] > 0
            and entry["proven_count"] == 0
            and entry["claimed_count"] == 0
        ):
            notes.append(
                f"No selected candidate has published {entry['display']} evidence."
            )
    unavailable_count = len(columns) - len(available_columns)
    if unavailable_count:
        notes.append(
            f"{unavailable_count} selected "
            + ("candidate is" if unavailable_count == 1 else "candidates are")
            + " no longer publicly available."
        )
    if not axis:
        notes.append(
            "No requirements yet — describe the role or add requirements to "
            "build the evidence matrix."
        )

    return {
        "requirements": axis,
        "columns": columns,
        "coverage": coverage,
        "summaries": [_column_summary(c) for c in columns],
        "notes": notes,
        "requirements_view": requirements_view(plan),
        "plan": plan,
    }


# ── Persisted comparison sessions (CRUD, recruiter-isolated) ─────────────────


def _comparison_rows(db: Any) -> dict[str, dict[str, Any]]:
    return db.setdefault(_COMPARISONS_TABLE, {})


def _comparison_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "title": row.get("title"),
        "role_text": row.get("role_text"),
        "candidate_user_ids": [str(u) for u in (row.get("candidate_user_ids") or [])],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _get_comparison_row(
    db: Any, recruiter_user_id: str, comparison_id: str
) -> dict[str, Any]:
    if isinstance(db, dict):
        row = _comparison_rows(db).get(str(comparison_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            raise ComparisonNotFound(comparison_id)
        return row
    result = _read_with_transient_retry(
        db,
        lambda client: client.table(_COMPARISONS_TABLE)
        .select("*")
        .eq("id", comparison_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .limit(1)
        .execute(),
    )
    rows = getattr(result, "data", []) or []
    if not rows:
        raise ComparisonNotFound(comparison_id)
    return rows[0]


def create_comparison(
    db: Any,
    recruiter_user_id: str,
    *,
    candidate_user_ids: list[str],
    plan: dict[str, Any],
    title: Any = None,
    role_text: Any = None,
) -> dict[str, Any]:
    now = _now_iso()
    row = {
        "id": str(uuid4()),
        "recruiter_user_id": str(recruiter_user_id),
        "title": str(title or "").strip()[:MAX_TITLE_LENGTH] or None,
        "role_text": str(role_text or "").strip()[:MAX_QUERY_LENGTH] or None,
        "plan": _sanitize_plan(plan),
        "candidate_user_ids": [str(u) for u in candidate_user_ids],
        "created_at": now,
        "updated_at": now,
    }
    if isinstance(db, dict):
        _comparison_rows(db)[row["id"]] = row
    else:
        db.table(_COMPARISONS_TABLE).insert(make_json_safe(row)).execute()
    return row


def list_comparisons(db: Any, recruiter_user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            r
            for r in _comparison_rows(db).values()
            if str(r.get("recruiter_user_id")) == str(recruiter_user_id)
        ]
    else:
        result = _read_with_transient_retry(
            db,
            lambda client: client.table(_COMPARISONS_TABLE)
            .select("id, title, role_text, candidate_user_ids, created_at, updated_at")
            .eq("recruiter_user_id", recruiter_user_id)
            .order("updated_at", desc=True)
            .limit(MAX_LIST_COMPARISONS)
            .execute(),
        )
        rows = list(getattr(result, "data", []) or [])
    rows = sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return [_comparison_view(r) for r in rows[:MAX_LIST_COMPARISONS]]


def update_comparison(
    db: Any,
    recruiter_user_id: str,
    comparison_id: str,
    *,
    candidate_user_ids: list[str] | None = None,
    plan: dict[str, Any] | None = None,
    title: Any = ...,
    role_text: Any = ...,
) -> dict[str, Any]:
    row = _get_comparison_row(db, recruiter_user_id, comparison_id)
    updates: dict[str, Any] = {"updated_at": _now_iso()}
    if candidate_user_ids is not None:
        updates["candidate_user_ids"] = [str(u) for u in candidate_user_ids]
    if plan is not None:
        updates["plan"] = _sanitize_plan(plan)
    if title is not ...:
        updates["title"] = str(title or "").strip()[:MAX_TITLE_LENGTH] or None
    if role_text is not ...:
        updates["role_text"] = str(role_text or "").strip()[:MAX_QUERY_LENGTH] or None

    if isinstance(db, dict):
        row.update(updates)
        return row
    db.table(_COMPARISONS_TABLE).update(make_json_safe(updates)).eq(
        "id", comparison_id
    ).eq("recruiter_user_id", recruiter_user_id).execute()
    return {**row, **updates}


def delete_comparison(db: Any, recruiter_user_id: str, comparison_id: str) -> bool:
    if isinstance(db, dict):
        table = _comparison_rows(db)
        row = table.get(str(comparison_id))
        if row is None or str(row.get("recruiter_user_id")) != str(recruiter_user_id):
            return False
        del table[str(comparison_id)]
        return True
    result = (
        db.table(_COMPARISONS_TABLE)
        .delete()
        .eq("id", comparison_id)
        .eq("recruiter_user_id", recruiter_user_id)
        .execute()
    )
    return bool(getattr(result, "data", []) or [])


def get_comparison(
    db: Any, recruiter_user_id: str, comparison_id: str
) -> dict[str, Any]:
    """Load a session and re-evaluate its matrix live (fail closed)."""
    row = _get_comparison_row(db, recruiter_user_id, comparison_id)
    matrix = evaluate_matrix(
        db,
        recruiter_user_id=recruiter_user_id,
        candidate_user_ids=[str(u) for u in (row.get("candidate_user_ids") or [])],
        plan=row.get("plan") or {},
    )
    # The sanitized plan is engine-internal; the API contract exposes the
    # editable requirements_view instead.
    matrix.pop("plan", None)
    return {"comparison": _comparison_view(row), "matrix": matrix}


__all__ = [
    "CELL_CLAIMED",
    "CELL_NONE",
    "CELL_PROVEN",
    "CELL_UNAVAILABLE",
    "ComparisonError",
    "ComparisonNotFound",
    "MAX_COMPARE_CANDIDATES",
    "MIN_COMPARE_CANDIDATES",
    "create_comparison",
    "delete_comparison",
    "evaluate_matrix",
    "get_comparison",
    "list_comparisons",
    "normalize_requirement_term",
    "plan_from_requirements",
    "plan_from_role_text",
    "requirements_view",
    "resolve_candidate_user_ids",
    "update_comparison",
]
