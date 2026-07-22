"""Evidence-derived Skill Gaps — deterministic computation over stored evidence.

This service NEVER calls an AI provider and NEVER fabricates market data,
jobs, salaries, readiness percentages, or gaps that the stored evidence does
not support. It reads the same canonical tables the Passport / Project Report
already derive from and maps their exact states onto four honest statuses.

Data sources (all owner + project scoped):
  * Claimed axis      — ``vbr_projects.metadata`` via ``effective_claimed_skills``
                        (explicit ``claimed_skills`` list, else derived from
                        attached-proof summaries). ``vbr_project_skill_claims``
                        rows are a SUPERSET (auto-minted from document/GitHub
                        detections), so "claimed" anchors on
                        ``effective_claimed_skills`` while claim rows drive the
                        demonstrated axis.
  * Demonstrated axis — ``vbr_project_skill_claims`` (evidence_status ladder
                        not_assessed → insufficient_evidence →
                        partially_demonstrated → demonstrated; upgrade-only,
                        written solely by the canonical finalization boundary)
                        plus ``vbr_claim_evidence_links``
                        (link_status counted|pending|excluded,
                        evidence_quality primary|supporting|context|insufficient).
  * Runtime attempts  — completed website sessions attached to the project
                        (``canonical_website_session_ids``) and their stored
                        ``workflow_analysis_results``
                        supported/weakly_supported/unsupported skills.

RULE TABLE (deterministic, first match wins per skill):

  | # | Stored data state                                            | Status                  |
  |---|--------------------------------------------------------------|-------------------------|
  | 1 | claim evidence_status == demonstrated, or a counted+primary  | demonstrated            |
  |   | link exists                                                  | (NOT a gap — listed in  |
  |   |                                                              | demonstrated_skills)    |
  | 2 | claim evidence_status == partially_demonstrated, or any      | partially_demonstrated  |
  |   | counted link (best quality supporting)                       |                         |
  | 3 | claim has ≥1 link but none counted (all pending/excluded),   | insufficient_evidence   |
  |   | or claim evidence_status == insufficient_evidence            |                         |
  | 4 | no countable claim evidence, but a completed website         | insufficient_evidence   |
  |   | analysis lists the skill as supported / weakly supported     |                         |
  |   | (runtime signal exists, nothing counted)                     |                         |
  | 5 | no countable claim evidence, and a completed website         | missing_evidence        |
  |   | analysis lists the skill as unsupported (attempted at        |                         |
  |   | runtime, not demonstrated — a provable negative)             |                         |
  | 6 | claimed skill (or link-less claim row) with no evidence      | not_assessed            |
  |   | links and no website-analysis mention anywhere               |                         |
  | 7 | project has no claimed skills and no claim rows (website-    | project-level           |
  |   | only outcomes can never form items, so nothing is            | insufficient-evidence   |
  |   | assessable)                                                  | fallback — NO items     |

The gap universe for a project is ``effective_claimed_skills`` ∪ claim rows.
A skill mentioned only by a website analysis but neither claimed nor claim-
rowed is NOT a gap (nothing claims it — inventing an item would be a guess).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.schemas.skill_gaps import SKILL_GAP_STATUS_LABELS
from app.services.canonical_project_evidence import (
    canonical_website_session_ids,
    owned_rows,
)
from app.services.vbr_project_defense import effective_claimed_skills

logger = logging.getLogger(__name__)

# Website sessions whose stored analysis outcomes are usable evidence.
_USABLE_SESSION_STATUS = "completed"

_EVIDENCE_STATUS_LADDER = [
    "not_assessed",
    "insufficient_evidence",
    "partially_demonstrated",
    "demonstrated",
]

# Website analysis outcome strength (strongest wins when several analyses
# mention the same skill).
_WEBSITE_OUTCOME_RANK = {"supported": 2, "weakly_supported": 1, "unsupported": 0}

_INSUFFICIENT_PROJECT_NOTE = (
    "Not enough evidence to assess skill gaps for this project. Claim the "
    "skills this project demonstrates and attach proofs (document, GitHub, or "
    "a recorded website workflow) to enable an honest assessment."
)


def _norm(name: Any) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _rows(db: Any, table: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort equality-filtered read (dict-mode + Supabase)."""
    try:
        if isinstance(db, dict):
            out = []
            for row in db.get(table, {}).values():
                if isinstance(row, dict) and all(
                    str(row.get(k) or "") == str(v) for k, v in filters.items()
                ):
                    out.append(row)
            return out
        query = db.table(table).select("*")
        for key, value in filters.items():
            query = query.eq(key, value)
        response = query.execute()
        return [r for r in (getattr(response, "data", []) or []) if isinstance(r, dict)]
    except Exception:  # pragma: no cover - table availability is additive
        return []


