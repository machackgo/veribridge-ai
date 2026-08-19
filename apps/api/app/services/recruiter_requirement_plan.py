"""Canonical recruiter requirement plan — the ONE structured representation.

The "plan" dict produced by ``recruiter_query_understanding.parse_recruiter_query``
is the single canonical representation of recruiter intent across the whole
recruiter product: search executes it, evidence discovery filters by it, the
comparison matrix evaluates against it, and a Hiring Brief persists it
(``recruiter_hiring_briefs.plan`` jsonb). This module owns every conversion
in and out of that shape so search, comparison and briefs can never diverge:

    natural language  ──parse_recruiter_query──▶  plan
    edited chips      ──plan_from_requirements──▶  plan
    plan              ──requirements_view──▶       editable chips payload
    stored jsonb      ──sanitize_plan──▶           plan (re-validated)

SECURITY: a stored or client-supplied plan is UNTRUSTED input (it may come
from a jsonb round-trip, an older schema, or a hostile client). Everything
entering the engine passes through ``sanitize_plan``, which forces every
value back onto the closed vocabularies (taxonomy slugs, evidence keys,
bounded lists). Free text can never smuggle instructions into evaluation.
"""

from __future__ import annotations

from typing import Any

from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    MAX_BRIEF_LENGTH,
    describe_group,
    parse_recruiter_query,
)

# Closed evidence-phrase vocabulary reused so a manually typed requirement
# like "live deployment" lands on the same evidence key the NL parser uses.
from app.services.recruiter_query_understanding import (  # noqa: F401
    _EVIDENCE_PHRASES as _EVIDENCE_PHRASE_TO_KEY,
)
from app.services.recruiter_search_taxonomy import (
    PHRASE_TO_CONCEPT,
    concept_display,
)
from app.services.skill_normalization import skill_slug

# Version stamp persisted inside every stored plan so future grammar or
# taxonomy migrations can detect and upgrade older briefs instead of
# silently re-interpreting them.
PLAN_SCHEMA_VERSION = 1

MAX_REQUIREMENT_ROWS = 16
_MAX_GROUP_MEMBERS = 6
_MAX_RESIDUAL_TERMS = 12


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
            for term in list(entry)[:_MAX_GROUP_MEMBERS]:
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
        "schema_version": PLAN_SCHEMA_VERSION,
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
        "remote": bool(requirements.get("remote")),
        "residual_terms": [],
    }


def plan_from_role_text(role_text: Any) -> dict[str, Any]:
    """Parse a natural-language role brief with the SAME deterministic
    grammar as recruiter search (longer length cap). A brief always
    describes candidates, so the parsed intent is irrelevant here — even
    "show me who has ML proof" becomes requirements."""
    plan = parse_recruiter_query(
        str(role_text or "")[:MAX_BRIEF_LENGTH], MAX_BRIEF_LENGTH
    )
    plan["intent"] = "candidate_search"
    plan["schema_version"] = PLAN_SCHEMA_VERSION
    return plan


def sanitize_plan(plan: Any) -> dict[str, Any]:
    """Re-normalize an UNTRUSTED plan (jsonb round-trip, older schema, or a
    hostile client) so the engine only ever sees closed-vocabulary slugs and
    keys, bounded lists, and a forced candidate_search intent."""
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
            groups.append(slugs[:_MAX_GROUP_MEMBERS])
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "raw": str(plan.get("raw") or "")[:MAX_BRIEF_LENGTH],
        "mode": "structured"
        if groups or plan.get("evidence")
        else str(plan.get("mode") or "structured"),
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
            k
            for k in list(plan.get("evidence") or [])
            if k in EVIDENCE_REQUIREMENT_DISPLAY
        ],
        "preferred_evidence": [
            k
            for k in list(plan.get("preferred_evidence") or [])
            if k in EVIDENCE_REQUIREMENT_DISPLAY
        ],
        "role": plan.get("role") if isinstance(plan.get("role"), dict) else None,
        "seniority": plan.get("seniority")
        if isinstance(plan.get("seniority"), dict)
        else None,
        "location": _normalize_phrase(plan.get("location"))[:60] or None,
        "remote": bool(plan.get("remote")),
        "residual_terms": [
            str(t) for t in list(plan.get("residual_terms") or [])[:_MAX_RESIDUAL_TERMS]
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
        "remote": bool(plan.get("remote")),
        # Terms the parser could not turn into a requirement — surfaced so
        # the recruiter can see what was NOT understood, never silently used.
        "unrecognized_terms": list(plan.get("residual_terms") or []),
    }


def required_concept_set(plan: dict[str, Any]) -> set[str]:
    """Flat set of required concept slugs — used for duplicate-brief
    similarity, never for evaluation."""
    out: set[str] = set()
    for group in plan.get("required_groups") or []:
        for slug in group:
            out.add(str(slug))
    return out


def merge_refinement(plan: dict[str, Any], refine_text: Any) -> dict[str, Any]:
    """Overlay a TEMPORARY search refinement ("only candidates in
    Massachusetts") on a copy of the brief's plan. The stored brief is
    never modified — the caller renders the merged interpretation so the
    distinction between brief requirement and temporary filter stays
    visible."""
    refined = sanitize_plan(plan)
    extra = parse_recruiter_query(str(refine_text or "")[:MAX_BRIEF_LENGTH])
    for group in extra.get("required_groups") or []:
        if group not in refined["required_groups"]:
            refined["required_groups"].append(list(group))
    for slug in extra.get("preferred") or []:
        if slug not in refined["preferred"]:
            refined["preferred"].append(slug)
    for slug in extra.get("excluded") or []:
        if slug not in refined["excluded"]:
            refined["excluded"].append(slug)
    for key in extra.get("evidence") or []:
        if key not in refined["evidence"]:
            refined["evidence"].append(key)
    for key in extra.get("preferred_evidence") or []:
        if key not in refined["preferred_evidence"]:
            refined["preferred_evidence"].append(key)
    if extra.get("location"):
        refined["location"] = extra["location"]
    if extra.get("remote"):
        refined["remote"] = True
    if extra.get("seniority") and not refined.get("seniority"):
        refined["seniority"] = extra["seniority"]
    refined["residual_terms"] = list(
        dict.fromkeys(
            [*refined.get("residual_terms", []), *(extra.get("residual_terms") or [])]
        )
    )[:_MAX_RESIDUAL_TERMS]
    return sanitize_plan(refined)


__all__ = [
    "MAX_REQUIREMENT_ROWS",
    "PLAN_SCHEMA_VERSION",
    "merge_refinement",
    "normalize_requirement_term",
    "plan_from_requirements",
    "plan_from_role_text",
    "required_concept_set",
    "requirements_view",
    "sanitize_plan",
]
