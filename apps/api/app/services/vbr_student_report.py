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

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.services.defense_answer_evidence_service import (
    MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION,
)
from app.services.project_defense_analysis_service import (
    coherent_overall_defense_score,
)
from app.services.project_defense_inspection_service import (
    build_project_defense_inspection_cards,
)
from app.services.defense_evidence_access_service import (
    build_recording_playback,
    build_safe_answer_excerpts,
)
from app.services.github_canonical_skill_evidence_adapter import (
    collect_canonical_github_skill_evidence,
    repo_identity,
)
from app.services.github_skill_evidence_service import (
    is_strong_code_snippet as _is_strong_code_snippet,
)
from app.services.github_skill_evidence_service import (
    ml_pipeline_rank as _ml_pipeline_rank,
)
from app.services.github_skill_evidence_service import (
    safe_code_snippet as _safe_code_snippet,
)
from app.services.github_skill_evidence_service import (
    safe_commit_sha as _safe_commit_sha,
)
from app.services.safe_public_url import is_safe_public_url, safe_repo_relative_path
from app.services.skill_normalization import canonical_skill
from app.services.skill_evidence_pipeline_service import (
    PipelineNotFoundError,
    SkillEvidencePipelineService,
)
from app.services.vbr_question_generation import get_latest_session, list_session_questions
from app.services.vbr_session_recording import count_chunks
from app.services.website_proof_detail_service import get_website_proof_detail
from app.services.website_skill_proof_focus import (
    WEBSITE_STRENGTHEN_ACTION,
    classify_website_purpose,
    classify_website_skill_relevance,
    describe_website_purpose,
    describe_website_skill_relevance,
    is_direct_website_relevance,
    map_website_supported_skills,
    website_app_context,
    website_behavior_claim,
    website_evidence_source_types,
    website_limitation_for,
    website_output_observed,
    website_page_context_label,
    website_purpose_summary,
    website_recruiter_checklist,
    website_runtime_claim,
    website_skill_relevance_summary,
    website_target_domain,
    website_unmapped_skill_reason,
    website_user_action_observed,
    website_verification_mode_label,
)
from app.services.website_skill_proof_focus import (
    VERIFICATION_MODE_LIVE,
    VERIFICATION_MODE_RECORDED,
)

logger = logging.getLogger(__name__)


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

# Canonical recruiter-facing evidence-source labels. Kept identical to the
# Work Passport badge set so a skill's supporting sources read the same across
# the per-project report, the public report, and the passport drilldowns.
_SRC_GITHUB = "GitHub Proof"
_SRC_DOCUMENT = "Document Proof"
_SRC_WEBSITE = "Website Proof"
_SRC_DEFENSE = "Project Defense"
_SRC_VIDEO = "Video Evidence"

# A skill with no strong evidence carries this honest, recruiter-safe note so
# the matrix never overstates a claim.
_SKILL_UNEVIDENCED_LIMITATION = (
    "Not yet strongly evidenced — treat as a claim pending more proof."
)

# ── Real-unmapped-proof context (private surfaces only) ──────────────────────
#
# Honest per-proof-type reasons for the "Attached proof not yet skill-mapped"
# layer: REAL analyzed proof is attached to the project, but no exact claimed
# skill row consumed it. Never generated from metadata alone (a repo URL, a
# website URL, a filename, an unanswered question plan), never counted as skill
# evidence, and never included in any public payload.
_REAL_UNMAPPED_GITHUB_REASON = (
    "Analyzed source evidence exists, but no exact skill row consumed it yet."
)
_REAL_UNMAPPED_WEBSITE_REASON = (
    "Runtime proof exists, but it is not mapped to a specific skill yet."
)
_REAL_UNMAPPED_DOCUMENT_REASON = (
    "Analyzed document evidence exists, but it is not mapped to a specific skill yet."
)
_REAL_UNMAPPED_DEFENSE_REASON = (
    "Defense evidence exists, but it is not mapped to a specific skill yet."
)

# Owner-only route prefix for a project's private report preview (mirrors
# ``vbr_work_passport_service._PRIVATE_PROJECT_REPORT_PREFIX``). Private
# surfaces only — the public projections never include this context at all.
_PRIVATE_PROJECT_REPORT_PREFIX = "/student/vbr/projects/"


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
        # Coherence: legacy stored rows may carry an overall that exceeds what
        # their component scores support — label the derived coherent value.
        "overall_assessment": _defense_area_label(coherent_overall_defense_score(analysis)),
        "explanation_clarity": _defense_area_label(int(analysis.get("explanation_clarity_score") or 0)),
        "ownership_signal": _defense_area_label(int(analysis.get("ownership_signal_score") or 0)),
        "technical_depth": _defense_area_label(int(analysis.get("technical_depth_score") or 0)),
        "consistency_with_evidence": _defense_area_label(int(analysis.get("consistency_with_evidence_score") or 0)),
        "risk_flags": [str(s) for s in (analysis.get("risk_flags") or [])],
        "recruiter_summary": str(analysis.get("recruiter_summary") or ""),
        "recommended_improvements": [str(s) for s in (analysis.get("recommended_improvements") or [])],
        # Preserve the stored status verbatim — never manufacture "clean" for a row
        # that has no explicit status. A missing / None / empty status must reach
        # the public builder as-is so its fail-closed privacy gate
        # (``defense_privacy_is_clean``) treats a legacy or malformed analysis as
        # NOT shareable rather than publishing its transcript-derived summary.
        "privacy_scan_status": str(analysis.get("privacy_scan_status") or ""),
    }


# Cap the owner-visible answer evidence cards so a corrupt/inflated telemetry
# blob cannot balloon the report payload.
_MAX_ANSWER_EVIDENCE_CARDS = 20

# Privacy statuses under which an answer object's summary is safe to render on the
# owner card. Anything else (a flagged / redacted / sensitive scan, an unknown or
# empty legacy status) is treated as privacy-flagged and its summary is
# neutralized — the owner still learns privacy was flagged, but no raw PII is
# retained in a field named "safe".
_ANSWER_PRIVACY_CLEAN_STATUSES = frozenset({"clean"})

# Neutral notice shown in place of a privacy-flagged / sensitive answer summary
# on the owner card. It never echoes the raw content or the internal scan status.
_ANSWER_SUMMARY_WITHHELD = (
    "Answer summary withheld because privacy review flagged sensitive content."
)

# Defense-in-depth PII backstop for the owner-visible summary. The raw-transcript
# sanitizer that produced ``safe_answer_summary`` only strips paths / URLs /
# tokens / env pairs — it leaves SSN- and payment-card-shaped values intact — so
# even a summary whose object status looks clean is neutralized if it still
# carries such a value. SSN allows space/hyphen separators; the digit-run pattern
# is a separator-tolerant 13-19 digit (card-shaped) candidate.
_ANSWER_SUMMARY_SSN_RE = re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b")
_ANSWER_SUMMARY_CARD_RE = re.compile(r"\d(?:[ \t\-]*\d){12,18}")


def _answer_summary_privacy_flagged(item: dict[str, Any], summary_text: str) -> bool:
    """``True`` when an answer object's summary must be neutralized on the owner card.

    Flagged when the object's privacy scan is not explicitly clean, or when the
    summary text still carries an SSN- / payment-card-shaped value (defense in
    depth). A contradiction alone is NOT a privacy flag: a contradicted-but-clean
    answer keeps its summary so the owner can review it.
    """
    status = str(item.get("privacy_status") or "").strip().lower()
    if status not in _ANSWER_PRIVACY_CLEAN_STATUSES:
        return True
    if _ANSWER_SUMMARY_SSN_RE.search(summary_text):
        return True
    if _ANSWER_SUMMARY_CARD_RE.search(summary_text):
        return True
    return False


def _repo_analysis_row(db: Any, project_ids: list[str]) -> dict[str, Any] | None:
    """The project's stored ``vbr_repo_analyses`` row, if any.

    The only candidate↔artifact attribution evidence the platform stores
    (``authorship_match_pct`` / ``fork`` / ``facts``) — the placeholder
    ingestion writes ``None`` values, so ownership stays statement-derived
    until real, identity-verified ingestion exists. Best-effort: any lookup
    problem returns ``None`` (ownership then derives from statements alone).
    """
    for project_id in project_ids or []:
        try:
            if isinstance(db, dict):
                row = next(
                    (
                        r
                        for r in db.get("vbr_repo_analyses", {}).values()
                        if str(r.get("project_id") or "") == str(project_id)
                    ),
                    None,
                )
            else:
                result = (
                    db.table("vbr_repo_analyses")
                    .select("project_id, fork, authorship_match_pct, computed_at")
                    .eq("project_id", str(project_id))
                    .limit(1)
                    .execute()
                )
                rows = getattr(result, "data", []) or []
                row = rows[0] if rows else None
        except Exception:  # pragma: no cover - attribution lookup is additive
            row = None
        if isinstance(row, dict):
            return row
    return None


def _report_safe_answer_evidence(items: Any) -> list[dict[str, Any]]:
    """Project stored ``telemetry.defense_answer_evidence`` to owner-safe cards.

    The stored objects are already built from safe inputs (deterministic
    question text, sanitized answer snippets, fixed taxonomies), but the report
    re-projects them through an allowlist anyway (defence in depth): bounded
    text, score fragments scrubbed, unknown keys dropped. The owner card keeps
    ``question_id`` (the owner already sees question IDs in
    ``defense_questions``); the public surface strips it separately.
    """
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items[:_MAX_ANSWER_EVIDENCE_CARDS]:
        if not isinstance(item, dict):
            continue
        raw_summary = str(item.get("safe_answer_summary") or "")
        # A privacy-flagged / sensitive answer summary is neutralized even on the
        # private owner card — a field named "safe" must never retain raw PII.
        if _answer_summary_privacy_flagged(item, raw_summary):
            safe_answer_summary = _ANSWER_SUMMARY_WITHHELD
        else:
            safe_answer_summary = _trace_text(_scrub_score_fragments(raw_summary))
        out.append(
            {
                "evidence_id_safe": str(item.get("evidence_id_safe") or f"defense-answer-{len(out) + 1}"),
                "question_id": str(item["question_id"]) if item.get("question_id") else None,
                "question_kind": str(item.get("question_kind") or "unknown_or_generic"),
                "question_text": _trace_text(_scrub_score_fragments(str(item.get("question_text") or ""))),
                "target_ref_kind": str(item["target_ref_kind"]) if item.get("target_ref_kind") else None,
                "target_ref_label_safe": (
                    _trace_text(str(item["target_ref_label_safe"]), 120)
                    if item.get("target_ref_label_safe")
                    else None
                ),
                "project_title": _trace_text(str(item.get("project_title") or ""), 200),
                "mapped_skill": str(item["mapped_skill"]) if item.get("mapped_skill") else None,
                "claim_type": str(item.get("claim_type") or "project_architecture"),
                "answer_purpose": str(item.get("answer_purpose") or "unknown_or_generic"),
                "evidence_role": str(item.get("evidence_role") or "insufficient_or_generic"),
                "qualitative_status": str(item.get("qualitative_status") or "Not explained"),
                "safe_answer_summary": safe_answer_summary,
                "evidence_basis_chips": [str(c) for c in (item.get("evidence_basis_chips") or [])][:8],
                "corroborates_github": bool(item.get("corroborates_github")),
                "corroborates_website": bool(item.get("corroborates_website")),
                "corroborates_document": bool(item.get("corroborates_document")),
                "contradiction_flag": bool(item.get("contradiction_flag")),
                # Closed-vocabulary ownership stance (candidate attribution input).
                "ownership_stance": (
                    str(item.get("ownership_stance"))
                    if str(item.get("ownership_stance") or "") in ("affirmed", "denied", "mixed", "none")
                    else "none"
                ),
                "limitation": _trace_text(str(item.get("limitation") or "")),
                "public_shareable": bool(item.get("public_shareable")),
                "privacy_status": str(item.get("privacy_status") or "unknown"),
            }
        )
    return out


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


def _project_repo_identities(
    project: dict[str, Any], github_proof: dict[str, Any] | None
) -> set[str]:
    """Resolved ``owner/name`` repo identities this project points at.

    Collapses every repo reference available on the project (its own
    ``repo_full_name`` / ``repo_url``) and its attached GitHub Proof
    (``repo_url`` or ``repo_owner``/``repo_name``) into normalized identities via
    :func:`repo_identity`. These are used ONLY to CORRELATE canonical GitHub code
    evidence to this project — never as evidence themselves. An empty set means
    the repo is ambiguous, so Smart GitHub evidence conservatively maps nothing.
    """
    gp = github_proof or {}
    owner = str(gp.get("repo_owner") or "").strip()
    name = str(gp.get("repo_name") or "").strip()
    candidates = [
        project.get("repo_full_name"),
        project.get("repo_url"),
        gp.get("repo_url"),
        f"{owner}/{name}" if owner and name else None,
    ]
    return {rid for rid in (repo_identity(c) for c in candidates) if rid}


def _collect_github_smart_supported_skills(
    db: Any,
    user_id: str,
    *,
    project_repo_ids: set[str],
    claimed_skills: list[str],
) -> set[str]:
    """Normalized CLAIMED-skill names backed by real Smart GitHub code evidence.

    Bridges the canonical GitHub skill-evidence engine
    (:func:`collect_canonical_github_skill_evidence` → the ``skill_evidence`` rows
    the older GitHub Portfolio & Proof scanner persisted with exact file/line
    locators) into the Project Report's per-skill supporting-source decision, so a
    skill can earn "GitHub Proof" from analyzed code even when it is absent from
    the attached GitHub Proof's ``detected_skills``.

    Strict, conservative matching — a claimed skill is returned ONLY when a
    canonical GitHub *source-code* row exists that satisfies ALL of:

    * it is genuine analyzed code evidence — every row from the canonical
      collector carries a repo-relative ``file_path`` (repo metadata / a bare
      repo URL / ``repo_full_name`` / a source count can never produce one);
    * its repository identity (``owner/name``) matches one of THIS project's
      ``project_repo_ids`` — evidence from an unrelated repo never maps, and an
      ownerless / ambiguous row (empty ``repo_id``) is dropped;
    * its skill matches a skill THIS project actually CLAIMS (by raw or canonical
      name) — evidence for a skill the project never claimed can never spray
      GitHub Proof onto other claimed skills.

    Returns ``set()`` when the repo is ambiguous (no ``project_repo_ids``), when
    there are no claimed skills, or when nothing matches — so the caller never
    manufactures GitHub Proof from project metadata alone.
    """
    if not project_repo_ids or not claimed_skills:
        return set()

    # Each claimed skill, indexed by the keys a canonical row could match it by.
    claimed_by_norm: dict[str, str] = {}
    claimed_by_canon: dict[str, str] = {}
    for skill in claimed_skills:
        norm = _norm(skill)
        if not norm:
            continue
        claimed_by_norm.setdefault(norm, skill)
        claimed_by_canon.setdefault(_norm(canonical_skill(skill)), skill)

    supported: set[str] = set()
    try:
        evidence = collect_canonical_github_skill_evidence(db, user_id)
    except Exception:  # pragma: no cover - Smart GitHub bridge is best-effort
        return set()
    for ev in evidence:
        # Ownerless / unrelated-repo evidence never maps to this project.
        if not ev.repo_id or ev.repo_id not in project_repo_ids:
            continue
        # Map the row's skill onto a skill THIS project claims (raw or canonical).
        match = claimed_by_norm.get(ev.skill_key) or claimed_by_canon.get(
            _norm(ev.canonical_skill_name)
        )
        if match is not None:
            supported.add(_norm(match))
    return supported


