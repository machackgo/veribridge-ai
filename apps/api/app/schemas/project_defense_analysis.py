"""Schemas for Project Defense Transcript Analysis (including media upload)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TranscriptRefinementStatus = Literal[
    "not_started",
    "in_progress",
    "complete",
    "failed",
]

# ── Constants ──────────────────────────────────────────────────────────────────

ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {"mp4", "mov", "webm", "mp3", "wav", "m4a"}
)
ALLOWED_MEDIA_MIME_TYPES: frozenset[str] = frozenset({
    "video/mp4",
    "video/quicktime",         # .mov
    "video/webm",
    "audio/mpeg",              # .mp3
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",               # .m4a
    "audio/x-m4a",
    "audio/webm",
})
MAX_MEDIA_SIZE_BYTES: int = 200 * 1024 * 1024  # 200 MB

TranscriptionStatus = Literal[
    "not_started",
    "uploaded",
    "transcription_pending",
    "transcript_ready",
    "analysis_complete",
]


# ── Main request schema ────────────────────────────────────────────────────────

class ProjectDefenseAnalyzeRequest(BaseModel):
    """Request body for analysing a project defense transcript."""

    video_url: str | None = Field(
        default=None,
        description=(
            "Optional video URL (Loom, YouTube, Google Drive, Vimeo, etc.). "
            "Stored for future transcription; not processed in the MVP."
        ),
    )
    transcript_text: str = Field(
        default="",
        description=(
            "The spoken explanation pasted or typed by the student. "
            "This is the primary input for the MVP analysis pipeline."
        ),
    )
    claimed_skills: list[str] = Field(
        default_factory=list,
        description="Claimed skills from the proof session.",
    )
    proof_objective: str = Field(
        default="",
        description="What the student intends to demonstrate.",
    )
    # ── Optional context from other evidence sources ─────────────────────────
    workflow_summary: str = Field(
        default="",
        description="Brief summary text from an existing workflow analysis (if any).",
    )
    github_summary: str = Field(
        default="",
        description="Brief summary text from an existing GitHub analysis (if any).",
    )
    live_check_summary: str = Field(
        default="",
        description="Brief summary text from a live website check (if any).",
    )


# ── Main analysis response schema ──────────────────────────────────────────────

class ProjectDefenseAnalysisResponse(BaseModel):
    """
    Stored result of a project defense analysis.

    IMPORTANT: This feature does not set final_verification_status to
    "complete".  That requires a separate VeriBridge reviewer step.
    """

    id: str | None = None
    user_id: str
    proof_session_id: str

    # ── Media metadata ─────────────────────────────────────────────────────────
    video_url: str | None = None
    media_url: str | None = None
    media_type: str | None = None          # file extension: mp4 | mov | webm | mp3 | wav | m4a
    media_filename: str | None = None
    media_storage_path: str | None = None
    transcription_status: str = "not_started"
    transcript_reviewed: bool = False

    # ── Transcript ─────────────────────────────────────────────────────────────
    transcript_text: str = ""

    # ── Refinement fields ──────────────────────────────────────────────────────
    raw_transcript: str | None = Field(
        default=None,
        description="Verbatim ASR output — never overwritten after first save.",
    )
    refined_transcript: str | None = Field(
        default=None,
        description="AI-corrected version of the raw transcript.",
    )
    transcript_correction_summary: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of individual corrections made during refinement.",
    )
    transcript_glossary_matches: list[str] = Field(
        default_factory=list,
        description="Terms matched from the project-specific or base glossary.",
    )
    transcript_refinement_status: str = Field(
        default="not_started",
        description="Lifecycle status of the refinement pipeline.",
    )
    transcript_needs_review: bool = Field(
        default=False,
        description="True when confidence is low or many corrections were made.",
    )

    # ── AI-computed outputs ────────────────────────────────────────────────────
    transcript_summary: str = ""
    skills_mentioned: list[str] = Field(default_factory=list)
    skills_explained_well: list[str] = Field(default_factory=list)
    skills_missing_from_explanation: list[str] = Field(default_factory=list)

    consistency_with_evidence_score: int = Field(
        default=0, ge=0, le=100,
        description="How well the transcript matches existing evidence (0–100).",
    )
    explanation_clarity_score: int = Field(
        default=0, ge=0, le=100,
        description="How clearly the student explains the project (0–100).",
    )
    ownership_signal_score: int = Field(
        default=0, ge=0, le=100,
        description="How clearly the student claims personal ownership/contribution (0–100).",
    )
    technical_depth_score: int = Field(
        default=0, ge=0, le=100,
        description="How much technical detail the student provides (0–100).",
    )
    overall_defense_score: int = Field(
        default=0, ge=0, le=100,
        description="Overall weighted defense score (0–100).",
    )

    risk_flags: list[str] = Field(default_factory=list)
    recruiter_summary: str = ""
    recommended_improvements: list[str] = Field(default_factory=list)

    privacy_scan_status: str = "clean"   # 'clean' | 'redacted' | 'flagged'

    created_at: str | None = None
    updated_at: str | None = None


# ── Media upload response ──────────────────────────────────────────────────────

class ProjectDefenseMediaUploadResponse(BaseModel):
    """Response after registering an uploaded defense media file."""

    proof_session_id: str
    media_filename: str
    media_type: str
    media_size_bytes: int
    media_url: str | None = None
    media_storage_path: str | None = None
    transcription_status: str = "uploaded"
    storage_configured: bool = False
    message: str = ""


# ── Update transcript request ──────────────────────────────────────────────────

class ProjectDefenseUpdateTranscriptRequest(BaseModel):
    """PATCH request to update the transcript text and reviewed flag."""

    transcript_text: str = Field(
        default="",
        description="Reviewed and optionally edited transcript text.",
    )
    transcript_reviewed: bool = Field(
        default=False,
        description="True once the student has confirmed the transcript is accurate.",
    )


# ── Transcription response ────────────────────────────────────────────────────

class ProjectDefenseTranscribeResponse(BaseModel):
    """
    Response after attempting to transcribe a registered defense media file.

    When ``configured=False`` the transcript was not generated — the student
    should paste or edit the transcript manually.  This is NOT an error; it is
    a graceful fallback for deployments that have not set up a transcription
    provider.
    """

    proof_session_id: str
    transcript_text: str = ""
    transcription_status: str = "uploaded"   # transcript_ready when successful
    transcript_reviewed: bool = False
    provider_used: str = "none"
    configured: bool = False
    message: str = ""

    # ── Timestamped segments (when local_whisper/faster-whisper produced them) ───
    transcript_segments: list[dict[str, Any]] = Field(default_factory=list)

    # ── Refinement output (included when refinement ran automatically) ─────────
    raw_transcript: str | None = None
    refined_transcript: str | None = None
    transcript_correction_summary: list[dict[str, Any]] = Field(default_factory=list)
    transcript_glossary_matches: list[str] = Field(default_factory=list)
    transcript_refinement_status: str = "not_started"
    transcript_needs_review: bool = False
    refinement_display_summary: str = ""   # e.g. "Corrected: FastAPI, Google Maps API"


# ── Refine transcript request / response ──────────────────────────────────────

class ProjectDefenseRefineTranscriptRequest(BaseModel):
    """Request body for POST /defense/refine-transcript."""

    # Optional context overrides; if omitted the service reads from the session
    claimed_skills: list[str] = Field(default_factory=list)
    project_context: str = ""
    website_url: str | None = None
    github_url: str | None = None


class ProjectDefenseRefineTranscriptResponse(BaseModel):
    """Response from POST /defense/refine-transcript."""

    proof_session_id: str
    raw_transcript: str = ""
    refined_transcript: str = ""
    transcript_correction_summary: list[dict[str, Any]] = Field(default_factory=list)
    transcript_glossary_matches: list[str] = Field(default_factory=list)
    transcript_refinement_status: str = "complete"
    transcript_needs_review: bool = False
    confidence: float = 1.0
    refinement_display_summary: str = ""
    message: str = ""
