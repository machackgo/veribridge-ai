"""Recruiter Evidence Discovery (V1.6) — search the PROOF, not just the people.

Candidate search answers "who matches?"; this module answers the follow-up
that makes VeriBridge different: "show me WHY — open the actual proof."

    "show me proof of machine learning"
    "which project proves FastAPI"
    "show me Mohammed's Python proof"
    "show me GitHub proof of data engineering"

EVIDENCE MODEL — nothing new is invented here:
  Every evidence unit served by this module already exists on the candidate's
  PUBLIC Work Passport (``/p/{slug}``): per-skill project proof refs, closed
  proof-type labels (GitHub Proof / Website Proof / Document Proof / Project
  Defense / Video Evidence), qualitative statuses, published report paths,
  and the already-sanitized public trace previews. The recruiter search index
  row is derived exclusively from ``build_public_passport`` output, and this
  module reads ONLY that row (plus the same live re-validation candidate
  search performs). Search can therefore never surface proof a recruiter
  could not already open on the public passport — privacy by construction.

ANTI-HALLUCINATION CONTRACT (shared with candidate search):
  * a requirement is satisfied ONLY via ``taxonomy.satisfies`` — exact slug
    or child-proves-parent, never the reverse, never "related";
  * "related" evidence (NLP asked, only ML published) is returned ONLY in a
    separate, explicitly-labeled related section — never as proof;
  * a claimed project technology is returned as tier="claimed" with an
    explicit not-independently-verified note — never presented as verified;
  * zero published evidence yields an explicit unmatched entry, never a
    silent substitution.

Deterministic and dual-mode (dict / Supabase) like every search service.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    describe_group,
    parse_recruiter_query,
)
from app.services.recruiter_search_service import (
    EVIDENCE_FILTERS,
    _excluded_user_ids,
    _fetch_candidate_pool,
    _live_disclosure_versions,
    _live_publication_map,
    _retrieval_terms,
)
from app.services.recruiter_search_taxonomy import (
    concept_display,
    related,
    satisfies,
)
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

# Evidence-type filter key → the closed public proof-type labels it selects.
_TYPE_TO_LABELS: dict[str, tuple[str, ...]] = {
    "github": ("GitHub Proof",),
    "live_site": ("Website Proof",),
    "documents": ("Document Proof",),
    "project_defense": ("Project Defense",),
    "video": ("Video Evidence",),
}

_STATUS_ORDER = {
    "Demonstrated": 0,
    "Partially demonstrated": 1,
    "Evidence observed": 2,
    "Supporting evidence": 3,
    "Needs review": 4,
    "Not assessed": 5,
}

_MAX_GROUPS = 12
_MAX_ITEMS_PER_CANDIDATE = 8
_MAX_ITEM_PROJECTS = 4
_MAX_ITEM_TRACES = 3
_MIN_NAME_TERM_LEN = 3


def _type_labels(evidence_types: list[str]) -> set[str]:
    labels: set[str] = set()
    for key in evidence_types:
        labels.update(_TYPE_TO_LABELS.get(key, ()))
    return labels


def _status_rank(status: Any) -> int:
    return _STATUS_ORDER.get(str(status or ""), 9)


def _passport_path(slug: str) -> str:
    return f"/p/{slug}"


def _skill_proof_path(slug: str, skill_slug_value: str) -> str:
    """The public per-skill evidence drilldown — the real artifact surface."""
    return f"/p/{slug}/skills/{skill_slug_value}"


def _filter_projects_by_labels(
    projects: list[dict[str, Any]], labels: set[str]
) -> list[dict[str, Any]]:
    if not labels:
        return list(projects)
    return [
        p
        for p in projects
        if labels & {str(t) for t in (p.get("proof_types") or [])}
    ]


def _filter_traces_by_labels(
    traces: list[dict[str, Any]], labels: set[str]
) -> list[dict[str, Any]]:
    if not labels:
        return list(traces)
    return [t for t in traces if str(t.get("source_type") or "") in labels]


def _skill_item(
    row: dict[str, Any],
    entry: dict[str, Any],
    labels: set[str],
    *,
    requirement: str | None,
    requirement_display: str | None,
    related_to: str | None = None,
) -> dict[str, Any] | None:
    """One proof item for a passport skill entry, or None when the active
    evidence-type filter leaves no supporting proof of that type."""
    sources = [str(s) for s in (entry.get("evidence_sources") or [])]
    projects = _filter_projects_by_labels(
        list(entry.get("projects") or []), labels
    )[:_MAX_ITEM_PROJECTS]
    traces = _filter_traces_by_labels(
        list(entry.get("traces") or []), labels
    )[:_MAX_ITEM_TRACES]
    if labels:
        # Type-filtered: the skill counts only if the requested proof type
        # actually supports it (per-project proof types, falling back to the
        # skill-level source union for rows projected before enrichment).
        if not projects and not (labels & set(sources)):
            return None
        sources = [s for s in sources if s in labels]
    slug_value = str(entry.get("skill_slug") or skill_slug(str(entry.get("skill") or "")))
    direct = bool(requirement) and slug_value == requirement
    note = None
    if requirement and not direct:
        note = f"{entry.get('skill')} evidence satisfies {requirement_display}"
    return {
        "tier": "skill",
        "requirement": requirement,
        "requirement_display": requirement_display,
        "related_to": related_to,
        "skill": str(entry.get("skill") or ""),
        "skill_slug": slug_value,
        "status": str(entry.get("status") or "Not assessed"),
        "direct": direct,
        "note": note,
        "evidence_sources": sources,
        "proof_path": _skill_proof_path(str(row.get("public_slug") or ""), slug_value),
        "projects": projects,
        "traces": traces,
    }


def _claimed_item(
    row: dict[str, Any],
    tech_label: str,
    project: dict[str, Any],
    labels: set[str],
    *,
    requirement: str,
    requirement_display: str,
) -> dict[str, Any] | None:
    """A claimed-technology fallback item — explicitly NOT verified proof."""
    project_sources = [str(s) for s in (project.get("evidence_sources") or [])]
    if labels and not (labels & set(project_sources)):
        return None
    title = str(project.get("title") or "")
    return {
        "tier": "claimed",
        "requirement": requirement,
        "requirement_display": requirement_display,
        "related_to": None,
        "skill": tech_label,
        "skill_slug": skill_slug(tech_label),
        "status": "Claimed",
        "direct": skill_slug(tech_label) == requirement,
        "note": (
            f"Listed as a technology on “{title}” — a project claim, not "
            "independently verified skill evidence"
        ),
        "evidence_sources": project_sources,
        # A claim has no per-skill evidence drilldown; the published project
        # report is its context.
        "proof_path": None,
        "projects": [
            {
                "title": title,
                "public_report_path": str(project.get("public_report_path") or ""),
                "skill_status": "Claimed",
                "proof_types": project_sources[:6],
            }
        ],
        "traces": [],
    }


def _items_for_group(
    row: dict[str, Any], group: list[str], labels: set[str]
) -> list[dict[str, Any]]:
    """Every proof item on this candidate satisfying one requirement group."""
    display = describe_group(group)
    items: list[dict[str, Any]] = []
    matched_slugs: set[str] = set()
    for entry in row.get("skills") or []:
        slug_value = str(entry.get("skill_slug") or "") or skill_slug(
            str(entry.get("skill") or "")
        )
        if not any(satisfies(slug_value, req) for req in group):
            continue
        item = _skill_item(
            row, entry, labels, requirement=group[0], requirement_display=display
        )
        if item is not None:
            matched_slugs.add(slug_value)
            items.append(item)
    if not items:
        # Claim-tier fallback ONLY when no verified skill evidence exists —
        # clearly labeled, never mixed in above real evidence.
        for project in row.get("projects") or []:
            for tech in project.get("technologies") or []:
                tech_slug = skill_slug(str(tech or ""))
                if not tech_slug or tech_slug in matched_slugs:
                    continue
                if not any(satisfies(tech_slug, req) for req in group):
                    continue
                item = _claimed_item(
                    row,
                    str(tech),
                    project,
                    labels,
                    requirement=group[0],
                    requirement_display=display,
                )
                if item is not None:
                    matched_slugs.add(tech_slug)
                    items.append(item)
    items.sort(key=lambda i: (0 if i["tier"] == "skill" else 1, 0 if i["direct"] else 1, _status_rank(i["status"]), i["skill"]))
    return items


def _all_evidence_items(row: dict[str, Any], labels: set[str]) -> list[dict[str, Any]]:
    """Every evidence-backed skill on this candidate (no concept asked) —
    the "show me Mohammed's proof" / "show me live deployment proof" path."""
    items: list[dict[str, Any]] = []
    for entry in row.get("skills") or []:
        item = _skill_item(row, entry, labels, requirement=None, requirement_display=None)
        if item is not None:
            items.append(item)
    items.sort(key=lambda i: (_status_rank(i["status"]), i["skill"]))
    return items


def _resolve_candidate_scope(
    rows: list[dict[str, Any]],
    residual_terms: list[str],
    candidate_slug: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str]]:
    """Restrict the pool to an explicitly referenced candidate.

    Explicit ``candidate_slug`` wins (the View-proof drilldown path). Free
    text uses residual terms that match a published display name — stable
    identity comes from the passport slug, and when a name term matches more
    than one candidate we show EACH of them clearly grouped, never guessing.
    Residual terms that match no name are returned for retrieval use.
    """
    if candidate_slug:
        scoped = [r for r in rows if str(r.get("public_slug")) == candidate_slug]
        info = {
            "terms": [],
            "matched_candidates": [
                str(r.get("display_name") or "") for r in scoped
            ],
            "ambiguous": False,
        }
        return scoped, info, []

    name_terms: list[str] = []
    non_name_terms: list[str] = []
    scoped = rows
    for term in residual_terms:
        t = str(term or "").strip().lower()
        if len(t) < _MIN_NAME_TERM_LEN:
            non_name_terms.append(t)
            continue
        hits = [
            r
            for r in scoped
            if t in str(r.get("display_name") or "").lower()
        ]
        if hits:
            name_terms.append(t)
            scoped = hits
        else:
            non_name_terms.append(t)
    if not name_terms:
        return rows, None, non_name_terms
    names = sorted({str(r.get("display_name") or "") for r in scoped})
    info = {
        "terms": name_terms,
        "matched_candidates": names,
        "ambiguous": len(names) > 1,
    }
    return scoped, info, non_name_terms


def build_evidence_results(
    db: Any,
    *,
    plan: dict[str, Any],
    candidate_slug: str | None = None,
    extra_evidence_types: list[str] | None = None,
) -> dict[str, Any]:
    """Run one evidence-discovery search over the validated public index."""
    groups: list[list[str]] = [list(g) for g in (plan.get("required_groups") or [])]
    for slug in plan.get("preferred") or []:
        if not any(slug in g for g in groups):
            groups.append([slug])
    evidence_types: list[str] = []
    for key in list(plan.get("evidence") or []) + list(
        plan.get("preferred_evidence") or []
    ) + list(extra_evidence_types or []):
        if key in EVIDENCE_FILTERS and key not in evidence_types:
            evidence_types.append(key)
    labels = _type_labels(evidence_types)

    # ── Retrieval pool + the SAME live privacy re-validation as candidate
    # search (fail closed on unpublish / disclosure change / exclusions). ──
    pool_terms = _retrieval_terms(plan)
    if candidate_slug:
        pool_terms = []  # explicit candidate: fetch broadly, filter by slug
    pool = _fetch_candidate_pool(db, pool_terms)
    user_ids = [str(r.get("user_id")) for r in pool]
    published = _live_publication_map(db, user_ids)
    live_versions = _live_disclosure_versions(db, user_ids)
    discovery_excluded = _excluded_user_ids(db, user_ids)
    validated = [
        row
        for row in pool
        if str(row.get("user_id")) not in discovery_excluded
        and published.get(str(row.get("user_id")))
        and live_versions.get(str(row.get("user_id")), 1)
        <= int(row.get("disclosure_version") or 1)
    ]

    scoped, candidate_filter, _ = _resolve_candidate_scope(
        validated, list(plan.get("residual_terms") or []), candidate_slug
    )

    notes: list[str] = []
    type_displays = [
        EVIDENCE_REQUIREMENT_DISPLAY.get(k, k) for k in evidence_types
    ]

    # A completely unscoped evidence request ("show me private evidence",
    # "show all proof") has nothing verifiable to retrieve — be explicit
    # instead of dumping everything or guessing.
    unscoped = not groups and not evidence_types and candidate_filter is None
    if unscoped:
        return {
            "total_items": 0,
            "groups": [],
            "unmatched": [],
            "related": [],
            "evidence_types": [
                {"key": k, "display": d}
                for k, d in zip(evidence_types, type_displays)
            ],
            "candidate_filter": candidate_filter,
            "notes": [
                "Name a skill, technology, project, evidence type, or "
                "candidate to see its published proof. Only evidence each "
                "candidate has chosen to publish on their public Work "
                "Passport is searchable."
            ],
        }

    # ── Build per-candidate proof groups ─────────────────────────────────────
    candidate_groups: list[dict[str, Any]] = []
    satisfied_requirements: set[str] = set()
    for row in scoped:
        items: list[dict[str, Any]] = []
        if groups:
            for group in groups:
                group_items = _items_for_group(row, group, labels)
                if group_items:
                    satisfied_requirements.add(describe_group(group))
                items.extend(group_items)
        else:
            items.extend(_all_evidence_items(row, labels))
        if not items:
            continue
        items = items[:_MAX_ITEMS_PER_CANDIDATE]
        candidate_groups.append(
            {
                "public_slug": str(row.get("public_slug") or ""),
                "display_name": row.get("display_name"),
                "headline": row.get("headline"),
                "passport_path": _passport_path(str(row.get("public_slug") or "")),
                "items": items,
            }
        )

    # Deterministic order: strongest proof first (best item status, verified
    # tier before claims, direct before via), then name, then slug.
    def _group_key(g: dict[str, Any]) -> tuple[Any, ...]:
        best = min(
            (
                (
                    0 if i["tier"] == "skill" else 1,
                    0 if i.get("direct") else 1,
                    _status_rank(i["status"]),
                )
                for i in g["items"]
            ),
            default=(9, 9, 9),
        )
        return (*best, str(g.get("display_name") or ""), g["public_slug"])

    candidate_groups.sort(key=_group_key)
    candidate_groups = candidate_groups[:_MAX_GROUPS]

    # ── Unmatched requirements + explicitly-labeled RELATED evidence ─────────
    unmatched: list[dict[str, Any]] = []
    related_hints: list[dict[str, Any]] = []
    for group in groups:
        display = describe_group(group)
        if display in satisfied_requirements:
            continue
        if labels:
            note = (
                f"No published {' / '.join(type_displays).lower()} for "
                f"{display} — no other evidence type was substituted."
            )
        else:
            note = f"No published {display} evidence exists yet."
        unmatched.append(
            {"requirement": group[0], "display": display, "note": note}
        )
        # Related evidence is a labeled HINT, never proof of the requirement.
        related_names: list[str] = []
        related_displays: list[str] = []
        for rel in related(group[0]):
            if any(satisfies(rel, req) for req in group):
                continue  # would have satisfied it — already covered above
            for row in scoped:
                for entry in row.get("skills") or []:
                    slug_value = str(entry.get("skill_slug") or "") or skill_slug(
                        str(entry.get("skill") or "")
                    )
                    if not satisfies(slug_value, rel):
                        continue
                    name = str(row.get("display_name") or "")
                    if name and name not in related_names:
                        related_names.append(name)
                    rel_display = concept_display(rel)
                    if rel_display not in related_displays:
                        related_displays.append(rel_display)
        if related_names and related_displays:
            related_hints.append(
                {
                    "requirement_display": display,
                    "related_display": " / ".join(related_displays[:3]),
                    "candidate_names": related_names[:5],
                    "note": (
                        f"Related {' / '.join(related_displays[:3])} evidence "
                        f"is published — it is NOT {display} proof."
                    ),
                }
            )

    if candidate_filter and candidate_filter.get("ambiguous"):
        notes.append(
            "Several published candidates match that name — each is shown "
            "separately with their own proof."
        )
    if candidate_filter is not None and not candidate_filter.get("matched_candidates"):
        notes.append("No published candidate matches that name.")

    return {
        "total_items": sum(len(g["items"]) for g in candidate_groups),
        "groups": candidate_groups,
        "unmatched": unmatched,
        "related": related_hints,
        "evidence_types": [
            {"key": k, "display": d} for k, d in zip(evidence_types, type_displays)
        ],
        "candidate_filter": candidate_filter,
        "notes": notes,
    }


def search_evidence(
    db: Any,
    *,
    skill: str | None = None,
    candidate_slug: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Structured evidence lookup — the View-proof drilldown path.

    No natural-language parsing: ``skill`` (name or slug) and/or
    ``candidate_slug`` arrive as explicit, stable identifiers from a result
    the recruiter is already looking at.
    """
    plan = parse_recruiter_query("")
    plan["required_groups"] = []
    plan["residual_terms"] = []
    requested = str(skill or "").strip()
    if requested:
        plan["required_groups"] = [[skill_slug(requested)]]
    return build_evidence_results(
        db,
        plan=plan,
        candidate_slug=str(candidate_slug or "").strip() or None,
        extra_evidence_types=[e for e in (evidence or []) if e in EVIDENCE_FILTERS],
    )


__all__ = ["build_evidence_results", "search_evidence"]
