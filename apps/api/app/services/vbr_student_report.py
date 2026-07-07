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

from app.services.defense_answer_evidence_service import (
    MISSING_IMPLEMENTATION_EVIDENCE_LIMITATION,
)
from app.services.project_defense_inspection_service import (
    build_project_defense_inspection_cards,
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
    website_behavior_claim,
    website_evidence_source_types,
    website_limitation_for,
    website_purpose_summary,
    website_skill_relevance_summary,
    website_unmapped_skill_reason,
)

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

    if normalized in github_detected_skills:
        candidates.append((_SUPPORTING_EVIDENCE, "Detected in the attached GitHub Proof."))
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
    out: dict[str, dict[str, Any]] = {}
    for item in row.get("evidence_objects") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("skill_name") or "").strip()
        key = _norm(name)
        if not key or key in out:
            continue
        page = item.get("page_number")
        snippet = _trace_text(_scrub_score_fragments(str(item.get("snippet") or "")), 200) or None
        # A safe document citation: the section heading the analyzer matched the
        # skill under (e.g. "Methods", "System Design"). This is a structural
        # reference, never raw body text, so it is safe on the public surface.
        section = _trace_text(str(item.get("section_label") or ""), 80) or None
        out[key] = {
            "page_number": int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None,
            "snippet": snippet,
            "citation": section,
        }
    return out


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
            # Bare location labels — the UI renders these as "Doc: Page 2" /
            # "Doc: Citation" / "Doc: Snippet" / "Document" via ``matrixTraceLabel``.
            # Priority: page locator > section citation > snippet > matched-skill.
            if page is not None:
                location_type = "document_page"
                location_label = f"Page {page}"
                location_detail = (f"Page {page} · {citation}" if citation else f"Page {page}")
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
                    "public_url": None,
                    "public_url_label": None,
                    "timestamp": None,
                    "limitation": _DOC_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _PRIVATE_DOC_NOTE,
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
                "timestamp": None,
                "limitation": " ".join(website_limitations),
                "is_publicly_openable": safe,
                "private_evidence_note": (
                    None if safe else "Deployment URL is private or internal and is not publicly linked."
                ),
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
                    "timestamp": None,
                    "limitation": _WEBSITE_BEHAVIOUR_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _WEBSITE_ARTIFACT_NOTE,
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
        out.append(
            {
                "target_website": safe_target,
                "behavior_claim": website_behavior_claim(purpose_key),
                "website_purpose_key": purpose_key,
                "website_purpose_label": describe_website_purpose(purpose_key),
                "website_purpose_summary": website_purpose_summary(purpose_key),
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
        attach(
            {
                "trace_id": "project-defense",
                "source_type": _SRC_DEFENSE,
                "source_title": "Project Defense",
                "skill_names": defense_skills,
                "qualitative_status": _PARTIALLY_DEMONSTRATED if explained else _SUPPORTING_EVIDENCE,
                "safe_summary": _trace_text(
                    summary or "The candidate explained their own work and approach during the Project Defense."
                ),
                "safe_detail": (
                    "Process/ownership evidence: the candidate explained how and why they built the project."
                ),
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

    github_proof = attached.get("github_proof") if isinstance(attached.get("github_proof"), dict) else None
    documents_raw = attached.get("documents") if isinstance(attached.get("documents"), list) else []
    website_proofs_raw = attached.get("website_proofs") if isinstance(attached.get("website_proofs"), list) else []
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
        matched_norms = {
            _norm(s) for s in (doc.get("skills") or []) if _norm(s) in claimed_by_norm
        }
        matched_norms.update(key for key in locators if key in claimed_by_norm)
        matched = [claimed_by_norm[key] for key in claimed_by_norm if key in matched_norms]

        document_entries.append(
            {
                "title": str(doc.get("title") or "Document"),
                "source_type": doc.get("source_type"),
                "status": doc.get("status"),
                "skills": matched,
                # Keep only locators for matched (claimed) skills so an
                # ``evidence_objects`` entry for a skill the project never claimed
                # can never leak through as a document locator.
                "skill_locators": {key: val for key, val in locators.items() if key in matched_norms},
            }
        )

    documents = [
        {"title": e["title"], "source_type": e["source_type"], "status": e["status"]}
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
    project_defense_inspection = build_project_defense_inspection_cards(
        answer_evidence=defense_answer_evidence,
        video_chips=video_chips,
        project_title=str(project.get("title") or ""),
    )

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
    # The claimed skills that Website Proof supports — taken from the mapped
    # behavior-evidence above so the skill matrix, the passport
    # ``supporting_proof_types`` and the behavior-evidence cards can never
    # disagree. A skill only earns the "Website Proof" source chip when a mapped
    # skill row exists for it (extracted or safely derived); a generic website
    # that mapped nothing adds no Website Proof chip to any skill.
    website_supported_skills: set[str] = {
        _norm(str(row.get("skill_name") or ""))
        for entry in website_skill_evidence
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
        ]

    pipeline_lookup = _build_pipeline_lookup(pipeline_db, user_id, skill_pipeline_ids) if skill_pipeline_ids else {}

    skill_evidence = [
        _skill_evidence_row(
            skill,
            analysis,
            github_detected_skills,
            website_supported_skills,
            document_supported_skills,
            pipeline_lookup,
            video_chips,
        )
        for skill in claimed_skills
    ]

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
                "repo_is_public": repo_is_public,
            }
            if github_proof is not None
            else None
        ),
        "documents": documents,
        "website_proofs": website_proofs,
        "website_skill_evidence": website_skill_evidence,
        "project_defense_analysis": _report_safe_analysis(analysis),
        "defense_questions": defense_questions,
        "defense_answer_evidence": defense_answer_evidence,
        "project_defense_inspection": project_defense_inspection,
        "video_evidence_chips": video_chips,
        "skill_evidence": skill_evidence,
        "evidence_traces": evidence_traces,
        "other_student_proofs": other_student_proofs,
        "suggested_evidence": suggested_evidence,
        "limitations": limitations,
        "next_actions": next_actions,
        "preview_only": True,
        "public_recruiter_sharing_enabled": False,
    }
