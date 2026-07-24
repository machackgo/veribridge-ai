"""Owner-facing Privacy & Sharing editor context (migration 063).

Builds everything the Privacy Center UI needs in one authenticated read:

* the passport's publish state + disclosure mode + version,
* per published project: which proof aspects actually exist, each aspect's
  CONFIGURED state (the stored override, if any) and EFFECTIVE state (what an
  anonymous recruiter would get), per-document view/download states, and the
  project's skill claims,
* the skills tree (taxonomy group → skill → per-project claim) with
  configured/effective at every level,
* the effective public-access summary (counts computed from actual effective
  visibility — never from raw data).

Effective states here are computed AS IF the passport were Public (the UI
overlays the master Private banner itself) so a student can prepare a custom
policy while Private and publish it intact — granular settings always survive
the master switch.

Owner-only; never called from a public route. This module never calls an LLM.
"""

from __future__ import annotations

import logging

from typing import Any

from app.services import proof_artifact_service as artifacts
from app.services.passport_disclosure import (
    HIDDEN,
    MODE_CUSTOM,
    PROJECT_ASPECTS,
    RECRUITER_SAFE_DEFAULTS,
    RESOURCE_TYPES,
    SUMMARY,
    VIEWABLE,
    EffectiveDisclosure,
    get_policy,
    list_overrides,
    project_skill_key,
)
from app.services.skill_normalization import canonical_skill, skill_category, skill_slug

logger = logging.getLogger(__name__)

# Aspect display metadata (order matters — it drives the editor layout).
_ASPECT_LABELS: list[tuple[str, str, str]] = [
    ("github_repo", "GitHub repository", "Repository identity and link"),
    ("github_lines", "Exact code references", "File paths and line ranges"),
    ("website_summary", "Website Proof summary", "Verified workflow summary"),
    ("website_url", "Live website link", "The deployed site URL"),
    ("website_frames", "Website screenshots", "Captured frames"),
    ("website_video", "Website recording", "Workflow replay video"),
    ("defense_summary", "Project Defense summary", "Verified defense summary"),
    ("defense_transcript", "Defense transcript", "The spoken-answer transcript"),
    ("defense_video", "Defense recording", "The defense video/audio"),
    ("video_summary", "Video evidence moments", "Timestamped video chips"),
    ("video_full", "Full video evidence", "Complete video playback"),
]


def _aspect_entry(
    disclosure: EffectiveDisclosure,
    project_id: str,
    resource_type: str,
    *,
    available: bool,
    label: str,
    description: str,
) -> dict[str, Any]:
    return {
        "resource_type": resource_type,
        "resource_key": project_id,
        "label": label,
        "description": description,
        "available": available,
        "configured": disclosure.configured(resource_type, project_id),
        "effective": disclosure.aspect(project_id, resource_type),
        "default": RECRUITER_SAFE_DEFAULTS.get(resource_type, HIDDEN),
        "allowed": sorted(RESOURCE_TYPES[resource_type]),
    }


