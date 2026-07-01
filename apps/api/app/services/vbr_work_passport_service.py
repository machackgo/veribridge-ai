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

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.public_report_safety_service import (
    PublicReportUnsafeError,
    enforce_public_safe,
    public_safe_skill_name,
)
from app.services.safe_public_url import is_safe_public_url
from app.services.vbr_public_project_report import (
    _lookup_display_name,
    _scrub_public_report,
)
from app.services.student_proof_vault_service import (
    collect_skill_summaries,
    collect_vault_items,
)
from app.services.vbr_student_report import build_student_vbr_report

_MAX_SKILL_TRACES = 8

logger = logging.getLogger(__name__)

_PASSPORTS_TABLE = "vbr_work_passports"
_PROJECTS_TABLE = "vbr_projects"
_ONBOARDING_TABLE = "student_onboarding_profiles"

# Whitelisted, recruiter-safe onboarding profile fields for the identity header.
# Deliberately excludes every private/sensitive field (visa_status, sponsorship,
# work-authorization, timeline, raw institution name) — only education context.
_SAFE_PROFILE_FIELDS = ("degree_level", "major", "graduation_year", "university_country")

_VERIFICATION_LABEL = "Verified Work Passport"

_SLUG_GENERATION_ATTEMPTS = 5
_PUBLIC_PATH_PREFIX = "/p/"
_REPORT_PATH_PREFIX = "/vbr/report/"
_MAX_TOP_SKILLS = 16

# Evidence source badge labels (the canonical, recruiter-facing set).
_SRC_GITHUB = "GitHub Proof"
_SRC_DOCUMENT = "Document Proof"
_SRC_WEBSITE = "Website Proof"
_SRC_DEFENSE = "Project Defense"
_SRC_VIDEO = "Video Evidence"
_SRC_REPORT = "VBR Report"

