"""Verified Work Passport (v1) — student's full passport-to-recruiter loop.

This module aggregates a student's Verified Build Report (VBR) projects and
their *published* public reports into two surfaces:

* **Private Work Passport** (owner-only) — the student's evidence wallet:
  every owned ``vbr_projects`` row, grouped evidence-backed skills, per-project
  evidence source badges, and each project's public report publish status.
  Reuses the already-sanitized ``build_student_vbr_report`` summaries, so it
  never surfaces raw transcripts, raw docs/GitHub snapshots, storage paths,
  signed URLs, tokens, ``artifact_data``, or numeric trust scores.

* **Public Work Passport** (no auth) — a recruiter-safe profile resolved by a
  stable ``public_slug``. It exposes ONLY the candidate display name, a safe
  headline/summary, top evidence-backed skills (qualitative labels only), and
  the projects that have an *active* public VBR report token — each linked via
  ``/vbr/report/{token}``. Unpublishing the passport 404s this surface without
  touching evidence; unpublishing an individual VBR report drops that project
  from the featured list automatically.

Owner operations (``publish_passport`` / ``unpublish_passport`` /
``get_passport_status``) mint / clear / report the passport's published state.
Ownership is always enforced because ``get_db`` returns the service-role client
which bypasses RLS.

The public projection re-uses the defence-in-depth scrubbers from
``vbr_public_project_report`` (score-style redaction + unsafe-field scan) so it
can never leak private fields or numeric scores. This module never calls an LLM.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.db.supabase import create_service_role_client
from app.services.passport_attachment_intelligence import (
    PUBLIC_UNATTACHED_LIMITATION,
    build_attachment_suggestions,
    chain_label,
    next_best_action,
    proof_chain_gaps,
    suggested_attachments_for_project,
)
from app.services.proof_attachment_intelligence import classify_vault_attachments
from app.services.proof_synthesis_agent_service import synthesize_skill_report
from app.services.passport_profile_service import public_passport_profile
from app.services.public_report_safety_service import (
    PublicReportUnsafeError,
    enforce_public_safe,
    public_safe_skill_name,
    public_safe_skill_report,
    scrub_public_text,
)
from app.services.skill_normalization import skill_slug
from app.services.safe_public_url import is_safe_public_url
from app.services.vbr_public_project_report import (
    _lookup_display_name,
    _scrub_public_report,
)
from app.services.student_proof_vault_service import (
    collect_skill_report,
    collect_skill_summaries,
    collect_vault_items,
)
from app.services.vbr_student_report import build_student_vbr_report

_MAX_SKILL_TRACES = 8

logger = logging.getLogger(__name__)

_PASSPORTS_TABLE = "vbr_work_passports"
_PROJECTS_TABLE = "vbr_projects"
_RELATIONSHIPS_TABLE = "proof_project_relationships"
_ONBOARDING_TABLE = "student_onboarding_profiles"
_STUDENT_PROFILES_TABLE = "student_profiles"

# Whitelisted, recruiter-safe onboarding profile fields for the identity header.
# Deliberately excludes every private/sensitive field (visa_status, sponsorship,
# work-authorization, timeline, raw institution name) — only education context.
_SAFE_PROFILE_FIELDS = ("degree_level", "major", "graduation_year", "university_country")
# Additional non-education profile fields read for the identity header. Kept out
# of ``_SAFE_PROFILE_FIELDS`` (which is strictly education context); ``avatar_url``
# is a recruiter-safe public photo URL that is re-sanitized before it is emitted.
_PROFILE_SELECT_FIELDS = (*_SAFE_PROFILE_FIELDS, "avatar_url")

# Whitelisted, recruiter-safe identity fields read from the student-maintained
# profile (``student_profiles`` — the same table behind /api/v1/student/profile).
# Deliberately excludes every private field: work_authorization/visa status,
# target_locations, links (github/linkedin), email, and any internal id.
_STUDENT_PROFILE_IDENTITY_FIELDS = (
    "full_name",
    "degree",
    "major",
    "school_name",
    "graduation_year",
    "target_roles",
)

_VERIFICATION_LABEL = "Verified Work Passport"

_SLUG_GENERATION_ATTEMPTS = 5
_PUBLIC_PATH_PREFIX = "/p/"
_REPORT_PATH_PREFIX = "/vbr/report/"
# Owner-only (private) app routes for cross-linking the passport's lenses.
# These NEVER appear in the public projection — the public surface links only
# through ``/vbr/report/{token}`` paths.
_PRIVATE_PROJECT_REPORT_PREFIX = "/student/vbr/projects/"
_PRIVATE_SKILL_REPORT_PREFIX = "/student/vbr/passport/skills/"
_MAX_TOP_SKILLS = 16

# Evidence source badge labels (the canonical, recruiter-facing set).
_SRC_GITHUB = "GitHub Proof"
_SRC_DOCUMENT = "Document Proof"
_SRC_WEBSITE = "Website Proof"
_SRC_DEFENSE = "Project Defense"
_SRC_VIDEO = "Video Evidence"
_SRC_REPORT = "VBR Report"

# Honest fallback for a skill→project row that DOES carry Website Proof but whose
# safe pipeline summaries were too thin to derive a specific behaviour sentence.
# Never fabricated detail — states the runtime-behaviour scope and the gap.
_WEBSITE_LIMITED_NOTE = (
    "Website Proof supports runtime/product behavior for this skill, but detailed "
    "website evidence is limited."
)

_EVIDENCE_SOURCE_LABELS = [
    _SRC_GITHUB,
    _SRC_DOCUMENT,
    _SRC_WEBSITE,
    _SRC_DEFENSE,
    _SRC_VIDEO,
    _SRC_REPORT,
]

# The closed proof-type vocabulary a single skill row may cite as *supporting*
# evidence, in canonical render order. This is deliberately a SUBSET of the
# source-badge set above (``VBR Report`` is a passport-level aggregate, never a
# per-skill proof) so a skill→project row can only ever surface a real, attached
# proof type — never an invented or project-wide one.
_SKILL_PROOF_TYPE_ORDER = [
    _SRC_GITHUB,
    _SRC_WEBSITE,
    _SRC_DOCUMENT,
    _SRC_DEFENSE,
    _SRC_VIDEO,
]
_KNOWN_SKILL_PROOF_TYPES = frozenset(_SKILL_PROOF_TYPE_ORDER)


def _order_skill_proof_types(values: Any) -> list[str]:
    """Dedupe + canonically order proof-type labels for a skill→project row.

    Fails closed: any label outside the known proof-type vocabulary is dropped,
    so a skill row can never advertise a proof type the evidence mapping did not
    actually record for that skill in that project.
    """
    present = {str(v).strip() for v in (values or [])}
    return [p for p in _SKILL_PROOF_TYPE_ORDER if p in present]

# Qualitative skill labels ranked best→worst for cross-project aggregation.
# Numeric trust/confidence scores are never used here.
_STATUS_ORDER = {
    "Demonstrated": 0,
    "Partially demonstrated": 1,
    "Evidence observed": 2,
    "Supporting evidence": 3,
    "Needs review": 4,
    "Not assessed": 5,
}

_DEFAULT_HEADLINE = "Verified Work Passport"
# Neutral, non-PII fallback used when the onboarding-derived display name is
# missing OR scrubs down to nothing safe (e.g. it was only a UUID / private id /
# email). It never leaks a private value while still rendering a usable header.
_SAFE_DISPLAY_NAME = "Verified candidate profile"
_DEFAULT_SUMMARY = (
    "An evidence-backed profile of projects this candidate has built and "
    "defended. Each linked Verified Build Report shows recruiter-safe evidence "
    "summaries — never numbers, rankings, or guarantees."
)

_VERIFICATION_NOTE = (
    "This is a candidate-published Verified Work Passport. It links only to "
    "reports the candidate chose to make public. Evidence is described "
    "qualitatively (observed, supporting, or process evidence) — never as a "
    "number, percentage, or ranking — and is not a guarantee of employment, "
    "skill mastery, or identity."
)

__all__ = [
    "publish_passport",
    "unpublish_passport",
    "get_passport_status",
    "build_private_passport",
    "build_public_passport",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Persistence helpers (dict + Supabase) ────────────────────────────────────


def _get_passport_by_user(db: Any, user_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_PASSPORTS_TABLE, {}).values()
                if str(row.get("user_id")) == str(user_id)
            ),
            None,
        )

    result = (
        db.table(_PASSPORTS_TABLE).select("*").eq("user_id", user_id).limit(1).execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_passport_by_slug(db: Any, slug: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_PASSPORTS_TABLE, {}).values()
                if row.get("public_slug") == slug
            ),
            None,
        )

    result = (
        db.table(_PASSPORTS_TABLE).select("*").eq("public_slug", slug).limit(1).execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _slug_exists(db: Any, slug: str) -> bool:
    if isinstance(db, dict):
        return any(
            row.get("public_slug") == slug
            for row in db.setdefault(_PASSPORTS_TABLE, {}).values()
        )

    result = db.table(_PASSPORTS_TABLE).select("id").eq("public_slug", slug).limit(1).execute()
    return bool(getattr(result, "data", []) or [])


def _generate_slug(db: Any) -> str:
    for _ in range(_SLUG_GENERATION_ATTEMPTS):
        slug = secrets.token_urlsafe(8)
        if not _slug_exists(db, slug):
            return slug
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "vbr_work_passport_slug_generation_failed",
            "message": "Could not generate a unique passport link. Please try again.",
        },
    )


def _insert_passport(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        db.setdefault(_PASSPORTS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_PASSPORTS_TABLE).insert(row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else row


def _update_passport(db: Any, passport_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_PASSPORTS_TABLE, {}).get(passport_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_PASSPORTS_TABLE).update(updates).eq("id", passport_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _list_owned_projects(db: Any, user_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_PROJECTS_TABLE, {}).values()
            if str(row.get("user_id")) == str(user_id)
        ]
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return rows

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return getattr(result, "data", []) or []


# ── Status projection ────────────────────────────────────────────────────────


def _public_path(slug: str) -> str:
    return f"{_PUBLIC_PATH_PREFIX}{slug}"


def _headline_of(row: dict[str, Any] | None) -> str:
    if row and isinstance(row.get("headline"), str) and row["headline"].strip():
        return row["headline"].strip()
    return _DEFAULT_HEADLINE


def _summary_of(row: dict[str, Any] | None) -> str:
    if row and isinstance(row.get("summary"), str) and row["summary"].strip():
        return row["summary"].strip()
    return _DEFAULT_SUMMARY


def _status_response(row: dict[str, Any] | None) -> dict[str, Any]:
    """Owner-only publish status. ``public_slug`` / ``public_path`` are only
    surfaced when the passport is actively published."""
    is_published = bool(row and row.get("is_published") and row.get("public_slug"))
    slug = row.get("public_slug") if row else None
    return {
        "is_published": is_published,
        "public_slug": slug if is_published else None,
        "public_path": _public_path(slug) if is_published and slug else None,
        "published_at": row.get("published_at") if row else None,
        "headline": _headline_of(row),
        "summary": _summary_of(row),
    }


# ── Per-project evidence projection ──────────────────────────────────────────


def _evidence_sources(report: dict[str, Any], has_public_report: bool) -> list[str]:
    """Derive recruiter-facing evidence source badges from a student report."""
    pkg = report.get("evidence_package") or {}
    sources: list[str] = []
    if pkg.get("github_proof_attached"):
        sources.append(_SRC_GITHUB)
    if int(pkg.get("documents_count") or 0) > 0:
        sources.append(_SRC_DOCUMENT)
    if int(pkg.get("website_proofs_count") or 0) > 0:
        sources.append(_SRC_WEBSITE)
    if pkg.get("project_defense_completed"):
        sources.append(_SRC_DEFENSE)
    if pkg.get("video_defense_recorded") or int(pkg.get("video_evidence_chip_count") or 0) > 0:
        sources.append(_SRC_VIDEO)
    if has_public_report:
        sources.append(_SRC_REPORT)
    return sources


# The five attachable proof-chain sources a project card reports completeness
# for. "VBR Report" is a publish outcome, not an attachable proof source, so it
# is deliberately not part of the chain.
_PROOF_CHAIN_STEPS = [
    ("github", _SRC_GITHUB),
    ("website", _SRC_WEBSITE),
    ("document", _SRC_DOCUMENT),
    ("project_defense", _SRC_DEFENSE),
    ("video", _SRC_VIDEO),
]

_MAX_PROJECT_TOP_SKILLS = 5


def _proof_chain(evidence_sources: list[str]) -> dict[str, Any]:
    """Per-project proof-chain completeness, derived purely from the already
    recruiter-safe evidence source badges. Booleans + missing labels only —
    never a numeric completeness score."""
    present = set(evidence_sources)
    chain: dict[str, Any] = {key: label in present for key, label in _PROOF_CHAIN_STEPS}
    chain["attached_count"] = sum(1 for _, label in _PROOF_CHAIN_STEPS if label in present)
    chain["total_count"] = len(_PROOF_CHAIN_STEPS)
    chain["missing"] = [label for _, label in _PROOF_CHAIN_STEPS if label not in present]
    return chain


def _private_project_report_path(project_id: Any) -> str | None:
    """Owner-only route to a project's report preview. Private surface only."""
    pid = str(project_id or "").strip()
    return f"{_PRIVATE_PROJECT_REPORT_PREFIX}{pid}/report" if pid else None


