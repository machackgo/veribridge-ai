"""Schemas for Project Defense Transcript Analysis."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    # ── Optional context from other evidence sources ───────────────────────────
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


class ProjectDefenseAnalysisResponse(BaseModel):
    """
    Stored result of a project defense transcript analysis.

    IMPORTANT: This feature does not set final_verification_status to
    "complete".  That requires a separate VeriBridge reviewer step.
    """

    id: str | None = None
    user_id: str
    proof_session_id: str

    video_url: str | None = None
    transcript_text: str = ""

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
