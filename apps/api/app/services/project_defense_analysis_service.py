"""
Project Defense Transcript Analysis Service.

Analyses a student's spoken project explanation (transcript) and compares it
against existing evidence sources (workflow analysis, GitHub analysis, live
website check, claimed skills) to produce a structured defense report.

This is project-agnostic — it does NOT contain hardcoded project names, URLs,
frameworks, or domains.  It works for:
    - frontend-only websites
    - full-stack apps
    - backend/API apps
    - ML/AI apps
    - dashboards
    - portfolios
    - local-only apps
    - cloud-deployed apps
    - future non-CS fields (civil, mechanical, business, etc.)

IMPORTANT:
    - final_verification_status is NEVER set to "complete" from this service.
    - If the transcript privacy scan is flagged, the result is hidden from
      recruiter/public view until reviewed.

Privacy:
    The transcript is scanned for sensitive data (API keys, tokens, credentials,
    PII) using the same patterns as WorkflowPrivacyScanService before storage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.services.workflow_privacy_scan_service import scan_proof_data

logger = logging.getLogger(__name__)

_TABLE = "project_defense_analysis_results"

# ── Minimum transcript length constants ───────────────────────────────────────
_MIN_WORDS_FOR_SHORT_PENALTY: int = 50    # fewer → "extremely short" penalty
_MIN_WORDS_FOR_LENGTH_BONUS: int = 100   # ≥ this → length bonus earned


# ── Ownership signal patterns ─────────────────────────────────────────────────
# Phrases that suggest the student personally built the project.
# Each phrase is matched case-insensitively.

_OWNERSHIP_PHRASES: list[str] = [
    r"\bi built\b",
    r"\bi implemented\b",
    r"\bi developed\b",
    r"\bi created\b",
    r"\bi designed\b",
    r"\bi wrote\b",
    r"\bi coded\b",
    r"\bi set up\b",
    r"\bmy implementation\b",
    r"\bmy approach\b",
    r"\bmy design\b",
    r"\bmy project\b",
    r"\bmy contribution\b",
    r"\bi was responsible for\b",
    r"\bi handled\b",
    r"\bi chose\b",
    r"\bi decided\b",
    r"\bi worked on\b",
    r"\bi integrated\b",
    r"\bi configured\b",
    r"\bi refactored\b",
    r"\bi optimized\b",
]
_OWNERSHIP_RE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _OWNERSHIP_PHRASES
]


# ── Technical depth signal patterns ───────────────────────────────────────────
# Words/phrases that indicate technical depth, not vague generic answers.

_TECH_DEPTH_PHRASES: list[str] = [
    r"\barchitecture\b",
    r"\bcomponent\b",
    r"\bapi\b",
    r"\bendpoint\b",
    r"\bdatabase\b",
    r"\bmodel\b",
    r"\balgorithm\b",
    r"\bdeployment\b",
    r"\bperformance\b",
    r"\bcaching\b",
    r"\bauthentication\b",
    r"\bauthorization\b",
    r"\bmiddleware\b",
    r"\bschema\b",
    r"\bpipeline\b",
    r"\bworkflow\b",
    r"\binterface\b",
    r"\bstate management\b",
    r"\basynchronous\b",
    r"\bconcurrency\b",
    r"\bscalability\b",
    r"\bsecurity\b",
    r"\btesting\b",
    r"\bunit test\b",
    r"\bintegration test\b",
    r"\bcontainer\b",
    r"\bmicroservice\b",
    r"\bmonorepo\b",
    r"\bci[/\s]?cd\b",
    r"\brefactor\b",
    r"\boptimization\b",
    r"\blatency\b",
    r"\bthroughput\b",
    r"\bdesign pattern\b",
    r"\bdata flow\b",
    r"\bresponse time\b",
    r"\binput\b.*\boutput\b",
    r"\berror handling\b",
    r"\bvalidation\b",
]
_TECH_DEPTH_RE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _TECH_DEPTH_PHRASES
]


# ── Limitations / future improvements signal ──────────────────────────────────

_LIMITATION_PHRASES: list[str] = [
    r"\blimitation\b",
    r"\bimprove\b",
    r"\bimprovement\b",
    r"\bfuture\b",
    r"\bnext step\b",
    r"\bwould add\b",
    r"\bwould improve\b",
    r"\bcould be better\b",
    r"\bscale\b",
    r"\bcould add\b",
    r"\bnot yet\b",
    r"\bpending\b",
    r"\btodo\b",
    r"\btradeoff\b",
    r"\btrade.off\b",
    r"\bdecision\b",
    r"\bchallenge\b",
    r"\bobstacle\b",
]
_LIMITATION_RE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _LIMITATION_PHRASES
]


# ── Generic / vague explanation signals ───────────────────────────────────────
# Phrases that suggest a copy-pasted or extremely generic answer.

_VAGUE_PHRASES: list[str] = [
    r"\bbasically\b.*\bbasically\b",           # "basically … basically"
    r"\bvery good project\b",
    r"\bamazing project\b",
    r"\bgreat application\b",
    r"\bgreat app\b",
    r"\bsimply amazing\b",
    r"\bthis project is about\b.*\bthis project is about\b",
    r"\bused many technologies\b",
    r"\bfull stack\b.*\bfull stack\b",         # repeated without substance
    r"\bi learned a lot\b",
    r"\bgood project\b",
    r"\binteresting project\b",
    r"\bcomplex application\b",
]
_VAGUE_RE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _VAGUE_PHRASES
]


# ── Problem framing signals ────────────────────────────────────────────────────

_PROBLEM_PHRASES: list[str] = [
    r"\bproblem\b",
    r"\bsolution\b",
    r"\bgoal\b",
    r"\bpurpose\b",
    r"\bchallenge\b",
    r"\bneed\b.*\bsolve\b",
    r"\bsolve\b",
    r"\bbuild\b",
    r"\bcreate\b",
    r"\bdemo\b",
    r"\bshow\b",
    r"\bprove\b",
]
_PROBLEM_RE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _PROBLEM_PHRASES
]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class DefenseAnalysisResult:
    """Pure-computation result of a transcript analysis."""

    transcript_summary: str = ""
    skills_mentioned: list[str] = field(default_factory=list)
    skills_explained_well: list[str] = field(default_factory=list)
    skills_missing_from_explanation: list[str] = field(default_factory=list)
    consistency_with_evidence_score: int = 0
    explanation_clarity_score: int = 0
    ownership_signal_score: int = 0
    technical_depth_score: int = 0
    overall_defense_score: int = 0
    risk_flags: list[str] = field(default_factory=list)
    recruiter_summary: str = ""
    recommended_improvements: list[str] = field(default_factory=list)
    privacy_scan_status: str = "clean"


# ── Pure analysis function ────────────────────────────────────────────────────

def analyze_defense_transcript(
    *,
    transcript_text: str,
    claimed_skills: list[str],
    proof_objective: str = "",
    workflow_summary: str = "",
    github_summary: str = "",
    live_check_summary: str = "",
) -> DefenseAnalysisResult:
    """
    Analyse a project defense transcript and return a structured result.

    This function is pure (no DB, no side effects) and project-agnostic.
    It does NOT hardcode any project name, URL, framework, or discipline.

    Scoring:
        +20  transcript exists and is long enough (≥100 words)
        +20  claimed skills are mentioned naturally
        +20  explanation matches other evidence sources
        +15  student explains their own role / contribution
        +15  technical/project depth is present
        +10  limitations / future improvements explained

    Deductions:
        -10  vague or generic explanation
        -15  transcript contradicts evidence
        -10  claimed skills never mentioned
        -10  no role/ownership signal
        -10  extremely short transcript (<50 words)
        -5   suspicious copy-paste generic text
    """
    result = DefenseAnalysisResult()

    # ── Privacy scan on transcript ─────────────────────────────────────────────
    privacy_result = scan_proof_data({"transcript": transcript_text})
    result.privacy_scan_status = privacy_result.status
    if privacy_result.contains_sensitive_data:
        result.risk_flags.append(
            "Transcript contains potential sensitive data "
            "(API keys, tokens, credentials, or PII). "
            "This defense is hidden from recruiter/public view until reviewed."
        )

    # ── Basic transcript checks ────────────────────────────────────────────────
    text = (transcript_text or "").strip()
    words = text.split() if text else []
    word_count = len(words)

    if word_count == 0:
        result.transcript_summary = "No transcript provided."
        result.recruiter_summary = (
            "No project defense transcript was submitted for this proof session."
        )
        result.recommended_improvements.append(
            "Submit a written or recorded transcript explaining what you built, "
            "the tools you used, and how the project demonstrates your claimed skills."
        )
        return result

    score = 0
    risk_flags: list[str] = list(result.risk_flags)
    improvements: list[str] = []
    lower = text.lower()

    # ── 1. Length bonus (+20) / extreme-short penalty (-10) ───────────────────
    if word_count >= _MIN_WORDS_FOR_LENGTH_BONUS:
        score += 20
    elif word_count < _MIN_WORDS_FOR_SHORT_PENALTY:
        score = max(0, score - 10)
        risk_flags.append(
            f"Transcript is extremely short ({word_count} words). "
            "A meaningful defense should be at least 100–200 words."
        )
        improvements.append(
            "Expand the transcript to at least 100 words. "
            "Cover the problem, what you built, tools used, and a key feature demo."
        )

    # ── 2. Skills mentioned in transcript (+20) / none mentioned (-10) ────────
    skills_mentioned: list[str] = []
    skills_missing: list[str] = []
    for skill in claimed_skills:
        # Match the skill name (or major words in it) case-insensitively
        skill_words = [w for w in re.split(r"[\s/._-]+", skill) if len(w) >= 3]
        if skill_words:
            pattern = "|".join(re.escape(w) for w in skill_words)
            if re.search(pattern, text, re.IGNORECASE):
                skills_mentioned.append(skill)
            else:
                skills_missing.append(skill)
        else:
            if re.search(re.escape(skill), text, re.IGNORECASE):
                skills_mentioned.append(skill)
            else:
                skills_missing.append(skill)

    if skills_mentioned:
        score += 20
    elif claimed_skills:
        score = max(0, score - 10)
        risk_flags.append(
            "None of the claimed skills were explicitly mentioned in the transcript."
        )
        improvements.append(
            "Name the specific technologies and skills you used (e.g., React, "
            "FastAPI, PostgreSQL) directly in your explanation."
        )

    # Skills explained well = mentioned + clarity from context
    skills_explained_well: list[str] = []
    for skill in skills_mentioned:
        # A skill is "explained well" if it appears in a sentence that also
        # contains at least one ownership or depth signal.
        sentences = re.split(r"[.!?]", text)
        for sentence in sentences:
            s_lower = sentence.lower()
            skill_words = [w for w in re.split(r"[\s/._-]+", skill) if len(w) >= 3]
            skill_pat = "|".join(re.escape(w) for w in skill_words) if skill_words else re.escape(skill)
            if not re.search(skill_pat, sentence, re.IGNORECASE):
                continue
            has_ownership = any(p.search(s_lower) for p in _OWNERSHIP_RE)
            has_depth = any(p.search(s_lower) for p in _TECH_DEPTH_RE)
            if has_ownership or has_depth:
                skills_explained_well.append(skill)
                break
    # If no explanation context: every mentioned skill defaults to partially explained
    if skills_mentioned and not skills_explained_well:
        skills_explained_well = skills_mentioned[:max(1, len(skills_mentioned) // 2)]

    result.skills_mentioned = skills_mentioned
    result.skills_explained_well = list(dict.fromkeys(skills_explained_well))
    result.skills_missing_from_explanation = skills_missing

    # ── 3. Contradiction check (always, regardless of evidence context) ──────────
    # Detects language that suggests the student did not author the work.
    _CONTRADICTION_RE = re.compile(
        r"\b(?:did not use|never used|did not build|didn't build|not mine|"
        r"not my work|i did not write|copy[- ]paste[d]?|borrowed code|"
        r"found online|downloaded from)\b",
        re.IGNORECASE,
    )
    contradiction_found = False
    if _CONTRADICTION_RE.search(text):
        score = max(0, score - 15)
        contradiction_found = True
        risk_flags.append(
            "Transcript contains language that may contradict evidence or ownership claims. "
            "Review the transcript before submitting for recruiter review."
        )

    # ── 4. Evidence consistency (+20) ────────────────────────────────────────
    # Build a combined context string from existing evidence summaries
    evidence_context = " ".join(
        filter(None, [workflow_summary, github_summary, live_check_summary])
    ).lower()
    consistency_score = 0

    if evidence_context:
        # Extract tech words from evidence that also appear in transcript
        evidence_tokens = set(re.findall(r"\b[a-z][a-z0-9\-+#.]{2,}\b", evidence_context))
        transcript_tokens = set(re.findall(r"\b[a-z][a-z0-9\-+#.]{2,}\b", lower))
        common = evidence_tokens & transcript_tokens
        # Filter out stop words
        stop = {"the", "and", "for", "this", "that", "with", "from", "have",
                "been", "are", "was", "were", "has", "but", "not", "also",
                "can", "its", "some", "use", "used", "using", "into", "will"}
        common = common - stop
        # Normalise to [0, 20]
        if evidence_tokens - stop:
            overlap_ratio = len(common) / max(len(evidence_tokens - stop), 1)
            consistency_score = min(20, int(overlap_ratio * 40))
            score += consistency_score
    else:
        # No evidence to compare — partial credit for just having a transcript
        if word_count >= _MIN_WORDS_FOR_LENGTH_BONUS:
            consistency_score = 10
            score += 10

    result.consistency_with_evidence_score = min(100, consistency_score * 5)

    # ── 4. Ownership signal (+15) / no ownership signal (-10) ─────────────────
    ownership_matches = sum(1 for p in _OWNERSHIP_RE if p.search(text))
    if ownership_matches >= 2:
        score += 15
        result.ownership_signal_score = min(100, 50 + ownership_matches * 5)
    elif ownership_matches == 1:
        score += 8
        result.ownership_signal_score = 40
        improvements.append(
            "Use first-person ownership language more explicitly. "
            "Say 'I built X', 'I implemented Y', or 'my approach was Z' throughout."
        )
    else:
        score = max(0, score - 10)
        result.ownership_signal_score = 10
        risk_flags.append(
            "No clear ownership signal detected in the transcript. "
            "Use first-person language ('I built', 'I designed', 'my approach') "
            "to demonstrate this is your own work."
        )
        improvements.append(
            "Add clear first-person ownership statements: 'I built', 'I implemented', "
            "'my design decision was…' to demonstrate personal contribution."
        )

    # ── 5. Technical depth (+15) ───────────────────────────────────────────────
    depth_matches = sum(1 for p in _TECH_DEPTH_RE if p.search(text))
    if depth_matches >= 4:
        score += 15
        result.technical_depth_score = min(100, 50 + depth_matches * 3)
    elif depth_matches >= 2:
        score += 8
        result.technical_depth_score = 40
        improvements.append(
            "Add more technical detail: explain how key components work, "
            "what data flows where, or what tradeoffs you considered."
        )
    else:
        result.technical_depth_score = 15
        improvements.append(
            "Include more technical depth: mention architecture decisions, "
            "how the main feature works end-to-end, and any tradeoffs you made."
        )

    # ── 6. Limitations / future improvements (+10) ────────────────────────────
    limitation_matches = sum(1 for p in _LIMITATION_RE if p.search(text))
    if limitation_matches >= 2:
        score += 10
    elif limitation_matches == 1:
        score += 5
    else:
        improvements.append(
            "Mention at least one limitation or improvement: what you would do "
            "differently, what could be scaled further, or what you plan to add."
        )

    # ── 7. Vague/generic penalty (-10) ────────────────────────────────────────
    vague_matches = sum(1 for p in _VAGUE_RE if p.search(text))
    if vague_matches >= 2:
        score = max(0, score - 10)
        risk_flags.append(
            "Transcript contains vague or generic language. "
            "Add specific technical details about your implementation."
        )
        improvements.append(
            "Replace generic phrases like 'amazing project' or 'great app' with "
            "specific descriptions of what you built and how it works."
        )
    elif vague_matches == 1:
        score = max(0, score - 5)
        improvements.append(
            "Avoid vague generic phrases. Be specific about your implementation choices."
        )

    # ── 8. Problem framing bonus ───────────────────────────────────────────────
    # Not a requirement, but shows student understands the goal.
    problem_matches = sum(1 for p in _PROBLEM_RE if p.search(text))
    if problem_matches < 2:
        improvements.append(
            "Start by briefly explaining the problem or goal your project addresses. "
            "Recruiters value students who can frame 'why' before 'how'."
        )

    # ── Explanation clarity score (derived) ───────────────────────────────────
    # Based on word count, problem framing, and depth signals.
    clarity = 0
    if word_count >= _MIN_WORDS_FOR_LENGTH_BONUS:
        clarity += 30
    elif word_count >= _MIN_WORDS_FOR_SHORT_PENALTY:
        clarity += 15
    clarity += min(30, problem_matches * 5)
    clarity += min(40, depth_matches * 5)
    result.explanation_clarity_score = min(100, clarity)

    # ── Cap score at 100 ──────────────────────────────────────────────────────
    score = max(0, min(100, score))
    result.overall_defense_score = score

    # ── Transcript summary ─────────────────────────────────────────────────────
    _first_sentence = text.split(".")[0].strip()
    if len(_first_sentence) > 200:
        _first_sentence = _first_sentence[:200] + "…"
    result.transcript_summary = (
        f"Transcript ({word_count} words): "
        + (_first_sentence if _first_sentence else "No summary available.")
    )

    # ── Recruiter summary ─────────────────────────────────────────────────────
    if score >= 80:
        result.recruiter_summary = (
            "Project defense transcript analyzed. "
            "The student provided a clear, technically detailed explanation "
            "that aligns with the submitted evidence and claimed skills."
        )
    elif score >= 60:
        result.recruiter_summary = (
            "Project defense transcript analyzed. "
            "The explanation supports several claimed skills with moderate depth. "
            "Some areas could be strengthened with more specificity."
        )
    elif score >= 40:
        result.recruiter_summary = (
            "Project defense transcript analyzed. "
            "The transcript needs clearer explanation of skills and ownership. "
            "Follow the recommended improvements before recruiter review."
        )
    else:
        result.recruiter_summary = (
            "Project defense transcript analyzed. "
            "The explanation is too brief or lacks sufficient technical detail "
            "and ownership signals to support the claimed skills."
        )

    if result.privacy_scan_status == "flagged":
        result.recruiter_summary += (
            " NOTE: This defense is hidden from recruiter view — "
            "the transcript contains potential sensitive data."
        )

    result.risk_flags = list(dict.fromkeys(risk_flags))
    result.recommended_improvements = list(dict.fromkeys(improvements))

    return result


# ── DB-backed service ──────────────────────────────────────────────────────────

class ProjectDefenseAnalysisService:
    """Stores and retrieves project defense analysis results."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def store_analysis(
        self,
        user_id: str,
        proof_session_id: str,
        video_url: str | None,
        transcript_text: str,
        result: DefenseAnalysisResult,
        *,
        media_type: str | None = None,
        media_filename: str | None = None,
        media_storage_path: str | None = None,
        media_url: str | None = None,
        transcript_reviewed: bool = False,
    ) -> dict[str, Any]:
        """Insert or update an analysis row (upsert on proof_session_id)."""
        now = _now()
        data: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "video_url": video_url or None,
            "media_url": media_url or None,
            "media_type": media_type or None,
            "media_filename": media_filename or None,
            "media_storage_path": media_storage_path or None,
            "transcription_status": "analysis_complete",
            "transcript_reviewed": transcript_reviewed,
            "transcript_text": transcript_text,
            "transcript_summary": result.transcript_summary,
            "skills_mentioned": result.skills_mentioned,
            "skills_explained_well": result.skills_explained_well,
            "skills_missing_from_explanation": result.skills_missing_from_explanation,
            "consistency_with_evidence_score": result.consistency_with_evidence_score,
            "explanation_clarity_score": result.explanation_clarity_score,
            "ownership_signal_score": result.ownership_signal_score,
            "technical_depth_score": result.technical_depth_score,
            "overall_defense_score": result.overall_defense_score,
            "risk_flags": result.risk_flags,
            "recruiter_summary": result.recruiter_summary,
            "recommended_improvements": result.recommended_improvements,
            "privacy_scan_status": result.privacy_scan_status,
        }

        if isinstance(self._client, dict):
            # Preserve existing media fields if already set
            existing = self._client.get(_TABLE, {}).get(proof_session_id, {})
            for field in ("media_url", "media_type", "media_filename", "media_storage_path"):
                if data[field] is None and existing.get(field):
                    data[field] = existing[field]
            row = {"id": str(uuid4()), "created_at": now, "updated_at": now, **data}
            self._client.setdefault(_TABLE, {})[proof_session_id] = row
            return row

        try:
            res = (
                self._client.table(_TABLE)
                .upsert({**data, "updated_at": now}, on_conflict="proof_session_id")
                .execute()
            )
            rows = getattr(res, "data", []) or []
            if rows:
                return rows[0]
        except Exception as exc:
            logger.warning("Project defense DB store failed (non-critical): %s", exc)
        return {**data, "created_at": now, "updated_at": now}

    def register_media(
        self,
        user_id: str,
        proof_session_id: str,
        *,
        media_filename: str,
        media_type: str,
        media_size_bytes: int,
        media_url: str | None = None,
        media_storage_path: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a stub row for a media upload before analysis runs.

        If a full analysis row already exists, only the media fields are updated.
        """
        now = _now()

        # db_fields contains only columns that exist in project_defense_analysis_results.
        # media_size_bytes is NOT a table column — keep it in the response dict only.
        db_fields: dict[str, Any] = {
            "user_id": user_id,
            "proof_session_id": proof_session_id,
            "media_filename": media_filename,
            "media_type": media_type,
            "media_url": media_url or None,
            "media_storage_path": media_storage_path or None,
            "transcription_status": "uploaded",
        }
        # Full stub (includes media_size_bytes) returned to callers for in-memory store
        stub: dict[str, Any] = {**db_fields, "media_size_bytes": media_size_bytes}

        if isinstance(self._client, dict):
            existing = self._client.get(_TABLE, {}).get(proof_session_id, {})
            row = {
                "id": existing.get("id") or str(uuid4()),
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
                **existing,
                **stub,
            }
            self._client.setdefault(_TABLE, {})[proof_session_id] = row
            return row

        res = (
            self._client.table(_TABLE)
            .upsert({**db_fields, "updated_at": now}, on_conflict="proof_session_id")
            .execute()
        )
        rows = getattr(res, "data", []) or []
        if rows:
            return rows[0]
        # Supabase upsert returned no rows but didn't raise — surface as an error
        raise RuntimeError(
            f"register_media upsert returned no rows for session {proof_session_id!r}. "
            "Check that the proof_session_id UNIQUE constraint exists on "
            "project_defense_analysis_results."
        )

    def update_transcript(
        self,
        user_id: str,
        proof_session_id: str,
        *,
        transcript_text: str,
        transcript_reviewed: bool = False,
    ) -> dict[str, Any] | None:
        """Update the transcript text and reviewed flag on an existing row.

        Sets transcription_status = 'transcript_ready' once reviewed.
        Returns None if no row exists for this session.
        """
        now = _now()
        new_status = "transcript_ready" if transcript_reviewed else "uploaded"
        patch: dict[str, Any] = {
            "transcript_text": transcript_text,
            "transcript_reviewed": transcript_reviewed,
            "transcription_status": new_status,
            "updated_at": now,
        }

        if isinstance(self._client, dict):
            existing = self._client.get(_TABLE, {}).get(proof_session_id)
            if existing is None:
                return None
            existing.update(patch)
            return existing

        try:
            res = (
                self._client.table(_TABLE)
                .update(patch)
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .execute()
            )
            rows = getattr(res, "data", []) or []
            return rows[0] if rows else None
        except Exception as exc:
            logger.warning("Project defense transcript update failed: %s", exc)
            return None

    def save_transcription_result(
        self,
        user_id: str,
        proof_session_id: str,
        *,
        transcript_text: str,
        privacy_scan_status: str = "clean",
    ) -> dict[str, Any]:
        """
        Save an auto-generated transcript from the transcription provider.

        Sets transcription_status = 'transcript_ready' and transcript_reviewed =
        False so the student can review the text before running analysis.
        """
        now = _now()
        patch: dict[str, Any] = {
            "transcript_text": transcript_text,
            "transcript_reviewed": False,
            "transcription_status": "transcript_ready",
            "privacy_scan_status": privacy_scan_status,
            "updated_at": now,
        }

        if isinstance(self._client, dict):
            existing = self._client.get(_TABLE, {}).get(proof_session_id, {})
            row = {**existing, **patch}
            self._client.setdefault(_TABLE, {})[proof_session_id] = row
            return row

        try:
            res = (
                self._client.table(_TABLE)
                .update(patch)
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .execute()
            )
            rows = getattr(res, "data", []) or []
            return rows[0] if rows else {**patch, "proof_session_id": proof_session_id}
        except Exception as exc:
            logger.warning("Project defense transcription save failed: %s", exc)
            return {**patch, "proof_session_id": proof_session_id}

    def get_analysis(
        self,
        user_id: str,
        proof_session_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve the stored analysis result for a session."""
        if isinstance(self._client, dict):
            return self._client.get(_TABLE, {}).get(proof_session_id)

        try:
            res = (
                self._client.table(_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("proof_session_id", proof_session_id)
                .maybe_single()
                .execute()
            )
            return res.data if res else None
        except Exception as exc:
            logger.warning("Project defense DB fetch failed: %s", exc)
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).isoformat()
