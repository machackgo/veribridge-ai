"""Schemas for the public recruiter-safe VBR project report link (v1).

The public report is a read-only, tokenized projection of the student-owned
Final VBR Report preview (see ``vbr_student_report``). It re-uses the same
already-sanitized summary models and adds nothing private: no numeric trust
scores, no raw evidence, no storage paths/URLs, no internal IDs beyond what a
recruiter already holds (the public token in the URL).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.defense_answer_evidence import (
    PublicDefenseAnswerEvidence,
    PublicProjectDefenseInspectionCard,
)
from app.schemas.vbr_student_report import (
    VBREvidenceTrace,
    VBRReportDocumentSummary,
    VBRReportEvidencePackageSummary,
    VBRReportGitHubProofSummary,
    VBRReportProjectDefenseAnalysis,
    VBRReportSkillEvidenceRow,
    VBRReportWebsiteProofSummary,
)


class ProjectReportPublishStatusResponse(BaseModel):
    """Owner-only publish status for a project's public recruiter link.

    ``public_token`` is the owner's own token (needed to build the shareable
    link) — it is only ever returned to the authenticated owner.
    """

    project_id: str
    is_public: bool = False
    public_token: str | None = None
    public_path: str | None = None
    published_at: str | None = None

    model_config = {"extra": "forbid"}


class PublicVideoEvidenceChip(BaseModel):
    """A sanitized, timestamped reference into a Project Defense video.

    Carries no internal ``question_id`` — only safe, recruiter-readable fields.
    """

    label: str
    timestamp_start_s: float
    timestamp_end_s: float
    short_summary: str
    related_skill: str | None = None
    source: str = "project_defense_video"
    source_type: str = "video_transcript"

    model_config = {"extra": "forbid"}


class PublicVBRProjectReportResponse(BaseModel):
    """Public recruiter-safe Verified Build Report for one project.

    Intentionally omits ``project_id``, ``session_id``, the student's email,
    the auth user ID, defense question internals, and any numeric score.
    """

    report_title: str = "Verified Build Report"
    project_title: str = ""
    candidate_display_name: str | None = None
    project_summary: str = ""
    student_role: str = ""
    repo_full_name: str | None = None
    # A public deployed app URL, when the candidate provided one. Safe to link.
    deployed_url: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)

    evidence_package: VBRReportEvidencePackageSummary

    github_proof: VBRReportGitHubProofSummary | None = None
    documents: list[VBRReportDocumentSummary] = Field(default_factory=list)
    website_proofs: list[VBRReportWebsiteProofSummary] = Field(default_factory=list)

    project_defense_analysis: VBRReportProjectDefenseAnalysis | None = None
    # Claim-level answer evidence summaries (fail-closed: withheld placeholders
    # replace answer-derived text when the transcript privacy review failed).
    defense_answer_evidence: list[PublicDefenseAnswerEvidence] = Field(default_factory=list)
    # Recruiter-safe Project Defense inspection cards (fail-closed: not-public-safe
    # cards become withheld placeholders with no answer text or clip locator).
    project_defense_inspection: list[PublicProjectDefenseInspectionCard] = Field(
        default_factory=list
    )
    skill_evidence: list[VBRReportSkillEvidenceRow] = Field(default_factory=list)
    # Recruiter-safe claim→evidence audit trail referenced by the skill matrix.
    evidence_traces: list[VBREvidenceTrace] = Field(default_factory=list)
    video_evidence_chips: list[PublicVideoEvidenceChip] = Field(default_factory=list)

    limitations: list[str] = Field(default_factory=list)

    published_at: str | None = None
    generated_at: str = ""
    # Recruiter-safe link back to the candidate's published Work Passport
    # (`/p/{slug}`), or None when the passport is private/unpublished.
    public_passport_path: str | None = None
    verification_note: str = ""

    model_config = {"extra": "forbid"}


__all__ = [
    "ProjectReportPublishStatusResponse",
    "PublicVideoEvidenceChip",
    "PublicVBRProjectReportResponse",
]
