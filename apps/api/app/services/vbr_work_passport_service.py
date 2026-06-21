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
import secrets

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.vbr_public_project_report import (
    _contains_unsafe_fields,
    _lookup_display_name,
    _scrub_public_report,
)
from app.services.vbr_student_report import build_student_vbr_report

logger = logging.getLogger(__name__)

_PASSPORTS_TABLE = "vbr_work_passports"
_PROJECTS_TABLE = "vbr_projects"

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


def _aggregate_skills(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group skill evidence across projects, keeping the best qualitative
    label per skill (never a numeric score) plus a chip count and project tally.
    """
    by_skill: dict[str, dict[str, Any]] = {}
    for report in reports:
        for row in report.get("skill_evidence") or []:
            skill = str(row.get("skill") or "").strip()
            if not skill:
                continue
            status_label = str(row.get("status") or "Not assessed")
            chips = int(row.get("evidence_chip_count") or 0)
            entry = by_skill.get(skill.lower())
            if entry is None:
                by_skill[skill.lower()] = {
                    "skill": skill,
                    "status": status_label,
                    "evidence_chip_count": chips,
                    "project_count": 1,
                }
                continue
            entry["evidence_chip_count"] += chips
            entry["project_count"] += 1
            if _STATUS_ORDER.get(status_label, 99) < _STATUS_ORDER.get(entry["status"], 99):
                entry["status"] = status_label

    skills = list(by_skill.values())
    skills.sort(
        key=lambda s: (
            _STATUS_ORDER.get(s["status"], 99),
            -int(s["evidence_chip_count"]),
            s["skill"].lower(),
        )
    )
    return skills


def _evidence_source_counts(project_summaries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in _EVIDENCE_SOURCE_LABELS}
    for proj in project_summaries:
        for src in proj.get("evidence_sources") or []:
            if src in counts:
                counts[src] += 1
    return counts


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

    reports: list[dict[str, Any]] = []
    project_summaries: list[dict[str, Any]] = []
    for project in projects:
        report = build_student_vbr_report(db, pipeline_db, project, user_id)
        reports.append(report)
        token = project.get("public_report_token")
        has_public_report = bool(token)
        project_summaries.append(
            {
                "project_id": str(project["id"]),
                "project_title": report.get("project_title") or "",
                "project_summary": report.get("project_description") or "",
                "repo_full_name": report.get("repo_full_name"),
                "claimed_skills": list(report.get("claimed_skills") or []),
                "evidence_sources": _evidence_sources(report, has_public_report),
                "evidence_package": report.get("evidence_package") or {},
                # Owner-only publish status for this project's recruiter link.
                "report": {
                    "is_public": has_public_report,
                    "public_token": token,
                    "public_path": f"{_REPORT_PATH_PREFIX}{token}" if has_public_report else None,
                    "published_at": project.get("public_report_published_at"),
                },
            }
        )

    skills = _aggregate_skills(reports)
    published_report_count = sum(1 for p in project_summaries if p["report"]["is_public"])

    limitations: list[str] = []
    if not projects:
        limitations.append("No projects yet — create a Project Defense to start your passport.")
    if published_report_count == 0:
        limitations.append(
            "No recruiter-safe VBR reports published yet. Publish a project report to feature it."
        )
    limitations.append(
        "Skills and evidence are shown with qualitative labels only — never numeric trust scores."
    )

    status_part = _status_response(passport_row)
    return {
        "candidate_display_name": _lookup_display_name(db, str(user_id)),
        "headline": status_part["headline"],
        "summary": status_part["summary"],
        "is_published": status_part["is_published"],
        "public_slug": status_part["public_slug"],
        "public_path": status_part["public_path"],
        "published_at": status_part["published_at"],
        "skills": skills,
        "projects": project_summaries,
        "evidence_source_counts": _evidence_source_counts(project_summaries),
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

    featured_reports: list[dict[str, Any]] = []
    featured_summaries: list[dict[str, Any]] = []
    for project in projects:
        token = project.get("public_report_token")
        if not token:
            # Only projects with an active public report are ever shown publicly.
            continue
        report = build_student_vbr_report(db, pipeline_db, project, owner_id)
        summary = {
            "project_title": report.get("project_title") or "",
            "project_summary": report.get("project_description") or "",
            "claimed_skills": list(report.get("claimed_skills") or []),
            "evidence_sources": _evidence_sources(report, has_public_report=True),
            # The token is intentionally linked (the recruiter follows this path).
            # We never expose a bare token field — only the public report path.
            "public_report_path": f"{_REPORT_PATH_PREFIX}{token}",
            "published_at": project.get("public_report_published_at"),
        }
        featured_summaries.append(summary)
        featured_reports.append(report)

    # Top skills are aggregated only from featured (published-report) projects,
    # so the public passport reflects only published evidence. Qualitative only.
    top_skills = [
        {"skill": s["skill"], "status": s["status"]}
        for s in _aggregate_skills(featured_reports)[:_MAX_TOP_SKILLS]
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

    public = {
        "candidate_display_name": _lookup_display_name(db, owner_id),
        "headline": _headline_of(passport_row),
        "summary": _summary_of(passport_row),
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
    if _contains_unsafe_fields(public):
        logger.warning("[VBR] Public Work Passport failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    return public
