"""Build the student-owned Final VBR Report (v1) preview.

This summarizes the evidence package attached to a Project Defense project
for the *student themselves* — it is a private preview, not the public
tokenized recruiter report (see ``vbr_public_report``).

Only safe, already-sanitized summary data is read and returned:

- ``vbr_projects.metadata.attached_proofs`` (safe summaries written by
  ``create_project_defense`` — never raw proof payloads).
- ``vbr_verification_sessions.telemetry.project_defense_analysis`` (the
  deterministic ``DefenseAnalysisResponse``-shaped analysis written by
  ``submit_defense_answers`` — its numeric scores are mapped to qualitative
  labels via ``_report_safe_analysis`` and never returned as-is).
- ``vbr_verification_sessions.telemetry.video_evidence_chips`` (sanitized
  timestamped transcript snippets from ``project_defense_evidence_chips``).
- ``vbr_session_questions`` (deterministic defense question text).
- ``skill_evidence_pipelines`` (only ``support_status`` — never numeric
  confidence scores are surfaced in the skill evidence table).

Skill-level evidence, the Project Defense analysis summary, and Website
Proof "evidence strength" are all expressed using qualitative labels — never
numeric trust scores — and Project Defense is always framed as
process/explanation evidence, not independent proof of authorship.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.services.skill_evidence_pipeline_service import (
    PipelineNotFoundError,
    SkillEvidencePipelineService,
)
from app.services.vbr_question_generation import get_latest_session, list_session_questions
from app.services.vbr_session_recording import count_chunks

# Qualitative skill evidence labels. Numeric trust/confidence scores are
# intentionally never surfaced in the skill evidence table.
_DEMONSTRATED = "Demonstrated"
_PARTIALLY_DEMONSTRATED = "Partially demonstrated"
_SUPPORTING_EVIDENCE = "Supporting evidence"
_NEEDS_REVIEW = "Needs review"
_NOT_ASSESSED = "Not assessed"

_STATUS_RANK = {
    _DEMONSTRATED: 0,
    _PARTIALLY_DEMONSTRATED: 1,
    _SUPPORTING_EVIDENCE: 2,
    _NEEDS_REVIEW: 3,
    _NOT_ASSESSED: 4,
}

_PIPELINE_SUPPORT_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "strongly_supported": (_DEMONSTRATED, "Strongly supported by evidence saved to your Skill Graph."),
    "partially_supported": (
        _PARTIALLY_DEMONSTRATED,
        "Partially supported by evidence saved to your Skill Graph.",
    ),
    "needs_review": (_NEEDS_REVIEW, "Skill Graph evidence for this skill needs review."),
}

# Qualitative label for Website Proof "evidence strength" — never a numeric score.
_EVIDENCE_OBSERVED = "Evidence observed"


def _defense_area_label(score: int) -> str:
    """Map a 0-100 Project Defense analysis score to a qualitative label.

    Raw numeric scores are never surfaced in the student report — only this
    label is returned.
    """
    if score >= 80:
        return _DEMONSTRATED
    if score >= 60:
        return _PARTIALLY_DEMONSTRATED
    if score >= 40:
        return _SUPPORTING_EVIDENCE
    if score >= 1:
        return _NEEDS_REVIEW
    return _NOT_ASSESSED


def _website_evidence_label(score: int) -> str:
    """Map a 0-100 Website Proof evidence-strength score to a qualitative label."""
    if score >= 60:
        return _EVIDENCE_OBSERVED
    if score >= 30:
        return _SUPPORTING_EVIDENCE
    if score >= 1:
        return _NEEDS_REVIEW
    return _NOT_ASSESSED


def _report_safe_analysis(analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the report-safe ``VBRReportProjectDefenseAnalysis`` summary.

    Numeric analysis scores are mapped to qualitative labels and never
    included in the returned dict.
    """
    if analysis is None:
        return None
    return {
        "transcript_summary": str(analysis.get("transcript_summary") or ""),
        "skills_mentioned": [str(s) for s in (analysis.get("skills_mentioned") or [])],
        "skills_explained_well": [str(s) for s in (analysis.get("skills_explained_well") or [])],
        "skills_missing_from_explanation": [str(s) for s in (analysis.get("skills_missing_from_explanation") or [])],
        "overall_assessment": _defense_area_label(int(analysis.get("overall_defense_score") or 0)),
        "explanation_clarity": _defense_area_label(int(analysis.get("explanation_clarity_score") or 0)),
        "ownership_signal": _defense_area_label(int(analysis.get("ownership_signal_score") or 0)),
        "technical_depth": _defense_area_label(int(analysis.get("technical_depth_score") or 0)),
        "consistency_with_evidence": _defense_area_label(int(analysis.get("consistency_with_evidence_score") or 0)),
        "risk_flags": [str(s) for s in (analysis.get("risk_flags") or [])],
        "recruiter_summary": str(analysis.get("recruiter_summary") or ""),
        "recommended_improvements": [str(s) for s in (analysis.get("recommended_improvements") or [])],
        "privacy_scan_status": str(analysis.get("privacy_scan_status") or "clean"),
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _norm(value: str) -> str:
    return value.strip().lower()


def _build_pipeline_lookup(pipeline_db: Any, user_id: str, skill_pipeline_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map ``skill_name`` (lowercased) -> pipeline summary for attached pipelines.

    Pipelines that no longer exist or are no longer owned by ``user_id`` are
    silently skipped (the attachment reference may be stale).
    """
    svc = SkillEvidencePipelineService(pipeline_db)
    lookup: dict[str, dict[str, Any]] = {}
    for pipeline_id in skill_pipeline_ids:
        try:
            pipeline = svc.get_pipeline(str(pipeline_id), user_id)
        except PipelineNotFoundError:
            continue
        skill_name = (pipeline.skill_name or "").strip()
        if skill_name:
            lookup[_norm(skill_name)] = {
                "support_status": pipeline.support_status,
            }
    return lookup


def _evidence_chip_count_for_skill(skill: str, video_chips: list[dict[str, Any]]) -> int:
    target = _norm(skill)
    count = 0
    for chip in video_chips:
        related = chip.get("related_skill")
        if related and _norm(str(related)) == target:
            count += 1
    return count


def _skill_evidence_row(
    skill: str,
    analysis: dict[str, Any] | None,
    github_detected_skills: set[str],
    website_supported_skills: set[str],
    pipeline_lookup: dict[str, dict[str, Any]],
    video_chips: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    normalized = _norm(skill)

    if analysis is not None:
        explained_well = {_norm(s) for s in analysis.get("skills_explained_well") or []}
        mentioned = {_norm(s) for s in analysis.get("skills_mentioned") or []}
        if normalized in explained_well:
            candidates.append((_DEMONSTRATED, "Explained clearly during the Project Defense."))
        elif normalized in mentioned:
            candidates.append(
                (_PARTIALLY_DEMONSTRATED, "Mentioned during the Project Defense but not fully explained.")
            )

    if normalized in github_detected_skills:
        candidates.append((_SUPPORTING_EVIDENCE, "Detected in the attached GitHub Proof."))

    if normalized in website_supported_skills:
        candidates.append((_SUPPORTING_EVIDENCE, "Supported by the attached Website Proof."))

    pipeline = pipeline_lookup.get(normalized)
    if pipeline is not None:
        label, note = _PIPELINE_SUPPORT_STATUS_LABELS.get(
            pipeline["support_status"], (_SUPPORTING_EVIDENCE, "Supported by evidence saved to your Skill Graph.")
        )
        candidates.append((label, note))

    if not candidates:
        candidates.append((_NOT_ASSESSED, "No evidence has been reviewed for this skill yet."))

    best_status, best_note = min(candidates, key=lambda c: _STATUS_RANK[c[0]])
    return {
        "skill": skill,
        "status": best_status,
        "evidence_chip_count": _evidence_chip_count_for_skill(skill, video_chips),
        "notes": best_note,
    }


_GITHUB_PROOFS_TABLE = "github_proof_submissions"

_SCORE_PHRASE_RE = re.compile(
    r"\s+with\s+\d{1,3}\s*/\s*100\s+confidence\b",
    re.IGNORECASE,
)
_SCORE_FRAGMENT_RE = re.compile(
    r"\b\d{1,3}\s*/\s*100\b|\b\d{1,3}\s*%\b|\bconfidence\b",
    re.IGNORECASE,
)


def _scrub_score_fragments(value: str) -> str:
    """Remove score-like fragments from report summaries."""
    scrubbed = _SCORE_PHRASE_RE.sub("", value or "")
    scrubbed = _SCORE_FRAGMENT_RE.sub("", scrubbed)
    scrubbed = re.sub(r"\s{2,}", " ", scrubbed)
    scrubbed = re.sub(r"\s+([.,;:])", r"\1", scrubbed)
    return scrubbed.strip()


def _repo_is_public(db: Any, github_proof: dict[str, Any] | None) -> bool:
    """Best-effort: True only when the linked GitHub repo is known to be public.

    Reads ``visibility`` from the github_proof_submissions row when a proof id is
    present. Any uncertainty (missing id, lookup error, non-public value) returns
    False so a private repo is never advertised as a public, linkable URL.
    """
    if not isinstance(github_proof, dict):
        return False
    # Visibility may already be inlined on the attached proof.
    inline = str(github_proof.get("visibility") or "").strip().lower()
    if inline:
        return inline == "public"
    proof_id = github_proof.get("github_proof_id") or github_proof.get("id")
    if not proof_id:
        return False
    try:
        if isinstance(db, dict):
            row = db.get(_GITHUB_PROOFS_TABLE, {}).get(str(proof_id))
        else:
            result = (
                db.table(_GITHUB_PROOFS_TABLE)
                .select("visibility")
                .eq("id", str(proof_id))
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - visibility is best-effort
        return False
    if not isinstance(row, dict):
        return False
    return str(row.get("visibility") or "").strip().lower() == "public"


def build_student_vbr_report(db: Any, pipeline_db: Any, project: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Build the safe, student-owned VBR report preview for ``project``.

    ``project`` must already be ownership-checked (see
    ``get_owned_vbr_project_or_404``).
    """
    metadata = project.get("metadata") or {}
    attached = metadata.get("attached_proofs") or {}
    if not isinstance(attached, dict):
        attached = {}

    claimed_skills: list[str] = [str(s) for s in (metadata.get("claimed_skills") or [])]

    github_proof = attached.get("github_proof") if isinstance(attached.get("github_proof"), dict) else None
    documents_raw = attached.get("documents") if isinstance(attached.get("documents"), list) else []
    website_proofs_raw = attached.get("website_proofs") if isinstance(attached.get("website_proofs"), list) else []
    skill_pipeline_ids = [str(p) for p in (attached.get("skill_pipeline_ids") or []) if p]

    documents = [
        {
            "title": str(doc.get("title") or "Document"),
            "source_type": doc.get("source_type"),
            "status": doc.get("status"),
        }
        for doc in documents_raw
        if isinstance(doc, dict)
    ]

    website_proofs = [
        {
            "target_website": str(wp.get("target_website") or ""),
            "evidence_strength": _website_evidence_label(int(wp.get("evidence_strength_score") or 0)),
            "workflow_confidence": str(wp.get("workflow_confidence") or "insufficient"),
            "supported_skills": [str(s) for s in (wp.get("supported_skills") or [])],
        }
        for wp in website_proofs_raw
        if isinstance(wp, dict)
    ]

    session = get_latest_session(db, str(project["id"]))
    telemetry = (session.get("telemetry") or {}) if session else {}
    if not isinstance(telemetry, dict):
        telemetry = {}

    analysis = telemetry.get("project_defense_analysis")
    if not isinstance(analysis, dict):
        analysis = None

    video_chips_raw = telemetry.get("video_evidence_chips")
    video_chips: list[dict[str, Any]] = video_chips_raw if isinstance(video_chips_raw, list) else []

    questions: list[dict[str, Any]] = []
    chunk_count = 0
    if session is not None:
        questions = list_session_questions(db, str(session["id"]))
        chunk_count = count_chunks(db, str(session["id"]))

    defense_questions = []
    for q in questions:
        target_ref = q.get("target_ref") or {}
        defense_questions.append(
            {
                "id": str(q["id"]),
                "question_text": q.get("question_text") or "",
                "kind": target_ref.get("kind") if isinstance(target_ref, dict) else None,
                "skill": target_ref.get("skill") if isinstance(target_ref, dict) else None,
                "answered": bool(q.get("answered")),
            }
        )

    project_defense_completed = metadata.get("project_defense_status") == "analyzed"
    video_defense_recorded = chunk_count > 0

    # ── Skill evidence table ────────────────────────────────────────────────
    github_detected_skills = {_norm(s) for s in (github_proof.get("detected_skills") or [])} if github_proof else set()
    website_supported_skills: set[str] = set()
    for wp in website_proofs:
        website_supported_skills.update(_norm(s) for s in wp["supported_skills"])

    pipeline_lookup = _build_pipeline_lookup(pipeline_db, user_id, skill_pipeline_ids) if skill_pipeline_ids else {}

    skill_evidence = [
        _skill_evidence_row(
            skill,
            analysis,
            github_detected_skills,
            website_supported_skills,
            pipeline_lookup,
            video_chips,
        )
        for skill in claimed_skills
    ]

    # ── Limitations ──────────────────────────────────────────────────────────
    limitations: list[str] = []
    if github_proof is None:
        limitations.append("GitHub Proof not attached — repository evidence has not been independently checked.")
    if not website_proofs:
        limitations.append("Website proof not attached.")
    if not documents:
        limitations.append("No document proof attached.")
    if not video_defense_recorded:
        limitations.append("Video defense not recorded yet.")
    if not video_chips:
        limitations.append("No timestamped video evidence chips yet.")
    if analysis is None:
        limitations.append("Project Defense has not been analyzed yet.")
    else:
        if analysis.get("privacy_scan_status") == "flagged":
            limitations.append(
                "This Project Defense transcript was flagged by a privacy scan and is hidden from recruiter view "
                "until reviewed."
            )
        if analysis.get("skills_missing_from_explanation"):
            limitations.append(
                "Some claimed skills were not explained in the Project Defense: "
                + ", ".join(str(s) for s in analysis["skills_missing_from_explanation"])
                + "."
            )
    limitations.append(
        "Project Defense reflects the student's own process and explanation of their work — "
        "it is not independent proof of code authorship."
    )
    limitations.append(
        "This preview is private by default — it becomes recruiter-visible only for the "
        "project reports you choose to publish."
    )

    # ── Next actions ─────────────────────────────────────────────────────────
    next_actions: list[str] = []
    if github_proof is None:
        next_actions.append("Attach a GitHub Proof to strengthen repository-based evidence.")
    if not website_proofs:
        next_actions.append("Attach a Website Proof to demonstrate a working deployed app.")
    if not documents:
        next_actions.append("Attach supporting documents (design notes, READMEs, etc.) as additional evidence.")
    if session is None or not questions:
        next_actions.append("Generate Project Defense questions for this project.")
    elif analysis is None:
        next_actions.append("Submit your Project Defense answers to generate an analysis.")
    if not video_defense_recorded:
        next_actions.append("Record a video defense to add timestamped evidence chips.")
    if analysis is not None and analysis.get("skills_missing_from_explanation"):
        next_actions.append("Explain the skills you missed in more depth in a future defense attempt.")

    return {
        "project_id": str(project["id"]),
        "project_title": project.get("title") or "",
        "project_description": metadata.get("description") or "",
        "repo_url": project.get("repo_url") or "",
        "repo_full_name": project.get("repo_full_name"),
        "deployed_url": project.get("deployed_url") or None,
        "student_role": metadata.get("student_role") or "",
        "claimed_skills": claimed_skills,
        "project_status": project.get("status") or "draft",
        "session_id": str(session["id"]) if session else None,
        "generated_at": _now_iso(),
        "evidence_package": {
            "github_proof_attached": github_proof is not None,
            "documents_count": len(documents),
            "website_proofs_count": len(website_proofs),
            "project_defense_completed": project_defense_completed,
            "video_defense_recorded": video_defense_recorded,
            "video_evidence_chip_count": len(video_chips),
        },
        "github_proof": (
            {
                "repo_url": github_proof.get("repo_url"),
                "repo_owner": github_proof.get("repo_owner"),
                "repo_name": github_proof.get("repo_name"),
                "status": github_proof.get("status"),
                "detected_skills": [str(s) for s in (github_proof.get("detected_skills") or [])],
                "public_safe_summary": _scrub_score_fragments(
                    str(github_proof.get("public_safe_summary") or "")
                ),
                "repo_is_public": _repo_is_public(db, github_proof),
            }
            if github_proof is not None
            else None
        ),
        "documents": documents,
        "website_proofs": website_proofs,
        "project_defense_analysis": _report_safe_analysis(analysis),
        "defense_questions": defense_questions,
        "video_evidence_chips": video_chips,
        "skill_evidence": skill_evidence,
        "limitations": limitations,
        "next_actions": next_actions,
        "preview_only": True,
        "public_recruiter_sharing_enabled": False,
    }