def _collect_github_smart_project_evidence_count(
    db: Any, user_id: str, *, project_repo_ids: set[str]
) -> int:
    """Count canonical Smart GitHub code-evidence rows belonging to THIS project.

    Counts every canonical ``skill_evidence`` row whose repository identity
    matches one of ``project_repo_ids`` — regardless of whether its skill is
    claimed on the project. Each canonical row carries a real repo-relative
    ``file_path`` by construction, so this can only ever count genuine analyzed
    source-code evidence (never repo metadata / a bare repo URL). Used solely to
    decide whether REAL unmapped GitHub proof exists for the private
    ``real_unmapped_proof_context`` layer; it never creates a skill row.
    """
    if not project_repo_ids:
        return 0
    try:
        evidence = collect_canonical_github_skill_evidence(db, user_id)
    except Exception:  # pragma: no cover - Smart GitHub bridge is best-effort
        return 0
    return sum(1 for ev in evidence if ev.repo_id and ev.repo_id in project_repo_ids)


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
    document_supported_skills: set[str],
    pipeline_lookup: dict[str, dict[str, Any]],
    video_chips: list[dict[str, Any]],
    github_smart_skills: set[str] | None = None,
) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    # Canonical source labels that contributed evidence for this skill, in a
    # stable recruiter-facing order. Used to render the per-skill "supporting
    # evidence" chips in the skill evidence matrix.
    supporting_sources: list[str] = []
    normalized = _norm(skill)

    # Project Defense is explanation/corroboration evidence: on its own it can
    # at most PARTIALLY demonstrate a skill (a targeted, well-explained answer)
    # and never marks an implementation-heavy claim "Demonstrated" without
    # artifact evidence. A bare keyword mention is only weak supporting context.
    if analysis is not None:
        explained_well = {_norm(s) for s in analysis.get("skills_explained_well") or []}
        mentioned = {_norm(s) for s in analysis.get("skills_mentioned") or []}
        if normalized in explained_well:
            candidates.append(
                (
                    _PARTIALLY_DEMONSTRATED,
                    "Project Defense explanation supports this skill claim "
                    "(explanation evidence, not implementation proof).",
                )
            )
            supporting_sources.append(_SRC_DEFENSE)
        elif normalized in mentioned:
            candidates.append(
                (
                    _SUPPORTING_EVIDENCE,
                    "Mentioned during the Project Defense, but not explained through "
                    "a targeted defense answer.",
                )
            )
            supporting_sources.append(_SRC_DEFENSE)

    # GitHub Proof is earned two conservative ways, either of which is real
    # analyzed code evidence (never repo metadata / a bare repo URL / a source
    # count): the attached GitHub Proof's own ``detected_skills`` (legacy path),
    # OR a canonical Smart GitHub code-evidence row (exact file/line locators the
    # Portfolio & Proof scanner persisted) that matches THIS project's repo AND
    # this claimed skill. The note stays honest about which path supported it.
    smart_skills = github_smart_skills or set()
    if normalized in github_detected_skills or normalized in smart_skills:
        github_note = (
            "Backed by analyzed GitHub code evidence located in this project's repository."
            if normalized in smart_skills
            else "Detected in the attached GitHub Proof."
        )
        candidates.append((_SUPPORTING_EVIDENCE, github_note))
        supporting_sources.append(_SRC_GITHUB)

    if normalized in website_supported_skills:
        candidates.append((_SUPPORTING_EVIDENCE, "Supported by the attached Website Proof."))
        supporting_sources.append(_SRC_WEBSITE)

    # Document Proof is conservative supporting evidence and is only attached to a
    # skill the analyzer explicitly matched in the document (never to every
    # claimed skill). Keeping this in lockstep with the document evidence trace
    # guarantees the matrix row and the trace agree.
    if normalized in document_supported_skills:
        candidates.append(
            (_SUPPORTING_EVIDENCE, "Supported by an attached Document Proof referencing this skill.")
        )
        supporting_sources.append(_SRC_DOCUMENT)

    pipeline = pipeline_lookup.get(normalized)
    if pipeline is not None:
        label, note = _PIPELINE_SUPPORT_STATUS_LABELS.get(
            pipeline["support_status"], (_SUPPORTING_EVIDENCE, "Supported by evidence saved to your Skill Graph.")
        )
        candidates.append((label, note))

    if not candidates:
        candidates.append((_NOT_ASSESSED, "No evidence has been reviewed for this skill yet."))

    chip_count = _evidence_chip_count_for_skill(skill, video_chips)
    if chip_count > 0 and _SRC_VIDEO not in supporting_sources:
        supporting_sources.append(_SRC_VIDEO)

    best_status, best_note = min(candidates, key=lambda c: _STATUS_RANK[c[0]])

    # Per-skill limitations keep the matrix honest: a weakly evidenced skill is
    # flagged as a pending claim rather than presented as proven.
    limitations: list[str] = []
    if best_status in {_NEEDS_REVIEW, _NOT_ASSESSED}:
        limitations.append(_SKILL_UNEVIDENCED_LIMITATION)
    # Defense-only support (no GitHub/Website/Document artifact and no Skill
    # Graph pipeline) is honest about the missing implementation evidence.
    if _SRC_DEFENSE in supporting_sources and pipeline is None and not (
        set(supporting_sources) & {_SRC_GITHUB, _SRC_WEBSITE, _SRC_DOCUMENT}
    ):
        limitations.append(MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION)

    # De-dupe while preserving the canonical order above.
    ordered_sources = [
        src
        for src in (_SRC_GITHUB, _SRC_WEBSITE, _SRC_DEFENSE, _SRC_VIDEO, _SRC_DOCUMENT)
        if src in supporting_sources
    ]

    return {
        "skill": skill,
        "status": best_status,
        "evidence_chip_count": chip_count,
        "notes": best_note,
        "supporting_sources": ordered_sources,
        "limitations": limitations,
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


# NOTE: ``_safe_code_snippet``, ``_safe_commit_sha`` and ``_is_strong_code_snippet``
# now live in ``github_skill_evidence_service`` (the canonical, shared GitHub
# skill-evidence filter) and are imported above as aliases, so the VBR Project
# Report and the Work Passport Skill Report downgrade weak GitHub line evidence
# (imports, sys.path/setup, package/README/metadata, notebook markdown/prose)
# with exactly the same logic.


def _github_code_evidence(db: Any, github_proof: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Recover safe file/line/function GitHub evidence for the attached proof.

    The GitHub Proof analyzer records deep, line-level evidence
    (``skill_code_evidence``: ``{skill, file_path, line_start, line_end,
    code_snippet, github_url, function_name?}``) inside the proof's
    ``analysis_snapshot``. The attach-time summary only carries repo-relative
    file paths, so we re-read the live proof here at report-build time to
    surface exact line ranges / functions instead of a coarse repo-level card.

    Only the safe subset is returned — repo-relative file paths (no absolute
    URLs / traversal), integer line ranges, a bounded score-scrubbed snippet,
    an optional function name, and a public ``…/blob/…#L`` link (only when it is
    a safe public github.com URL). Any lookup problem returns ``[]`` so the
    report honestly falls back to file-level / repo-level GitHub traces.
    """
    if not isinstance(github_proof, dict):
        return []
    proof_id = github_proof.get("github_proof_id") or github_proof.get("id")
    if not proof_id:
        return []
    try:
        if isinstance(db, dict):
            row = db.get(_GITHUB_PROOFS_TABLE, {}).get(str(proof_id))
        else:
            result = (
                db.table(_GITHUB_PROOFS_TABLE)
                .select("analysis_snapshot")
                .eq("id", str(proof_id))
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - code evidence is best-effort
        return []
    if not isinstance(row, dict):
        return []
    snapshot = row.get("analysis_snapshot")
    if not isinstance(snapshot, dict):
        return []
    raw_items = snapshot.get("skill_code_evidence")
    if not isinstance(raw_items, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, Any, Any]] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        # Reject absolute / local / Windows / UNC / file:// / traversal paths
        # outright — never lstrip("/") an absolute path into a fake repo-relative
        # one that would leak a private filesystem location into a public link.
        file_path = safe_repo_relative_path(item.get("file_path"))
        if not skill or not file_path:
            continue

        def _line(value: Any) -> int | None:
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value if value > 0 else None
            if isinstance(value, str) and value.isdigit():
                n = int(value)
                return n if n > 0 else None
            return None

        line_start = _line(item.get("line_start"))
        line_end = _line(item.get("line_end"))
        function_name = str(item.get("function_name") or "").strip() or None

        key = (_norm(skill), file_path, line_start, line_end)
        if key in seen:
            continue
        seen.add(key)

        github_url = str(item.get("github_url") or "").strip() or None
        if github_url and (not is_safe_public_url(github_url) or "github.com" not in github_url):
            github_url = None

        raw_snippet = str(item.get("code_snippet") or "")
        out.append(
            {
                "skill": skill,
                "file_path": file_path,
                "line_start": line_start,
                "line_end": line_end,
                "function_name": function_name,
                "code_snippet": _safe_code_snippet(raw_snippet),
                "commit_sha": _safe_commit_sha(item.get("commit_sha")),
                "github_url": github_url,
                # Strength ranking (internal): only "strong" snippets are promoted
                # to line-level traces; "weak" ones (import/setup/comment-only or
                # notebook markdown) fall back to the repo-level card.
                "evidence_strength": (
                    "strong" if _is_strong_code_snippet(file_path, raw_snippet, function_name) else "weak"
                ),
            }
        )
        if len(out) >= 40:
            break
    return out


# ── Evidence traceability (claim → evidence → source → safe link) ────────────
#
# Each evidence trace ties one concrete, already-sanitized evidence source to
# the skills it supports, with a safe explanation, an in-page anchor, and — only
# when the target is genuinely public — a directly-openable link. Traces are the
# recruiter-readable audit trail behind the qualitative skill labels. They are
# built ONLY from summary fields (never raw transcripts/docs/snapshots/media).

_PRIVATE_DOC_NOTE = "Private document retained in student evidence vault; only a safe summary is shown."
_DOC_LIMITATION = (
    "Recruiter can see the summarized evidence; the original private document is not publicly exposed."
)
# Used when a document was attached but the analyzer matched no specific skill in
# it: it is shown as project-level context only and never implies a skill claim.
_DOC_PROJECT_LIMITATION = (
    "Document evidence was attached as project context but not mapped to specific skills."
)
_DEFENSE_LIMITATION = "Self-explanation evidence; should be combined with artifact evidence."
_WEBSITE_LIMITATION = (
    "Demonstrates the deployed behaviour at check time; it is not a guarantee of ongoing "
    "uptime or of sole authorship."
)
# Website artifact cards (DOM/OCR/visual/NLP/workflow) confirm observed behaviour
# at inspection time — they are never proof of source-code authorship.
_WEBSITE_BEHAVIOUR_LIMITATION = (
    "Website proof confirms observed behaviour at inspection time, not source-code authorship."
)
_WEBSITE_ARTIFACT_NOTE = (
    "Captured during the proof session; only a safe summary is shown — never the raw DOM, OCR, "
    "screenshots, or provider payloads."
)
# Website Proof is attached but the saved artifact mapped it to no specific skill —
# it is honest project-level context, never a per-skill claim.
_WEBSITE_NO_SKILLS_LIMITATION = (
    "Website Proof is attached and available as project-level evidence, but it is not mapped to "
    "specific skills because the saved Website Proof has no supported_skills."
)
# Website Proof is attached but the saved artifact carried no safe deeper summaries
# (live check / workflow / DOM / OCR / vision / NLP) to surface.
_WEBSITE_NO_SUMMARY_LIMITATION = (
    "Website Proof is attached, but no safe OCR/DOM/vision/NLP summaries were available in the "
    "saved proof artifact."
)
_VIDEO_LIMITATION = (
    "A short timestamped moment; it corroborates the explanation but does not independently prove authorship."
)


def _trace_text(text: Any, limit: int = 240) -> str:
    """Collapse whitespace and cap length for a safe one/two-sentence summary."""
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _humanize_list(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _document_skill_locators(db: Any, user_id: str, doc_id: str) -> dict[str, dict[str, Any]]:
    """Re-read a document's structured evidence to recover safe per-skill locators.

    Returns ``{normalized_skill: {"page_number": int|None, "snippet": str|None}}``
    built ONLY from the analyzer's structured ``evidence_objects`` (matched skill
    name + page number + the short excerpt the analyzer already extracted). The
    snippet is bounded and score-scrubbed; raw document text, file paths and
    storage locators are never read. Document snippets are intentionally NOT
    persisted into ``vbr_projects.metadata`` (privacy), so they are recovered
    here at report-build time and stripped again on the public surface.

    Any lookup problem returns ``{}`` so the report falls back to a safe,
    locator-free document trace rather than failing.
    """
    if not doc_id:
        return {}
    try:
        from app.services.optional_evidence_service import OptionalEvidenceService

        row = OptionalEvidenceService(db).get_by_id(user_id=user_id, evidence_id=doc_id)
    except Exception:  # pragma: no cover - document locators are best-effort
        return {}
    if not isinstance(row, dict):
        return {}
    from app.services.canonical_evidence_service import document_evidence_object_has_locator

    def _rank(item: dict[str, Any]) -> int:
        # Prefer an exact page, then a typed block (table/chart/diagram/code/…),
        # then any real section heading, over a bare keyword match.
        if item.get("page_number") is not None:
            return 0
        if str(item.get("block_type") or "").strip().lower() not in ("", "paragraph", "heading"):
            return 1
        if document_evidence_object_has_locator(item):
            return 2
        return 3

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in row.get("evidence_objects") or []:
        if not isinstance(item, dict):
            continue
        key = _norm(str(item.get("skill_name") or "").strip())
        if key:
            grouped.setdefault(key, []).append(item)
    out: dict[str, dict[str, Any]] = {}
    for key, items in grouped.items():
        item = min(items, key=_rank)
        page = item.get("page_number")
        snippet = _trace_text(_scrub_score_fragments(str(item.get("snippet") or "")), 200) or None
        # A safe document citation: the section heading the analyzer matched the
        # skill under (e.g. "Methods", "System Design"). This is a structural
        # reference, never raw body text, so it is safe on the public surface.
        # Default paragraph styles ("Normal") are layout names, not locators.
        raw_section = str(item.get("section_label") or "").strip()
        if raw_section.lower() in ("normal", "body text", "default", "default paragraph font"):
            raw_section = ""
        section = _trace_text(raw_section, 80) or None
        out[key] = {
            "page_number": int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None,
            "snippet": snippet,
            "citation": section,
            # Source-native block locator (block-aware extraction; None on
            # pre-block documents).
            "block_type": str(item.get("block_type") or "").strip().lower() or None,
            "block_index": item.get("block_index"),
            "table_cells": [
                [str(cell)[:80] for cell in row_cells][:6]
                for row_cells in (item.get("table_cells") or [])[:8]
                if isinstance(row_cells, list)
            ],
            "visual_description": _trace_text(str(item.get("visual_description") or ""), 200) or None,
            "nearby_caption": _trace_text(str(item.get("nearby_caption") or ""), 200) or None,
            "figure_reference": _trace_text(str(item.get("figure_reference") or ""), 60) or None,
            "has_exact_locator": document_evidence_object_has_locator(item),
        }
    return out


# Honest not-retained explanation for the owner-only original-document access
# descriptor (mirrors the vault's retention copy).
_DOC_ORIGINAL_NOT_RETAINED_NOTE = (
    "The original document file was not retained — only verified excerpts and "
    "locators are stored, so there is no file to open or download."
)


def _document_original_access(db: Any, user_id: str, doc_id: str) -> dict[str, Any]:
    """Owner-only access descriptor for a document's RETAINED original file.

    Built for the PRIVATE student report only — ``user_id`` is the already
    ownership-checked project owner, and the artifact is re-gated here through
    ``can_access_artifact`` (defence in depth). The descriptor carries the
    opaque artifact id plus the access-gated view/download API routes, which
    re-check ownership on every request — never a storage path, bucket, or
    signed URL. Fails closed to an honest ``available=False`` state when no
    retained original exists (older uploads / retention storage unavailable).
    The public report builder strips this descriptor entirely.
    """
    unavailable: dict[str, Any] = {
        "available": False,
        "artifact_id": None,
        "file_name": None,
        "mime_type": None,
        "size_bytes": None,
        "page_count": None,
        "open_path": None,
        "download_path": None,
        "note": _DOC_ORIGINAL_NOT_RETAINED_NOTE,
    }
    if not doc_id:
        return unavailable
    try:
        from app.services import proof_artifact_service

        rows = proof_artifact_service.list_artifacts_for_proof(
            db, proof_type="document", proof_id=doc_id, artifact_type="document_original"
        )
        accessible = [r for r in rows if proof_artifact_service.can_access_artifact(r, user_id)]
    except Exception:  # pragma: no cover - retention lookup is best-effort
        return unavailable
    if not accessible:
        return unavailable
    artifact = accessible[-1]
    artifact_id = str(artifact.get("id") or "")
    if not artifact_id:
        return unavailable
    return {
        "available": True,
        "artifact_id": artifact_id,
        "file_name": artifact.get("file_name"),
        "mime_type": artifact.get("mime_type"),
        "size_bytes": artifact.get("size_bytes"),
        "page_count": artifact.get("page_count"),
        "open_path": f"/api/v1/proofs/artifacts/{artifact_id}/view",
        "download_path": f"/api/v1/proofs/artifacts/{artifact_id}/download",
        "note": None,
    }


_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"


def _defense_answer_excerpts(db: Any, session_id: str) -> dict[str, str]:
    """Map ``question_id`` → a bounded, sanitized excerpt of the student's answer.

    Defense answers are stored as ``vbr_transcript_segments`` (each carrying the
    answering ``question_id`` and the answer ``text``). We surface only a short,
    score-scrubbed excerpt of the candidate's *own* answer for the private/student
    report — never the full transcript. The public surface strips ``answer_excerpt``
    entirely. Any lookup problem returns ``{}`` (honest fallback to no excerpt).
    """
    if not session_id:
        return {}
    try:
        if isinstance(db, dict):
            transcript_ids = {
                str(r["id"])
                for r in db.get(_TRANSCRIPTS_TABLE, {}).values()
                if str(r.get("session_id")) == session_id and r.get("id")
            }
            segments = [
                r
                for r in db.get(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
                if str(r.get("transcript_id")) in transcript_ids
            ]
        else:
            tx = db.table(_TRANSCRIPTS_TABLE).select("id").eq("session_id", session_id).execute()
            transcript_ids = [str(r["id"]) for r in (getattr(tx, "data", []) or []) if r.get("id")]
            segments = []
            for tid in transcript_ids:
                seg = (
                    db.table(_TRANSCRIPT_SEGMENTS_TABLE)
                    .select("question_id,text")
                    .eq("transcript_id", tid)
                    .execute()
                )
                segments.extend(getattr(seg, "data", []) or [])
    except Exception:  # pragma: no cover - answer excerpts are best-effort
        return {}

    out: dict[str, str] = {}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        qid = seg.get("question_id")
        if not qid or str(qid) in out:
            continue
        excerpt = _trace_text(_scrub_score_fragments(str(seg.get("text") or "")), 200)
        if excerpt:
            out[str(qid)] = excerpt
    return out


def _slugify(text: str, max_len: int = 48) -> str:
    """Lowercase, hyphenated, filesystem/anchor-safe slug of ``text``.

    Used to derive *unique, stable* evidence anchors from concrete locators
    (a file path, a matched skill + page, a timestamp) so a trace card id never
    collapses onto a coarse, duplicate anchor like ``github-proof``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:max_len].strip("-")