# ── Website analysis outcomes ─────────────────────────────────────────────────


def _website_outcomes(
    db: Any, *, user_id: str, project_id: str
) -> dict[str, dict[str, Any]]:
    """Per-skill strongest runtime outcome from completed, project-linked sessions.

    Returns ``{skill_key: {"outcome", "skill_name", "entries": [basis dict]}}``
    where each basis dict carries the analysis id + session id + an honest
    sentence describing exactly what the stored analysis says.
    """
    session_ids = canonical_website_session_ids(
        db, user_id=user_id, project_ids=[project_id]
    )
    if not session_ids:
        return {}
    sessions_by_id = {
        str(row.get("id") or ""): row
        for row in owned_rows(db, "extension_proof_sessions", user_id)
    }
    outcomes: dict[str, dict[str, Any]] = {}
    for sid in session_ids:
        session = sessions_by_id.get(sid)
        if not session or str(session.get("status") or "") != _USABLE_SESSION_STATUS:
            continue  # never derive from an incomplete/orphaned recording
        analyses = sorted(
            _rows(db, "workflow_analysis_results", {"proof_session_id": sid}),
            key=lambda row: str(row.get("created_at") or ""),
        )
        if not analyses:
            continue
        analysis = analyses[-1]  # latest stored analysis for the session
        analysis_id = str(analysis.get("id") or "")
        for field, outcome, sentence in (
            (
                "supported_skills",
                "supported",
                "The completed website workflow analysis lists this skill as supported.",
            ),
            (
                "weakly_supported_skills",
                "weakly_supported",
                "The completed website workflow analysis lists this skill as only weakly supported.",
            ),
            (
                "unsupported_skills",
                "unsupported",
                "The completed website workflow analysis attempted this skill at "
                "runtime and lists it as not demonstrated.",
            ),
        ):
            for skill in analysis.get(field) or []:
                key = _norm(skill)
                if not key:
                    continue
                entry = {
                    "kind": "website_analysis",
                    "reference_id": analysis_id,
                    "proof_type": "website",
                    "proof_id": sid,
                    "citation_type": "website_workflow",
                    "link_status": None,
                    "evidence_quality": None,
                    "detail": sentence,
                    "limitations": [],
                }
                current = outcomes.get(key)
                if current is None:
                    outcomes[key] = {
                        "outcome": outcome,
                        "skill_name": str(skill).strip(),
                        "entries": [entry],
                    }
                else:
                    current["entries"].append(entry)
                    if (
                        _WEBSITE_OUTCOME_RANK[outcome]
                        > _WEBSITE_OUTCOME_RANK[current["outcome"]]
                    ):
                        current["outcome"] = outcome
    return outcomes


# ── Per-link basis + honest framing ───────────────────────────────────────────


def _link_basis_entry(link: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "claim_link",
        "reference_id": str(link.get("id") or ""),
        "proof_type": str(link.get("proof_type") or "") or None,
        "proof_id": str(link.get("proof_id") or "") or None,
        "citation_type": str(link.get("citation_type") or "") or None,
        "link_status": str(link.get("link_status") or "") or None,
        "evidence_quality": str(link.get("evidence_quality") or "") or None,
        "detail": str(link.get("link_reason") or "").strip(),
        "limitations": [str(x) for x in (link.get("limitations") or []) if str(x).strip()],
    }


