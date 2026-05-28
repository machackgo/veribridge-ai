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

VisualAnalysisStatus = Literal["available", "partial", "not_available"]

SupportLevel = Literal["strong", "partial", "weak", "missing"]

ResultValueSource = Literal["ocr", "dom", "event", "model_output_text"]


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


# ── Observed Demonstration schema ──────────────────────────────────────────────

class DetectedResultValue(BaseModel):
    """A single result value detected during the demonstration.

    E.g. { label: "dog", value: "0.89", confidence: 0.89, source: "model_output_text" }
    Populated only when frame/OCR analysis is available or DOM text captures the output.
    """
    label: str
    value: str
    confidence: float | None = None
    source: ResultValueSource


class DemonstrationSkillEvidence(BaseModel):
    """How a single skill is supported by a demonstration step."""
    skill: str
    support_level: SupportLevel
    reasoning: str


class DemonstrationStep(BaseModel):
    """One meaningful step in the observed demonstration timeline."""
    step_number: int
    timestamp_ms: int | None = None
    user_action: str
    observed_input: str | None = None
    observed_output: str | None = None
    visible_text_evidence: list[str] = Field(default_factory=list)
    detected_result_values: list[DetectedResultValue] = Field(default_factory=list)
    demonstrated_feature: str
    skill_evidence: list[DemonstrationSkillEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    needs_review: bool


class ObservedDemonstration(BaseModel):
    """Structured precise evidence about what was actually demonstrated.

    visual_analysis_status reflects whether frame/OCR evidence was used:
    - "available"     : video frames were sampled and OCR was applied
    - "partial"       : some DOM/text evidence was extracted but not full frame analysis
    - "not_available" : no frame/OCR available; inferred from event timeline only

    When visual_analysis_status is "not_available", detected_result_values in steps
    will be empty and the summary will say outputs were not readable from the timeline.
    """
    target_app: str
    visual_analysis_status: VisualAnalysisStatus
    steps: list[DemonstrationStep] = Field(default_factory=list)
    summary: str
    limitations: list[str] = Field(default_factory=list)


# ── API response model ─────────────────────────────────────────────────────────

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

    # ── Precise visual workflow evidence (v3) ──────────────────────────────────
    observed_demonstration: ObservedDemonstration | None = Field(
        default=None,
        description=(
            "Structured input→action→output evidence extracted from the workflow. "
            "visual_analysis_status='not_available' when frame/OCR is not yet implemented."
        ),
    )
    visual_analysis_status: VisualAnalysisStatus = Field(
        default="not_available",
        description="Whether frame/OCR evidence was used in this analysis",
    )

    # ── Progress tracking ──────────────────────────────────────────────────────
    # Computed at response time, not stored in DB.
    # After successful analysis all stages are "complete" and progress = 100.
    progress: int = Field(default=100, ge=0, le=100)
    current_stage: str = "AI reviewed"
    stages: list[AnalysisStage] = Field(default_factory=list)

    # ── Analysis metadata ──────────────────────────────────────────────────────
    analysis_stage: str = Field(default="complete", description="Current stage key")
    progress_percent: int = Field(default=100, ge=0, le=100)

    created_at: str
    updated_at: str | None = None