def _blob_url(repo_url: str | None, branch: str | None, file_path: str) -> str | None:
    """Build a public ``…/blob/<branch>/<path>`` link for a public GitHub repo.

    Returns ``None`` unless the repo URL is a safe public github.com target, so
    a private/internal repo file is never advertised as openable.

    The ``file_path`` is routed through :func:`safe_repo_relative_path` (the same
    gate as :func:`build_github_line_url`) so an absolute / local / Windows /
    UNC / ``file://`` / traversal / encoded-traversal path is *rejected* — never
    ``lstrip("/")``-ed into a fake repo-relative link that leaks a developer's
    private filesystem into public output.
    """
    base = str(repo_url or "").rstrip("/")
    if not base or not is_safe_public_url(base) or "github.com" not in base:
        return None
    clean_path = safe_repo_relative_path(file_path)
    if not clean_path:
        return None
    ref = (str(branch or "").strip() or "HEAD")
    return f"{base}/blob/{ref}/{clean_path}"


def _safe_domain(url: str) -> str | None:
    """Return just the host of a safe public URL (e.g. ``example.com``).

    Used as a short, recruiter-safe location label for Website Proof traces.
    Returns ``None`` when the host cannot be parsed.
    """
    try:
        from urllib.parse import urlparse

        host = urlparse(str(url or "")).hostname
    except Exception:  # pragma: no cover - defensive
        return None
    return host or None