def _private_skill_report_path(skill: str) -> str | None:
    """Owner-only route to a skill's full Skill Report. Private surface only."""
    slug = skill_slug(skill)
    return f"{_PRIVATE_SKILL_REPORT_PREFIX}{slug}" if slug else None


# How each attachable proof source relates to a project claim — the safe,
# recruiter-facing relationship vocabulary used to compose relationship notes.
_SOURCE_RELATIONSHIP = {
    _SRC_GITHUB: "GitHub code",
    _SRC_WEBSITE: "Website behavior evidence",
    _SRC_DOCUMENT: "Document corroboration",
    _SRC_DEFENSE: "Project Defense explanation",
    _SRC_VIDEO: "Video evidence",
}

# Each qualitative status maps to its OWN recruiter-facing claim tier — they are
# never collapsed together. "Demonstrated" is the only status that reads as
# "demonstrates"; "Partially demonstrated" and "Evidence observed" keep their own
# weaker wording so they are never promoted to a full demonstrated claim.
# "Supporting evidence" gets a middle tier ("has supporting evidence for"), and
# everything weaker (Needs review, Not assessed, Insufficient evidence, or
# unknown) is only ever described with neutral, under-review wording so the
# relationship note never overclaims proof.
_DEMONSTRATED_STATUS = "Demonstrated"
_PARTIAL_STATUS = "Partially demonstrated"
_OBSERVED_STATUS = "Evidence observed"
_SUPPORTING_SKILL_STATUSES = {"Supporting evidence"}

# Statuses strong enough to make a positive (non–under-review) skill claim, each
# in its own wording tier.
_POSITIVE_SKILL_STATUSES = {
    _DEMONSTRATED_STATUS,
    _PARTIAL_STATUS,
    _OBSERVED_STATUS,
} | _SUPPORTING_SKILL_STATUSES


