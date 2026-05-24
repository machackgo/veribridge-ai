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

    created_at: str
    updated_at: str | None = None
