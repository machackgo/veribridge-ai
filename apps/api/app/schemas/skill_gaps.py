"""Schemas for evidence-derived Skill Gaps.

Skill gaps are computed deterministically from stored evidence only:
``vbr_projects`` claimed skills, ``vbr_project_skill_claims`` +
``vbr_claim_evidence_links`` (the canonical demonstrated axis), and completed
website ``workflow_analysis_results`` outcomes. No AI is involved, and nothing
is ever fabricated: every item carries its exact evidence basis, and a project
without assessable evidence returns an explicit insufficient-evidence state
instead of invented gaps.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SkillGapStatus = Literal[
    "missing_evidence",
    "partially_demonstrated",
    "not_assessed",
    "insufficient_evidence",
]

SKILL_GAP_STATUS_LABELS: dict[str, str] = {
    "missing_evidence": "Missing evidence",
    "partially_demonstrated": "Partially demonstrated",
    "not_assessed": "Not assessed",
    "insufficient_evidence": "Insufficient evidence",
}


class EvidenceBasisEntry(BaseModel):
    """One concrete piece of stored evidence (or its provable absence) behind a gap item."""

    kind: Literal["claim_link", "website_analysis", "claimed_skill"]
    reference_id: str = ""
    proof_type: str | None = None
    proof_id: str | None = None
    citation_type: str | None = None
    link_status: str | None = None
    evidence_quality: str | None = None
    detail: str = ""
    limitations: list[str] = Field(default_factory=list)


class SkillGapItem(BaseModel):
    skill_name: str
    skill_key: str
    status: SkillGapStatus
    status_label: str
    why: str
    evidence_basis: list[EvidenceBasisEntry] = Field(default_factory=list)
    recommended_action: str
    claim_id: str | None = None


class ProjectSkillGapSummary(BaseModel):
    total_claimed: int = 0
    demonstrated: int = 0
    partially_demonstrated: int = 0
    insufficient_evidence: int = 0
    missing_evidence: int = 0
    not_assessed: int = 0


class ProjectSkillGapReport(BaseModel):
    project_id: str
    project_title: str
    # "assessed" when at least one claimed skill / skill claim / completed
    # website analysis exists; "insufficient_evidence" when nothing legitimate
    # can be inferred (no items are fabricated in that state).
    assessment_state: Literal["assessed", "insufficient_evidence"]
    insufficient_evidence_note: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)
    demonstrated_skills: list[str] = Field(default_factory=list)
    gap_items: list[SkillGapItem] = Field(default_factory=list)
    summary: ProjectSkillGapSummary = Field(default_factory=ProjectSkillGapSummary)


class SkillGapsOverviewResponse(BaseModel):
    projects: list[ProjectSkillGapReport] = Field(default_factory=list)
    total_gap_count: int = 0
    generated_at: str