def _distinct_reasons(links: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for link in links:
        reason = str(link.get("link_reason") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _proof_types(links: list[dict[str, Any]]) -> list[str]:
    types: list[str] = []
    for link in links:
        proof_type = str(link.get("proof_type") or "").strip()
        if proof_type and proof_type not in types:
            types.append(proof_type)
    return types


# ── Per-skill status resolution (the rule table) ──────────────────────────────


def _resolve_skill(
    *,
    skill_name: str,
    skill_key: str,
    claim: dict[str, Any] | None,
    links: list[dict[str, Any]],
    website: dict[str, Any] | None,
    is_claimed: bool,
) -> dict[str, Any] | None:
    """Apply the rule table to ONE skill.

    Returns a gap-item dict, ``{"status": "demonstrated"}`` for rule 1, or the
    item for rules 2–6. All ``why`` text is assembled from actual stored
    link_reason / limitations / analysis outcomes — never from assumptions.
    """
    evidence_status = str((claim or {}).get("evidence_status") or "not_assessed")
    counted = [l for l in links if str(l.get("link_status") or "") == "counted"]
    has_primary = any(
        str(l.get("evidence_quality") or "") == "primary" for l in counted
    )
    website_outcome = (website or {}).get("outcome")
    website_entries = list((website or {}).get("entries") or [])

    # Rule 1 — demonstrated: not a gap.
    if evidence_status == "demonstrated" or has_primary:
        return {"status": "demonstrated"}

    basis: list[dict[str, Any]] = [_link_basis_entry(l) for l in links]
    basis.extend(website_entries)
    claim_id = str((claim or {}).get("id") or "") or None

    # Rule 2 — partially demonstrated (counted evidence, best quality supporting).
    if evidence_status == "partially_demonstrated" or counted:
        why_parts = [
            "Counted evidence supports this skill, but only at supporting "
            "quality — no primary (direct) citation has been counted."
        ]
        why_parts.extend(_distinct_reasons(counted))
        return {
            "status": "partially_demonstrated",
            "why": " ".join(why_parts),
            "evidence_basis": basis,
            "claim_id": claim_id,
            "recommended_action": (
                f"Add a proof with a direct, primary citation for {skill_name}: "
                "upload a document that cites the exact section where it is "
                "implemented, cite the exact code lines in the GitHub proof, or "
                "record a website workflow that directly demonstrates it."
            ),
        }

    # Rule 3 — links exist but none counted (all pending/excluded), or the
    # canonical ladder itself says insufficient_evidence.
    if links or evidence_status == "insufficient_evidence":
        reasons = _distinct_reasons(links)
        why = (
            "Evidence is attached to this skill claim, but none of it counts "
            "toward demonstration."
        )
        if reasons:
            why += " Stored link reasons: " + " ".join(reasons)
        proof_types = _proof_types(links)
        via = f" (current evidence: {', '.join(proof_types)})" if proof_types else ""
        return {
            "status": "insufficient_evidence",
            "why": why,
            "evidence_basis": basis,
            "claim_id": claim_id,
            "recommended_action": (
                f"The existing evidence for {skill_name}{via} was not counted. "
                "Attach evidence with a specific citation — exact code lines, an "
                "exact document section, or a recorded website workflow step — "
                f"that directly demonstrates {skill_name}."
            ),
        }

    # Rule 4 — runtime signal exists but nothing is counted for the project.
    if website_outcome in ("supported", "weakly_supported"):
        strength = (
            "supporting" if website_outcome == "supported" else "weak supporting"
        )
        return {
            "status": "insufficient_evidence",
            "why": (
                f"A completed website workflow analysis recorded {strength} "
                "runtime signals for this skill, but no counted evidence links "
                "it to this project."
            ),
            "evidence_basis": basis,
            "claim_id": claim_id,
            "recommended_action": (
                f"Link the website proof that shows {skill_name} to this project "
                "(finalize the proof), or add a document/GitHub proof with a "
                "direct citation."
            ),
        }

    # Rule 5 — attempted at runtime, not demonstrated: a provable negative.
    if website_outcome == "unsupported":
        return {
            "status": "missing_evidence",
            "why": (
                "A completed website workflow analysis attempted this skill at "
                "runtime and listed it as not demonstrated. No other evidence "
                "is linked to it for this project."
            ),
            "evidence_basis": basis,
            "claim_id": claim_id,
            "recommended_action": (
                f"Record a website workflow that visibly demonstrates "
                f"{skill_name} in action, or attach a document/GitHub proof "
                "with a direct citation for it."
            ),
        }

    # Rule 6 — nothing has assessed this skill at all.
    if is_claimed:
        basis.append(
            {
                "kind": "claimed_skill",
                "reference_id": "",
                "proof_type": None,
                "proof_id": None,
                "citation_type": None,
                "link_status": None,
                "evidence_quality": None,
                "detail": "Claimed in the project's claimed_skills metadata.",
                "limitations": [],
            }
        )
        why = (
            "Claimed for this project, but no attached proof has been assessed "
            "against it — there are no evidence links and no completed website "
            "workflow analysis mentions it."
        )
    else:
        why = (
            "A skill claim exists for this project, but no evidence has been "
            "linked to it and no completed website workflow analysis mentions it."
        )
    return {
        "status": "not_assessed",
        "why": why,
        "evidence_basis": basis,
        "claim_id": claim_id,
        "recommended_action": (
            f"Attach a proof that demonstrates {skill_name}: upload a document "
            "citing it, add a GitHub proof with relevant code, or record a "
            "website workflow showing it in action."
        ),
    }


# ── Project + user reports ────────────────────────────────────────────────────


def build_project_skill_gap_report(
    db: Any, *, user_id: str, project: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic per-project skill-gap report (dict shaped like the DTO)."""
    project_id = str(project.get("id") or "")
    project_title = str(project.get("title") or "Project")
    metadata = project.get("metadata") if isinstance(project.get("metadata"), dict) else {}

    claimed = effective_claimed_skills(metadata)
    claims = _rows(db, "vbr_project_skill_claims", {"project_id": project_id})
    claims_by_key = {_norm(c.get("skill_key") or c.get("skill_name")): c for c in claims}

    # Rule 7 — nothing legitimate can be inferred: explicit fallback, no items.
    # Website-only outcomes can never form gap items (nothing claims them), so
    # a project with no claimed skills and no claim rows is not assessable —
    # saying "no gaps" there would be misleading.
    if not claimed and not claims:
        return {
            "project_id": project_id,
            "project_title": project_title,
            "assessment_state": "insufficient_evidence",
            "insufficient_evidence_note": _INSUFFICIENT_PROJECT_NOTE,
            "claimed_skills": [],
            "demonstrated_skills": [],
            "gap_items": [],
            "summary": {
                "total_claimed": 0,
                "demonstrated": 0,
                "partially_demonstrated": 0,
                "insufficient_evidence": 0,
                "missing_evidence": 0,
                "not_assessed": 0,
            },
        }

    website_outcomes = _website_outcomes(db, user_id=user_id, project_id=project_id)

    # Gap universe: claimed skills first (owner's own ordering, deduped by
    # normalized key so case/whitespace variants never yield duplicate items),
    # then claim rows not covered by a claimed skill (deterministic name
    # order). Website-only skills are never a gap (nothing claims them).
    seen_keys: set[str] = set()
    universe: list[tuple[str, str, bool]] = []  # (skill_name, key, is_claimed)
    for skill in claimed:
        key = _norm(skill)
        if key and key not in seen_keys:
            seen_keys.add(key)
            universe.append((skill.strip(), key, True))
    for key, claim in sorted(
        claims_by_key.items(), key=lambda kv: _norm(kv[1].get("skill_name"))
    ):
        if key and key not in seen_keys:
            seen_keys.add(key)
            universe.append((str(claim.get("skill_name") or key).strip(), key, False))

    claimed_display = [name for name, _key, is_claimed in universe if is_claimed]
    demonstrated_skills: list[str] = []
    gap_items: list[dict[str, Any]] = []
    counts = {
        "demonstrated": 0,
        "partially_demonstrated": 0,
        "insufficient_evidence": 0,
        "missing_evidence": 0,
        "not_assessed": 0,
    }

    for skill_name, key, is_claimed in universe:
        claim = claims_by_key.get(key)
        links = (
            _rows(
                db,
                "vbr_claim_evidence_links",
                {"project_skill_claim_id": str(claim.get("id") or "")},
            )
            if claim
            else []
        )
        resolved = _resolve_skill(
            skill_name=skill_name,
            skill_key=key,
            claim=claim,
            links=links,
            website=website_outcomes.get(key),
            is_claimed=is_claimed,
        )
        if resolved is None:
            continue
        status = resolved["status"]
        counts[status] = counts.get(status, 0) + 1
        if status == "demonstrated":
            demonstrated_skills.append(skill_name)
            continue
        gap_items.append(
            {
                "skill_name": skill_name,
                "skill_key": key,
                "status": status,
                "status_label": SKILL_GAP_STATUS_LABELS[status],
                "why": resolved["why"],
                "evidence_basis": resolved["evidence_basis"],
                "recommended_action": resolved["recommended_action"],
                "claim_id": resolved["claim_id"],
            }
        )

    return {
        "project_id": project_id,
        "project_title": project_title,
        "assessment_state": "assessed",
        "insufficient_evidence_note": None,
        "claimed_skills": claimed_display,
        "demonstrated_skills": demonstrated_skills,
        "gap_items": gap_items,
        "summary": {
            "total_claimed": len(claimed_display),
            "demonstrated": counts["demonstrated"],
            "partially_demonstrated": counts["partially_demonstrated"],
            "insufficient_evidence": counts["insufficient_evidence"],
            "missing_evidence": counts["missing_evidence"],
            "not_assessed": counts["not_assessed"],
        },
    }


def build_user_skill_gaps(db: Any, *, user_id: str) -> dict[str, Any]:
    """Skill-gap reports for every project owned by ``user_id`` (newest first)."""
    projects = sorted(
        owned_rows(db, "vbr_projects", user_id),
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )
    reports = [
        build_project_skill_gap_report(db, user_id=user_id, project=project)
        for project in projects
    ]
    return {
        "projects": reports,
        "total_gap_count": sum(len(r["gap_items"]) for r in reports),
        "generated_at": _now(),
    }
