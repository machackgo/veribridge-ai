"""Schemas for Extension Proof Workflow Analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

WorkflowAnalysisType = Literal[
    "timeline_only",
    "video_frame_analysis",
    "full_multimodal_analysis",
]

WorkflowConfidence = Literal["high", "medium", "low", "insufficient"]

AnalysisStageStatus = Literal["pending", "in_progress", "complete", "failed", "coming_soon"]


class WorkflowAnalyzeRequest(BaseModel):
    claimed_skills: list[str] = Field(
        default_factory=list,
        description="Skills the student claims this workflow demonstrates",
    )
    proof_objective: str = Field(
        default="",
        description="What the student intended to demonstrate in this recording",
    )
    original_url: str = Field(
        default="",
        description="The starting URL that was opened for the proof session",
    )
    url_type: str = Field(
        default="invalid_url",
        description="Classification of the original URL (live_deployed_url / localhost_url / local_network_url / invalid_url)",
    )
    github_url: str | None = Field(
        default=None,
        description="GitHub repository URL associated with this proof (not scanned in this step)",
    )


class AnalysisStage(BaseModel):
    key: str
    label: str
    status: AnalysisStageStatus


class WorkflowAnalysisResponse(BaseModel):
    id: str
    proof_session_id: str
    analysis_type: WorkflowAnalysisType
    analyzer_version: str

    workflow_summary: str
    demonstrated_actions: list[str]

    supported_skills: list[str]
    weakly_supported_skills: list[str]
    unsupported_skills: list[str]

    evidence_strength_score: int = Field(ge=0, le=100)
    workflow_confidence: WorkflowConfidence

    missing_evidence: list[str]
    risk_flags: list[str]
    recruiter_summary: str
    student_improvement_suggestions: list[str]

    human_review_needed: bool

    # ── Target-site filtering metadata (v2) ────────────────────────────────────
    # These fields are informational — not included in recruiter_summary text.
    target_website: str = Field(
        default="",
        description="Domain/netloc of the proof target website that was analysed",
    )
    target_site_pages_count: int = Field(
        default=0,
        description="Number of pages visited on the target proof website",
    )
    supporting_evidence_count: int = Field(
        default=0,
        description="Number of supporting evidence pages visited (e.g. GitHub)",
    )
    noise_filtered_count: int = Field(
        default=0,
        description="Number of noise events filtered out (unrelated tabs, VeriBridge dashboard, Supabase)",
    )

    # Progress tracking — computed at response time, not stored in DB.
    # After successful analysis all stages are "complete" and progress = 100.
    progress: int = Field(default=100, ge=0, le=100)
    current_stage: str = "AI reviewed"
    stages: list[AnalysisStage] = Field(default_factory=list)

    created_at: str
    updated_at: str | None = None
