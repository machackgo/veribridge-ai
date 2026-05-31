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

VisualAnalysisStatus = Literal[
    # v5 provider-agnostic visual frame analysis statuses
    "analyzed",         # frames captured and analyzed by configured provider
    "pending",          # frames stored, analysis queued
    "skipped",          # frames stored but analysis skipped (no bytes)
    "failed",           # provider encountered an error
    "not_configured",   # no VISUAL_ANALYSIS_PROVIDER set (safe default)
    # Legacy values kept for backward compatibility with stored rows / old analysis results
    "available",        # old: frame/OCR evidence available (pre-v5)
    "partial",          # old: partial frame evidence
    "not_available",    # old: no frame/OCR (pre-v5 label, replaced by not_configured)
    "not_captured",     # edge case: maps to not_configured when returned from frame store
]

# Distinct from visual_analysis_status (OCR/frame).
# Reflects DOM-text snapshot capture by the browser extension.
VisibleEvidenceStatus = Literal[
    "available",      # full DOM evidence captured; result values extracted
    "partial",        # some DOM events captured, partial result extraction
    "not_captured",   # old recording — extension did not send visible evidence
]

SupportLevel = Literal["strong", "partial", "weak", "missing"]

ResultValueSource = Literal["ocr", "dom", "event", "model_output_text"]

# Evidence source for a demonstration step
EvidenceSource = Literal["dom_snapshot", "event_metadata", "inferred_from_click"]


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
    note: str | None = None   # optional warning / context for this stage


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
    # v4: evidence provenance per step
    evidence_source: EvidenceSource = Field(
        default="event_metadata",
        description=(
            "dom_snapshot = enriched with captured DOM text; "
            "event_metadata = inferred from browser events only; "
            "inferred_from_click = only a click event, low confidence"
        ),
    )


class ObservedDemonstration(BaseModel):
    """Structured precise evidence about what was actually demonstrated.

    visual_analysis_status reflects whether frame/OCR evidence was used (v5 values):
    - "analyzed"        : provider ran and frames were analyzed
    - "not_configured"  : VISUAL_ANALYSIS_PROVIDER not set (safe default)
    - "pending"         : frames stored, analysis queued
    - "skipped"         : frames stored but analysis skipped
    - "failed"          : provider error
    Legacy (pre-v5, kept for backward compatibility):
    - "available", "partial", "not_available"

    visible_evidence_status reflects DOM-text capture by the browser extension:
    - "available"     : full DOM snapshots captured; result values may be extracted
    - "partial"       : some events captured but incomplete coverage
    - "not_captured"  : old recording — extension did not send DOM snapshots

    When visual_analysis_status is "not_configured" AND visible_evidence_status is
    "not_captured", detected_result_values will be empty and the summary will say
    outputs were not readable from the timeline.
    """
    target_app: str
    visual_analysis_status: VisualAnalysisStatus
    visible_evidence_status: VisibleEvidenceStatus = "not_captured"
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

    # ── Precise visual workflow evidence (v3/v4/v5) ───────────────────────────
    observed_demonstration: ObservedDemonstration | None = Field(
        default=None,
        description=(
            "Structured input→action→output evidence extracted from the workflow. "
            "visual_analysis_status='not_configured' when no provider is set. "
            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr|local_vision|openai to enable. "
            "visible_evidence_status reflects DOM text capture from the extension."
        ),
    )
    visual_analysis_status: VisualAnalysisStatus = Field(
        default="not_configured",
        description=(
            "Visual frame analysis status: "
            "not_configured (default, safe) | analyzed | pending | skipped | failed. "
            "Set VISUAL_ANALYSIS_PROVIDER to enable."
        ),
    )
    visible_evidence_status: VisibleEvidenceStatus = Field(
        default="not_captured",
        description=(
            "Whether DOM-visible text evidence was captured by the browser extension. "
            "'available' = full capture with result values; "
            "'partial' = partial capture; "
            "'not_captured' = old recording (extension update needed)"
        ),
    )

    # ── Progress tracking ──────────────────────────────────────────────────────
    # ── Video keyframe evidence (Phase 0 — unified recorder) ──────────────────
    # Populated by live query against workflow_visual_frame_evidence at response time.
    # None when no video was uploaded for this session.
    video_keyframe_status: str | None = Field(
        default=None,
        description=(
            "'extracted' when keyframes were extracted from the uploaded WebM video. "
            "'failed' when the video was uploaded but extraction failed. "
            "None when no video was recorded for this session."
        ),
    )
    video_keyframe_count: int = Field(
        default=0,
        description="Number of keyframes extracted from the uploaded video (0 when not extracted).",
    )
    video_keyframe_timestamps_ms: list[int] = Field(
        default_factory=list,
        description="Timestamps (ms from start) of each extracted keyframe. Empty when no video.",
    )
    video_duration_ms: int | None = Field(
        default=None,
        description="Duration of the uploaded video in milliseconds (None when no video).",
    )
    video_upload_error: str | None = Field(
        default=None,
        description="Exact error reason from the backend when video_keyframe_status='failed'.",
    )

    # ── Sequence analysis (v6 — Week 3) ──────────────────────────────────────
    # Multi-frame temporal chain: keyframes + DOM + visible evidence.
    # Serialised via to_public_dict() — no raw paths or private metadata.
    # None when no keyframes or insufficient frames for sequence analysis.
    sequence_analysis: dict | None = Field(
        default=None,
        description=(
            "Sequence analysis result (v6). "
            "Contains sequence_analysis_status, analyzed_frame_count, "
            "workflow_stage_summaries, input_action_output_chain, before_after_changes, "
            "observed_outputs, supported_skills, evidence_strength, confidence_score. "
            "None when video keyframes or DOM events are insufficient."
        ),
    )

    # ── Video upload status ────────────────────────────────────────────────────
    # Whether a video was uploaded for this session.
    # Derived from video_keyframe_status at response time.
    video_upload_status: str = Field(
        default="none",
        description=(
            "'uploaded' when the video upload completed and keyframes were extracted or attempted. "
            "'none' when no video was recorded. "
            "'failed' when keyframe extraction failed."
        ),
    )

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
