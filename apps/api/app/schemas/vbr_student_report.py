"""Schemas for the student-owned Final VBR Report (v1) preview.

This is a private, student-owned preview of the evidence package collected
for a Project Defense project. It is NOT the public tokenized recruiter
report (see ``vbr_public_report``) — public recruiter sharing is not enabled
by this endpoint.

Only safe summary data is returned: no raw transcript text, document text,
GitHub snapshots, storage paths, signed/upload URLs, bucket names, env
values, tokens, or provider payloads. Evidence strength is expressed using
qualitative labels (``Demonstrated`` / ``Partially demonstrated`` /
``Supporting evidence`` / ``Not assessed`` / ``Needs review``) — never
numeric trust scores.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.vbr_sessions import VideoEvidenceChipResponse


class VBRReportGitHubProofSummary(BaseModel):
    repo_url: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None
    status: str | None = None
    detected_skills: list[str] = Field(default_factory=list)
    public_safe_summary: str = ""


class VBRReportDocumentSummary(BaseModel):
    title: str
    source_type: str | None = None
    status: str | None = None


class VBRReportWebsiteProofSummary(BaseModel):
    target_website: str = ""
    evidence_strength: str = "Not assessed"
    workflow_confidence: str = "insufficient"
    supported_skills: list[str] = Field(default_factory=list)


class VBRReportEvidencePackageSummary(BaseModel):
    github_proof_attached: bool = False
    documents_count: int = 0
    website_proofs_count: int = 0
    project_defense_completed: bool = False
    video_defense_recorded: bool = False
    video_evidence_chip_count: int = 0


class VBRReportQuestionSummary(BaseModel):
    id: str
    question_text: str
    kind: str | None = None
    skill: str | None = None
    answered: bool = False


class VBRReportSkillEvidenceRow(BaseModel):
    skill: str
    status: str
    evidence_chip_count: int = 0
    notes: str = ""


class VBRReportProjectDefenseAnalysis(BaseModel):
    """Report-safe summary of a ``DefenseAnalysisResponse``.

    Numeric analysis scores (``overall_defense_score``,
    ``explanation_clarity_score``, ``ownership_signal_score``,
    ``technical_depth_score``, ``consistency_with_evidence_score``) are
    intentionally never included here — they are mapped to qualitative
    labels (``Demonstrated`` / ``Partially demonstrated`` /
    ``Supporting evidence`` / ``Needs review`` / ``Not assessed``).
    """

    transcript_summary: str = ""
    skills_mentioned: list[str] = Field(default_factory=list)
    skills_explained_well: list[str] = Field(default_factory=list)
    skills_missing_from_explanation: list[str] = Field(default_factory=list)
    overall_assessment: str = "Not assessed"
    explanation_clarity: str = "Not assessed"
    ownership_signal: str = "Not assessed"
    technical_depth: str = "Not assessed"
    consistency_with_evidence: str = "Not assessed"
    risk_flags: list[str] = Field(default_factory=list)
    recruiter_summary: str = ""
    recommended_improvements: list[str] = Field(default_factory=list)
    privacy_scan_status: str = "clean"

    model_config = {"extra": "forbid"}


class VBRStudentProjectReportResponse(BaseModel):
    project_id: str
    project_title: str
    project_description: str = ""
    repo_url: str = ""
    repo_full_name: str | None = None
    student_role: str = ""
    claimed_skills: list[str] = Field(default_factory=list)
    project_status: str = "draft"
    session_id: str | None = None
    generated_at: str

    evidence_package: VBRReportEvidencePackageSummary

    github_proof: VBRReportGitHubProofSummary | None = None
    documents: list[VBRReportDocumentSummary] = Field(default_factory=list)
    website_proofs: list[VBRReportWebsiteProofSummary] = Field(default_factory=list)

    project_defense_analysis: VBRReportProjectDefenseAnalysis | None = None
    defense_questions: list[VBRReportQuestionSummary] = Field(default_factory=list)
    video_evidence_chips: list[VideoEvidenceChipResponse] = Field(default_factory=list)

    skill_evidence: list[VBRReportSkillEvidenceRow] = Field(default_factory=list)

    limitations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    preview_only: bool = True
    public_recruiter_sharing_enabled: bool = False
    note: str = (
        "This is a student preview of the evidence package collected for this project. "
        "It is private by default — use the controls below to publish a recruiter-safe "
        "link when you're ready to share."
    )

    model_config = {"extra": "forbid"}


__all__ = [
    "VBRReportGitHubProofSummary",
    "VBRReportDocumentSummary",
    "VBRReportWebsiteProofSummary",
    "VBRReportEvidencePackageSummary",
    "VBRReportQuestionSummary",
    "VBRReportSkillEvidenceRow",
    "VBRReportProjectDefenseAnalysis",
    "VBRStudentProjectReportResponse",
]