def _join_labels(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _join_clauses(clauses: list[str]) -> str:
    """Join status-specific verb clauses (e.g. "demonstrates React", "partially
    demonstrates API Development") into one natural phrase, keeping each tier's
    wording intact. Oxford-comma style for three or more."""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return clauses[0] + " and " + clauses[1]
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _project_relationship_note(
    top_skills: list[dict[str, Any]], evidence_sources: list[str]
) -> str | None:
    """A single safe sentence connecting a project's skills to its proof
    sources — built ONLY from qualitative skill names and the canonical source
    labels (never ids, scores, or raw evidence).

    Status-aware, and each qualitative tier keeps its OWN recruiter-facing
    wording — they are never collapsed together:
      • Demonstrated            → "demonstrates X"
      • Partially demonstrated  → "partially demonstrates X"
      • Evidence observed       → "has observed evidence for X"
        (or, when it is the only tier, "Evidence was observed for X in this
        project")
      • Supporting evidence     → "has supporting evidence for X"
      • Needs review / Not assessed / Insufficient evidence / unknown →
        "Additional evidence is under review for X" (or, when no positive tier
        exists at all, a preliminary / under-review sentence).
    Partially demonstrated and Evidence observed are never promoted into the
    full "demonstrates" claim."""
    considered = top_skills[:3]
    present = set(evidence_sources)
    source_phrases = [
        _SOURCE_RELATIONSHIP[label] for _, label in _PROOF_CHAIN_STEPS if label in present
    ]
    if not considered or not source_phrases:
        return None

    def _skills_with(status: str) -> list[str]:
        return [s["skill"] for s in considered if s.get("status") == status]

    demonstrated = _skills_with(_DEMONSTRATED_STATUS)
    partial = _skills_with(_PARTIAL_STATUS)
    observed = _skills_with(_OBSERVED_STATUS)
    supporting = [
        s["skill"] for s in considered if s.get("status") in _SUPPORTING_SKILL_STATUSES
    ]
    weak = [
        s["skill"]
        for s in considered
        if s.get("status") not in _POSITIVE_SKILL_STATUSES
    ]
    through = f"through {_join_labels(source_phrases)}"
    weak_sentence = (
        f" Additional evidence is under review for {_join_labels(weak)}." if weak else ""
    )

    # Each positive tier contributes its own verb clause — never merged.
    clauses: list[str] = []
    if demonstrated:
        clauses.append(f"demonstrates {_join_labels(demonstrated)}")
    if partial:
        clauses.append(f"partially demonstrates {_join_labels(partial)}")
    if observed:
        clauses.append(f"has observed evidence for {_join_labels(observed)}")
    if supporting:
        clauses.append(f"has supporting evidence for {_join_labels(supporting)}")

    if clauses:
        # Evidence-observed only → its own natural standalone phrasing, so it is
        # never dressed up as something the project "demonstrates".
        if observed and not demonstrated and not partial and not supporting:
            note = (
                f"Evidence was observed for {_join_labels(observed)} in this "
                f"project {through}"
            )
        else:
            note = f"This project {_join_clauses(clauses)} {through}"
        return note + "." + weak_sentence

    # Only weak skills → neutral, under-review wording only.
    return (
        f"This project has preliminary or under-review evidence for "
        f"{_join_labels(weak)} {through}."
    )


def _project_top_skills(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The strongest evidence-backed skills a project demonstrates, ranked by
    qualitative label (best first) and capped. Merged across duplicate-attempt
    reports, keeping each skill's best label. Each entry carries the skill's
    stable slug + owner-only Skill Report route so the project lens can link
    straight into the skill lens (private passport only)."""
    best: dict[str, dict[str, Any]] = {}
    # skill key → the union of proof types that support THIS skill in THIS
    # project, taken directly from each report row's already-skill-specific,
    # fail-closed ``supporting_sources`` (never the project-wide source union).
    proof_types_by_skill: dict[str, set[str]] = {}
    for report in reports:
        for row in report.get("skill_evidence") or []:
            skill = str(row.get("skill") or "").strip()
            if not skill:
                continue
            key = skill.lower()
            status_label = str(row.get("status") or "Not assessed")
            entry = best.get(key)
            if entry is None or _STATUS_ORDER.get(status_label, 99) < _STATUS_ORDER.get(
                entry["status"], 99
            ):
                best[key] = {
                    "skill": skill,
                    "status": status_label,
                    "skill_slug": skill_slug(skill),
                    "skill_report_path": _private_skill_report_path(skill),
                }
            proof_types_by_skill.setdefault(key, set()).update(
                str(s).strip() for s in (row.get("supporting_sources") or [])
            )
    ranked = sorted(
        best.values(),
        key=lambda s: (_STATUS_ORDER.get(s["status"], 99), s["skill"].lower()),
    )
    for entry in ranked:
        entry["supporting_proof_types"] = _order_skill_proof_types(
            proof_types_by_skill.get(entry["skill"].lower(), set())
        )
    return ranked[:_MAX_PROJECT_TOP_SKILLS]


def _sanitize_skill_chips(report: dict[str, Any], skill: str) -> list[dict[str, Any]]:
    """Sanitized video-evidence snippets tied to a skill (no raw media URLs)."""
    skill_l = skill.strip().lower()
    chips: list[dict[str, Any]] = []
    for chip in report.get("video_evidence_chips") or []:
        if not isinstance(chip, dict):
            continue
        related = str(chip.get("related_skill") or "").strip().lower()
        if related and related == skill_l:
            chips.append(
                {
                    "label": str(chip.get("label") or ""),
                    "short_summary": str(chip.get("short_summary") or ""),
                    "source": str(chip.get("source") or "project_defense_video"),
                }
            )
    return chips


def _project_ref_identity(summary: dict[str, Any], *, public: bool) -> str:
    """Stable identity for a project reference inside a skill drilldown.

    Two genuinely different projects can share a human-readable title (e.g. two
    repos both called "Portfolio"). Deduping references by title alone would
    collapse them into one Skill Intelligence reference — undercounting
    ``project_count`` and merging unrelated statuses/traces. This keys on a
    stable per-project identity instead, so same-title / different-repository
    projects stay distinct while repeated attempts of one grouped project (which
    share the same representative summary) still collapse to one reference.

    Priority:
      1. private/internal ``project_id`` — strongest identity, private only.
      2. ``public_report_path`` — unique per grouped project, public-safe.
      3. repository ``owner/name`` — distinguishes same-title different repos.
      4. normalized title — final human-readable fallback only.

    The private id is never consulted for the public projection (it is absent
    from public summaries and must not leak into public output).
    """
    if not public:
        pid = str(summary.get("project_id") or "").strip()
        if pid:
            return f"id:{pid}"
    path = str(summary.get("public_report_path") or "").strip().lower()
    if path:
        return f"path:{path}"
    repo = str(summary.get("repo_full_name") or "").strip().lower()
    if repo:
        return f"repo:{repo}"
    title = str(summary.get("project_title") or "").strip().lower()
    return f"title:{title}"


def _aggregate_skills_with_detail(
    cards: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    public: bool,
) -> list[dict[str, Any]]:
    """Group skill evidence across project cards into a safe skill drilldown.

    Each ``card`` is a ``(project_summary, representative_report)`` pair. The
    result keeps the best qualitative label per skill (never a numeric score),
    and attaches the supporting projects, unioned evidence-source badges, and
    sanitized evidence snippets. For the public projection, only published
    projects ever reach this function, and internal ids are dropped downstream.
    """
    by_skill: dict[str, dict[str, Any]] = {}

    for summary, report in cards:
        proj_sources = list(summary.get("evidence_sources") or [])
        # Index this project's evidence traces so each skill row can pull the
        # concrete traces it references (claim → evidence audit trail).
        report_traces = {
            str(t.get("trace_id")): t
            for t in (report.get("evidence_traces") or [])
            if isinstance(t, dict)
        }
        if public:
            public_report_path = summary.get("public_report_path")
            is_public = True
        else:
            report_status = summary.get("report") or {}
            is_public = bool(report_status.get("is_public"))
            public_report_path = report_status.get("public_path") if is_public else None

        project_title = summary.get("project_title") or report.get("project_title") or ""

        # Safe per-skill Website Proof behaviour sentence for THIS project, taken
        # from the canonical Website→skill mapping the report already computed
        # (``website_skill_evidence`` → each mapped skill's ``relevance_summary``).
        # Only closed-vocabulary, recruiter-safe summaries — never raw
        # DOM/OCR/visual/provider text. Prefer a DIRECT-evidence relevance when a
        # skill mapped more than once. Keyed by lowercased skill for the row below.
        website_note_by_skill: dict[str, str] = {}
        website_note_direct: set[str] = set()
        for wentry in report.get("website_skill_evidence") or []:
            if not wentry.get("skill_mapping_available"):
                continue  # project-level only — surfaced elsewhere, never as a row note
            for srow in wentry.get("skills") or []:
                sk = str(srow.get("skill_name") or "").strip().lower()
                if not sk:
                    continue
                note = str(srow.get("relevance_summary") or "").strip()
                if not note:
                    continue
                is_direct = bool(srow.get("is_direct_evidence"))
                # First writer wins, but a later DIRECT-evidence relevance upgrades
                # a previously-recorded supporting one.
                if sk not in website_note_by_skill or (is_direct and sk not in website_note_direct):
                    website_note_by_skill[sk] = note[:400]
                    if is_direct:
                        website_note_direct.add(sk)

        for row in report.get("skill_evidence") or []:
            skill = str(row.get("skill") or "").strip()
            if not skill:
                continue
            key = skill.lower()
            status_label = str(row.get("status") or "Not assessed")
            chip_count = int(row.get("evidence_chip_count") or 0)
            notes = str(row.get("notes") or "").strip()
            # The proof types that support THIS skill in THIS project — the
            # report row's already-skill-specific, fail-closed ``supporting_sources``
            # (e.g. Website Proof appears only when the website evidence actually
            # supported this skill). Never the project-wide source union below.
            row_proof_types = list(row.get("supporting_sources") or [])

            entry = by_skill.get(key)
            if entry is None:
                entry = {
                    "skill": skill,
                    "status": status_label,
                    "evidence_chip_count": chip_count,
                    "project_count": 0,
                    "evidence_sources": [],
                    "projects": [],
                    "evidence_chips": [],
                    "evidence_traces": [],
                    "notes": notes,
                    "limitations": [],
                    "_ref_by_ident": {},
                }
                by_skill[key] = entry
            else:
                entry["evidence_chip_count"] += chip_count
                if _STATUS_ORDER.get(status_label, 99) < _STATUS_ORDER.get(entry["status"], 99):
                    entry["status"] = status_label
                if not entry["notes"] and notes:
                    entry["notes"] = notes

            # The concrete traces THIS project contributes for THIS skill — used
            # both for the flat aggregate and for the per-project drilldown group.
            project_skill_traces = [
                report_traces[str(tid)]
                for tid in (row.get("evidence_traces") or [])
                if str(tid) in report_traces
            ]

            # Dedupe references by a stable per-project identity, NOT by title:
            # two distinct projects can share a title but differ by repository /
            # public report path, and must stay as separate references.
            ref_ident = _project_ref_identity(summary, public=public)
            existing = entry["_ref_by_ident"].get(ref_ident)
            if existing is None:
                entry["project_count"] += 1
                ref: dict[str, Any] = {
                    "project_title": project_title,
                    # This project's qualitative status FOR THIS SKILL (not the
                    # skill's best status across projects).
                    "skill_status": status_label,
                    "evidence_sources": list(proj_sources),
                    # Proof types supporting THIS skill in THIS project only —
                    # the closed, skill-specific breakdown (not ``evidence_sources``,
                    # which is the whole project's source union).
                    "supporting_proof_types": _order_skill_proof_types(row_proof_types),
                    "report_is_public": is_public,
                    "public_report_path": public_report_path,
                    # The proof-native trace cards this project contributes for
                    # this skill (grouped under the project in the drilldown).
                    "evidence_traces": list(project_skill_traces),
                }
                # Attach a safe Website Proof behaviour sentence ONLY where Website
                # Proof actually supports THIS skill in THIS project (fail-closed on
                # the skill-specific ``row_proof_types``, never the project union).
                # Falls back to the honest "detail limited" note so a mapped-but-thin
                # capture is never described with fabricated specifics.
                if _SRC_WEBSITE in row_proof_types:
                    ref["website_evidence_summary"] = (
                        website_note_by_skill.get(key) or _WEBSITE_LIMITED_NOTE
                    )
                if not public:
                    ref["project_id"] = summary.get("project_id")
                entry["_ref_by_ident"][ref_ident] = ref
                entry["projects"].append(ref)
            else:
                # Same project seen again (another attempt in the grouped
                # project, or another skill row): merge any additional traces
                # into the existing per-project group and keep the strongest
                # qualitative label any attempt earned for this skill, so a
                # later stronger attempt is never masked by the representative.
                existing["evidence_traces"].extend(project_skill_traces)
                existing["supporting_proof_types"] = _order_skill_proof_types(
                    list(existing.get("supporting_proof_types") or []) + row_proof_types
                )
                # A later attempt may be the one that maps Website Proof to this
                # skill — attach/keep the safe behaviour note (never downgrade a
                # specific note back to the limited fallback).
                if _SRC_WEBSITE in row_proof_types and not existing.get("website_evidence_summary"):
                    existing["website_evidence_summary"] = (
                        website_note_by_skill.get(key) or _WEBSITE_LIMITED_NOTE
                    )
                if _STATUS_ORDER.get(status_label, 99) < _STATUS_ORDER.get(
                    str(existing.get("skill_status")), 99
                ):
                    existing["skill_status"] = status_label

            for src in proj_sources:
                if src not in entry["evidence_sources"]:
                    entry["evidence_sources"].append(src)

            entry["evidence_chips"].extend(_sanitize_skill_chips(report, skill))

            # Pull the concrete evidence traces this skill row references.
            for trace in project_skill_traces:
                entry["evidence_traces"].append(trace)

    skills: list[dict[str, Any]] = []
    for entry in by_skill.values():
        entry.pop("_ref_by_ident", None)
        # Dedupe chips and cap so the drilldown stays scannable.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for chip in entry["evidence_chips"]:
            ck = (chip["label"], chip["short_summary"])
            if ck in seen:
                continue
            seen.add(ck)
            deduped.append(chip)
        entry["evidence_chips"] = deduped[:6]
        # Dedupe evidence traces across projects (same source can recur) and cap.
        seen_traces: set[tuple[str, str, str]] = set()
        deduped_traces: list[dict[str, Any]] = []
        for trace in entry["evidence_traces"]:
            tk = (
                str(trace.get("source_type")),
                str(trace.get("source_title")),
                str(trace.get("safe_summary")),
            )
            if tk in seen_traces:
                continue
            seen_traces.add(tk)
            deduped_traces.append(trace)
        entry["evidence_traces"] = deduped_traces[:_MAX_SKILL_TRACES]
        # Dedupe + cap the per-project trace groups the same way so the
        # cross-project drilldown stays scannable.
        for ref in entry["projects"]:
            seen_ref: set[tuple[str, str, str]] = set()
            ref_traces: list[dict[str, Any]] = []
            for trace in ref.get("evidence_traces") or []:
                tk = (
                    str(trace.get("source_type")),
                    str(trace.get("source_title")),
                    str(trace.get("safe_summary")),
                )
                if tk in seen_ref:
                    continue
                seen_ref.add(tk)
                ref_traces.append(trace)
            ref["evidence_traces"] = ref_traces[:_MAX_SKILL_TRACES]
        # The single project where this skill is most strongly evidenced —
        # ranked by that project's qualitative label for THIS skill.
        strongest = min(
            entry["projects"],
            key=lambda ref: _STATUS_ORDER.get(str(ref.get("skill_status")), 99),
            default=None,
        )
        entry["strongest_project_title"] = strongest.get("project_title") if strongest else None
        entry["strongest_project_status"] = strongest.get("skill_status") if strongest else None
        # Skill → Project cross-link: the strongest project as a linkable
        # reference. The private shape carries the owner-only project id +
        # report-preview route; the public projection re-derives a safe shape
        # (title / status / public report path only) in ``_to_public_skill``.
        if strongest is None:
            entry["strongest_project"] = None
        else:
            link: dict[str, Any] = {
                "project_title": strongest.get("project_title") or "",
                "skill_status": strongest.get("skill_status") or "Not assessed",
                "evidence_sources": list(strongest.get("evidence_sources") or []),
                "supporting_proof_types": list(strongest.get("supporting_proof_types") or []),
                "report_is_public": bool(strongest.get("report_is_public")),
                "public_report_path": strongest.get("public_report_path"),
            }
            if strongest.get("website_evidence_summary"):
                link["website_evidence_summary"] = strongest["website_evidence_summary"]
            if not public:
                link["project_id"] = strongest.get("project_id")
                link["project_report_path"] = _private_project_report_path(
                    strongest.get("project_id")
                )
            entry["strongest_project"] = link
        if entry["status"] in {"Needs review", "Not assessed"}:
            entry["limitations"].append(
                "This skill is not yet strongly evidenced — treat it as a claim pending more proof."
            )
        skills.append(entry)

    skills.sort(
        key=lambda s: (
            _STATUS_ORDER.get(s["status"], 99),
            -int(s["evidence_chip_count"]),
            s["skill"].lower(),
        )
    )
    return skills


def _public_safe_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Re-gate a trace's direct link for the public passport (defence in depth)."""
    row = dict(trace)
    if not is_safe_public_url(row.get("public_url")):
        row["public_url"] = None
        row["public_url_label"] = None
        row["is_publicly_openable"] = False
        if not row.get("private_evidence_note"):
            row["private_evidence_note"] = "A direct link was omitted because it was private or internal."
    title = str(row.get("source_title") or "")
    if "://" in title and not is_safe_public_url(title):
        row["source_title"] = str(row.get("source_type") or "Evidence source")
    # Strip the detailed private-only proof excerpts; keep the safe
    # human-readable location label + deterministic question text.
    row["snippet"] = None
    row["answer_excerpt"] = None
    # GitHub code snippet is private-only; the public ``…#L`` link is the proof.
    row["code_snippet"] = None
    if row.get("source_type") == "Document Proof" and row.get("location_detail"):
        row["location_detail"] = (
            "The matched passage is retained privately; only the document reference is shown."
        )
    return row


def _to_public_skill(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a rich skill detail entry to the recruiter-safe public shape
    (qualitative label only; no internal ids, counts, or private fields)."""
    # Public strongest-project link: title / per-skill status / published report
    # path only. Rebuilt from scratch (never passed through) so a private id or
    # owner-only route can never ride along; omitted when the strongest project
    # has no published public report.
    strongest = entry.get("strongest_project") or {}
    public_strongest = None
    if strongest.get("public_report_path"):
        public_strongest = {
            "project_title": strongest.get("project_title") or "",
            "skill_status": strongest.get("skill_status") or "Not assessed",
            "evidence_sources": list(strongest.get("evidence_sources") or []),
            "supporting_proof_types": list(strongest.get("supporting_proof_types") or []),
            "public_report_path": strongest.get("public_report_path"),
        }
    return {
        "skill": entry["skill"],
        "status": entry["status"],
        "strongest_project": public_strongest,
        "evidence_sources": list(entry.get("evidence_sources") or []),
        "projects": [
            {
                "project_title": ref.get("project_title") or "",
                # Per-project qualitative status for this skill (label only).
                "skill_status": ref.get("skill_status") or "Not assessed",
                "evidence_sources": list(ref.get("evidence_sources") or []),
                # Proof types supporting this skill in this published project only.
                "supporting_proof_types": list(ref.get("supporting_proof_types") or []),
                "public_report_path": ref.get("public_report_path") or "",
                # Per-project trace cards, re-sanitized — published projects only.
                "evidence_traces": [_public_safe_trace(t) for t in ref.get("evidence_traces") or []],
            }
            for ref in entry.get("projects") or []
            if ref.get("public_report_path")
        ],
        "evidence_chips": list(entry.get("evidence_chips") or []),
        "evidence_traces": [_public_safe_trace(t) for t in entry.get("evidence_traces") or []],
        "limitations": list(entry.get("limitations") or []),
    }


def _lookup_candidate_profile(db: Any, user_id: str) -> dict[str, Any]:
    """Best-effort, recruiter-safe education context from onboarding.

    Reads ONLY the whitelisted safe fields (degree level, major, graduation year,
    region/country) — never visa/sponsorship/work-authorization or any private
    field. Any lookup problem returns ``{}`` so the header degrades gracefully.
    """
    try:
        if isinstance(db, dict):
            row = next(
                (
                    r
                    for r in db.setdefault(_ONBOARDING_TABLE, {}).values()
                    if str(r.get("user_id")) == str(user_id)
                ),
                None,
            )
        else:
            result = (
                db.table(_ONBOARDING_TABLE)
                .select(",".join(_PROFILE_SELECT_FIELDS))
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - profile context is optional
        return {}
    if not isinstance(row, dict):
        return {}
    return {k: row.get(k) for k in _PROFILE_SELECT_FIELDS}


def _lookup_student_profile_identity(db: Any, user_id: str) -> dict[str, Any]:
    """Best-effort, safe identity fields from the student-maintained profile.

    Reads ONLY the whitelisted ``_STUDENT_PROFILE_IDENTITY_FIELDS`` from
    ``student_profiles`` (name, degree, major, university, graduation year,
    target roles) — never work-authorization/visa status, locations, links,
    email, or internal ids. Any lookup problem returns ``{}`` so the identity
    header degrades gracefully to the users-row / placeholder fallbacks.
    """
    try:
        if isinstance(db, dict):
            row = next(
                (
                    r
                    for r in db.setdefault(_STUDENT_PROFILES_TABLE, {}).values()
                    if str(r.get("user_id")) == str(user_id)
                ),
                None,
            )
        else:
            result = (
                db.table(_STUDENT_PROFILES_TABLE)
                .select(",".join(_STUDENT_PROFILE_IDENTITY_FIELDS))
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - profile identity is optional
        return {}
    if not isinstance(row, dict):
        return {}
    return {k: row.get(k) for k in _STUDENT_PROFILE_IDENTITY_FIELDS}


def _student_profile_display_name(profile: dict[str, Any]) -> str | None:
    """The student's own saved full name, or ``None`` when not set."""
    name = profile.get("full_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _first_target_role(profile: dict[str, Any]) -> str | None:
    """First non-empty target role from the student profile, or ``None``."""
    roles = profile.get("target_roles")
    if not isinstance(roles, list):
        return None
    for role in roles:
        text = str(role or "").strip()
        if text:
            return text
    return None


def _merge_identity_profile(
    onboarding: dict[str, Any], student: dict[str, Any]
) -> dict[str, Any]:
    """Overlay safe ``student_profiles`` education fields onto the onboarding
    education context. The student-maintained profile is the richer, more
    current source, so its fields win when present; onboarding remains the
    fallback. Only whitelisted education fields are merged — never any private
    profile field.
    """
    merged = dict(onboarding)
    for student_key, merged_key in (
        ("major", "major"),
        ("degree", "degree"),
        ("school_name", "university"),
    ):
        value = str(student.get(student_key) or "").strip()
        if value:
            merged[merged_key] = value
    grad = student.get("graduation_year")
    if isinstance(grad, int) and grad > 0:
        merged["graduation_year"] = grad
    return merged


def _education_summary(profile: dict[str, Any]) -> str:
    """A single safe education line from whitelisted profile fields."""
    parts: list[str] = []
    major = str(profile.get("major") or "").strip()
    if major:
        parts.append(major)
    # The student profile's free-text degree ("B.S.", "MS") wins over the
    # onboarding degree-level enum; exactly one of the two is emitted.
    degree = str(profile.get("degree") or "").strip()
    degree_level = str(profile.get("degree_level") or "").strip()
    if degree:
        parts.append(degree)
    elif degree_level:
        parts.append(degree_level.replace("_", " ").title())
    university = str(profile.get("university") or "").strip()
    if university:
        parts.append(university)
    grad = profile.get("graduation_year")
    if isinstance(grad, int) and grad > 0:
        parts.append(f"Class of {grad}")
    region = str(profile.get("university_country") or "").strip()
    if region:
        parts.append(region)
    return " · ".join(parts)


def _evidence_source_summary(counts: dict[str, int]) -> list[str]:
    """Compact ``"GitHub Proof · 3"`` badges for nonzero evidence sources."""
    return [f"{label} · {count}" for label, count in counts.items() if count > 0]


def _safe_identity_text(value: Any) -> str | None:
    """Scrub one onboarding-derived identity field for the public/private header.

    Reuses the Step 7 public-safety scrubber (:func:`public_safe_skill_name`): it
    redacts emails + score/secret fragments and drops any token shaped like a
    bare UUID, hex blob, or a private-prefixed id — both ``prefix_<hex>`` and a
    long *alphanumeric* suffix (``user_1234567890ghijkl`` / ``project_ABCXYZ…`` /
    ``student_…`` / ``artifact_…`` / ``source_…`` / ``provider_…`` / ``report_…``).
    Returns ``None`` when nothing human-readable survives, so the caller can omit
    the field or substitute a neutral placeholder. Onboarding values are untrusted
    free text, so a UUID / private id / email must never ride out raw on the
    identity header — public OR private.
    """
    return public_safe_skill_name(value)


# Signed-URL / private-storage markers that must NEVER surface as a public photo.
_UNSAFE_AVATAR_MARKER_RE = re.compile(
    r"(x-amz-|[?&](signature|token|expires|sig|sv|se)=|/object/sign/|/private/)",
    re.IGNORECASE,
)


def _public_safe_avatar_url(url: Any) -> str | None:
    """Return a profile-photo URL only when it is public-safe, else ``None``.

    Mirrors the client-side ``publicSafeAvatarUrl`` guard so the identity header
    can never emit a signed/tokenized storage URL, a private storage path, or a
    raw storage key: only an absolute ``http(s)`` URL (or a root-relative path)
    with no signed/private markers is allowed. Anything else → ``None`` so the
    card falls back to safe initials.
    """
    raw = str(url).strip() if url is not None else ""
    if not raw:
        return None
    if _UNSAFE_AVATAR_MARKER_RE.search(raw):
        return None
    if re.match(r"^https?://", raw, re.IGNORECASE):
        return raw
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    return None


def _safe_identity_long_text(value: Any, limit: int = 700) -> str | None:
    """Scrub a longer student-authored paragraph (bio) for public display.

    Uses the shared scrubber (emails / score-style / secret fragments redacted,
    length-capped) without the single-line token filtering — a bio is a real
    paragraph, not a label. Empty after scrubbing → ``None`` (omitted).
    """
    if value is None:
        return None
    scrubbed = scrub_public_text(value, limit=limit)
    return scrubbed or None


def _public_safe_link(url: Any) -> str | None:
    """A student profile link, only when it is a plain public https URL.

    Write-time validation already enforces https + host pinning; this read-time
    guard re-checks so a value that bypassed validation (e.g. direct DB write)
    still cannot ride out signed/tokenized or non-https.
    """
    raw = str(url).strip() if url is not None else ""
    if not raw or not raw.lower().startswith("https://"):
        return None
    if _UNSAFE_AVATAR_MARKER_RE.search(raw):
        return None
    return raw


def _build_identity(
    *,
    display_name: str | None,
    headline: str,
    profile: dict[str, Any],
    evidence_source_counts: dict[str, int],
    public_status: str,
    public_path: str | None,
    last_updated: str | None,
    passport_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the recruiter-safe identity header (non-PII only).

    Every free-text field sourced from onboarding/profile data is scrubbed with
    :func:`_safe_identity_text`. Unsafe / empty values are either omitted
    (optional fields → ``None``) or replaced with a neutral placeholder
    (``display_name``/``headline``) so a raw UUID, private id, email, path, or
    token can never surface on the identity header.

    ``passport_profile`` is the consented candidate identity (migration 062,
    already visibility-filtered by :func:`public_passport_profile`). Its fields
    are the canonical source when present; onboarding/legacy fields remain the
    fallback. Fields the student left empty are omitted — never invented.
    """
    pp = passport_profile or {}
    # The consented profile's education fields win inside the education line.
    edu_profile = dict(profile)
    if pp.get("institution"):
        edu_profile["university"] = pp["institution"]
    if pp.get("degree"):
        edu_profile["degree"] = pp["degree"]
    if isinstance(pp.get("graduation_year"), int):
        edu_profile["graduation_year"] = pp["graduation_year"]
    grad = edu_profile.get("graduation_year")
    role_areas = [
        cleaned
        for cleaned in (_safe_identity_text(r) for r in pp.get("role_areas") or [])
        if cleaned
    ][:6]
    return {
        "display_name": _safe_identity_text(display_name) or _SAFE_DISPLAY_NAME,
        "headline": _safe_identity_text(headline) or _DEFAULT_HEADLINE,
        "program": _safe_identity_text(profile.get("major")),
        "degree_level": _safe_identity_text(
            str(profile.get("degree_level") or "").replace("_", " ").title()
        ),
        "graduation_year": grad if isinstance(grad, int) and grad > 0 else None,
        "region": _safe_identity_text(profile.get("university_country")),
        "education_summary": _safe_identity_text(_education_summary(edu_profile)) or "",
        "public_status": public_status,
        "public_path": public_path,
        "last_updated": last_updated,
        "evidence_source_summary": _evidence_source_summary(evidence_source_counts),
        "verification_label": _VERIFICATION_LABEL,
        "avatar_url": _public_safe_avatar_url(profile.get("avatar_url")),
        # Consented Passport Profile fields (already visibility-filtered).
        "preferred_name": _safe_identity_text(pp.get("preferred_name")),
        "pronunciation": _safe_identity_text(pp.get("pronunciation")),
        "bio": _safe_identity_long_text(pp.get("bio")),
        "institution": _safe_identity_text(pp.get("institution")),
        "degree": _safe_identity_text(pp.get("degree")),
        "location": _safe_identity_text(pp.get("location")),
        "availability_label": _safe_identity_text(pp.get("availability_label")),
        "github_url": _public_safe_link(pp.get("github_url")),
        "linkedin_url": _public_safe_link(pp.get("linkedin_url")),
        "portfolio_url": _public_safe_link(pp.get("portfolio_url")),
        "role_areas": role_areas,
        "work_authorization_note": _safe_identity_text(pp.get("work_authorization_note")),
        "has_custom_profile": bool(pp),
    }


def _evidence_source_counts(project_summaries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in _EVIDENCE_SOURCE_LABELS}
    for proj in project_summaries:
        for src in proj.get("evidence_sources") or []:
            if src in counts:
                counts[src] += 1
    return counts


# ── Duplicate-project grouping ───────────────────────────────────────────────
#
# A student may have several ``vbr_projects`` rows for the *same* real project
# (e.g. repeated Project Defense attempts on the same repo). Without grouping
# the passport renders one card per row — many near-identical duplicates. We
# collapse rows that share a project identity (repo, else title) into a single
# evidence card, unioning their evidence badges/skills and surfacing the count.

_GITHUB_REPO_RE = re.compile(r"github\.com[/:]+([^/]+/[^/]+?)(?:\.git)?/?$", re.IGNORECASE)


def _repo_identity(project: dict[str, Any], report: dict[str, Any]) -> str:
    """Normalized ``owner/name`` repo identity, or '' when none is known."""
    repo_full = (report.get("repo_full_name") or project.get("repo_full_name") or "").strip().lower()
    if repo_full:
        return repo_full
    repo_url = (project.get("repo_url") or report.get("repo_url") or "").strip().lower()
    if repo_url:
        match = _GITHUB_REPO_RE.search(repo_url)
        return match.group(1) if match else repo_url.rstrip("/")
    return ""


def _project_identity_key(project: dict[str, Any], report: dict[str, Any]) -> str:
    """Group key for a project. Same repo (or same title when no repo) → same
    card. Falls back to the row id so genuinely distinct projects never merge."""
    repo = _repo_identity(project, report)
    if repo:
        return f"repo:{repo}"
    title = (report.get("project_title") or project.get("title") or "").strip().lower()
    if title:
        return f"title:{title}"
    return f"id:{project.get('id')}"


def _dedupe_preserve(values: list[str]) -> list[str]:
    """Union helper: dedupe case-insensitively while preserving first order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _latest_direct_evidence_by_project(db: Any, user_id: str) -> dict[str, str]:
    """Raw project id → most recent ``directly_linked`` proof attachment stamp.

    ``proof_project_relationships`` rows are written only by the canonical
    finalization boundary, so their timestamps are the truthful "this project's
    attached evidence changed" signal. ``vbr_projects.updated_at`` alone misses
    canonical finalizations (they never touch the project row), which let a
    grouped card's representative — and therefore every report link on the card —
    stay pinned to an older attempt while a newer attempt actually carried the
    freshly attached proof. Missing table / lookup errors return ``{}`` (grouping
    then falls back to project-row recency alone).
    """
    try:
        if isinstance(db, dict):
            rows = [
                row
                for row in db.get(_RELATIONSHIPS_TABLE, {}).values()
                if isinstance(row, dict)
                and str(row.get("owner_user_id") or "") == str(user_id)
            ]
        else:
            response = (
                db.table(_RELATIONSHIPS_TABLE)
                .select("project_id,relationship_state,updated_at,created_at")
                .eq("owner_user_id", user_id)
                .eq("relationship_state", "directly_linked")
                .execute()
            )
            rows = [row for row in (getattr(response, "data", []) or []) if isinstance(row, dict)]
    except Exception:  # pragma: no cover - relationship table availability is additive
        return {}
    latest: dict[str, str] = {}
    for row in rows:
        if row.get("relationship_state") != "directly_linked":
            continue
        pid = str(row.get("project_id") or "")
        stamp = str(row.get("updated_at") or row.get("created_at") or "")
        if pid and stamp and stamp > latest.get(pid, ""):
            latest[pid] = stamp
    return latest


def _group_project_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    evidence_recency: dict[str, str] | None = None,
) -> list[list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Group (project, report) pairs by identity, preserving first-seen order.

    Within each group, members are ordered so the representative (first) is the
    one with an active public report token, else the one with the most recent
    activity — where activity is the LATER of the project row's own update and
    its newest canonical proof attachment (``evidence_recency``). Attaching a
    proof therefore deterministically promotes that attempt to representative,
    so the card's report links land on the report that actually contains the
    newly attached proof.
    """
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    order: list[str] = []
    for project, report in pairs:
        key = _project_identity_key(project, report)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((project, report))

    def _recency(pair: tuple[dict[str, Any], dict[str, Any]]) -> str:
        project, _ = pair
        row_stamp = str(project.get("updated_at") or project.get("created_at") or "")
        evidence_stamp = (evidence_recency or {}).get(str(project.get("id") or ""), "")
        return max(row_stamp, evidence_stamp)

    result: list[list[tuple[dict[str, Any], dict[str, Any]]]] = []
    for key in order:
        # Newest first, then (stable) move any token-holder to the front so the
        # representative carries the published report status.
        members = sorted(groups[key], key=_recency, reverse=True)
        members.sort(key=lambda p: 0 if p[0].get("public_report_token") else 1)
        result.append(members)
    return result


# ── Owner operations ─────────────────────────────────────────────────────────


def publish_passport(
    db: Any,
    user_id: str,
    headline: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Publish (or re-publish) the student's public Work Passport.

    The ``public_slug`` is minted once and kept stable across re-publishes so a
    recruiter link never breaks. Optional ``headline`` / ``summary`` update the
    public-safe profile text. Idempotent for the slug.
    """
    row = _get_passport_by_user(db, user_id)
    now = _now()

    updates: dict[str, Any] = {"is_published": True, "updated_at": now}
    if headline is not None:
        updates["headline"] = headline.strip() or None
    if summary is not None:
        updates["summary"] = summary.strip() or None

    if row is None:
        slug = _generate_slug(db)
        new_row = {
            "id": str(uuid4()),
            "user_id": str(user_id),
            "public_slug": slug,
            "headline": updates.get("headline"),
            "summary": updates.get("summary"),
            "is_published": True,
            "published_at": now,
            "created_at": now,
            "updated_at": now,
        }
        created = _insert_passport(db, new_row)
        logger.info("[VBR] Public Work Passport published for user %s", user_id)
        return _status_response(created or new_row)

    if not row.get("public_slug"):
        updates["public_slug"] = _generate_slug(db)
    # Keep the original first-published timestamp stable; only set it the first time.
    if not row.get("published_at"):
        updates["published_at"] = now

    updated = _update_passport(db, str(row["id"]), updates)
    row.update(updates)
    logger.info("[VBR] Public Work Passport re-published for user %s", user_id)
    return _status_response(updated or row)


def unpublish_passport(db: Any, user_id: str) -> dict[str, Any]:
    """Hide the public Work Passport (404s the public surface).

    The slug is preserved so re-publishing restores the same link, and no
    underlying evidence or individual VBR report tokens are touched. Idempotent.
    """
    row = _get_passport_by_user(db, user_id)
    if row is None or not row.get("is_published"):
        return _status_response(row)

    now = _now()
    updated = _update_passport(db, str(row["id"]), {"is_published": False, "updated_at": now})
    row.update({"is_published": False})
    logger.info("[VBR] Public Work Passport unpublished for user %s", user_id)
    return _status_response(updated or row)


def get_passport_status(db: Any, user_id: str) -> dict[str, Any]:
    """Return the owner's passport publish status (safe defaults when none)."""
    return _status_response(_get_passport_by_user(db, user_id))


# ── Private passport (owner-only) ────────────────────────────────────────────


def _worker_clients(
    db: Any, pipeline_db: Any, thread_local: threading.local
) -> tuple[Any, Any]:
    """Per-worker-thread (db, pipeline_db) for the report thread pool.

    The request-scoped Supabase sync client is NOT safe to share across threads
    issuing requests concurrently: racing its single httpx transport surfaces
    ``httpx.ReadError: [Errno 11] Resource temporarily unavailable`` and the
    whole passport 500s (deterministically on accounts with many projects).
    Each worker thread therefore gets its OWN client. Dict stores (tests /
    dev fallbacks) are plain in-process data and are shared as-is; if a fresh
    client cannot be constructed we fall back to the shared one rather than
    fail the passport outright.
    """
    if isinstance(db, dict):
        return db, pipeline_db
    pair = getattr(thread_local, "vb_client_pair", None)
    if pair is None:
        try:
            fresh = create_service_role_client()
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception("[VBR] per-thread Supabase client creation failed; sharing request client")
            fresh = None
        worker_db = fresh if fresh is not None else db
        # In production ``get_pipeline_db`` returns the same client as ``db``;
        # a dict pipeline store (dev fallback) is shared as-is.
        if isinstance(pipeline_db, dict):
            worker_pipeline = pipeline_db
        elif pipeline_db is db:
            worker_pipeline = worker_db
        else:
            worker_pipeline = fresh if fresh is not None else pipeline_db
        pair = (worker_db, worker_pipeline)
        thread_local.vb_client_pair = pair
    return pair


def _build_report_pairs(
    db: Any, pipeline_db: Any, projects: list[dict[str, Any]], user_id: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(project, report) for each project — reports built CONCURRENTLY.

    Each ``build_student_vbr_report`` is independent and read-only, and its cost
    is dominated by database round-trip latency, so a passport with many
    projects used to pay (projects × report latency) sequentially — tens of
    seconds on a real account. A small thread pool collapses that to roughly the
    slowest single report. Order is preserved. Every worker thread uses its own
    Supabase client (see :func:`_worker_clients`) — the shared sync client is
    not thread-safe under concurrent requests.
    """
    if len(projects) <= 1:
        return [
            (p, build_student_vbr_report(db, pipeline_db, p, user_id, include_cross_proof=False))
            for p in projects
        ]
    thread_local = threading.local()

    def _build_one(project: dict[str, Any]) -> dict[str, Any]:
        worker_db, worker_pipeline_db = _worker_clients(db, pipeline_db, thread_local)
        return build_student_vbr_report(
            worker_db, worker_pipeline_db, project, user_id, include_cross_proof=False
        )

    with ThreadPoolExecutor(max_workers=min(8, len(projects))) as pool:
        reports = list(pool.map(_build_one, projects))
    return list(zip(projects, reports))


def build_private_passport(db: Any, pipeline_db: Any, user_id: str) -> dict[str, Any]:
    """Build the owner-only private Work Passport (full evidence wallet)."""
    passport_row = _get_passport_by_user(db, user_id)
    projects = _list_owned_projects(db, user_id)

    # Build one report per owned row, then collapse duplicate rows of the same
    # real project (same repo/title) into a single evidence card.
    # The passport only reads the attached-project matrix/traces/evidence_package
    # from each report — never the additive ``other_student_proofs`` cross-proof
    # vault scan. Skip it so the passport doesn't pay a whole-vault scan PER
    # project (the dominant cost when a student has many projects). The Student
    # Proof Vault dashboard below already surfaces every owned proof once.
    pairs = _build_report_pairs(db, pipeline_db, projects, user_id)
    groups = _group_project_pairs(
        pairs, evidence_recency=_latest_direct_evidence_by_project(db, user_id)
    )

    # RAW ``vbr_projects`` row id → the grouped project's REPRESENTATIVE id (the
    # single card it collapses into on this passport). Vault proofs are attached to
    # raw rows (one per Project Defense attempt), so this map lets us resolve a
    # vault skill's raw ``project_ids`` to the deduplicated projects that actually
    # appear on the passport — a truthful connected-project set, never inflated by
    # duplicate attempts.
    raw_to_grouped: dict[str, str] = {}
    for group in groups:
        representative_id = str(group[0][0]["id"])
        for member_project, _ in group:
            raw_to_grouped[str(member_project["id"])] = representative_id

    project_summaries: list[dict[str, Any]] = []
    # Project-level-only Website Proof context (Diagnosis-C helper): attached
    # Website Proofs that did NOT map to any skill. Deduped per (project, focus)
    # so multiple generic captures of the same kind collapse to one honest card.
    website_proof_project_context: list[dict[str, Any]] = []
    # Real-unmapped-proof context mirrored from each project's private report
    # (the report is the single source of truth — the passport never re-detects
    # proof itself). Aggregated across EVERY report attempt in each grouped
    # project (deduped), so real analyzed proof attached to a non-representative
    # attempt never disappears. Context only: never skill evidence, never
    # counted anywhere, and never on the public passport projection.
    real_unmapped_proof_context: list[dict[str, Any]] = []
    for group in groups:
        representative_project, representative_report = group[0]
        group_reports = [report for _, report in group]
        token = representative_project.get("public_report_token")
        has_public_report = bool(token)

        # Claimed skills are project *claims* (not proof), so unioning them across
        # collapsed attempts is safe context.
        claimed_skills = _dedupe_preserve(
            [s for _, report in group for s in (report.get("claimed_skills") or [])]
        )
        # GROUPED-ATTEMPT AGGREGATION: the representative report still provides
        # the card's stable display metadata (title / description / repo identity /
        # the single report link + publish state), but PROOF-BEARING fields are
        # aggregated across EVERY report attempt in the group. Each attempt's
        # evidence badges are derived by the same fail-closed report logic
        # (``_evidence_sources`` reads only the report's attached, analyzed
        # ``evidence_package``), so unioning them never invents proof — it only
        # stops real attached proof on a non-representative attempt from
        # disappearing off the card. Vault-only / suggested / unattached proof is
        # never part of any report's evidence package, so it can never ride in.
        # Each attempt's own report remains the drill-down source of truth for
        # exactly which attempt carries which proof.
        evidence_sources = _dedupe_preserve(
            [
                src
                for report in group_reports
                for src in _evidence_sources(report, has_public_report=False)
            ]
            + ([_SRC_REPORT] if has_public_report else [])
        )
        evidence_package = representative_report.get("evidence_package") or {}

        top_skills = _project_top_skills(group_reports)
        project_summaries.append(
            {
                "project_id": str(representative_project["id"]),
                "project_title": representative_report.get("project_title") or "",
                "project_summary": representative_report.get("project_description") or "",
                "repo_full_name": representative_report.get("repo_full_name"),
                "claimed_skills": claimed_skills,
                "evidence_sources": evidence_sources,
                "evidence_package": evidence_package,
                # Proof-chain completeness across the five attachable sources.
                "proof_chain": _proof_chain(evidence_sources),
                # Project → Skill cross-links: each entry carries the skill's
                # slug + owner-only Skill Report route (private surface only).
                "top_skills": top_skills,
                # One safe sentence relating this project's skills to its proof
                # sources (labels only — never ids, scores, or raw evidence).
                "evidence_relationship_note": _project_relationship_note(
                    top_skills, evidence_sources
                ),
                # Number of underlying evidence attempts merged into this card.
                "attempt_count": len(group),
                # Owner-only publish status for this project's recruiter link.
                "report": {
                    "is_public": has_public_report,
                    "public_token": token,
                    "public_path": f"{_REPORT_PATH_PREFIX}{token}" if has_public_report else None,
                    "published_at": representative_project.get("public_report_published_at"),
                },
            }
        )

        # Collect this project's Website Proofs that stayed PROJECT-LEVEL only
        # (mapped no skill) so the Skills Evidence Map can explain the honest gap.
        project_title = representative_report.get("project_title") or ""
        seen_focus: set[str] = set()
        # Every attempt in the group — a project-level Website Proof attached to a
        # non-representative attempt is still real, attached context for this
        # grouped project. Each entry links to the report of the attempt that
        # actually carries it (owner-only route), deduped per focus so repeated
        # generic captures across attempts collapse to one honest card.
        for member_project, report in group:
            member_id = str(member_project["id"])
            for entry in report.get("website_skill_evidence") or []:
                if entry.get("skill_mapping_available"):
                    continue  # mapped a skill — surfaced as skill evidence, not here
                focus_key = str(entry.get("website_purpose_key") or "")
                if focus_key in seen_focus:
                    continue
                seen_focus.add(focus_key)
                website_proof_project_context.append(
                    {
                        "project_id": member_id,
                        "project_title": project_title,
                        "focus_key": focus_key,
                        "focus_label": str(entry.get("website_purpose_label") or ""),
                        "explanation": str(entry.get("website_purpose_summary") or ""),
                        "reason": str(entry.get("unmapped_reason") or ""),
                        "action_guidance": str(entry.get("strengthen_action") or ""),
                        "mapped_to_skills": False,
                        "report_path": f"{_PRIVATE_PROJECT_REPORT_PREFIX}{member_id}/report",
                    }
                )

        # Mirror EVERY attempt's real-unmapped-proof context — no re-detection,
        # the report builder already fail-closed-qualified each entry. Entries
        # keep their own attempt's report_url (that report is where the proof
        # actually lives), and identical proof recurring across attempts of this
        # grouped project is deduped by its safe display identity so it never
        # renders twice.
        seen_unmapped: set[tuple[str, str, str, str]] = set()
        for report in group_reports:
            for ctx in report.get("real_unmapped_proof_context") or []:
                if not isinstance(ctx, dict):
                    continue
                unmapped_key = (
                    str(ctx.get("proof_type") or "").strip().lower(),
                    str(ctx.get("evidence_label") or "").strip().lower(),
                    str(ctx.get("reason") or "").strip().lower(),
                    str(ctx.get("safe_summary") or "").strip().lower(),
                )
                if unmapped_key in seen_unmapped:
                    continue
                seen_unmapped.add(unmapped_key)
                real_unmapped_proof_context.append(dict(ctx))

    published_report_count = sum(1 for p in project_summaries if p["report"]["is_public"])

    # Skills aggregate from EVERY report attempt of each grouped project: one
    # shared project summary paired with each attempt report, so exact skill
    # evidence recorded on a non-representative attempt (its fail-closed,
    # skill-specific ``supporting_sources`` / trace references) merges into the
    # grouped skill→project row instead of disappearing. The aggregation dedupes
    # the grouped project to a single reference (``_project_ref_identity``),
    # unions each skill's proof types, keeps the strongest qualitative label any
    # attempt earned, and never fabricates proof — only report-qualified skill
    # rows contribute. ``project_count`` still reflects distinct projects, not
    # duplicate attempts.
    skill_cards = [
        (project_summaries[i], report)
        for i, group in enumerate(groups)
        for _, report in group
    ]
    skills = _aggregate_skills_with_detail(skill_cards, public=False)

    # ── Student Proof Vault (Layer 1 — compact skill dashboard) ──────────────
    # The passport is no longer attached-proof-only: it aggregates EVERY safe,
    # student-owned proof (GitHub / Document / Website / Project Defense / Video /
    # Skill Graph) directly from its source — attached to a VBR project or not.
    # The main page shows only COMPACT per-skill summaries (category, counts, a
    # few previews) — never every proof card, and without hydrating website
    # detail. The full evidence for one skill is loaded lazily by the Skill
    # Report endpoint (``collect_skill_report``). We still compute the raw vault
    # counts (cheap) so the page can show "N proofs / M unattached".
    vault_items = collect_vault_items(db, pipeline_db, str(user_id))
    vault_skill_summaries = collect_skill_summaries(db, pipeline_db, str(user_id), items=vault_items)
    vault_unattached_count = sum(1 for item in vault_items if not item.get("is_attached_to_project"))

    # Resolve each vault skill's RAW attached project ids to the deduplicated,
    # on-passport representative projects. This gives the Skills Evidence Map a
    # truthful connected-project set for a skill whose proof lives in the vault
    # (never the inflated raw-attempt ``project_count``), and lets it distinguish
    # "attached to a real project (not yet skill-mapped)" from purely-vault proof.
    grouped_title_by_id = {p["project_id"]: p["project_title"] for p in project_summaries}
    for summary in vault_skill_summaries:
        seen: list[str] = []
        for raw_pid in summary.get("project_ids") or []:
            grouped = raw_to_grouped.get(str(raw_pid))
            if grouped and grouped in grouped_title_by_id and grouped not in seen:
                seen.append(grouped)
        summary["connected_project_ids"] = seen
        summary["connected_project_titles"] = [grouped_title_by_id[g] for g in seen]

    # Vault-only (standalone) proof-type sources per skill: the proof types that
    # exist for a skill in the vault but are NOT attached to any project. Kept
    # strictly separate from each skill's project-attached breakdown so vault
    # evidence is never counted as project proof. Only the closed skill-proof
    # vocabulary is considered (a "Skill Graph" pipeline is never a proof type),
    # so a vault-only chip can never advertise something that is not real,
    # attachable proof.
    vault_only_by_skill: dict[str, set[str]] = {}
    for item in vault_items:
        if item.get("is_attached_to_project"):
            continue
        skill_name = str(item.get("skill_name") or "").strip()
        proof_type = str(item.get("proof_type") or "").strip()
        if not skill_name or proof_type not in _KNOWN_SKILL_PROOF_TYPES:
            continue
        vault_only_by_skill.setdefault(skill_name.lower(), set()).add(proof_type)
    for skill in skills:
        skill["vault_only_sources"] = _order_skill_proof_types(
            vault_only_by_skill.get(str(skill.get("skill") or "").strip().lower(), set())
        )

    # ── Proof Attachment Intelligence (owner-only, deterministic) ────────────
    # Match unattached vault proofs to the project they likely belong to using
    # safe metadata only (repo identity, website domain, titles, shared skills).
    # Purely derived: nothing is attached automatically, no data is mutated, and
    # none of this reaches the public projection.
    attachment_suggestions = build_attachment_suggestions(vault_items, project_summaries)
    # Centralized attachment intelligence (Step 4): every vault proof classified
    # into attached / suggested / unattached — deduplicated display entries with
    # closed reason codes and relation-strength labels. Suggested evidence is
    # NEVER counted as attached, and duplicate rows never inflate any count.
    attachment_overview = classify_vault_attachments(vault_items, project_summaries)
    for summary in project_summaries:
        summary["chain_label"] = chain_label(summary["proof_chain"])
        summary["proof_chain_gaps"] = proof_chain_gaps(summary["proof_chain"])
        summary["suggested_attachments"] = suggested_attachments_for_project(
            summary["project_id"], attachment_suggestions
        )
        summary["next_best_action"] = next_best_action(
            summary["proof_chain"], summary["suggested_attachments"]
        )
    unattached_proof_summary = {
        "unattached_count": vault_unattached_count,
        "suggestion_count": len(attachment_suggestions),
        # Unattached proof rows no suggestion covers (still shown in the vault,
        # honestly labelled — never silently guessed onto a project).
        "unmatched_count": max(
            0,
            vault_unattached_count
            - sum(int(s.get("proof_count") or 1) for s in attachment_suggestions),
        ),
        "suggestions": attachment_suggestions,
    }

    # ── Evidence Graph Overview ──────────────────────────────────────────────
    # The passport is an evidence graph (Project ↔ Skill ↔ Proof). This compact
    # summary answers "what's here and what's next" at the top of the page —
    # counts and next actions only, never a numeric score.
    next_actions: list[str] = []
    if not project_summaries:
        next_actions.append("Create a Project Defense to start your first evidence-backed project.")
    elif published_report_count == 0:
        next_actions.append("Publish a recruiter-safe report for your strongest project.")
    incomplete_chains = sum(1 for p in project_summaries if p["proof_chain"]["missing"])
    if incomplete_chains:
        next_actions.append(
            f"{incomplete_chains} project(s) have missing proof sources — attach more evidence "
            "to complete their proof chains."
        )
    if attachment_suggestions:
        next_actions.append(
            f"Review {len(attachment_suggestions)} suggested proof attachment(s) — "
            "likely project matches were found for unattached proof."
        )
    elif vault_unattached_count:
        next_actions.append(
            f"Attach {vault_unattached_count} unattached proof item(s) to a project so they "
            "count as project evidence."
        )
    evidence_graph_overview = {
        "project_count": len(project_summaries),
        "published_report_count": published_report_count,
        "skills_with_evidence": len(vault_skill_summaries),
        # Deduplicated proof counts (Step 4): duplicate rows of the same proof
        # collapse, and suggested evidence is counted separately — it is never
        # part of the attached count.
        "proof_count": (
            attachment_overview["attached_count"]
            + attachment_overview["suggested_count"]
            + attachment_overview["unattached_count"]
        ),
        "attached_proof_count": attachment_overview["attached_count"],
        "suggested_proof_count": attachment_overview["suggested_count"],
        "unattached_proof_count": attachment_overview["unattached_count"],
        "next_actions": next_actions[:3],
    }

    limitations: list[str] = []
    if not projects:
        limitations.append("No projects yet — create a Project Defense to start your passport.")
    if published_report_count == 0:
        limitations.append(
            "No recruiter-safe VBR reports published yet. Publish a project report to feature it."
        )
    if vault_unattached_count:
        limitations.append(
            f"{vault_unattached_count} proof item(s) are not attached to any VBR project. They are "
            "shown in your vault under the relevant skill so nothing is lost — attach them to a "
            "project to feature them in a report."
        )
    limitations.append(
        "Skills and evidence are shown with qualitative labels only — never numeric trust scores."
    )

    status_part = _status_response(passport_row)
    # Identity source order (private passport): the consented Passport Profile
    # (passport_profiles, migration 062) first, then the student-maintained
    # profile (student_profiles.full_name), then the users row, then the neutral
    # safe placeholder applied inside ``_build_identity``. Only whitelisted safe
    # profile fields are ever read — real identity, never invented. The private
    # header uses the SAME visibility-filtered projection the public surface
    # serves, so the owner previews exactly what a recruiter will see.
    passport_profile = public_passport_profile(db, str(user_id))
    student_profile = _lookup_student_profile_identity(db, str(user_id))
    display_name = (
        passport_profile.get("full_name")
        or _student_profile_display_name(student_profile)
        or _lookup_display_name(db, str(user_id))
    )
    # The Passport Profile headline is the canonical personal headline; an
    # explicitly saved passport headline is the next fallback; then the first
    # safe target role; the generic default remains only when none exists.
    identity_headline = passport_profile.get("headline") or status_part["headline"]
    if identity_headline == _DEFAULT_HEADLINE:
        identity_headline = _first_target_role(student_profile) or _DEFAULT_HEADLINE
    evidence_source_counts = _evidence_source_counts(project_summaries)
    identity = _build_identity(
        display_name=display_name,
        headline=identity_headline,
        profile=_merge_identity_profile(
            _lookup_candidate_profile(db, str(user_id)), student_profile
        ),
        evidence_source_counts=evidence_source_counts,
        public_status="Public passport live" if status_part["is_published"] else "Private only",
        public_path=status_part["public_path"],
        last_updated=status_part["published_at"] or _now(),
        passport_profile=passport_profile,
    )
    return {
        "candidate_display_name": display_name,
        "headline": status_part["headline"],
        "summary": status_part["summary"],
        "identity": identity,
        "is_published": status_part["is_published"],
        "public_slug": status_part["public_slug"],
        "public_path": status_part["public_path"],
        "published_at": status_part["published_at"],
        "evidence_graph_overview": evidence_graph_overview,
        "skills": skills,
        "projects": project_summaries,
        "evidence_source_counts": evidence_source_counts,
        "website_proof_project_context": website_proof_project_context,
        "real_unmapped_proof_context": real_unmapped_proof_context,
        "vault_skill_summaries": vault_skill_summaries,
        "vault_proof_count": len(vault_items),
        "vault_unattached_count": vault_unattached_count,
        "unattached_proof_summary": unattached_proof_summary,
        # Attached / Suggested / Unattached display sections (owner-only).
        "attachment_overview": attachment_overview,
        "project_count": len(project_summaries),
        "published_report_count": published_report_count,
        "limitations": limitations,
        "generated_at": _now(),
    }


# ── Public passport (no auth) ────────────────────────────────────────────────


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_work_passport_not_found",
            "message": "This passport is not available.",
        },
    )


def build_public_passport(db: Any, pipeline_db: Any, slug: str) -> dict[str, Any]:
    """Resolve a published passport by ``slug`` and return its public projection.

    Raises 404 unless an *active* (published) passport with this slug exists.
    Only projects with an active public VBR report token are featured, and only
    qualitative skill labels are surfaced. The result is recursively scrubbed of
    score-style fragments and scanned for unsafe fields as defence in depth.
    """
    if not slug:
        raise _not_found()

    passport_row = _get_passport_by_slug(db, slug)
    if passport_row is None or not passport_row.get("is_published"):
        raise _not_found()

    owner_id = str(passport_row.get("user_id") or "")
    projects = _list_owned_projects(db, owner_id)

    # Only projects with an active public report token are shown publicly, and
    # duplicate rows of the same project are collapsed into a single card so a
    # recruiter never sees the same report featured twice.
    published_pairs = _build_report_pairs(
        db,
        pipeline_db,
        [project for project in projects if project.get("public_report_token")],
        owner_id,
    )

    featured_summaries: list[dict[str, Any]] = []
    featured_groups = _group_project_pairs(published_pairs)
    for group in featured_groups:
        representative_project, representative_report = group[0]
        token = representative_project.get("public_report_token")
        claimed_skills = _dedupe_preserve(
            [s for _, report in group for s in (report.get("claimed_skills") or [])]
        )
        # NAVIGATION-CONSISTENCY (fail-closed): the featured card links to the
        # representative's published report token, so its evidence badges/proof
        # chain/top skills come from the REPRESENTATIVE report ONLY — never unioned
        # across other collapsed published attempts (which would advertise a proof
        # the linked report does not show).
        evidence_sources = _dedupe_preserve(
            _evidence_sources(representative_report, has_public_report=True)
        )
        # Public Project → Skill chips: skill name, qualitative status, and the
        # skill's stable slug ONLY (used for in-page anchors to the public
        # skills section). The owner-only skill_report_path is stripped — the
        # public surface never links to private routes.
        public_top_skills = [
            {
                "skill": s["skill"],
                "status": s["status"],
                "skill_slug": s["skill_slug"],
                # Proof types supporting this skill in this published project only
                # (closed, safe labels — never scores, ids, or the project-wide union).
                "supporting_proof_types": list(s.get("supporting_proof_types") or []),
            }
            for s in _project_top_skills([representative_report])
        ]
        summary = {
            "project_title": representative_report.get("project_title") or "",
            "project_summary": representative_report.get("project_description") or "",
            "claimed_skills": claimed_skills,
            "evidence_sources": evidence_sources,
            # Safe proof-chain completeness (booleans + source labels only) so a
            # recruiter can see what is verified and what is missing.
            "proof_chain": _proof_chain(evidence_sources),
            "top_skills": public_top_skills,
            "evidence_relationship_note": _project_relationship_note(
                public_top_skills, evidence_sources
            ),
            # The token is intentionally linked (the recruiter follows this path).
            # We never expose a bare token field — only the public report path.
            "public_report_path": f"{_REPORT_PATH_PREFIX}{token}",
            "published_at": representative_project.get("public_report_published_at"),
        }
        featured_summaries.append(summary)

    # Top skills are aggregated from each featured group's REPRESENTATIVE report —
    # the published report the featured card links to — so a public skill row never
    # advertises a proof attached only to a different collapsed attempt. Qualitative
    # only, with a safe drilldown sourced exclusively from that published report.
    skill_cards = [
        (featured_summaries[i], featured_groups[i][0][1])
        for i in range(len(featured_groups))
    ]
    top_skills = [
        _to_public_skill(s)
        for s in _aggregate_skills_with_detail(skill_cards, public=True)[:_MAX_TOP_SKILLS]
    ]

    limitations: list[str] = []
    if not featured_summaries:
        limitations.append("No public reports published yet.")
        limitations.append("No featured projects yet.")
    limitations.append(
        "This passport links only to reports the candidate has chosen to make public."
    )
    # Honest, count-free public note when unattached private vault evidence
    # exists. This is the ONLY Proof Attachment Intelligence artifact allowed on
    # the public surface — never suggestion objects, private ids, routes, or
    # internal matching logic. Best-effort: a vault read problem never breaks
    # the public passport.
    try:
        if any(
            not item.get("is_attached_to_project")
            for item in collect_vault_items(db, pipeline_db, owner_id)
        ):
            limitations.append(PUBLIC_UNATTACHED_LIMITATION)
    except Exception:  # pragma: no cover - the note is optional context
        pass
    limitations.append(
        "Evidence is shown with qualitative labels only — never numeric scores or rankings."
    )

    # Identity source order (public passport): the consented Passport Profile
    # first (visibility-filtered — only fields the student chose to publish),
    # then the student-maintained profile name, then the users-row lookup, then
    # the neutral placeholder. Identity is served LIVE at read time (the
    # documented consistency policy): profile edits propagate immediately to an
    # already-published passport, while evidence/report content stays
    # publication-versioned behind its own report tokens.
    passport_profile = public_passport_profile(db, owner_id)
    student_profile = _lookup_student_profile_identity(db, owner_id)
    public_display_name = (
        passport_profile.get("full_name")
        or _student_profile_display_name(student_profile)
        or _lookup_display_name(db, owner_id)
    )
    public_headline = passport_profile.get("headline") or _headline_of(passport_row)
    public_evidence_counts = _evidence_source_counts(featured_summaries)
    public_identity = _build_identity(
        display_name=public_display_name,
        headline=public_headline,
        profile=_merge_identity_profile(
            _lookup_candidate_profile(db, owner_id), student_profile
        ),
        evidence_source_counts=public_evidence_counts,
        # The public surface is itself the passport — it never carries a private
        # owner link or owner-only publish-status text.
        public_status=_VERIFICATION_LABEL,
        public_path=None,
        last_updated=passport_row.get("published_at"),
        passport_profile=passport_profile,
    )
    public = {
        "candidate_display_name": public_display_name,
        "headline": public_headline,
        "summary": _summary_of(passport_row),
        "identity": public_identity,
        "top_skills": top_skills,
        "featured_projects": featured_summaries,
        "evidence_source_counts": _evidence_source_counts(featured_summaries),
        "featured_project_count": len(featured_summaries),
        "limitations": limitations,
        "published_at": passport_row.get("published_at"),
        "generated_at": _now(),
        "verification_note": _VERIFICATION_NOTE,
    }

    # Recursively redact score-style fragments from every public string field…
    public = _scrub_public_report(public)

    # …then refuse to serve anything that still trips the unsafe-field scan.
    # Step 7: the final gate runs through the centralized Public Safety layer,
    # a strict superset of the inline scan (rejects private source_id / metadata /
    # raw-payload / provider keys, ``/Users/…`` & ``file://`` paths, raw emails)
    # that also strengthens scrubbing (rank/rating/percentile + emails).
    try:
        public = enforce_public_safe(public)
    except PublicReportUnsafeError:
        logger.warning("[VBR] Public Work Passport failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    return public


def build_public_skill_report(
    db: Any, pipeline_db: Any, slug: str, skill: str
) -> dict[str, Any]:
    """Resolve a published passport by ``slug`` and return ONE skill's public report.

    The recruiter-facing drilldown behind a public passport skill row. Fail-closed
    at every step:

    * 404 unless an *active* (published) passport with this slug exists — a skill
      report can never be read for an unpublished/unknown passport.
    * 404 when the requested skill has no proof at all for this candidate, so the
      route cannot be used to probe arbitrary skill pages.
    * The internal skill report is built with ``synthesize=False`` plus the
      deterministic-only synthesis pass — an anonymous request never resolves or
      calls an LLM provider (this module never calls an LLM).
    * The response is the centralized :func:`public_safe_skill_report` whitelist
      projection (which itself runs ``enforce_public_safe``), so private source
      ids, storage paths, snippets, owner routes, and raw payloads are
      structurally absent — a questionable payload 404s rather than serves.
    """
    if not slug or not skill:
        raise _not_found()

    passport_row = _get_passport_by_slug(db, slug)
    if passport_row is None or not passport_row.get("is_published"):
        raise _not_found()

    owner_id = str(passport_row.get("user_id") or "")

    report = collect_skill_report(db, pipeline_db, owner_id, skill, synthesize=False)
    report.update(synthesize_skill_report(report, use_llm=False))

    # A skill with zero proof does not exist for this candidate — same generic
    # 404 as a bad slug, so nothing can be inferred from the difference.
    overview = report.get("overview") or {}
    if not int(overview.get("proof_count") or 0):
        raise _not_found()

    try:
        public = public_safe_skill_report(report)
    except PublicReportUnsafeError:
        logger.warning(
            "[VBR] Public skill report failed the unsafe-field scan; refusing to serve."
        )
        raise _not_found()

    # Safe header context on top of the centralized projection: the canonical
    # slug (derived, never echoed), the closed qualitative status label, and the
    # scrubbed category — all label-only, never counts/scores/ids.
    public["skill_slug"] = skill_slug(public.get("skill") or skill)
    raw_status = report.get("status")
    public["status"] = raw_status if raw_status in _STATUS_ORDER else "Supporting evidence"
    public["category"] = public_safe_skill_name(report.get("category")) or "Other"
    public["generated_at"] = _now()
    return public