def build_disclosure_context(db: Any, pipeline_db: Any, user_id: str) -> dict[str, Any]:
    """The complete Privacy & Sharing editor context for the owner."""
    # Local imports: the passport service imports the disclosure resolver, so
    # importing its helpers at module top would be circular.
    from app.services.vbr_work_passport_service import (
        _build_report_pairs,
        _group_project_pairs,
        _list_owned_projects,
        get_passport_status,
    )

    status_row = get_passport_status(db, user_id)
    policy = get_policy(db, user_id)
    overrides = list_overrides(db, user_id)
    # Effective states AS IF public — see module docstring.
    disclosure = EffectiveDisclosure(
        user_id=str(user_id),
        passport_public=True,
        mode=str(policy.get("mode") or "recruiter_safe"),
        disclosure_version=int(policy.get("disclosure_version") or 1),
        overrides=overrides,
    )

    owned = _list_owned_projects(db, str(user_id))
    published = [p for p in owned if p.get("public_report_token")]
    pairs = _build_report_pairs(db, pipeline_db, published, str(user_id))
    groups = _group_project_pairs(pairs)

    projects_out: list[dict[str, Any]] = []
    skills_index: dict[str, dict[str, Any]] = {}

    summary_counts = {
        "projects_public": 0,
        "skills_public": 0,
        "skill_groups_public": 0,
        "github_repositories_viewable": 0,
        "exact_code_references": 0,
        "websites_public": 0,
        "website_screenshot_sets": 0,
        "website_recordings_viewable": 0,
        "document_summaries": 0,
        "documents_viewable": 0,
        "document_downloads": 0,
        "defense_summaries": 0,
        "defense_transcripts_viewable": 0,
        "defense_recordings_viewable": 0,
        "video_moments_public": 0,
    }

    for group in groups:
        project, report = group[0]
        project_id = str(project.get("id") or "")
        title = str(report.get("project_title") or project.get("title") or "Project")

        github_proof = report.get("github_proof")
        website_rows = [w for w in (report.get("website_proofs") or []) if isinstance(w, dict)]
        documents = [d for d in (report.get("documents") or []) if isinstance(d, dict)]
        defense_present = report.get("project_defense_analysis") is not None
        video_chip_count = len(report.get("video_evidence_chips") or [])
        github_code_reference_count = sum(
            1
            for trace in (report.get("evidence_traces") or [])
            if isinstance(trace, dict)
            and trace.get("source_type") == "GitHub Proof"
            and trace.get("file_path")
        )

        website_keys = [str(w.get("website_key") or "") for w in website_rows]
        frames_exist = any(
            artifacts.list_artifacts_for_proof(
                db, proof_type="website", proof_id=key, artifact_type="website_frame"
            )
            for key in website_keys
            if key
        )
        replay_exists = any(
            artifacts.list_artifacts_for_proof(
                db, proof_type="website", proof_id=key, artifact_type="website_replay_video"
            )
            for key in website_keys
            if key
        )
        defense_transcript_exists = bool(
            artifacts.list_artifacts_for_project(
                db, project_id=project_id, artifact_type="defense_transcript"
            )
        )
        defense_video_exists = bool(
            artifacts.list_artifacts_for_project(db, project_id=project_id, artifact_type="defense_video")
            or artifacts.list_artifacts_for_project(db, project_id=project_id, artifact_type="defense_audio")
        )

        availability = {
            "github_repo": github_proof is not None,
            "github_lines": github_code_reference_count > 0,
            "website_summary": bool(website_rows),
            "website_url": bool(website_rows) or bool(report.get("deployed_url")),
            "website_frames": frames_exist,
            "website_video": replay_exists,
            "defense_summary": defense_present,
            "defense_transcript": defense_transcript_exists,
            "defense_video": defense_video_exists,
            "video_summary": video_chip_count > 0,
            "video_full": video_chip_count > 0,
        }

        aspects = [
            _aspect_entry(
                disclosure,
                project_id,
                resource_type,
                available=bool(availability.get(resource_type)),
                label=label,
                description=description,
            )
            for resource_type, label, description in _ASPECT_LABELS
        ]

        documents_out: list[dict[str, Any]] = []
        for doc in documents:
            key = str(doc.get("document_key") or "")
            if not key:
                continue
            original = doc.get("original_document") or {}
            state = disclosure.document_state(project_id, key)
            documents_out.append(
                {
                    "document_key": key,
                    "title": doc.get("title"),
                    "source_type": doc.get("source_type"),
                    "configured": disclosure.configured("document", key),
                    "effective": state,
                    "default": RECRUITER_SAFE_DEFAULTS["document"],
                    "allowed": sorted(RESOURCE_TYPES["document"]),
                    "download_configured": disclosure.configured("document_download", key),
                    "effective_downloadable": disclosure.document_downloadable(project_id, key),
                    "has_retained_original": bool(
                        isinstance(original, dict) and original.get("available")
                    ),
                }
            )

        project_visible = disclosure.project_visible(project_id)
        report_visible = disclosure.report_visible(project_id)
        project_entry = {
            "project_id": project_id,
            "title": title,
            "public_report_path": f"/vbr/report/{project.get('public_report_token')}",
            "published_at": project.get("public_report_published_at"),
            "project": {
                "configured": disclosure.configured("project", project_id),
                "effective": "visible" if project_visible else "hidden",
                "allowed": sorted(RESOURCE_TYPES["project"]),
            },
            "report": {
                "configured": disclosure.configured("report", project_id),
                "effective": "visible" if report_visible else "hidden",
                "allowed": sorted(RESOURCE_TYPES["report"]),
            },
            "aspects": aspects,
            "documents": documents_out,
            "override_count": sum(
                1
                for (rtype, key) in overrides
                if key == project_id
                or (rtype in {"document", "document_download"} and key in {d["document_key"] for d in documents_out})
                or (rtype == "project_skill" and key.startswith(f"{project_id}:"))
            ),
        }
        projects_out.append(project_entry)

        # ── Skills tree contributions ────────────────────────────────────────
        for row in report.get("skill_evidence") or []:
            if not isinstance(row, dict):
                continue
            raw_name = str(row.get("skill") or "").strip()
            if not raw_name:
                continue
            name = canonical_skill(raw_name)
            slug = skill_slug(name)
            category = skill_category(name)
            entry = skills_index.setdefault(
                slug,
                {
                    "skill": name,
                    "skill_slug": slug,
                    "category": category,
                    "configured": disclosure.configured("skill", slug),
                    "effective": (
                        "visible" if disclosure.skill_visible(category, slug) else "hidden"
                    ),
                    "allowed": sorted(RESOURCE_TYPES["skill"]),
                    "project_claims": [],
                },
            )
            claim_key = project_skill_key(project_id, slug)
            if not any(
                claim["project_id"] == project_id for claim in entry["project_claims"]
            ):
                entry["project_claims"].append(
                    {
                        "project_id": project_id,
                        "project_title": title,
                        "resource_key": claim_key,
                        "configured": disclosure.configured("project_skill", claim_key),
                        "effective": (
                            "visible"
                            if disclosure.project_skill_visible(project_id, category, slug)
                            else "hidden"
                        ),
                        "allowed": sorted(RESOURCE_TYPES["project_skill"]),
                    }
                )

        # ── Effective public-access summary contributions ────────────────────
        if report_visible:
            summary_counts["projects_public"] += 1
            github_state = disclosure.aspect(project_id, "github_repo")
            if (
                github_state == VIEWABLE
                and isinstance(github_proof, dict)
                and github_proof.get("repo_is_public")
            ):
                summary_counts["github_repositories_viewable"] += 1
                if disclosure.aspect(project_id, "github_lines") == VIEWABLE:
                    summary_counts["exact_code_references"] += github_code_reference_count
            if (
                disclosure.aspect(project_id, "website_summary") != HIDDEN
                and disclosure.aspect(project_id, "website_url") != HIDDEN
                and website_rows
            ):
                summary_counts["websites_public"] += 1
            if disclosure.aspect(project_id, "website_frames") == VIEWABLE and frames_exist:
                summary_counts["website_screenshot_sets"] += 1
            if disclosure.aspect(project_id, "website_video") == VIEWABLE and replay_exists:
                summary_counts["website_recordings_viewable"] += 1
            for doc_entry in documents_out:
                if doc_entry["effective"] == SUMMARY:
                    summary_counts["document_summaries"] += 1
                elif doc_entry["effective"] == VIEWABLE:
                    summary_counts["document_summaries"] += 1
                    if doc_entry["has_retained_original"]:
                        summary_counts["documents_viewable"] += 1
                        if doc_entry["effective_downloadable"]:
                            summary_counts["document_downloads"] += 1
            if disclosure.aspect(project_id, "defense_summary") != HIDDEN and defense_present:
                summary_counts["defense_summaries"] += 1
                if (
                    disclosure.aspect(project_id, "defense_transcript") == VIEWABLE
                    and defense_transcript_exists
                ):
                    summary_counts["defense_transcripts_viewable"] += 1
                if (
                    disclosure.aspect(project_id, "defense_video") == VIEWABLE
                    and defense_video_exists
                ):
                    summary_counts["defense_recordings_viewable"] += 1
            if disclosure.aspect(project_id, "video_summary") != HIDDEN:
                summary_counts["video_moments_public"] += video_chip_count

    # Skills counts: a skill is public when its group + itself are visible AND
    # at least one of its project claims is effectively visible.
    visible_groups: set[str] = set()
    skills_out: list[dict[str, Any]] = []
    for entry in skills_index.values():
        visible_claims = [
            claim for claim in entry["project_claims"] if claim["effective"] == "visible"
        ]
        effectively_visible = entry["effective"] == "visible" and bool(visible_claims)
        entry["effectively_public"] = effectively_visible
        if effectively_visible:
            summary_counts["skills_public"] += 1
            visible_groups.add(str(entry["category"]))
        skills_out.append(entry)
    summary_counts["skill_groups_public"] = len(visible_groups)

    # Group the skills tree by taxonomy category for the editor.
    groups_out: dict[str, dict[str, Any]] = {}
    for entry in skills_out:
        category = str(entry["category"])
        group_entry = groups_out.setdefault(
            category,
            {
                "category": category,
                "configured": disclosure.configured("skill_group", category),
                "effective": (
                    "visible" if disclosure.skill_group_visible(category) else "hidden"
                ),
                "allowed": sorted(RESOURCE_TYPES["skill_group"]),
                "skills": [],
            },
        )
        group_entry["skills"].append(entry)
    skill_groups = sorted(groups_out.values(), key=lambda g: str(g["category"]).lower())
    for group_entry in skill_groups:
        group_entry["skills"].sort(key=lambda s: str(s["skill"]).lower())

    return {
        "passport": {
            "is_published": bool(status_row.get("is_published")),
            "public_slug": status_row.get("public_slug"),
            "public_path": status_row.get("public_path"),
            "preview_public_path": status_row.get("preview_public_path"),
            "mode": disclosure.mode,
            "disclosure_version": disclosure.disclosure_version,
            "custom_overrides_active": disclosure.mode == MODE_CUSTOM,
            "override_count": len(overrides),
        },
        "projects": projects_out,
        "skill_groups": skill_groups,
        "summary": summary_counts,
    }