_EVIDENCE_SOURCE_LABELS = [
    _SRC_GITHUB,
    _SRC_DOCUMENT,
    _SRC_WEBSITE,
    _SRC_DEFENSE,
    _SRC_VIDEO,
    _SRC_REPORT,
]

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

        for row in report.get("skill_evidence") or []:
            skill = str(row.get("skill") or "").strip()
            if not skill:
                continue
            key = skill.lower()
            status_label = str(row.get("status") or "Not assessed")
            chip_count = int(row.get("evidence_chip_count") or 0)
            notes = str(row.get("notes") or "").strip()

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
                    "_seen_projects": set(),
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

            title_key = project_title.strip().lower()
            if title_key not in entry["_seen_projects"]:
                entry["_seen_projects"].add(title_key)
                entry["project_count"] += 1
                ref: dict[str, Any] = {
                    "project_title": project_title,
                    # This project's qualitative status FOR THIS SKILL (not the
                    # skill's best status across projects).
                    "skill_status": status_label,
                    "evidence_sources": list(proj_sources),
                    "report_is_public": is_public,
                    "public_report_path": public_report_path,
                    # The proof-native trace cards this project contributes for
                    # this skill (grouped under the project in the drilldown).
                    "evidence_traces": list(project_skill_traces),
                }
                if not public:
                    ref["project_id"] = summary.get("project_id")
                entry["projects"].append(ref)
            else:
                # Same project seen again (e.g. another claimed skill row): merge
                # any additional traces into the existing per-project group.
                for existing in entry["projects"]:
                    if existing.get("project_title", "").strip().lower() == title_key:
                        existing["evidence_traces"].extend(project_skill_traces)
                        break

            for src in proj_sources:
                if src not in entry["evidence_sources"]:
                    entry["evidence_sources"].append(src)

            entry["evidence_chips"].extend(_sanitize_skill_chips(report, skill))

            # Pull the concrete evidence traces this skill row references.
            for trace in project_skill_traces:
                entry["evidence_traces"].append(trace)

    skills: list[dict[str, Any]] = []
    for entry in by_skill.values():
        entry.pop("_seen_projects", None)
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
    return {
        "skill": entry["skill"],
        "status": entry["status"],
        "evidence_sources": list(entry.get("evidence_sources") or []),
        "projects": [
            {
                "project_title": ref.get("project_title") or "",
                # Per-project qualitative status for this skill (label only).
                "skill_status": ref.get("skill_status") or "Not assessed",
                "evidence_sources": list(ref.get("evidence_sources") or []),
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
                .select(",".join(_SAFE_PROFILE_FIELDS))
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
    return {k: row.get(k) for k in _SAFE_PROFILE_FIELDS}


def _education_summary(profile: dict[str, Any]) -> str:
    """A single safe education line from whitelisted onboarding fields."""
    parts: list[str] = []
    major = str(profile.get("major") or "").strip()
    if major:
        parts.append(major)
    degree = str(profile.get("degree_level") or "").strip()
    if degree:
        parts.append(degree.replace("_", " ").title())
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


def _build_identity(
    *,
    display_name: str | None,
    headline: str,
    profile: dict[str, Any],
    evidence_source_counts: dict[str, int],
    public_status: str,
    public_path: str | None,
    last_updated: str | None,
) -> dict[str, Any]:
    """Assemble the recruiter-safe identity header (non-PII only).

    Every free-text field sourced from onboarding/profile data is scrubbed with
    :func:`_safe_identity_text`. Unsafe / empty values are either omitted
    (optional fields → ``None``) or replaced with a neutral placeholder
    (``display_name``/``headline``) so a raw UUID, private id, email, path, or
    token can never surface on the identity header.

    TODO(profile-model): this is an interim header assembled from the few safe
    onboarding fields available today. When a dedicated, consented candidate
    profile model exists (verified name, avatar, links), build the header from it
    here — never invent profile fields; keep the "Verified candidate profile"
    placeholder until real, recruiter-safe fields are supplied.
    """
    grad = profile.get("graduation_year")
    return {
        "display_name": _safe_identity_text(display_name) or _SAFE_DISPLAY_NAME,
        "headline": _safe_identity_text(headline) or _DEFAULT_HEADLINE,
        "program": _safe_identity_text(profile.get("major")),
        "degree_level": _safe_identity_text(
            str(profile.get("degree_level") or "").replace("_", " ").title()
        ),
        "graduation_year": grad if isinstance(grad, int) and grad > 0 else None,
        "region": _safe_identity_text(profile.get("university_country")),
        "education_summary": _safe_identity_text(_education_summary(profile)) or "",
        "public_status": public_status,
        "public_path": public_path,
        "last_updated": last_updated,
        "evidence_source_summary": _evidence_source_summary(evidence_source_counts),
        "verification_label": _VERIFICATION_LABEL,
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


def _merge_evidence_packages(packages: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-attempt evidence packages: booleans OR-ed, counts max-ed.

    Counts use max (not sum) because duplicate attempts re-attach the same
    evidence — summing would inflate the badge numbers.
    """
    merged: dict[str, Any] = {}
    for pkg in packages:
        for key, value in (pkg or {}).items():
            if isinstance(value, bool):
                merged[key] = bool(merged.get(key)) or value
            elif isinstance(value, (int, float)):
                merged[key] = max(int(merged.get(key) or 0), int(value))
            else:
                merged.setdefault(key, value)
    return merged


def _group_project_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> list[list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Group (project, report) pairs by identity, preserving first-seen order.

    Within each group, members are ordered so the representative (first) is the
    one with an active public report token, else the most recently updated.
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
        return project.get("updated_at") or project.get("created_at") or ""

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
    pairs = [
        (project, build_student_vbr_report(db, pipeline_db, project, user_id, include_cross_proof=False))
        for project in projects
    ]
    groups = _group_project_pairs(pairs)

    project_summaries: list[dict[str, Any]] = []
    for group in groups:
        representative_project, representative_report = group[0]
        token = representative_project.get("public_report_token")
        has_public_report = bool(token)

        claimed_skills = _dedupe_preserve(
            [s for _, report in group for s in (report.get("claimed_skills") or [])]
        )
        evidence_sources = _dedupe_preserve(
            [
                src
                for project, report in group
                for src in _evidence_sources(report, bool(project.get("public_report_token")))
            ]
        )
        evidence_package = _merge_evidence_packages(
            [report.get("evidence_package") or {} for _, report in group]
        )

        project_summaries.append(
            {
                "project_id": str(representative_project["id"]),
                "project_title": representative_report.get("project_title") or "",
                "project_summary": representative_report.get("project_description") or "",
                "repo_full_name": representative_report.get("repo_full_name"),
                "claimed_skills": claimed_skills,
                "evidence_sources": evidence_sources,
                "evidence_package": evidence_package,
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

    published_report_count = sum(1 for p in project_summaries if p["report"]["is_public"])

    # Skills aggregate over one representative report per distinct project (so
    # ``project_count`` reflects distinct projects, not duplicate attempts), and
    # carry the safe skill-drilldown detail.
    skills = _aggregate_skills_with_detail(
        list(zip(project_summaries, [group[0][1] for group in groups])),
        public=False,
    )

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
    display_name = _lookup_display_name(db, str(user_id))
    evidence_source_counts = _evidence_source_counts(project_summaries)
    identity = _build_identity(
        display_name=display_name,
        headline=status_part["headline"],
        profile=_lookup_candidate_profile(db, str(user_id)),
        evidence_source_counts=evidence_source_counts,
        public_status="Public passport live" if status_part["is_published"] else "Private only",
        public_path=status_part["public_path"],
        last_updated=status_part["published_at"] or _now(),
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
        "skills": skills,
        "projects": project_summaries,
        "evidence_source_counts": evidence_source_counts,
        "vault_skill_summaries": vault_skill_summaries,
        "vault_proof_count": len(vault_items),
        "vault_unattached_count": vault_unattached_count,
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
    published_pairs = [
        (project, build_student_vbr_report(db, pipeline_db, project, owner_id, include_cross_proof=False))
        for project in projects
        if project.get("public_report_token")
    ]

    featured_reports: list[dict[str, Any]] = []
    featured_summaries: list[dict[str, Any]] = []
    for group in _group_project_pairs(published_pairs):
        representative_project, representative_report = group[0]
        token = representative_project.get("public_report_token")
        claimed_skills = _dedupe_preserve(
            [s for _, report in group for s in (report.get("claimed_skills") or [])]
        )
        evidence_sources = _dedupe_preserve(
            [src for _, report in group for src in _evidence_sources(report, has_public_report=True)]
        )
        summary = {
            "project_title": representative_report.get("project_title") or "",
            "project_summary": representative_report.get("project_description") or "",
            "claimed_skills": claimed_skills,
            "evidence_sources": evidence_sources,
            # The token is intentionally linked (the recruiter follows this path).
            # We never expose a bare token field — only the public report path.
            "public_report_path": f"{_REPORT_PATH_PREFIX}{token}",
            "published_at": representative_project.get("public_report_published_at"),
        }
        featured_summaries.append(summary)
        featured_reports.append(representative_report)

    # Top skills are aggregated only from featured (published-report) projects,
    # so the public passport reflects only published evidence. Qualitative only,
    # with a safe drilldown sourced exclusively from published reports.
    top_skills = [
        _to_public_skill(s)
        for s in _aggregate_skills_with_detail(
            list(zip(featured_summaries, featured_reports)), public=True
        )[:_MAX_TOP_SKILLS]
    ]

    limitations: list[str] = []
    if not featured_summaries:
        limitations.append("No public reports published yet.")
        limitations.append("No featured projects yet.")
    limitations.append(
        "This passport links only to reports the candidate has chosen to make public."
    )
    limitations.append(
        "Evidence is shown with qualitative labels only — never numeric scores or rankings."
    )

    public_display_name = _lookup_display_name(db, owner_id)
    public_evidence_counts = _evidence_source_counts(featured_summaries)
    public_identity = _build_identity(
        display_name=public_display_name,
        headline=_headline_of(passport_row),
        profile=_lookup_candidate_profile(db, owner_id),
        evidence_source_counts=public_evidence_counts,
        # The public surface is itself the passport — it never carries a private
        # owner link or owner-only publish-status text.
        public_status=_VERIFICATION_LABEL,
        public_path=None,
        last_updated=passport_row.get("published_at"),
    )
    public = {
        "candidate_display_name": public_display_name,
        "headline": _headline_of(passport_row),
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
