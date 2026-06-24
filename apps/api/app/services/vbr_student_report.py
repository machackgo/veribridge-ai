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

from app.services.safe_public_url import is_safe_public_url
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

    if analysis is not None:
        explained_well = {_norm(s) for s in analysis.get("skills_explained_well") or []}
        mentioned = {_norm(s) for s in analysis.get("skills_mentioned") or []}
        if normalized in explained_well:
            candidates.append((_DEMONSTRATED, "Explained clearly during the Project Defense."))
            supporting_sources.append(_SRC_DEFENSE)
        elif normalized in mentioned:
            candidates.append(
                (_PARTIALLY_DEMONSTRATED, "Mentioned during the Project Defense but not fully explained.")
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
        out[key] = {
            "page_number": int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None,
            "snippet": snippet,
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
    """
    base = str(repo_url or "").rstrip("/")
    if not base or not is_safe_public_url(base) or "github.com" not in base:
        return None
    ref = (str(branch or "").strip() or "HEAD")
    return f"{base}/blob/{ref}/{file_path.lstrip('/')}"


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
    repo_full_name: str | None,
    repo_url: str | None,
    repo_is_public: bool,
    documents: list[dict[str, Any]],
    website_proofs: list[dict[str, Any]],
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

    # ── GitHub Proof ─────────────────────────────────────────────────────────
    if github_proof is not None:
        detected = [str(s) for s in (github_proof.get("detected_skills") or [])]
        owner = github_proof.get("repo_owner")
        name = github_proof.get("repo_name")
        title = repo_full_name or (f"{owner}/{name}" if owner and name else None) or (repo_url or "GitHub repository")
        public_url = repo_url if (repo_is_public and is_safe_public_url(repo_url)) else None
        summary = _scrub_score_fragments(str(github_proof.get("public_safe_summary") or "")) or (
            "Repository analyzed; VeriBridge detected the skills below from its files and structure."
        )
        # Safe repo-relative evidence file paths the analyzer flagged. Present ⇒
        # we emit file-level traces (the recruiter lands on the exact file, not a
        # broad repo card); absent ⇒ we honestly fall back to the repo-level
        # trace below. The analyzer never stores line ranges or function names,
        # so file-level is the deepest honest GitHub granularity — we never
        # invent line numbers or functions.
        evidence_files = [str(f) for f in (github_proof.get("evidence_files") or []) if str(f).strip()]
        branch = github_proof.get("default_branch")

        _attach(
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
                "limitation": (
                    "Repository-level analysis detected related files and structure, but this is not line-level "
                    "proof and does not, by itself, prove the candidate personally authored every part."
                ),
                "is_publicly_openable": bool(public_url),
                "private_evidence_note": (
                    None if public_url else "Repository is private; only a recruiter-safe summary is shown."
                ),
            }
        )

        for file_path in evidence_files:
            file_url = _blob_url(repo_url, branch, file_path) if public_url else None
            _attach(
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
                        "This is file-level evidence; the analyzer does not record line ranges or function "
                        "names, so it is not line-level authorship proof."
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

    # ── Document Proof ───────────────────────────────────────────────────────
    # Documents are mapped ONLY to the skills the analyzer explicitly matched in
    # them (``doc["skills"]``, already narrowed to claimed skills upstream) — never
    # to every claimed skill. When a document matched no specific skill it is kept
    # as project-level context (``skill_names: []``) so it can never imply that a
    # skill was supported when the matrix row says otherwise.
    for idx, doc in enumerate(documents, start=1):
        title = str(doc.get("title") or "Document")
        status_label = str(doc.get("status") or "analyzed")
        doc_skills = [str(s) for s in (doc.get("skills") or [])]
        locators = doc.get("skill_locators") or {}

        if not doc_skills:
            # Project-level context: no matched skill, so it never implies a claim.
            _attach(
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
            # Bare location labels — the UI renders these as "Doc: Page 2" /
            # "Doc: Snippet" / "Document" via ``matrixTraceLabel``.
            if page is not None:
                location_type = "document_page"
                location_label = f"Page {page}"
                location_detail = f"Page {page}"
            elif snippet:
                location_type = "document_snippet"
                location_label = "Snippet"
                location_detail = "Matched passage"
            else:
                location_type = "document"
                location_label = "matched skill"
                location_detail = None
            _attach(
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
                    "public_url": None,
                    "public_url_label": None,
                    "timestamp": None,
                    "limitation": _DOC_LIMITATION,
                    "is_publicly_openable": False,
                    "private_evidence_note": _PRIVATE_DOC_NOTE,
                }
            )

    # ── Website Proof ────────────────────────────────────────────────────────
    for idx, wp in enumerate(website_proofs, start=1):
        target = str(wp.get("target_website") or "")
        safe = is_safe_public_url(target)
        supported = [str(s) for s in (wp.get("supported_skills") or [])]
        confidence = str(wp.get("workflow_confidence") or "insufficient")
        _attach(
            {
                "trace_id": f"website-proof-{idx}",
                "source_type": _SRC_WEBSITE,
                "source_title": target if safe else "Website Proof",
                "skill_names": supported,
                "qualitative_status": str(wp.get("evidence_strength") or _NOT_ASSESSED),
                "safe_summary": _trace_text(
                    f"A working deployment was inspected for the supported skills (workflow confidence: {confidence})."
                ),
                "safe_detail": (
                    "The deployed site was checked for the supported skills' working behaviour at inspection time."
                ),
                "evidence_anchor": f"website-proof-{idx}",
                "location_type": "website_url" if safe else "website_proof",
                "location_label": "Live URL" if safe else "Proof",
                "location_detail": _safe_domain(target) if safe else None,
                "public_url": target if safe else None,
                "public_url_label": "Open live website" if safe else None,
                "timestamp": None,
                "limitation": (
                    "Demonstrates the deployed behaviour at check time; it is not a guarantee of ongoing "
                    "uptime or of sole authorship."
                ),
                "is_publicly_openable": safe,
                "private_evidence_note": (
                    None if safe else "Deployment URL is private or internal and is not publicly linked."
                ),
            }
        )

    # ── Project Defense ──────────────────────────────────────────────────────
    if analysis is not None:
        explained = [str(s) for s in (analysis.get("skills_explained_well") or [])]
        mentioned = [str(s) for s in (analysis.get("skills_mentioned") or [])]
        defense_skills = _dedupe_skill_names(explained + mentioned)
        summary = _scrub_score_fragments(
            str(analysis.get("recruiter_summary") or analysis.get("transcript_summary") or "")
        )
        _attach(
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
        _attach(
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

    # ── Video Evidence chips ─────────────────────────────────────────────────
    for idx, chip in enumerate(video_chips, start=1):
        related = chip.get("related_skill")
        label = str(chip.get("label") or f"Video chip {idx}")
        _attach(
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

    return traces, by_skill


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
        matched = _dedupe_skill_names(
            [claimed_by_norm[_norm(s)] for s in (doc.get("skills") or []) if _norm(s) in claimed_by_norm]
        )
        # Recover safe per-skill page/snippet locators at report-build time
        # (never persisted into project metadata). Empty ⇒ locator-free trace.
        locators = (
            _document_skill_locators(db, user_id, str(doc.get("document_evidence_id") or ""))
            if matched
            else {}
        )
        document_entries.append(
            {
                "title": str(doc.get("title") or "Document"),
                "source_type": doc.get("source_type"),
                "status": doc.get("status"),
                "skills": matched,
                "skill_locators": locators,
            }
        )

    documents = [
        {"title": e["title"], "source_type": e["source_type"], "status": e["status"]}
        for e in document_entries
    ]
    # Skills the matrix may mark as Document-Proof-supported — identical to the set
    # used to build the document evidence traces, so the two never disagree.
    document_supported_skills = {_norm(s) for e in document_entries for s in e["skills"]}

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
            document_supported_skills,
            pipeline_lookup,
            video_chips,
        )
        for skill in claimed_skills
    ]

    # ── Evidence traceability (claim → concrete evidence source) ─────────────
    repo_is_public = _repo_is_public(db, github_proof)
    evidence_traces, traces_by_skill = _build_evidence_traces(
        github_proof=github_proof,
        repo_full_name=project.get("repo_full_name"),
        repo_url=(github_proof or {}).get("repo_url") or project.get("repo_url"),
        repo_is_public=repo_is_public,
        documents=document_entries,
        website_proofs=website_proofs,
        analysis=analysis,
        defense_questions=defense_questions,
        video_chips=video_chips,
    )
    traces_index = {t["trace_id"]: t for t in evidence_traces}
    for row in skill_evidence:
        _enrich_skill_row(row, traces_by_skill.get(_norm(row["skill"]), []), traces_index)

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
        "project_defense_analysis": _report_safe_analysis(analysis),
        "defense_questions": defense_questions,
        "video_evidence_chips": video_chips,
        "skill_evidence": skill_evidence,
        "evidence_traces": evidence_traces,
        "limitations": limitations,
        "next_actions": next_actions,
        "preview_only": True,
        "public_recruiter_sharing_enabled": False,
    }
