"""Recruiter candidate comparison — the deterministic evidence-matrix engine.

Evidence-based comparison: given a requirement plan (canonical shape owned by
``recruiter_requirement_plan``) and 2–5 candidates, produce a requirement ×
candidate matrix where every cell is a deterministic evidence state derived
from the SAME machinery as recruiter search:

  * the candidate axis is the recruiter_search_index row — itself derived
    exclusively from the public passport projection (privacy by construction);
  * requirement satisfaction reuses ``_candidate_evidence_map`` /
    ``_verify_concept`` and the taxonomy ``satisfies()`` contract — a child
    skill proves a parent requirement, NEVER the reverse, and "related"
    concepts prove nothing;
  * every load re-runs the live fail-closed triple (discovery exclusions,
    ``is_published``, ``disclosure_version``) — nothing here stores an
    evidence snapshot, so unpublished evidence can never be served stale.

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

V3: comparison is a LIVE VIEW scoped to a Hiring Brief — the brief owns the
plan and the candidate pool; this module owns only evaluation. There is no
persisted comparison session and therefore nothing that can go stale when
the brief's requirements or a candidate's published evidence change.

Storage is dual-mode like every service in this codebase: ``db`` is either
the service-role Supabase client or a plain ``dict`` (hermetic tests).
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.recruiter_query_understanding import (
    EVIDENCE_REQUIREMENT_DISPLAY,
    describe_group,
)
from app.services.recruiter_requirement_plan import (
    MAX_REQUIREMENT_ROWS,
    requirements_view,
    sanitize_plan,
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
    ancestors,
    concept_display,
    related,
)
from app.services.skill_normalization import skill_slug

logger = logging.getLogger(__name__)

_INDEX_TABLE = "recruiter_search_index"
_CONNECTIONS_TABLE = "recruiter_candidate_connections"
_PASSPORTS_TABLE = "vbr_work_passports"

MIN_COMPARE_CANDIDATES = 2
MAX_COMPARE_CANDIDATES = 5
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
    candidate_user_ids: list[str] | None = None,
    allowed_user_ids: set[str] | None = None,
) -> list[str]:
    """Resolve the recruiter's selection to stable student user ids.

    ``connection_ids`` must be the caller's OWN connections (foreign ids are
    indistinguishable from missing — same error). ``candidate_slugs`` must be
    actively published passports. ``candidate_user_ids`` are accepted only
    when ``allowed_user_ids`` whitelists them (the brief's own pool) — a raw
    user id from a client is never trusted on its own. One human → one
    column: duplicates collapse by user id, preserving selection order.
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

    if candidate_user_ids:
        allowed = {str(u) for u in (allowed_user_ids or set())}
        for raw in candidate_user_ids:
            uid = str(raw or "").strip()
            if not uid or uid not in allowed:
                raise ComparisonError(
                    "candidate_not_found",
                    "One of the selected candidates is not in this role.",
                )
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


def live_valid_index_rows(
    db: Any, user_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Index rows for ``user_ids`` that pass the live fail-closed triple
    (discovery exclusions, publication, disclosure version) RIGHT NOW."""
    rows = _index_rows_by_user_ids(db, [str(u) for u in user_ids])
    ids = list(rows.keys())
    if not ids:
        return {}
    excluded = _excluded_user_ids(db, ids)
    published = _live_publication_map(db, ids)
    live_versions = _live_disclosure_versions(db, ids)
    valid: dict[str, dict[str, Any]] = {}
    for uid, row in rows.items():
        if uid in excluded:
            continue
        if not published.get(uid, False):
            continue
        if live_versions.get(uid, 1) > int(row.get("disclosure_version") or 1):
            continue
        valid[uid] = row
    return valid


def evaluate_candidate_summary(
    row: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Lightweight per-candidate evaluation for the role's candidate list:
    transparent counts + missing displays, no full matrix cells. The plan
    MUST already be sanitized."""
    axis = _requirement_axis(plan)
    column = _candidate_column(row, axis, plan)
    return {
        "available": True,
        "counts": column["counts"],
        "missing_required": column["missing_required"],
        "missing_preferred": column["missing_preferred"],
        "excluded_hits": column["excluded_hits"],
    }


def evaluate_candidate_checklist(
    db: Any,
    recruiter_user_id: str,
    candidate_user_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """The deterministic single-candidate verification checklist: the
    requirement axis plus this candidate's live evidence cells.

    This is the interview workspace's backbone — the SAME axis / cell /
    summary machinery as the comparison matrix, re-run against the live
    fail-closed triple on every call. When the candidate is no longer
    publicly comparable (unpublished / excluded / stale disclosure) the
    checklist fails closed: no cells, ``available=False``, and identity
    for the summary comes from the recruiter's OWN connection projection —
    never a stale index row.
    """
    plan = sanitize_plan(plan)
    axis = _requirement_axis(plan)
    uid = str(candidate_user_id)

    row = live_valid_index_rows(db, [uid]).get(uid)
    if row is None:
        identity = None
        try:
            from app.services.recruiter_connection_service import (
                _candidate_summary,
            )

            identity = _candidate_summary(db, uid)
        except Exception:
            identity = None
        column = _unavailable_column(uid, identity)
        return {
            "requirements": axis,
            "cells": {},
            "counts": column["counts"],
            "available": False,
            "unavailable_note": column["unavailable_note"],
            "summary": _column_summary(column),
        }

    column = _candidate_column(row, axis, plan)
    return {
        "requirements": axis,
        "cells": column["cells"],
        "counts": column["counts"],
        "available": True,
        "unavailable_note": None,
        "summary": _column_summary(column),
    }


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
    plan = sanitize_plan(plan)
    ordered = [str(u) for u in candidate_user_ids][:MAX_COMPARE_CANDIDATES]
    axis = _requirement_axis(plan)

    valid = live_valid_index_rows(db, ordered)

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

    # Attach the recruiter's own connection id so the matrix can save /
    # deep-link in place. Never another recruiter's data by construction.
    # Role-scoped review status is annotated by the hiring-brief service —
    # workspace membership itself carries no status.
    for column in columns:
        conn = connection_by_student.get(column["user_id"])
        column["connection"] = (
            {"id": str(conn.get("id"))} if conn is not None else None
        )
        column["brief_status"] = None

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
    }


__all__ = [
    "CELL_CLAIMED",
    "CELL_NONE",
    "CELL_PROVEN",
    "CELL_UNAVAILABLE",
    "ComparisonError",
    "MAX_COMPARE_CANDIDATES",
    "MIN_COMPARE_CANDIDATES",
    "evaluate_candidate_checklist",
    "evaluate_candidate_summary",
    "evaluate_matrix",
    "live_valid_index_rows",
    "resolve_candidate_user_ids",
]
