"""Schemas for Project Defense (Phase 1 — individual project defense MVP).

Phase 1 scope: a student creates an individual Project Defense identity,
attaches existing proof sources (GitHub / Website / Document / Skill Graph),
generates deterministic defense questions, submits manual answers, and runs
a deterministic (non-LLM) analysis. Team proof, live recording, and final
public report publishing are out of scope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.defense_answer_evidence import DefenseAnswerEvidenceCard
from app.schemas.vbr_project import VBRProjectResponse
from app.schemas.vbr_questions import VBRSessionQuestionResponse
from app.schemas.vbr_sessions import VideoEvidenceChipResponse


class AttachedProofsRequest(BaseModel):
    """Identifiers for existing proof sources to attach to this project defense.

    Only IDs (and a fallback repo_url) are accepted here — the backend stores
    safe summaries derived from these, never raw proof payloads.
    """

    github_proof_id: str | None = Field(default=None, max_length=64)
    website_proof_session_ids: list[str] = Field(default_factory=list)
    document_evidence_ids: list[str] = Field(default_factory=list)
    skill_pipeline_ids: list[str] = Field(default_factory=list)
    repo_url: str | None = Field(default=None, max_length=500)


class ProjectDefenseCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    claimed_skills: list[str] = Field(default_factory=list)
    student_role: str = Field(default="", max_length=2000)
    repo_url: str | None = Field(default=None, max_length=500)
    attached_proofs: AttachedProofsRequest = Field(default_factory=AttachedProofsRequest)


class ProjectDefenseMetadataResponse(BaseModel):
    description: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    student_role: str = ""
    individual_project_only: bool = True
    attached_proofs: dict[str, Any] = Field(default_factory=dict)
    phase: str = "project_defense_mvp_v1"


class ProjectDefenseCreateResponse(BaseModel):
    project: VBRProjectResponse
    metadata: ProjectDefenseMetadataResponse


class GenerateDefenseQuestionsResponse(BaseModel):
    project_id: str
    session_id: str
    status: str
    questions: list[VBRSessionQuestionResponse]


class DefenseAnswerItem(BaseModel):
    question_id: str | None = None
    answer_text: str = Field(default="", max_length=8000)


class SubmitDefenseAnswersRequest(BaseModel):
    """Pasted / manually-entered defense answers.

    Either ``answers`` (question-by-question) or ``combined_text`` (a single
    explanation) may be provided. At least one must contain text.
    """

    answers: list[DefenseAnswerItem] = Field(default_factory=list)
    combined_text: str | None = Field(default=None, max_length=20000)


class DefenseAnalysisResponse(BaseModel):
    transcript_summary: str = ""
    skills_mentioned: list[str] = Field(default_factory=list)
    skills_explained_well: list[str] = Field(default_factory=list)
    skills_missing_from_explanation: list[str] = Field(default_factory=list)
    consistency_with_evidence_score: int = 0
    explanation_clarity_score: int = 0
    ownership_signal_score: int = 0
    technical_depth_score: int = 0
    overall_defense_score: int = 0
    risk_flags: list[str] = Field(default_factory=list)
    recruiter_summary: str = ""
    recommended_improvements: list[str] = Field(default_factory=list)
    privacy_scan_status: str = "clean"


class SubmitDefenseAnswersResponse(BaseModel):
    project_id: str
    session_id: str
    transcript_id: str
    segment_count: int
    answered_question_count: int
    analysis: DefenseAnalysisResponse
    video_evidence_chips: list[VideoEvidenceChipResponse] = Field(default_factory=list)
    # Claim-level, question-grounded answer evidence (owner-visible shape).
    defense_answer_evidence: list[DefenseAnswerEvidenceCard] = Field(default_factory=list)


# ── Project-first defense flow ───────────────────────────────────────────────
#
# Project Defense is a defense layer on top of an existing project, not a
# fourth standalone proof form. These schemas back the "choose a project to
# defend" selection view and the selected-project workspace: they expose only
# safe, already-derived summaries from ``vbr_projects.metadata`` — never raw
# proof payloads, storage paths, signed URLs, provider JSON, or numeric scores.

DefenseStatus = str  # "not_started" | "in_progress" | "completed"


class DefenseEvidenceTypeSummary(BaseModel):
    """Safe attached/missing summary for one evidence type on a project."""

    attached: bool = False
    count: int = 0
    # Safe display label only (repo full name / document titles / website URLs).
    # Never a storage path, signed URL, provider JSON, or numeric score.
    label: str = ""


class ProjectDefenseEvidenceSummary(BaseModel):
    github_proof: DefenseEvidenceTypeSummary = Field(default_factory=DefenseEvidenceTypeSummary)
    documents: DefenseEvidenceTypeSummary = Field(default_factory=DefenseEvidenceTypeSummary)
    website_proof: DefenseEvidenceTypeSummary = Field(default_factory=DefenseEvidenceTypeSummary)
    project_defense: DefenseEvidenceTypeSummary = Field(default_factory=DefenseEvidenceTypeSummary)


class EligibleProjectResponse(BaseModel):
    """A project the current user owns and can defend, with a safe evidence summary."""

    id: str
    title: str
    description: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    repo_full_name: str | None = None
    defense_status: DefenseStatus = "not_started"
    report_ready: bool = False
    evidence: ProjectDefenseEvidenceSummary = Field(default_factory=ProjectDefenseEvidenceSummary)
    created_at: str = ""
    updated_at: str = ""


class EligibleProjectsResponse(BaseModel):
    projects: list[EligibleProjectResponse] = Field(default_factory=list)


# ── Allowlisted safe projection of vbr_projects.metadata.attached_proofs ──────
#
# The selected-project *context* endpoint reads whatever was stored on the
# project — including legacy rows that may carry unsafe fields (raw provider
# JSON, storage paths, signed URLs, private proof IDs, raw document text, or
# numeric evidence scores). These models are a strict allowlist: only the safe
# display fields the workspace UI needs survive. ``extra="ignore"`` guarantees
# any unknown/legacy field is silently dropped rather than echoed back.


class SafeAttachedGitHubProofSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo_url: str = ""
    repo_owner: str | None = None
    repo_name: str | None = None
    status: str | None = None
    detected_skills: list[str] = Field(default_factory=list)
    public_safe_summary: str = ""


class SafeAttachedDocumentSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "Document"
    source_type: str | None = None
    status: str | None = None
    skills: list[str] = Field(default_factory=list)


class SafeAttachedWebsiteProofSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_website: str = ""
    workflow_confidence: str | None = None
    supported_skills: list[str] = Field(default_factory=list)
    # Closed-vocabulary attachment status (``analysis_pending`` when the
    # attached session finished recording but its analysis has not landed).
    status: str | None = None


class SafeAttachedProofsSummary(BaseModel):
    """Allowlisted attached-proof summaries — never raw payloads/IDs/scores."""

    model_config = ConfigDict(extra="ignore")

    github_proof: SafeAttachedGitHubProofSummary | None = None
    documents: list[SafeAttachedDocumentSummary] = Field(default_factory=list)
    website_proofs: list[SafeAttachedWebsiteProofSummary] = Field(default_factory=list)


class SafeProjectDefenseMetadataResponse(BaseModel):
    """Safe metadata projection for the selected-project context view.

    Same owner-facing shape as ``ProjectDefenseMetadataResponse`` but with a
    strictly typed, allowlisted ``attached_proofs`` (no raw dict passthrough).
    """

    model_config = ConfigDict(extra="ignore")

    description: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    student_role: str = ""
    individual_project_only: bool = True
    attached_proofs: SafeAttachedProofsSummary = Field(default_factory=SafeAttachedProofsSummary)
    phase: str = "project_defense_mvp_v1"


class ProjectDefenseContextResponse(BaseModel):
    """Full defense context for a selected project (workspace view)."""

    project: VBRProjectResponse
    metadata: SafeProjectDefenseMetadataResponse
    evidence: ProjectDefenseEvidenceSummary = Field(default_factory=ProjectDefenseEvidenceSummary)
    defense_status: DefenseStatus = "not_started"
    report_ready: bool = False
    session_id: str | None = None
    questions: list[VBRSessionQuestionResponse] = Field(default_factory=list)
    # True when the active session's explanation evidence has already been
    # saved to the Skill Graph — so a reloaded workspace shows the honest
    # "Saved" state instead of always resetting to "Not saved".
    skill_graph_synced: bool = False


class AttachProofsResponse(BaseModel):
    """Attach-proofs response — same safe projection as the context endpoint.

    ``metadata`` is the strictly-typed, allowlisted ``Safe`` DTO (no raw
    ``attached_proofs`` passthrough) so the attach response never leaks storage
    paths, signed URLs, private ids, provider JSON, raw text, or numeric scores
    from legacy metadata already stored on the project.
    """

    project: VBRProjectResponse
    metadata: SafeProjectDefenseMetadataResponse
    evidence: ProjectDefenseEvidenceSummary = Field(default_factory=ProjectDefenseEvidenceSummary)