def _build_evidence_traces(
    *,
    github_proof: dict[str, Any] | None,
    github_code_evidence: list[dict[str, Any]],
    repo_full_name: str | None,
    repo_url: str | None,
    repo_is_public: bool,
    documents: list[dict[str, Any]],
    website_proofs: list[dict[str, Any]],
    website_details: dict[str, dict[str, Any]],
    website_mapped_skills_by_session: dict[str, list[str]] | None = None,
    analysis: dict[str, Any] | None,
    defense_questions: list[dict[str, Any]],
    video_chips: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Build the flat evidence-trace list and a normalized skill→trace-id map."""
    traces: list[dict[str, Any]] = []
    by_skill: dict[str, list[str]] = {}

    def _attach(trace: dict[str, Any]) -> None:
        # The in-page anchor is always derived from the trace id with a stable
        # "trace-" prefix so a trace card id can never collide with a coarse
        # evidence *section* id in the report UI (e.g. the "github-proof" or
        # "project-defense" section headers). A matrix link therefore always
        # lands on the precise trace card, never the section above it.
        trace["evidence_anchor"] = f"trace-{trace['trace_id']}"
        traces.append(trace)
        for skill in trace["skill_names"]:
            key = _norm(skill)
            if not key:
                continue
            ids = by_skill.setdefault(key, [])
            if trace["trace_id"] not in ids:
                ids.append(trace["trace_id"])

    collect_github_proof_traces(
        _attach,
        github_proof=github_proof,
        github_code_evidence=github_code_evidence,
        repo_full_name=repo_full_name,
        repo_url=repo_url,
        repo_is_public=repo_is_public,
    )

    collect_document_proof_traces(_attach, documents=documents)

    # ── Website Proof ────────────────────────────────────────────────────────
    collect_website_proof_traces(
        _attach,
        website_proofs=website_proofs,
        website_details=website_details,
        mapped_skills_by_session=website_mapped_skills_by_session,
    )

    collect_project_defense_traces(
        _attach, analysis=analysis, defense_questions=defense_questions
    )

    collect_video_evidence_traces(_attach, video_chips=video_chips)

    return traces, by_skill


# ── Per-source evidence adapters ─────────────────────────────────────────────
#
# Each ``collect_*`` adapter reads ONE already-saved proof source's output and
# normalizes it into VBR evidence-trace cards via the shared ``attach`` callback
# (which assigns the stable ``trace-`` anchor and maps the trace to its skills).
# These adapters are aggregators/normalizers/sanitizers — they never re-run an
# analyzer or invent evidence; they only project what the upstream proof pipeline
# already stored. ``attach`` has the signature ``(trace: dict) -> None``.

_AttachFn = Any


def collect_github_proof_traces(
    attach: _AttachFn,
    *,
    github_proof: dict[str, Any] | None,
    github_code_evidence: list[dict[str, Any]],
    repo_full_name: str | None,
    repo_url: str | None,
    repo_is_public: bool,
) -> None:
    """Normalize stored GitHub Proof output into evidence traces.

    Reuses the GitHub Proof pipeline's saved ``detected_skills`` /
    ``evidence_files`` / ``analysis_snapshot.skill_code_evidence`` (already read
    into ``github_code_evidence``). Emits, in descending honesty order: a
    repo-level card, then one line/function-level card per stored
    ``skill_code_evidence`` item (with the analyzer's own ``commit_sha`` and
    ``…#L`` link when public), then file-level cards for any remaining
    ``evidence_files``. Line/function evidence is surfaced ONLY when the analyzer
    genuinely recorded it — never keyword-guessed inside VBR.
    """
    if github_proof is None:
        return
    detected = [str(s) for s in (github_proof.get("detected_skills") or [])]
    owner = github_proof.get("repo_owner")
    name = github_proof.get("repo_name")
    title = repo_full_name or (f"{owner}/{name}" if owner and name else None) or (repo_url or "GitHub repository")
    public_url = repo_url if (repo_is_public and is_safe_public_url(repo_url)) else None
    summary = _scrub_score_fragments(str(github_proof.get("public_safe_summary") or "")) or (
        "Repository analyzed; VeriBridge detected the skills below from its files and structure."
    )
    # Deepest honest GitHub granularity, in priority order:
    #   1. ``github_code_evidence`` — exact file + line range (+ optional
    #      function) the analyzer recorded, with a public ``…#L`` link. Emit
    #      one trace per code-evidence item.
    #   2. ``evidence_files`` — safe repo-relative paths only (file-level).
    #   3. repo-level only (the card above) when neither exists.
    # We never invent line numbers or functions — line-level traces appear
    # only when the analyzer genuinely recorded ``skill_code_evidence``.
    evidence_files = [str(f) for f in (github_proof.get("evidence_files") or []) if str(f).strip()]
    branch = github_proof.get("default_branch")

    # ── Strength gate: only genuine line-level code is promoted ──────────
    # Stored ``skill_code_evidence`` can pin weak lines (imports, sys.path /
    # repo-root bootstrap, comment-only blocks, notebook markdown narrative).
    # We surface line-level traces ONLY for strong snippets; skills whose ONLY
    # stored line evidence is weak fall back to this repo-level card and carry an
    # honest "stored proof lacked strong line-level evidence — reanalysis needed"
    # limitation rather than advertising imports as skill proof.
    strong_code = [c for c in github_code_evidence if c.get("evidence_strength") != "weak"]
    # For ML-style skills, surface the most meaningful pipeline code first
    # (training / preprocessing / model / predict / metrics / dataset) ahead of
    # generic helper lines. Neutral for every non-ML skill, so other skills keep
    # their stored order (stable sort).
    strong_code.sort(
        key=lambda c: _ml_pipeline_rank(
            str(c.get("skill") or ""),
            str(c.get("file_path") or ""),
            str(c.get("code_snippet") or ""),
            str(c.get("function_name") or "") or None,
        )
    )
    strong_skills = {_norm(str(c.get("skill") or "")) for c in strong_code}
    weak_only_skills = _dedupe_skill_names(
        [
            str(c.get("skill") or "")
            for c in github_code_evidence
            if c.get("evidence_strength") == "weak"
            and _norm(str(c.get("skill") or "")) not in strong_skills
            and str(c.get("skill") or "").strip()
        ]
    )

    repo_limitation = (
        "Repository-level analysis detected related files and structure, but this is not line-level "
        "proof and does not, by itself, prove the candidate personally authored every part."
    )
    if weak_only_skills:
        repo_limitation += (
            " Stored GitHub Proof did not contain strong line-level evidence for "
            f"{_humanize_list(weak_only_skills)} (only imports/setup or notebook narrative); "
            "reanalysis/backfill is needed for stronger code-level proof of "
            + ("these skills." if len(weak_only_skills) > 1 else "this skill.")
        )

    attach(
        {
            "trace_id": "github-proof",
            "source_type": _SRC_GITHUB,
            "source_title": title,
            "skill_names": detected,
            "qualitative_status": _SUPPORTING_EVIDENCE,
            "safe_summary": _trace_text(summary),
            "safe_detail": (
                "Static analysis of the repository detected files and structure consistent with these skills. "
                "This is repository-level evidence, not line-level authorship proof."
            ),
            "evidence_anchor": "github-proof",
            "location_type": "repo_level",
            "location_label": "repo-level",
            "location_detail": title,
            "public_url": public_url,
            "public_url_label": "View public repository" if public_url else None,
            "timestamp": None,
            "limitation": repo_limitation,
            "is_publicly_openable": bool(public_url),
            "private_evidence_note": (
                None if public_url else "Repository is private; only a recruiter-safe summary is shown."
            ),
            # Skills whose stored line evidence was too weak to display — surfaced
            # so the matrix/UI can flag them as needing reanalysis.
            "weak_line_evidence_skills": weak_only_skills,
        }
    )

    # ── Line/function-level GitHub code evidence (strong only) ───────────
    for code in strong_code:
        file_path = str(code.get("file_path") or "")
        if not file_path:
            continue
        line_start = code.get("line_start")
        line_end = code.get("line_end")
        function_name = code.get("function_name")
        commit_sha = code.get("commit_sha")
        code_skill = str(code.get("skill") or "")
        code_skills = [code_skill] if code_skill else detected
        # The analyzer's own ``…#L`` blob link is preferred (it already
        # anchors the exact lines); fall back to a file blob link. Both are
        # only surfaced for public repos.
        code_url = code.get("github_url") if public_url else None
        if not code_url and public_url:
            code_url = _blob_url(repo_url, branch, file_path)
            if code_url and line_start:
                code_url += f"#L{line_start}" + (f"-L{line_end}" if line_end and line_end != line_start else "")

        # Proof-native location label → "GitHub: function classify_image" /
        # "GitHub: lines 24-38" / "GitHub: <path>", in that priority.
        if function_name:
            location_type = "github_function"
            location_label = f"function {function_name}"
            anchor_seed = f"{file_path}-fn-{function_name}"
        elif line_start:
            location_type = "github_lines"
            location_label = f"lines {line_start}-{line_end}" if line_end and line_end != line_start else f"line {line_start}"
            anchor_seed = f"{file_path}-L{line_start}-{line_end}"
        else:
            location_type = "github_file"
            location_label = file_path
            anchor_seed = file_path

        range_phrase = (
            f"lines {line_start}-{line_end}"
            if line_start and line_end and line_end != line_start
            else (f"line {line_start}" if line_start else "")
        )
        where = (
            f"{file_path} ({range_phrase})" if range_phrase else file_path
        )
        attach(
            {
                "trace_id": f"github-code-{_slugify(anchor_seed)}",
                "source_type": _SRC_GITHUB,
                "source_title": f"{title} — {where}",
                "skill_names": code_skills,
                "qualitative_status": _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(
                    f"The analyzer located code in {where} as evidence for "
                    + (code_skill or "the skills below")
                    + (f" (pinned to commit {commit_sha[:7]})." if commit_sha else ".")
                ),
                "safe_detail": (
                    "Line-level code evidence: the analyzer matched skill-relevant code at this exact "
                    "location. The public link opens the file at these lines; this corroborates the skill "
                    "but is not, by itself, proof the candidate personally authored every line."
                ),
                "evidence_anchor": "",
                "location_type": location_type,
                "location_label": location_label,
                "location_detail": where,
                "file_path": file_path,
                "line_start": line_start,
                "line_end": line_end,
                "function_name": function_name,
                # The commit the analyzer pinned this evidence to — a safe hex
                # reference (no path/url/content), kept on the public surface.
                "commit_sha": commit_sha,
                # Snippet is from a public repo file; the public surface drops
                # it in favour of the public ``…#L`` link.
                "code_snippet": code.get("code_snippet"),
                "public_url": code_url,
                "public_url_label": "View code on GitHub" if code_url else None,
                "timestamp": None,
                "limitation": (
                    "Pinpoints skill-relevant code, but matching code at a location is not the same as "
                    "proving sole authorship; combine with the Project Defense for ownership context."
                ),
                "is_publicly_openable": bool(code_url),
                "private_evidence_note": (
                    None if code_url else "Repository is private; the code location is shown without a public link."
                ),
            }
        )

    # ── File-level GitHub evidence (fallback when no line-level data) ────
    code_evidence_files = {str(c.get("file_path") or "") for c in github_code_evidence}
    for file_path in evidence_files:
        # Skip files already covered by a richer line-level trace above.
        if file_path in code_evidence_files:
            continue
        file_url = _blob_url(repo_url, branch, file_path) if public_url else None
        attach(
            {
                # Unique, stable anchor derived from the concrete file path so
                # the matrix link lands on this exact file's card.
                "trace_id": f"github-file-{_slugify(file_path)}",
                "source_type": _SRC_GITHUB,
                "source_title": f"{title} — {file_path}",
                "skill_names": detected,
                "qualitative_status": _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(
                    f"The analyzer flagged {file_path} in the repository as evidence for the skills below."
                ),
                "safe_detail": (
                    "A specific repository file the analyzer identified as relevant to these skills. "
                    "This is file-level evidence; no line range was recorded for this file, so it is "
                    "not line-level authorship proof."
                ),
                "evidence_anchor": "",
                "location_type": "github_file",
                # Bare suffix — the UI renders it as "GitHub: <path>" (the
                # matrix-link label), matching the repo-level "repo-level".
                "location_label": file_path,
                "location_detail": file_path,
                "file_path": file_path,
                "public_url": file_url,
                "public_url_label": "View file on GitHub" if file_url else None,
                "timestamp": None,
                "limitation": (
                    "Identifies a relevant file, not the exact lines or author; combine with the Project "
                    "Defense for authorship context."
                ),
                "is_publicly_openable": bool(file_url),
                "private_evidence_note": (
                    None if file_url else "Repository is private; the file path is shown without a public link."
                ),
            }
        )


def collect_document_proof_traces(attach: _AttachFn, *, documents: list[dict[str, Any]]) -> None:
    """Normalize stored Document Proof ``evidence_objects`` into evidence traces.

    Documents are mapped ONLY to the skills the analyzer explicitly matched in
    them (``doc["skills"]``, already narrowed to claimed skills upstream) — never
    to every claimed skill. When a document matched no specific skill it is kept
    as project-level context (``skill_names: []``) so it can never imply that a
    skill was supported when the matrix row says otherwise.
    """
    for idx, doc in enumerate(documents, start=1):
        title = str(doc.get("title") or "Document")
        status_label = str(doc.get("status") or "analyzed")
        doc_skills = [str(s) for s in (doc.get("skills") or [])]
        locators = doc.get("skill_locators") or {}

        if not doc_skills:
            # Project-level context: no matched skill, so it never implies a claim.
            attach(
                {
                    "trace_id": f"document-proof-{idx}",
                    "source_type": _SRC_DOCUMENT,
                    "source_title": title,
                    "skill_names": [],
                    "qualitative_status": _SUPPORTING_EVIDENCE,
                    "safe_summary": _trace_text(
                        f"{title} ({status_label}) — attached as project context; not mapped to specific skills."
                    ),
                    "safe_detail": (
                        "The document provides written project context. It was not matched to specific claimed "
                        "skills, so it is shown as project-level evidence only and summarized rather than exposed."
                    ),
                    "evidence_anchor": "",
                    "location_type": "project_level",
                    "location_label": "project context",
                    "location_detail": None,
                    "public_url": None,
                    "public_url_label": None,
                    "timestamp": None,
                    "limitation": _DOC_PROJECT_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _PRIVATE_DOC_NOTE,
                    # Owner-only retained-original access (public builder blanks it).
                    "document_original": doc.get("original_document"),
                    "document_key": doc.get("document_key"),
                }
            )
            continue

        # One trace per matched skill so the matrix link lands on the exact
        # claim. When the analyzer recorded a safe page/snippet locator we surface
        # it ("Doc: Page 2" / "Doc: Snippet"); otherwise we honestly stay at
        # matched-skill granularity ("Doc: matched skill") with no invented page.
        for skill in doc_skills:
            loc = locators.get(_norm(skill)) or {}
            page = loc.get("page_number")
            snippet = loc.get("snippet")
            citation = loc.get("citation")
            block_type = str(loc.get("block_type") or "").strip().lower() or None
            block_label = (
                block_type.replace("_", " ").title()
                if block_type and block_type not in ("paragraph", "heading")
                else None
            )
            # Bare location labels — the UI renders these as "Doc: Page 2" /
            # "Doc: Citation" / "Doc: Snippet" / "Document" via ``matrixTraceLabel``.
            # Priority: page locator > typed block > section citation > snippet >
            # matched-skill.
            if page is not None:
                location_type = "document_page"
                location_label = f"Page {page}"
                location_detail = (
                    f"Page {page} · {block_label or citation}"
                    if (block_label or citation)
                    else f"Page {page}"
                )
            elif block_label:
                location_type = "document_block"
                location_label = block_label
                location_detail = f"{citation} · {block_label}" if citation else block_label
            elif citation:
                location_type = "document_citation"
                location_label = "Citation"
                location_detail = citation
            elif snippet:
                location_type = "document_snippet"
                location_label = "Snippet"
                location_detail = "Matched passage"
            else:
                location_type = "document"
                location_label = "matched skill"
                location_detail = None
            attach(
                {
                    "trace_id": f"document-{idx}-{_slugify(skill)}",
                    "source_type": _SRC_DOCUMENT,
                    "source_title": title,
                    "skill_names": [skill],
                    "qualitative_status": _SUPPORTING_EVIDENCE,
                    "safe_summary": _trace_text(
                        f"{title} ({status_label}) — a supporting document the analyzer matched to {skill}"
                        + (f" on page {page}." if page is not None else ".")
                    ),
                    "safe_detail": (
                        "The document was analyzed and references this skill; a safe excerpt/page is shown "
                        "for recruiters rather than the raw file. Document evidence supports but does not "
                        "independently prove implementation or authorship."
                    ),
                    "evidence_anchor": "",
                    "location_type": location_type,
                    "location_label": location_label,
                    "location_detail": location_detail,
                    "page_number": page,
                    "snippet": snippet,
                    "citation": citation,
                    # Source-native block locator fields (block-aware extraction).
                    "block_type": block_type,
                    "block_index": loc.get("block_index"),
                    "table_cells": loc.get("table_cells") or [],
                    "visual_description": loc.get("visual_description"),
                    "nearby_caption": loc.get("nearby_caption"),
                    "figure_reference": loc.get("figure_reference"),
                    "has_exact_locator": bool(loc.get("has_exact_locator")),
                    "public_url": None,
                    "public_url_label": None,
                    "timestamp": None,
                    "limitation": _DOC_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _PRIVATE_DOC_NOTE,
                    # Owner-only retained-original access (public builder blanks it).
                    "document_original": doc.get("original_document"),
                    "document_key": doc.get("document_key"),
                }
            )


def collect_website_proof_traces(
    attach: _AttachFn,
    *,
    website_proofs: list[dict[str, Any]],
    website_details: dict[str, dict[str, Any]],
    mapped_skills_by_session: dict[str, list[str]] | None = None,
) -> None:
    """Normalize stored Website Proof summaries/artifacts into evidence traces.

    Reuses the attach-time summary (target / evidence strength / workflow
    confidence) plus the deeper, already-sanitized artifact summaries hydrated by
    ``website_proof_detail_service`` (live check, workflow steps, DOM/OCR/visual/
    NLP summaries). Raw DOM/OCR/provider payloads, screenshots, frame/storage
    paths and signed URLs are never read here — only the safe summaries the
    Website Proof pipeline already produced.

    A trace card's ``skill_names`` come from ``mapped_skills_by_session`` — the
    CANONICAL Website→skill mapping (``map_website_supported_skills``) the report
    already computed for this proof, NOT the raw stored ``supported_skills``. The
    stored list is a hint only, so a trace card can never attribute Website Proof
    to a skill the observed behaviour did not actually support (keeping the
    trace cards in lockstep with the skill matrix's supporting-source chips).
    """
    mapped_by_session = mapped_skills_by_session or {}
    for idx, wp in enumerate(website_proofs, start=1):
        target = str(wp.get("target_website") or "")
        safe = is_safe_public_url(target)
        session_id = str(wp.get("proof_session_id") or "")
        # Canonical mapped skills for THIS proof (hint-only stored ``supported_skills``
        # never rides through as a per-skill trace attribution).
        supported = [str(s) for s in (mapped_by_session.get(session_id) or [])]
        confidence = str(wp.get("workflow_confidence") or "insufficient")
        detail = website_details.get(session_id) or {}
        retained = (
            detail.get("retained_artifacts")
            if isinstance(detail.get("retained_artifacts"), dict)
            else {}
        )
        timeline = [
            event
            for event in (detail.get("workflow_timeline") or [])
            if isinstance(event, dict) and event.get("description")
        ]
        first_timestamp = next(
            (event.get("timestamp_label") for event in timeline if event.get("timestamp_label")),
            None,
        )
        website_trace_fields = {
            "website_replay_available": bool(retained.get("recording_available")),
            "website_replay_path": retained.get("replay_path"),
            "website_artifact_id": retained.get("artifact_id"),
            "website_replay_duration_seconds": retained.get("duration_seconds"),
            "website_replay_mime_type": retained.get("mime_type"),
            "website_analysis_path": retained.get("analysis_path"),
            "website_timeline": timeline,
            "timestamp_label": first_timestamp,
        }

        # Whether the saved proof carried any deeper safe summary to surface as a
        # dedicated artifact card below (live check / workflow / DOM / OCR / vision
        # / NLP). When none exist the project-level card carries an honest
        # "no safe summaries were available" limitation instead of implying depth.
        has_safe_summary = bool(
            (isinstance(detail.get("live_check"), dict) and detail.get("live_check"))
            or detail.get("workflow_steps")
            or detail.get("dom_summary")
            or detail.get("ocr_summary")
            or detail.get("visual_summary")
            or detail.get("workflow_summary")
        )
        # Website Proof is ALWAYS surfaced as project-level evidence when attached,
        # even with empty ``supported_skills`` (empty ``skill_names`` ⇒ it maps to
        # no skill row, so it can never overstate a per-skill claim). The honest
        # limitation explains why it is project-level only / lacks deeper summaries.
        website_limitations: list[str] = []
        if not supported:
            website_limitations.append(_WEBSITE_NO_SKILLS_LIMITATION)
        if not has_safe_summary:
            website_limitations.append(_WEBSITE_NO_SUMMARY_LIMITATION)
        if not website_limitations:
            website_limitations.append(_WEBSITE_LIMITATION)

        if supported:
            web_summary = (
                f"A working deployment was inspected for the supported skills "
                f"(workflow confidence: {confidence})."
            )
        else:
            web_summary = (
                f"A working deployment was inspected and attached as project-level evidence "
                f"(workflow confidence: {confidence})."
            )

        attach(
            {
                "trace_id": f"website-proof-{idx}",
                "source_type": _SRC_WEBSITE,
                "source_title": target if safe else "Website Proof",
                "skill_names": supported,
                "qualitative_status": str(wp.get("evidence_strength") or _NOT_ASSESSED),
                "safe_summary": _trace_text(web_summary),
                "safe_detail": (
                    "The deployed site was checked for the supported skills' working behaviour at inspection time."
                    if supported
                    else "The deployed site was inspected and is attached as project-level evidence; the saved "
                    "proof did not map it to specific skills."
                ),
                "evidence_anchor": f"website-proof-{idx}",
                "location_type": "website_url" if safe else "website_proof",
                "location_label": "Live URL" if safe else "Proof",
                "location_detail": _safe_domain(target) if safe else None,
                "public_url": target if safe else None,
                "public_url_label": "Open live website" if safe else None,
                "timestamp": first_timestamp,
                "limitation": " ".join(website_limitations),
                "is_publicly_openable": safe,
                "private_evidence_note": (
                    None if safe else "Deployment URL is private or internal and is not publicly linked."
                ),
                **website_trace_fields,
            }
        )

        # ── Proof-native Website artifact cards (hydrated, safe summaries) ───
        # Each card surfaces one deeper saved artifact (live check, workflow
        # step, DOM/OCR/visual/NLP summary) when it exists upstream. The matrix
        # label reads "Website: <aspect>". Raw DOM/OCR/provider payloads are
        # never included — only the already-sanitized summaries.
        def _website_card(suffix: str, loc_type: str, label: str, summary: str, detail_text: str) -> None:
            attach(
                {
                    "trace_id": f"website-proof-{idx}-{suffix}",
                    "source_type": _SRC_WEBSITE,
                    "source_title": (target if safe else "Website Proof") + f" — {label}",
                    "skill_names": supported,
                    "qualitative_status": _EVIDENCE_OBSERVED,
                    "safe_summary": _trace_text(summary),
                    "safe_detail": detail_text,
                    "evidence_anchor": "",
                    "location_type": loc_type,
                    "location_label": label,
                    "location_detail": _safe_domain(target) if safe else None,
                    "public_url": None,
                    "public_url_label": None,
                    "timestamp": first_timestamp,
                    "limitation": _WEBSITE_BEHAVIOUR_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _WEBSITE_ARTIFACT_NOTE,
                    **website_trace_fields,
                }
            )

        live = detail.get("live_check") if isinstance(detail.get("live_check"), dict) else None
        if live:
            live_status = "reachable" if live.get("is_reachable") else "not reachable"
            bits = [f"Live check: the deployment was {live_status} at inspection time (confidence: {live.get('confidence')})."]
            if live.get("page_title"):
                bits.append(f"Page title: {live['page_title']}.")
            if live.get("summary"):
                bits.append(str(live["summary"]))
            _website_card(
                "live-check",
                "website_live_check",
                "Live check",
                " ".join(bits),
                "An automated reachability check of the deployed URL at inspection time.",
            )

        steps = [str(s) for s in (detail.get("workflow_steps") or []) if str(s).strip()]
        if steps:
            _website_card(
                "workflow",
                "website_workflow",
                "Workflow step",
                "Observed workflow: " + "; ".join(steps[:6]) + ".",
                "The sequence of actions the candidate demonstrated on the live site.",
            )

        if detail.get("dom_summary"):
            _website_card(
                "dom",
                "website_dom",
                "DOM summary",
                str(detail["dom_summary"]),
                "A safe summary of the page structure/content observed in the DOM (no raw DOM is exposed).",
            )

        if detail.get("ocr_summary"):
            _website_card(
                "ocr",
                "website_ocr",
                "OCR summary",
                str(detail["ocr_summary"]),
                "Text read on-screen from recorded frames (safe summary; no raw OCR dump is exposed).",
            )

        if detail.get("visual_summary"):
            _website_card(
                "visual",
                "website_visual",
                "Visual summary",
                str(detail["visual_summary"]),
                "A safe summary of the vision model's reasoning over recorded frames (no raw provider payload).",
            )

        if detail.get("workflow_summary"):
            _website_card(
                "nlp",
                "website_nlp",
                "NLP summary",
                str(detail["workflow_summary"]),
                "A natural-language summary of what the live workflow demonstrated for the supported skills.",
            )


def collect_website_skill_evidence(
    *,
    website_entries: list[dict[str, Any]],
    website_details: dict[str, dict[str, Any]],
    claimed_skills: list[str],
) -> list[dict[str, Any]]:
    """Skill-specific Website Behavior Evidence for the PRIVATE project report.

    For each attached Website Proof, classify WHAT the recorded page demonstrably
    showed (closed vocabulary, derived only from the already-safe Website Proof
    summaries the pipeline persisted — never raw DOM/OCR/visual/provider payloads),
    then map that observed behaviour to THIS project's claimed skills two ways:

      1. EXTRACTED match — a claimed skill the saved proof's ``supported_skills``
         explicitly names (the pipeline's own evidence-source match, trusted);
      2. DERIVED match — a claimed skill the observed behaviour genuinely
         demonstrates on its own, via ``derive_website_supported_skills`` (an
         interactive UI, chart/dashboard, request→result API exchange, or model
         prediction/generation). This mirrors how GitHub Proof maps CODE to a
         skill; Website Proof maps observed RUNTIME behaviour.

    For every mapped skill we recompute how the observed behaviour relates to it
    (direct UI evidence vs. product/availability context) plus the honest
    per-family limitation.

    Honesty invariants (all inherited from ``website_skill_proof_focus``):
      * a skill is projected iff it is claimed on this project AND either the
        proof's extracted supported skills name it OR the observed behaviour's
        relevance is strong enough to derive it — broad ``claimed_skills`` alone
        never map website evidence;
      * a GENERIC page (bare deployment availability / documentation / unknown /
        structural-only UI) derives NOTHING, so it stays project-level only;
      * implementation-heavy skills (ML / GenAI / DevOps) can only ever read as
        product-behaviour / availability context (``is_direct_evidence`` False),
        never implementation proof from a demo UI;
      * fail-closed — a proof that maps no claimed skill yields ``skills == []``
        and ``skill_mapping_available == False`` (project-level; gap stated).

    Only closed-vocabulary labels + already-safe summaries leave this function.
    """
    claimed_by_norm: dict[str, str] = {}
    for s in claimed_skills:
        n = _norm(str(s))
        if n and n not in claimed_by_norm:
            claimed_by_norm[n] = str(s)

    out: list[dict[str, Any]] = []
    for wp in website_entries:
        target = str(wp.get("target_website") or "")
        # Never echo a raw private/internal deployment URL into the report.
        safe_target = target if is_safe_public_url(target) else ""
        sid = str(wp.get("proof_session_id") or "")
        detail = website_details.get(sid) or {}
        live = detail.get("live_check") if isinstance(detail.get("live_check"), dict) else None

        purpose_key = classify_website_purpose(
            workflow_summary=detail.get("workflow_summary"),
            workflow_steps=detail.get("workflow_steps") or [],
            dom_summary=detail.get("dom_summary"),
            ocr_summary=detail.get("ocr_summary"),
            visual_summary=detail.get("visual_summary"),
            live_check=live,
            page_context=detail.get("page_context"),
            extra_signals=detail.get("extra_signals") or [],
        )

        # Which safe pipeline summaries backed this proof (closed labels only —
        # never their raw text). Surfaces the DOM / OCR / visual / NLP / runtime
        # provenance behind the mapping honestly.
        evidence_source_types = website_evidence_source_types(
            has_dom=bool(detail.get("dom_summary")),
            has_ocr=bool(detail.get("ocr_summary")),
            has_visual=bool(detail.get("visual_summary")),
            has_nlp=bool(detail.get("workflow_summary")),
            live_reachable=bool(live and live.get("is_reachable")),
        )

        # THE canonical Website→skill mapping (single source of truth): extracted
        # matches (the proof's stored ``supported_skills``) first, then derived
        # matches (the observed behaviour genuinely demonstrates a claimed skill).
        # The Work Passport, Project Report, and Skill Report all consume this same
        # mapping, so they can never disagree about which skill this Website Proof
        # supports in this project.
        skill_rows: list[dict[str, Any]] = []
        for display, basis in map_website_supported_skills(
            purpose_key,
            extracted_supported_skills=[str(s) for s in (wp.get("supported_skills") or [])],
            claimed_skills=list(claimed_by_norm.values()),
        ):
            relevance_key = classify_website_skill_relevance(purpose_key, skill=display)
            skill_rows.append(
                {
                    "skill_name": display,
                    "relevance_key": relevance_key,
                    "relevance_label": describe_website_skill_relevance(relevance_key, display),
                    "relevance_summary": website_skill_relevance_summary(relevance_key, display),
                    "limitation": website_limitation_for(relevance_key, display),
                    "is_direct_evidence": is_direct_website_relevance(relevance_key),
                    "mapping_basis": basis,
                }
            )

        # When nothing mapped, this Website Proof stays PROJECT-LEVEL only — carry a
        # safe reason + strengthening action so the gap is legible (never faked into
        # a skill). When a skill DID map, these stay empty.
        mapped = bool(skill_rows)

        # ── Website Runtime Inspection fields (Sections 1/2/4) ────────────────
        # A recruiter can DIRECTLY verify only when a public safe URL survived —
        # the attach-time public URL or the live-check's already-safe final URL.
        # A local/private capture yields neither, so it stays recorded-replay-only
        # and never links a private host.
        live_final = str((live or {}).get("final_url") or "").strip()
        safe_live_final = live_final if (live_final and is_safe_public_url(live_final)) else ""
        has_public_live = bool(safe_target or safe_live_final)
        verification_mode = VERIFICATION_MODE_LIVE if has_public_live else VERIFICATION_MODE_RECORDED
        target_domain = website_target_domain(
            safe_target or None, safe_live_final or None, safe_target or None
        )
        page_title = str((live or {}).get("page_title") or "").strip()[:160] or None
        # Section 1 runtime claim keyed by the PRIMARY mapped skill's relevance
        # (empty when nothing mapped — the unmapped reason speaks instead).
        runtime_claim = (
            website_runtime_claim(skill_rows[0]["relevance_key"], skill_rows[0]["skill_name"])
            if mapped
            else ""
        )
        out.append(
            {
                "target_website": safe_target,
                "website_replay_available": bool(
                    (detail.get("retained_artifacts") or {}).get("recording_available")
                    if isinstance(detail.get("retained_artifacts"), dict)
                    else False
                ),
                "website_replay_path": (
                    (detail.get("retained_artifacts") or {}).get("replay_path")
                    if isinstance(detail.get("retained_artifacts"), dict)
                    else None
                ),
                "website_artifact_id": (
                    (detail.get("retained_artifacts") or {}).get("artifact_id")
                    if isinstance(detail.get("retained_artifacts"), dict)
                    else None
                ),
                "website_analysis_path": (
                    (detail.get("retained_artifacts") or {}).get("analysis_path")
                    if isinstance(detail.get("retained_artifacts"), dict)
                    else None
                ),
                "website_timeline": list(detail.get("workflow_timeline") or []),
                "behavior_claim": website_behavior_claim(purpose_key),
                "website_purpose_key": purpose_key,
                "website_purpose_label": describe_website_purpose(purpose_key),
                "website_purpose_summary": website_purpose_summary(purpose_key),
                "runtime_claim_observed": runtime_claim,
                "target_domain": target_domain or "",
                "app_context": website_app_context(target_domain, page_title) or "",
                "page_context_label": website_page_context_label(detail.get("page_context")) or "",
                "user_action_observed": website_user_action_observed(purpose_key) or "",
                "output_observed": website_output_observed(purpose_key) or "",
                "verification_mode": verification_mode,
                "verification_mode_label": website_verification_mode_label(verification_mode),
                "recruiter_checklist": website_recruiter_checklist(verification_mode, purpose_key),
                "evidence_source_types": evidence_source_types,
                "skills": skill_rows,
                "skill_mapping_available": mapped,
                "unmapped_reason": "" if mapped else website_unmapped_skill_reason(purpose_key),
                "strengthen_action": "" if mapped else WEBSITE_STRENGTHEN_ACTION,
            }
        )
    return out


def collect_project_defense_traces(
    attach: _AttachFn,
    *,
    analysis: dict[str, Any] | None,
    defense_questions: list[dict[str, Any]],
) -> None:
    """Normalize stored Project Defense data into process/ownership traces.

    Reuses the deterministic ``vbr_session_questions`` text and the already
    analyzed ``project_defense_analysis`` plus per-question bounded
    ``answer_excerpt`` (recovered from transcript segments upstream and stripped
    on the public surface). Only answered questions produce a question-level
    trace; the raw transcript is never read here.
    """
    if analysis is not None:
        explained = [str(s) for s in (analysis.get("skills_explained_well") or [])]
        mentioned = [str(s) for s in (analysis.get("skills_mentioned") or [])]
        defense_skills = _dedupe_skill_names(explained + mentioned)
        summary = _scrub_score_fragments(
            str(analysis.get("recruiter_summary") or analysis.get("transcript_summary") or "")
        )
        ownership_score = int(analysis.get("ownership_signal_score") or 0)
        ownership_established = ownership_score >= 60
        defense_detail = (
            "Process/contribution evidence: the candidate described their contribution and project decisions."
            if ownership_established
            else (
                "Project-understanding evidence: the candidate discussed the project, but personal "
                "ownership was not established by this defense."
            )
        )
        attach(
            {
                "trace_id": "project-defense",
                "source_type": _SRC_DEFENSE,
                "source_title": "Project Defense",
                "skill_names": defense_skills,
                "qualitative_status": _PARTIALLY_DEMONSTRATED if explained else _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(
                    summary
                    or (
                        "The candidate described their contribution and approach during the Project Defense."
                        if ownership_established
                        else "The candidate discussed the project during the Project Defense; personal ownership was not established."
                    )
                ),
                "safe_detail": defense_detail,
                "evidence_anchor": "project-defense",
                "location_type": "defense_overview",
                "location_label": "overall explanation",
                "location_detail": None,
                "public_url": None,
                "public_url_label": None,
                "timestamp": None,
                "limitation": _DEFENSE_LIMITATION,
                "is_publicly_openable": False,
                "private_evidence_note": "Full defense answers are summarized; the raw transcript is not exposed.",
            }
        )


    for idx, question in enumerate(defense_questions, start=1):
        if not question.get("answered"):
            continue
        skill = question.get("skill")
        # The deterministic question text is safe to show; the raw answer
        # transcript is never surfaced — only a short, sanitized answer excerpt
        # (stripped entirely on the public surface).
        q_text = _trace_text(_scrub_score_fragments(str(question.get("question_text") or "")))
        answer_excerpt = question.get("answer_excerpt") or None
        attach(
            {
                "trace_id": f"project-defense-q{idx}",
                "source_type": _SRC_DEFENSE,
                "source_title": f"Project Defense — Q{idx}",
                "skill_names": [str(skill)] if skill else [],
                "qualitative_status": _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(
                    "The candidate answered this Project Defense question in their own words."
                ),
                "safe_detail": (
                    "Self-explanation evidence for the question below; strongest when combined with "
                    "artifact evidence."
                ),
                "evidence_anchor": f"project-defense-q{idx}",
                "location_type": "defense_question",
                # Bare "Q{n}" — the UI renders it as "Defense Q{n}".
                "location_label": f"Q{idx}",
                "location_detail": None,
                "question_text": q_text or None,
                "answer_excerpt": answer_excerpt,
                "public_url": None,
                "public_url_label": None,
                "timestamp": None,
                "limitation": _DEFENSE_LIMITATION,
                "is_publicly_openable": False,
                "private_evidence_note": "Answer is summarized; the raw transcript is not exposed.",
            }
        )


def collect_video_evidence_traces(attach: _AttachFn, *, video_chips: list[dict[str, Any]]) -> None:
    """Normalize stored ``video_evidence_chips`` into timestamped traces.

    Reuses the sanitized chips written by ``project_defense_evidence_chips``
    (label / short summary / related skill / timestamp). The recording itself and
    any chunk/keyframe/media paths are never read here.
    """
    for idx, chip in enumerate(video_chips, start=1):
        related = chip.get("related_skill")
        label = str(chip.get("label") or f"Video chip {idx}")
        attach(
            {
                "trace_id": f"video-chip-{idx:03d}",
                "source_type": _SRC_VIDEO,
                "source_title": label,
                "skill_names": [str(related)] if related else [],
                "qualitative_status": _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(str(chip.get("short_summary") or "")),
                "safe_detail": (
                    "A timestamped moment in the recorded Project Defense where this skill/concept was discussed."
                ),
                "evidence_anchor": f"video-chip-{idx:03d}",
                "location_type": "video_timestamp",
                "location_label": label,
                "location_detail": None,
                "timestamp_label": label,
                "public_url": None,
                "public_url_label": None,
                "timestamp": label,
                "limitation": _VIDEO_LIMITATION,
                "is_publicly_openable": False,
                "private_evidence_note": "The recording itself is private; only this timestamped summary is shown.",
            }
        )


def _dedupe_skill_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _enrich_skill_row(
    row: dict[str, Any],
    trace_ids: list[str],
    traces_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach trace ids + a plain-language justification to a skill row."""
    sources = list(row.get("supporting_sources") or [])
    status = str(row.get("status") or _NOT_ASSESSED)

    if sources:
        why = f"Marked '{status}' because supporting evidence was found in: {_humanize_list(sources)}."
    else:
        why = (
            f"Marked '{status}' because no evidence source has been reviewed for this skill yet — "
            "treat it as a claim pending more proof."
        )

    section_types = _dedupe_skill_names(
        [traces_index[t]["source_type"] for t in trace_ids if t in traces_index]
    )
    openable = any(traces_index.get(t, {}).get("is_publicly_openable") for t in trace_ids)
    if section_types:
        verify = (
            f"Open the {_humanize_list(section_types)} evidence trace(s) below to see why this skill is supported."
        )
        if openable:
            verify += " Some sources link directly to public, openable evidence."
    else:
        verify = "No evidence is attached for this skill yet — there is nothing to verify."

    row["evidence_traces"] = trace_ids
    row["why_this_status"] = why
    row["recruiter_can_verify"] = verify
    return row


def _real_unmapped_entry(
    *,
    proof_type: str,
    project_id: str,
    project_title: str,
    reason: str,
    safe_summary: str,
    evidence_label: str | None = None,
    observed_at: str | None = None,
    source_count: int | None = None,
    inspection_anchor: str | None = None,
) -> dict[str, Any]:
    """One private-safe real-unmapped-proof context entry (closed field set).

    Only safe display fields: never a proof/session/evidence id, storage path,
    signed URL, raw text, or numeric score. Optional fields are omitted when
    unknown rather than emitted as nulls."""
    entry: dict[str, Any] = {
        "proof_type": proof_type,
        "project_id": project_id,
        "project_title": project_title,
        "report_url": f"{_PRIVATE_PROJECT_REPORT_PREFIX}{project_id}/report",
        "reason": reason,
        "safe_summary": _trace_text(safe_summary),
    }
    if evidence_label:
        entry["evidence_label"] = evidence_label
    if observed_at:
        entry["observed_at"] = observed_at
    if isinstance(source_count, int) and source_count > 0:
        entry["source_count"] = source_count
    if inspection_anchor:
        entry["inspection_anchor"] = inspection_anchor
    return entry


def _build_real_unmapped_proof_context(
    *,
    project_id: str,
    project_title: str,
    skill_evidence: list[dict[str, Any]],
    github_proof: dict[str, Any] | None,
    github_code_evidence: list[dict[str, Any]],
    github_smart_evidence_count: int,
    website_entries: list[dict[str, Any]],
    website_skill_evidence: list[dict[str, Any]],
    document_entries: list[dict[str, Any]],
    analysis: dict[str, Any] | None,
    defense_questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """REAL analyzed, project-attached proof that no exact skill row consumed.

    The honesty layer between "exact skill-mapped evidence" and "hidden": when a
    project carries genuinely analyzed proof (analyzed GitHub source code,
    recorded/analyzed website runtime behaviour, an analyzed document, an
    answered+analyzed Project Defense) but the skill matrix mapped none of it to
    an exact claimed skill row, that proof is surfaced HERE — clearly separated
    from skill evidence — instead of disappearing.

    Fail-closed qualification per proof type (metadata is NEVER proof):

    * GitHub — requires analyzed source evidence with real provenance: canonical
      Smart GitHub code rows for THIS project's repo, line-level
      ``skill_code_evidence`` from the attached analyzed proof, or the analyzed
      proof's own ``detected_skills`` / ``evidence_files``. A bare repo URL /
      ``repo_full_name`` / an attached-but-unanalyzed link qualifies nothing.
    * Website — requires an attached Website Proof from a REAL recorded/analyzed
      proof session (``proof_session_id`` present — attach-time validation only
      accepts sessions with a completed analysis) whose canonical mapping
      consumed no skill. A bare live/deployment URL qualifies nothing.
    * Document — requires an analyzed document (explicit ``analyzed`` status or
      recovered analyzer evidence locators) that matched no claimed skill.
      A filename / upload metadata alone qualifies nothing.
    * Project Defense — requires an answered, ANALYZED defense session
      (``analysis`` present) whose explanation evidence mapped to no claimed
      skill row. A question plan / unanswered defense qualifies nothing.

    Entries are context only. They are never skill evidence, never counted in
    proof filter counts / capability aggregates / graph nodes, and never present
    on any public payload.
    """
    out: list[dict[str, Any]] = []

    # Proof types an exact skill row already consumed — those never duplicate
    # into this layer (the exact row IS the evidence surface for them).
    consumed_proof_types = {
        str(src)
        for row in skill_evidence
        for src in (row.get("supporting_sources") or [])
    }

    # ── GitHub Proof ──────────────────────────────────────────────────────────
    if _SRC_GITHUB not in consumed_proof_types:
        gp = github_proof or {}
        analyzed_detected = [str(s) for s in (gp.get("detected_skills") or []) if str(s).strip()]
        analyzed_files = [str(f) for f in (gp.get("evidence_files") or []) if str(f).strip()]
        analyzed_item_count = github_smart_evidence_count + len(github_code_evidence)
        has_real_github_evidence = bool(
            analyzed_item_count or analyzed_detected or analyzed_files
        )
        if has_real_github_evidence:
            summary = _scrub_score_fragments(str(gp.get("public_safe_summary") or "")) or (
                "Analyzed GitHub source-code evidence is attached to this project, but it is "
                "not mapped to a specific claimed skill yet."
            )
            out.append(
                _real_unmapped_entry(
                    proof_type=_SRC_GITHUB,
                    project_id=project_id,
                    project_title=project_title,
                    reason=_REAL_UNMAPPED_GITHUB_REASON,
                    safe_summary=summary,
                    evidence_label="Analyzed source evidence",
                    source_count=analyzed_item_count or None,
                    inspection_anchor="github-proof",
                )
            )

    # ── Website Proof ─────────────────────────────────────────────────────────
    # One honest entry per distinct unmapped observed-behaviour classification.
    # ``website_skill_evidence`` is parallel to ``website_entries`` (one per
    # attached proof, in order), so zip re-associates each mapping with its
    # session-backed entry.
    seen_website_focus: set[str] = set()
    for entry, wse in zip(website_entries, website_skill_evidence):
        if wse.get("skill_mapping_available"):
            continue  # consumed as exact skill evidence — never duplicated here
        # A REAL recorded/analyzed proof session is required: attach-time
        # validation only accepts sessions with a completed analysis, so a
        # session id is the honest provenance marker. A URL-only metadata row
        # (no session) is not proof and must never appear in this layer.
        if not str(entry.get("proof_session_id") or "").strip():
            continue
        focus_key = str(wse.get("website_purpose_key") or "")
        if focus_key in seen_website_focus:
            continue
        seen_website_focus.add(focus_key)
        summary = (
            str(wse.get("website_purpose_summary") or "").strip()
            or str(wse.get("behavior_claim") or "").strip()
            or "A recorded website runtime proof is attached to this project, but it is not "
            "mapped to a specific claimed skill yet."
        )
        source_types = [str(t) for t in (wse.get("evidence_source_types") or []) if str(t).strip()]
        out.append(
            _real_unmapped_entry(
                proof_type=_SRC_WEBSITE,
                project_id=project_id,
                project_title=project_title,
                reason=str(wse.get("unmapped_reason") or "").strip() or _REAL_UNMAPPED_WEBSITE_REASON,
                safe_summary=summary,
                evidence_label=str(wse.get("website_purpose_label") or "").strip() or "Runtime proof",
                source_count=len(source_types) or None,
                inspection_anchor="website-proof",
            )
        )

    # ── Document Proof ────────────────────────────────────────────────────────
    for doc in document_entries:
        if doc.get("skills"):
            continue  # matched a claimed skill — consumed as exact skill evidence
        # Real analyzed evidence only: an explicit analyzed status or recovered
        # analyzer locators. A filename / upload metadata row qualifies nothing.
        if not doc.get("has_analyzed_evidence"):
            continue
        title = str(doc.get("title") or "Document")
        out.append(
            _real_unmapped_entry(
                proof_type=_SRC_DOCUMENT,
                project_id=project_id,
                project_title=project_title,
                reason=_REAL_UNMAPPED_DOCUMENT_REASON,
                safe_summary=(
                    f"{title} was analyzed and is attached as project context, but it is not "
                    "mapped to a specific claimed skill yet."
                ),
                evidence_label="Analyzed document evidence",
                inspection_anchor="documents",
            )
        )

    # ── Project Defense ───────────────────────────────────────────────────────
    if _SRC_DEFENSE not in consumed_proof_types and analysis is not None:
        answered_count = sum(1 for q in defense_questions if q.get("answered"))
        out.append(
            _real_unmapped_entry(
                proof_type=_SRC_DEFENSE,
                project_id=project_id,
                project_title=project_title,
                reason=_REAL_UNMAPPED_DEFENSE_REASON,
                safe_summary=(
                    "An answered and analyzed Project Defense session is attached to this "
                    "project, but its explanation evidence is not mapped to a specific "
                    "claimed skill yet."
                ),
                evidence_label="Analyzed defense evidence",
                source_count=answered_count or None,
                inspection_anchor="project-defense",
            )
        )

    return out


def _owned_rows(db: Any, table: str, user_id: str, *, user_key: str = "user_id") -> list[dict[str, Any]]:
    """Best-effort owner-scoped bulk read for canonical relationship hydration."""
    from app.services.canonical_project_evidence import owned_rows

    return owned_rows(db, table, user_id, user_key=user_key)


def _canonical_website_proofs_for_project(
    db: Any, *, user_id: str, project_ids: list[str]
) -> list[dict[str, Any]]:
    """Analyzed Website Proofs with a deterministic direct project edge.

    ``project_ids`` is the duplicate group of ONE logical project, so a proof
    the owner attached to any duplicate row still surfaces on this report.
    """
    from app.services.canonical_project_evidence import canonical_website_session_ids

    session_ids = set(
        canonical_website_session_ids(db, user_id=user_id, project_ids=project_ids)
    )
    if not session_ids:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Deterministic attachment order: oldest analysis first, session id as the
    # tiebreak. The bulk read has no ordering guarantee, and an unordered result
    # would let a project with several attached Website Proofs render them (and
    # pick "first" anywhere downstream) in a different order per request.
    analysis_rows = sorted(
        _owned_rows(db, "workflow_analysis_results", user_id),
        key=lambda row: (
            str(row.get("created_at") or ""),
            str(row.get("proof_session_id") or ""),
        ),
    )
    for row in analysis_rows:
        sid = str(row.get("proof_session_id") or "")
        if not sid or sid not in session_ids or sid in seen:
            continue
        seen.add(sid)
        out.append(
            {
                "proof_session_id": sid,
                "target_website": str(row.get("target_website") or ""),
                "evidence_strength_score": int(row.get("evidence_strength_score") or 0),
                "workflow_confidence": str(row.get("workflow_confidence") or "insufficient"),
                "supported_skills": [
                    str(skill) for skill in (row.get("supported_skills") or []) if str(skill).strip()
                ],
                "relationship_source": "canonical_direct",
            }
        )
    return out


def _canonical_proof_ids_for_project(
    db: Any, *, user_id: str, project_ids: list[str], proof_type: str
) -> list[str]:
    """Proof ids of ``proof_type`` with a deterministic direct edge to this project.

    Delegates to the shared canonical resolver (see
    ``canonical_project_evidence``): explicit finalization writes only, scoped
    by owner + the exact project ids, deterministically ordered.
    """
    from app.services.canonical_project_evidence import canonical_proof_ids_for_projects

    return canonical_proof_ids_for_projects(
        db, user_id=user_id, project_ids=project_ids, proof_type=proof_type
    )


def _canonical_github_proof_for_project(
    db: Any, *, user_id: str, project_ids: list[str], project_identity: str
) -> dict[str, Any] | None:
    """Attached GitHub Proof summary recovered from canonical relationship rows.

    Read-time parity with :func:`_canonical_website_proofs_for_project`: a
    GitHub Proof the owner explicitly finalized against this project must not
    disappear just because the legacy ``vbr_projects.metadata.attached_proofs``
    write was missed. Selection is the shared deterministic rule (identity gate
    → analysis-complete first → newest edge); the summary is rebuilt by the
    SAME safe builder the attach flow uses (never raw ``repo_metadata``).
    """
    from app.services.canonical_project_evidence import resolve_canonical_github_summary

    # Lazy import mirrors the existing attach-flow pattern and avoids a
    # service import cycle.
    from app.services.vbr_project_defense import _github_proof_summary

    return resolve_canonical_github_summary(
        db,
        user_id=user_id,
        project_ids=project_ids,
        project_identity=project_identity,
        build_summary=_github_proof_summary,
    )


def _canonical_documents_for_project(
    db: Any, *, user_id: str, project_ids: list[str], known_document_ids: set[str]
) -> list[dict[str, Any]]:
    """Attached Document Proof summaries recovered from canonical rows.

    Same read-time parity for Document Proof: an owner-finalized document whose
    canonical relationship row exists but whose legacy metadata write was
    missed still surfaces on the report. Documents already present in the
    project metadata (``known_document_ids``) are skipped so nothing is ever
    duplicated; summaries come from the SAME safe builder the attach flow uses.
    """
    out: list[dict[str, Any]] = []
    for proof_id in _canonical_proof_ids_for_project(
        db, user_id=user_id, project_ids=project_ids, proof_type="document"
    ):
        if proof_id in known_document_ids:
            continue
        try:
            from app.services.vbr_project_defense import _document_summaries

            summaries = _document_summaries(db, user_id, [proof_id])
        except Exception:  # pragma: no cover - canonical hydration is best-effort
            continue
        for summary in summaries:
            summary["relationship_source"] = "canonical_direct"
            out.append(summary)
    return out


def _log_evidence_discovery_diagnostics(report: dict[str, Any], *, user_id: str) -> None:
    """Development-only evidence-discovery trace: which owned rows the report
    found, what counted, and why the rest was excluded. IDs and closed-vocabulary
    states only — never tokens, URLs, transcripts, or file contents."""
    from app.core.config import get_settings

    try:
        if get_settings().environment.strip().lower() == "production":
            return
    except Exception:  # pragma: no cover - settings failure must never break reports
        return
    cem = report.get("claim_evidence_map") if isinstance(report.get("claim_evidence_map"), dict) else {}
    citations = [c for c in (cem.get("citations") or []) if isinstance(c, dict)]
    excluded_reasons: dict[str, int] = {}
    for citation in citations:
        if citation.get("counted_as_direct_evidence"):
            continue
        reason = str(
            citation.get("identity_state")
            or ("analysis_pending" if citation.get("analysis_pending") else "")
            or citation.get("evidence_status")
            or "context_only"
        )
        excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
    logger.info(
        "evidence-discovery user=%s project=%s github_proof=%s traces=%d website_counted=%d "
        "website_excluded=%d documents=%d defense_inspection=%d cem_citations=%d cem_counted=%d "
        "relationships=%s excluded_reasons=%s",
        user_id,
        report.get("project_id"),
        bool(report.get("github_proof")),
        len(report.get("evidence_traces") or []),
        (report.get("evidence_package") or {}).get("website_proofs_count"),
        (report.get("evidence_package") or {}).get("website_proofs_excluded_count"),
        (report.get("evidence_package") or {}).get("documents_count"),
        len(report.get("project_defense_inspection") or []),
        len(citations),
        sum(1 for c in citations if c.get("counted_as_direct_evidence")),
        sorted(
            {
                str((c.get("project_relationship") or {}).get("state") or "unknown")
                for c in citations
                if isinstance(c.get("project_relationship"), dict)
            }
        ),
        excluded_reasons,
    )


def build_student_vbr_report(
    db: Any,
    pipeline_db: Any,
    project: dict[str, Any],
    user_id: str,
    *,
    include_cross_proof: bool = True,
) -> dict[str, Any]:
    """Build the safe, student-owned VBR report preview for ``project``.

    ``project`` must already be ownership-checked (see
    ``get_owned_vbr_project_or_404``).

    ``include_cross_proof`` controls the ``other_student_proofs`` section, which
    scans the student's *entire* proof vault for related (unattached) proofs. It
    is needed by the single-project report view, but a caller that builds a
    report for every owned project (e.g. the Work Passport summary) pays that
    whole-vault scan once per project for data it never reads — so it passes
    ``include_cross_proof=False`` to skip it. The attached, project-honest
    matrix/traces are unaffected; only the additive cross-proof section is gated.
    """
    metadata = project.get("metadata") or {}
    attached = metadata.get("attached_proofs") or {}
    if not isinstance(attached, dict):
        attached = {}

    claimed_skills: list[str] = [str(s) for s in (metadata.get("claimed_skills") or [])]

    # One logical project can span several duplicate ``vbr_projects`` rows (one
    # per proof form the student started from). Canonical evidence resolution
    # covers the whole duplicate group so a proof the owner attached to any
    # duplicate row still surfaces on this report — the SAME grouping the
    # Project Defense workspace uses.
    project_group_ids = [str(project.get("id") or "")]
    try:
        from app.services.vbr_project_defense import _find_project_group

        group = _find_project_group(db, user_id, str(project.get("id") or ""))
        if group:
            project_group_ids = [str(p.get("id") or "") for p in group if p.get("id")]
    except Exception:  # pragma: no cover - grouping is a read-time widening only
        pass

    from app.services.canonical_project_evidence import (
        github_identity_conflict,
        project_repo_identity,
    )

    identity = project_repo_identity(project)

    github_proof = attached.get("github_proof") if isinstance(attached.get("github_proof"), dict) else None
    # Repository-identity read gate: a legacy metadata summary whose repository
    # contradicts the project's own declared repository must not leak an
    # unrelated repository into this report (see canonical resolver rule 4).
    if github_proof is not None and github_identity_conflict(identity, github_proof.get("repo_url")):
        github_proof = None
    documents_raw = list(attached.get("documents")) if isinstance(attached.get("documents"), list) else []
    website_proofs_raw = list(attached.get("website_proofs")) if isinstance(attached.get("website_proofs"), list) else []
    # Canonical direct links are equally authoritative for GitHub and Document
    # Proof (read-time parity with the Website fallback below): a proof the
    # owner explicitly finalized against this project surfaces even when the
    # legacy ``attached_proofs`` metadata write was missed. Deduped by proof id;
    # vault-only / suggested / mismatched proof is never admitted because the
    # helpers read only ``directly_linked`` finalization rows.
    if github_proof is None:
        github_proof = _canonical_github_proof_for_project(
            db, user_id=user_id, project_ids=project_group_ids, project_identity=identity
        )
    known_document_ids = {
        str((doc or {}).get("document_evidence_id") or "")
        for doc in documents_raw
        if isinstance(doc, dict)
    }
    documents_raw.extend(
        _canonical_documents_for_project(
            db,
            user_id=user_id,
            project_ids=project_group_ids,
            known_document_ids=known_document_ids,
        )
    )
    # Canonical direct links are equally authoritative and prevent a Website
    # Proof whose session/artifact carries this project_id from disappearing just
    # because legacy project metadata was not updated. Dedupe by session; no
    # suggested/vault/mismatched proof is admitted by the helper.
    known_website_sessions = {
        str(row.get("proof_session_id") or "")
        for row in website_proofs_raw
        if isinstance(row, dict)
    }
    for canonical_wp in _canonical_website_proofs_for_project(
        db, user_id=user_id, project_ids=project_group_ids
    ):
        canonical_sid = str(canonical_wp.get("proof_session_id") or "")
        if canonical_sid in known_website_sessions:
            for existing in website_proofs_raw:
                if isinstance(existing, dict) and str(existing.get("proof_session_id") or "") == canonical_sid:
                    existing["relationship_source"] = "canonical_direct"
                    break
        else:
            website_proofs_raw.append(canonical_wp)
    skill_pipeline_ids = [str(p) for p in (attached.get("skill_pipeline_ids") or []) if p]

    # Normalized claimed-skill lookup (normalized → canonical display name). A
    # document only ever evidences a skill the project actually claims.
    claimed_by_norm = {_norm(s): s for s in claimed_skills}

    # Internal entries carry the analyzer-matched skills (narrowed to claimed
    # skills) used to build per-skill document evidence + matrix rows. The public
    # ``documents`` projection below intentionally drops the skills list.
    document_entries: list[dict[str, Any]] = []
    for doc in documents_raw:
        if not isinstance(doc, dict):
            continue
        # Always re-read the document's structured ``evidence_objects`` at
        # report-build time — even when the attach-time metadata carried no
        # matched skills. Older attachments were written before document skills
        # were recorded into ``vbr_projects.metadata``, so the attach-time
        # ``skills`` list can be stale/empty while the real per-skill evidence
        # (skill_name + page/section/snippet) still lives on the
        # ``optional_evidence_submissions`` row. Recovering it here rehydrates
        # skill-level Document Proof without persisting snippets into metadata.
        # Any lookup problem returns ``{}`` ⇒ honest project-level document trace.
        locators = _document_skill_locators(db, user_id, str(doc.get("document_evidence_id") or ""))

        # Matched skills = (attach-time matched skills ∪ rehydrated locator
        # skill_names), intersected with the skills the project actually claims.
        # A document is therefore mapped ONLY to claimed skills the analyzer
        # explicitly referenced in it — never to every claimed skill. Order
        # follows ``claimed_skills`` so the output is deterministic.
        #
        # A project whose owner never filled in ``claimed_skills`` has nothing
        # to intersect with — there the analyzer's own matched skills stand
        # (detection, not a student claim; the matrix rows say so explicitly).
        if claimed_by_norm:
            matched_norms = {
                _norm(s) for s in (doc.get("skills") or []) if _norm(s) in claimed_by_norm
            }
            matched_norms.update(key for key in locators if key in claimed_by_norm)
            matched = [claimed_by_norm[key] for key in claimed_by_norm if key in matched_norms]
        else:
            matched = [str(s) for s in (doc.get("skills") or []) if str(s).strip()]
            matched_norms = {_norm(s) for s in matched}

        document_entries.append(
            {
                "title": str(doc.get("title") or "Document"),
                "source_type": doc.get("source_type"),
                "status": doc.get("status"),
                # Stable per-document disclosure key (the evidence submission
                # id) — drives the granular Privacy Center controls and the
                # public builder's per-document visibility filter. Stripped
                # from the public projection.
                "document_key": str(doc.get("document_evidence_id") or ""),
                # Owner-only retained-original access (opaque artifact id +
                # access-gated routes; honest available=False when the file was
                # never retained). Stripped by the public report builder.
                "original_document": _document_original_access(
                    db, user_id, str(doc.get("document_evidence_id") or "")
                ),
                "skills": matched,
                # Keep only locators for matched (claimed) skills so an
                # ``evidence_objects`` entry for a skill the project never claimed
                # can never leak through as a document locator.
                "skill_locators": {key: val for key, val in locators.items() if key in matched_norms},
                # Whether REAL analyzer output exists for this document (explicit
                # analyzed status or recovered evidence locators). Drives the
                # real-unmapped-proof layer only — filename/upload metadata alone
                # stays False and can never qualify as proof.
                "has_analyzed_evidence": bool(locators)
                or str(doc.get("status") or "").strip().lower() == "analyzed",
            }
        )

    documents = [
        {
            "title": e["title"],
            "source_type": e["source_type"],
            "status": e["status"],
            "document_key": e["document_key"],
            "original_document": e["original_document"],
        }
        for e in document_entries
    ]
    # Skills the matrix may mark as Document-Proof-supported — identical to the set
    # used to build the document evidence traces, so the two never disagree.
    document_supported_skills = {_norm(s) for e in document_entries for s in e["skills"]}

    # Internal entries keep ``proof_session_id`` so the report builder can
    # hydrate deeper Website Proof artifacts (live check / workflow / DOM / OCR /
    # visual / NLP summaries). The public ``website_proofs`` projection below
    # intentionally drops the session id.
    website_entries = [
        {
            "proof_session_id": str(wp.get("proof_session_id") or ""),
            "target_website": str(wp.get("target_website") or ""),
            "evidence_strength": _website_evidence_label(int(wp.get("evidence_strength_score") or 0)),
            "workflow_confidence": str(wp.get("workflow_confidence") or "insufficient"),
            "supported_skills": [str(s) for s in (wp.get("supported_skills") or [])],
            "relationship_source": str(wp.get("relationship_source") or "legacy_metadata"),
        }
        for wp in website_proofs_raw
        if isinstance(wp, dict)
    ]
    website_proofs = [
        {
            "target_website": e["target_website"],
            "evidence_strength": e["evidence_strength"],
            "workflow_confidence": e["workflow_confidence"],
            "supported_skills": e["supported_skills"],
            # Stable per-proof disclosure key (the proof session id) — used by
            # the public builder to attach replay/frame access ONLY when the
            # student's disclosure policy allows it. Stripped from the public
            # projection unless an access descriptor is explicitly granted.
            "website_key": e["proof_session_id"],
        }
        for e in website_entries
    ]

    # Hydrate safe, deeper Website Proof artifact summaries per session.
    website_details: dict[str, dict[str, Any]] = {}
    for e in website_entries:
        sid = e["proof_session_id"]
        if not sid:
            continue
        detail = get_website_proof_detail(db, user_id, sid)
        if detail:
            website_details[sid] = detail

    session = get_latest_session(db, str(project["id"]))
    telemetry = (session.get("telemetry") or {}) if session else {}
    if not isinstance(telemetry, dict):
        telemetry = {}

    analysis = telemetry.get("project_defense_analysis")
    if not isinstance(analysis, dict):
        analysis = None

    video_chips_raw = telemetry.get("video_evidence_chips")
    video_chips: list[dict[str, Any]] = video_chips_raw if isinstance(video_chips_raw, list) else []

    # Claim-level Defense Answer Evidence cards (owner view). Empty for
    # sessions analyzed before the answer-evidence engine existed.
    defense_answer_evidence = _report_safe_answer_evidence(
        telemetry.get("defense_answer_evidence")
    )

    # Project Defense inspection cards (owner view) — a first-class recruiter
    # inspection projection over the answer evidence above, parallel to GitHub /
    # Website / Document inspection. Built from the already-safe answer objects
    # plus the safe video evidence chips (for the timestamp/clip locator). Empty
    # when there is no answer evidence yet.
    # Authorized owner-only playable evidence: bounded transcript excerpts (from
    # the session's transcript segments) and a signed playback handle for the
    # owner's own recording. Both fail closed to "unavailable" without storage;
    # the public projection re-derives its cards and never sees these.
    defense_answer_excerpts = (
        build_safe_answer_excerpts(db, str(session["id"])) if session is not None else {}
    )
    defense_recording = build_recording_playback(db, session) if session is not None else None

    project_defense_inspection = build_project_defense_inspection_cards(
        answer_evidence=defense_answer_evidence,
        video_chips=video_chips,
        project_title=str(project.get("title") or ""),
        answer_excerpts=defense_answer_excerpts,
        recording=defense_recording,
        is_owner_view=True,
    )

    # ── Candidate ↔ project ownership (attribution integrity) ────────────────
    # Assessed ONLY from candidate↔artifact relationship evidence: the
    # candidate's own defense ownership stances plus any stored candidate-
    # specific repo attribution (vbr_repo_analyses). Artifact evidence (code
    # detected, behaviour recorded, documents) contributes nothing by design —
    # PROJECT EVIDENCE != CANDIDATE OWNERSHIP.
    from app.services.candidate_attribution_service import (
        assess_project_ownership,
        build_candidate_attribution,
    )

    candidate_ownership = assess_project_ownership(
        answer_items=defense_answer_evidence,
        repo_analysis=_repo_analysis_row(db, project_group_ids),
    )
    candidate_attribution = build_candidate_attribution(ownership=candidate_ownership)

    questions: list[dict[str, Any]] = []
    chunk_count = 0
    answer_excerpts: dict[str, str] = {}
    if session is not None:
        questions = list_session_questions(db, str(session["id"]))
        chunk_count = count_chunks(db, str(session["id"]))
        # Per-question bounded answer excerpts (private-only; stripped on public).
        answer_excerpts = _defense_answer_excerpts(db, str(session["id"]))

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
                "answer_excerpt": answer_excerpts.get(str(q["id"])),
            }
        )

    project_defense_completed = metadata.get("project_defense_status") == "analyzed"
    video_defense_recorded = chunk_count > 0

    # ── Skill evidence table ────────────────────────────────────────────────
    github_detected_skills = {_norm(s) for s in (github_proof.get("detected_skills") or [])} if github_proof else set()

    # Bridge the newer Smart GitHub Evidence pipeline (canonical ``skill_evidence``
    # code-line rows) into the per-skill decision: a claimed skill earns "GitHub
    # Proof" when real analyzed code evidence for THIS project's repo maps to it,
    # even if it is missing from the attached proof's ``detected_skills``. Matched
    # strictly by repo identity + claimed skill so repo metadata alone, an
    # unrelated repo, or an unclaimed skill can never manufacture GitHub Proof.
    project_repo_ids = _project_repo_identities(project, github_proof)
    github_smart_skills = _collect_github_smart_supported_skills(
        db,
        user_id,
        project_repo_ids=project_repo_ids,
        claimed_skills=claimed_skills,
    )

    # Skill-specific Website Behavior Evidence (owner/private view only): what each
    # attached Website Proof demonstrably showed + an honest per-skill relevance,
    # mapped to the claimed skills the proof's extracted supported-skills name OR
    # the observed behaviour genuinely demonstrates (conservative derivation).
    # Kept off the public projection.
    website_skill_evidence = collect_website_skill_evidence(
        website_entries=website_entries,
        website_details=website_details,
        claimed_skills=claimed_skills,
    )
    # Canonical Website→project identity gate. Every row here came through an
    # explicit project attachment (legacy project metadata, session project_id,
    # artifact project_id, or confirmed relationship). It therefore counts by
    # default. The fail-closed exception is a strong cross-project conflict: the
    # recorded app identity exactly names another owned project.
    # A duplicate row of THIS logical project is not "another project" — it
    # shares the title/repo by construction and must never demote evidence the
    # owner attached to the same logical project.
    other_projects = [
        row
        for row in _owned_rows(db, "vbr_projects", user_id)
        if str(row.get("id") or "") not in set(project_group_ids)
    ]
    extension_sessions = {
        str(row.get("id") or ""): row
        for row in _owned_rows(db, "extension_proof_sessions", user_id)
        if row.get("id")
    }
    # Proof ids the owner EXPLICITLY confirmed belong to THIS project through
    # the canonical finalization boundary. An explicit user confirmation is the
    # strongest identity signal we have — it must never be demoted by the fuzzy
    # cross-project conflict heuristics below (two owned projects legitimately
    # sharing a repo URL or similar titles would otherwise exclude the proof
    # from the very project the owner attached it to).
    user_confirmed_proof_ids: set[str] = {
        str(relation.get("proof_id"))
        for relation in _owned_rows(
            db, "proof_project_relationships", user_id, user_key="owner_user_id"
        )
        if relation.get("proof_type") == "website"
        and relation.get("relationship_state") == "directly_linked"
        and str(relation.get("project_id") or "") in set(project_group_ids)
        and bool(relation.get("confirmed_by_user"))
        and relation.get("proof_id")
    }
    for entry, wse in zip(website_entries, website_skill_evidence):
        session_context = extension_sessions.get(str(entry.get("proof_session_id") or "")) or {}
        session_metadata = (
            session_context.get("metadata")
            if isinstance(session_context.get("metadata"), dict)
            else {}
        )
        identity_norm = _norm(
            " ".join(
                str(value or "")
                for value in (
                    wse.get("app_context"),
                    session_context.get("title"),
                    session_context.get("proof_objective"),
                    session_metadata.get("project_title"),
                )
            )
        )
        session_repo = str(session_context.get("github_url") or "").lower().rstrip("/")
        conflicting_project = next(
            (
                other
                for other in other_projects
                if (
                    _norm(other.get("title"))
                    and len(_norm(other.get("title")).replace(" ", "")) >= 8
                    and _norm(other.get("title")) in identity_norm
                )
                or (
                    session_repo
                    and str(other.get("repo_url") or "").lower().rstrip("/") == session_repo
                )
            ),
            None,
        )
        if str(entry.get("proof_session_id") or "") in user_confirmed_proof_ids:
            state = "matched_direct"
            reasons = [
                "The student explicitly confirmed this Website Proof belongs to this project."
            ]
        elif conflicting_project:
            conflicting_title = str(conflicting_project.get("title") or "another project")
            state = "mismatched"
            reasons = [
                f"The recorded application identifies as '{wse.get('app_context')}', which matches "
                f"another owned project ('{conflicting_title}'), not this project."
            ]
        else:
            state = "matched_direct"
            reasons = [
                "The student explicitly attached or created this Website Proof for this owned project."
            ]
        wse["project_relationship_state"] = "directly_linked"
        wse["project_identity_state"] = state
        wse["project_identity_reasons"] = reasons
        wse["counted_for_project"] = state == "matched_direct"
    # The claimed skills that Website Proof supports — taken from the mapped
    # behavior-evidence above so the skill matrix, the passport
    # ``supporting_proof_types`` and the behavior-evidence cards can never
    # disagree. A skill only earns the "Website Proof" source chip when a mapped
    # skill row exists for it (extracted or safely derived); a generic website
    # that mapped nothing adds no Website Proof chip to any skill.
    website_supported_skills: set[str] = {
        _norm(str(row.get("skill_name") or ""))
        for entry in website_skill_evidence
        if entry.get("counted_for_project")
        for row in (entry.get("skills") or [])
        if str(row.get("skill_name") or "").strip()
    }
    # Per-session canonical mapped skills (same source of truth) so the Website
    # evidence TRACE cards attribute a proof only to the skills its behaviour
    # actually supports — never the raw stored ``supported_skills``. Parallel to
    # ``website_entries`` (``collect_website_skill_evidence`` yields one entry per
    # entry, in order), so zip re-associates each mapping with its session id.
    website_mapped_skills_by_session: dict[str, list[str]] = {}
    for _entry, _wse in zip(website_entries, website_skill_evidence):
        _sid = str(_entry.get("proof_session_id") or "")
        if not _sid:
            continue
        website_mapped_skills_by_session[_sid] = [
            str(r.get("skill_name"))
            for r in (_wse.get("skills") or [])
            if str(r.get("skill_name") or "").strip()
        ] if _wse.get("counted_for_project") else []

    pipeline_lookup = _build_pipeline_lookup(pipeline_db, user_id, skill_pipeline_ids) if skill_pipeline_ids else {}

    # A project whose owner never filled in ``claimed_skills`` but DID attach
    # analyzed evidence still gets an honest skill matrix: rows are derived from
    # the skills its attached evidence actually supports (document locators +
    # identity-matched website mappings). This is detection, not a student
    # claim — the report says so explicitly below. Nothing is derived from
    # titles or repo-level keyword matches.
    evidence_derived_skills: list[str] = []
    if not claimed_skills:
        seen_norm: set[str] = set()
        for entry in document_entries:
            for skill_name in entry.get("skills") or []:
                key = _norm(str(skill_name))
                if key and key not in seen_norm:
                    seen_norm.add(key)
                    evidence_derived_skills.append(str(skill_name))
        # Attached GitHub Proof contributes its analyzer-detected skills the same
        # way — the exact set ``_skill_evidence_row`` already treats as GitHub
        # support for a claimed skill — so a GitHub-only project is not silently
        # skill-less just because no other proof type is attached. Detection, not
        # a student claim; the shared limitation below says so explicitly.
        if github_proof is not None:
            for skill_name in github_proof.get("detected_skills") or []:
                key = _norm(str(skill_name))
                if key and key not in seen_norm:
                    seen_norm.add(key)
                    evidence_derived_skills.append(str(skill_name))
        for _entry, _wse in zip(website_entries, website_skill_evidence):
            if not _wse.get("counted_for_project"):
                continue
            for row in _wse.get("skills") or []:
                key = _norm(str(row.get("skill_name") or ""))
                if key and key not in seen_norm:
                    seen_norm.add(key)
                    evidence_derived_skills.append(str(row.get("skill_name")))
        evidence_derived_skills = evidence_derived_skills[:12]

    matrix_skills = claimed_skills or evidence_derived_skills

    skill_evidence = [
        _skill_evidence_row(
            skill,
            analysis,
            github_detected_skills,
            website_supported_skills,
            document_supported_skills,
            pipeline_lookup,
            video_chips,
            github_smart_skills,
        )
        for skill in matrix_skills
    ]
    if evidence_derived_skills and skill_evidence:
        for row in skill_evidence:
            row.setdefault("limitations", []).append(
                "Skill derived from attached, analyzed evidence — the student did not formally "
                "claim skills for this project."
            )

    # ── Evidence traceability (claim → concrete evidence source) ─────────────
    repo_is_public = _repo_is_public(db, github_proof)
    github_code_evidence = _github_code_evidence(db, github_proof)
    evidence_traces, traces_by_skill = _build_evidence_traces(
        github_proof=github_proof,
        github_code_evidence=github_code_evidence,
        repo_full_name=project.get("repo_full_name"),
        repo_url=(github_proof or {}).get("repo_url") or project.get("repo_url"),
        repo_is_public=repo_is_public,
        documents=document_entries,
        website_proofs=website_entries,
        website_details=website_details,
        website_mapped_skills_by_session=website_mapped_skills_by_session,
        analysis=analysis,
        defense_questions=defense_questions,
        video_chips=video_chips,
    )
    traces_index = {t["trace_id"]: t for t in evidence_traces}
    for row in skill_evidence:
        _enrich_skill_row(row, traces_by_skill.get(_norm(row["skill"]), []), traces_index)

    # ── Real-unmapped-proof context (private surfaces only) ──────────────────
    # REAL analyzed proof attached to this project that no exact skill row
    # consumed. Context only: never skill evidence, never counted anywhere, and
    # never included on public projections (the public builders allowlist their
    # fields and omit this one).
    real_unmapped_proof_context = _build_real_unmapped_proof_context(
        project_id=str(project["id"]),
        project_title=project.get("title") or "",
        skill_evidence=skill_evidence,
        github_proof=github_proof,
        github_code_evidence=github_code_evidence,
        github_smart_evidence_count=_collect_github_smart_project_evidence_count(
            db, user_id, project_repo_ids=project_repo_ids
        ),
        website_entries=website_entries,
        website_skill_evidence=website_skill_evidence,
        document_entries=document_entries,
        analysis=analysis,
        defense_questions=defense_questions,
    )

    # ── Other student proofs for related skills (cross-proof vault matches) ───
    # The primary skill matrix + evidence traces above are built ONLY from proofs
    # attached to THIS project, so it stays project-honest. Separately, we surface
    # the student's OTHER safe proofs (from their whole proof vault) that match
    # this project's claimed skills but are NOT attached to this project. These
    # are clearly labelled cross-proof / vault evidence and never folded into the
    # attached matrix — so e.g. a Website Proof attached to a different project is
    # never presented as if it belongs to this one. Lazy import breaks the import
    # cycle (the vault service imports scrubbers from this module).
    other_student_proofs: list[dict[str, Any]] = []
    suggested_evidence: list[dict[str, Any]] = []
    if include_cross_proof:
        try:
            from app.services.student_proof_vault_service import (
                collect_vault_items,
                vault_items_for_skills,
            )

            vault_items = collect_vault_items(db, pipeline_db, str(user_id))
            other_student_proofs = vault_items_for_skills(
                vault_items, claimed_skills, exclude_project_id=str(project["id"])
            )
        except Exception:  # pragma: no cover - the vault section is best-effort/additive
            vault_items = []
            other_student_proofs = []
        # "Suggested evidence to attach" (Step 4): unattached vault proofs whose
        # safe metadata points at THIS project. Owner-only, clearly labelled
        # "not counted until attached", never folded into the attached evidence
        # package, and never on the public report projection. Best-effort.
        try:
            from app.services.proof_attachment_intelligence import (
                classify_vault_attachments,
                suggested_evidence_for_project,
            )

            overview = classify_vault_attachments(
                vault_items,
                [
                    {
                        "project_id": str(project["id"]),
                        "project_title": project.get("title") or "",
                        "repo_full_name": project.get("repo_full_name"),
                        "claimed_skills": claimed_skills,
                    }
                ],
            )
            suggested_evidence = suggested_evidence_for_project(overview, str(project["id"]))
        except Exception:  # pragma: no cover - suggestions are additive, never blocking
            suggested_evidence = []

    # ── Limitations ──────────────────────────────────────────────────────────
    limitations: list[str] = []
    if github_proof is None:
        limitations.append("GitHub Proof not attached — repository evidence has not been independently checked.")
    counted_website_proof_count = sum(
        1 for entry in website_skill_evidence if entry.get("counted_for_project")
    )
    excluded_website_proof_count = max(0, len(website_skill_evidence) - counted_website_proof_count)
    if not website_skill_evidence:
        limitations.append("Website proof not attached.")
    elif counted_website_proof_count == 0:
        limitations.append(
            "No Website Proof has a confirmed, identity-matched relationship to this project."
        )
    if excluded_website_proof_count:
        limitations.append(
            f"{excluded_website_proof_count} Website Proof relationship"
            + (" is" if excluded_website_proof_count == 1 else "s are")
            + " excluded from project claims pending confirmation or mismatch repair."
        )
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
    if counted_website_proof_count == 0:
        next_actions.append(
            "Create or confirm a Website Proof explicitly linked to this project."
        )
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

    report = {
        "project_id": str(project["id"]),
        "project_title": project.get("title") or "",
        "project_description": metadata.get("description") or "",
        "repo_url": project.get("repo_url") or "",
        "repo_full_name": project.get("repo_full_name"),
        "deployed_url": project.get("deployed_url") or None,
        "student_role": metadata.get("student_role") or "",
        "claimed_skills": claimed_skills,
        # The persisted project workflow status may legitimately remain
        # ``questions_ready`` after answers were analyzed because Defense keeps
        # its completion marker in metadata.  The report must describe the
        # evidence state it is currently rendering, not expose that stale
        # internal workflow cursor.
        "project_status": (
            "defense complete"
            if project_defense_completed
            else (project.get("status") or "draft")
        ),
        "session_id": str(session["id"]) if session else None,
        "generated_at": _now_iso(),
        "evidence_package": {
            "github_proof_attached": github_proof is not None,
            "documents_count": len(documents),
            "website_proofs_count": counted_website_proof_count,
            "website_proofs_excluded_count": excluded_website_proof_count,
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
                "repo_is_public": repo_is_public,
            }
            if github_proof is not None
            else None
        ),
        "documents": documents,
        "website_proofs": website_proofs,
        "website_skill_evidence": website_skill_evidence,
        # Candidate↔project relationship: the assessment (owner/private input to
        # claim synthesis) and the renderable attribution block (closed
        # templates only; also projected onto the public report).
        "candidate_ownership": candidate_ownership,
        "candidate_attribution": candidate_attribution,
        "project_defense_analysis": _report_safe_analysis(analysis),
        "defense_questions": defense_questions,
        "defense_answer_evidence": defense_answer_evidence,
        "project_defense_inspection": project_defense_inspection,
        "video_evidence_chips": video_chips,
        "skill_evidence": skill_evidence,
        "evidence_traces": evidence_traces,
        "real_unmapped_proof_context": real_unmapped_proof_context,
        "other_student_proofs": other_student_proofs,
        "suggested_evidence": suggested_evidence,
        "limitations": limitations,
        "next_actions": next_actions,
        "preview_only": True,
        "public_recruiter_sharing_enabled": False,
    }

    # Canonical claim→evidence map — the ONE deterministic claim/citation/
    # relation/corroboration model shared with the Skill Report. Computed for
    # the single-project report view only: the Work Passport builds a report per
    # project with ``include_cross_proof=False`` and never reads this section.
    if include_cross_proof:
        from app.services.claim_evidence_synthesis_service import (
            build_project_claim_evidence_map,
        )

        report["claim_evidence_map"] = build_project_claim_evidence_map(report)
    else:
        report["claim_evidence_map"] = None
    _log_evidence_discovery_diagnostics(report, user_id=str(user_id))
    return report
