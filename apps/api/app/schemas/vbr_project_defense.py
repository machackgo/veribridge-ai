"""Schemas for Project Defense (Phase 1 — individual project defense MVP).

Phase 1 scope: a student creates an individual Project Defense identity,
attaches existing proof sources (GitHub / Website / Document / Skill Graph),
generates deterministic defense questions, submits manual answers, and runs
a deterministic (non-LLM) analysis. Team proof, live recording, and final
public report publishing are out of scope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.vbr_project import VBRProjectResponse
from app.schemas.vbr_questions import VBRSessionQuestionResponse


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
