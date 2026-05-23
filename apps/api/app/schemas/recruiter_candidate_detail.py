"""Schemas for the Recruiter Candidate Detail (Phase J2)."""

from __future__ import annotations

from pydantic import BaseModel


class EvidenceAccessLinkItem(BaseModel):
    id: str
    label: str
    url: str
    access_type: str
    source_type: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    availability_status: str


class ProofProjectSummary(BaseModel):
    project_title: str
    status_label: str | None = None
    status_code: str | None = None
    has_github_proof: bool
    has_website_proof: bool
    recruiter_summary: str | None = None
    associated_skill_labels: list[str]
    evidence_access_links: list[EvidenceAccessLinkItem]
    # Verification proof fields
    screenshot_url: str | None = None
    screenshot_caption: str | None = None
    api_verified: bool = False
    api_output_summary: str | None = None


class VerifiedSkillSummary(BaseModel):
    skill_name: str
    evidence_count: int
    strongest_status_label: str | None = None


class ProofOverview(BaseModel):
    total_evidence_count: int
    accepted_evidence_count: int
    github_proof_count: int
    website_proof_count: int
    strongest_display_status: str | None = None


class RecruiterCandidateDetailResponse(BaseModel):
    candidate_id: str
    display_name: str
    school_name: str | None = None
    degree: str | None = None
    major: str | None = None
    proof_overview: ProofOverview
    verified_or_supported_skills: list[VerifiedSkillSummary]
    proof_projects: list[ProofProjectSummary]