# ── Presets ───────────────────────────────────────────────────────────────────

PRESETS = ("recruiter_safe", "portfolio_open", "maximum_privacy")


def preset_changes(context: dict[str, Any], preset: str) -> list[dict[str, Any]]:
    """Override changes implementing one safe preset over the CURRENT projects.

    * ``portfolio_open`` — public repos/websites/screenshots and every retained
      document viewable; recordings/transcripts stay hidden; downloads stay
      disabled.
    * ``maximum_privacy`` — names and verified summaries only: repository
      identity withheld, live links hidden, all artifacts hidden or summary.
    (``recruiter_safe`` is a mode switch, not an override set — handled by the
    caller.)
    """
    changes: list[dict[str, Any]] = []
    for project in context.get("projects") or []:
        project_id = str(project.get("project_id") or "")
        if not project_id:
            continue
        if preset == "portfolio_open":
            changes.extend(
                [
                    {"resource_type": "github_repo", "resource_key": project_id, "visibility": "viewable"},
                    {"resource_type": "github_lines", "resource_key": project_id, "visibility": "viewable"},
                    {"resource_type": "website_url", "resource_key": project_id, "visibility": "visible"},
                    {"resource_type": "website_frames", "resource_key": project_id, "visibility": "viewable"},
                    {"resource_type": "website_video", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "defense_transcript", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "defense_video", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "video_full", "resource_key": project_id, "visibility": "hidden"},
                ]
            )
            for doc in project.get("documents") or []:
                changes.append(
                    {
                        "resource_type": "document",
                        "resource_key": str(doc.get("document_key")),
                        "visibility": "viewable",
                    }
                )
                changes.append(
                    {
                        "resource_type": "document_download",
                        "resource_key": str(doc.get("document_key")),
                        "visibility": "hidden",
                    }
                )
        elif preset == "maximum_privacy":
            changes.extend(
                [
                    {"resource_type": "github_repo", "resource_key": project_id, "visibility": "summary"},
                    {"resource_type": "github_lines", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "website_url", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "website_frames", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "website_video", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "defense_transcript", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "defense_video", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "video_summary", "resource_key": project_id, "visibility": "hidden"},
                    {"resource_type": "video_full", "resource_key": project_id, "visibility": "hidden"},
                ]
            )
            for doc in project.get("documents") or []:
                changes.append(
                    {
                        "resource_type": "document",
                        "resource_key": str(doc.get("document_key")),
                        "visibility": "summary",
                    }
                )
                changes.append(
                    {
                        "resource_type": "document_download",
                        "resource_key": str(doc.get("document_key")),
                        "visibility": "hidden",
                    }
                )
    return changes


__all__ = ["PRESETS", "build_disclosure_context", "preset_changes"]
