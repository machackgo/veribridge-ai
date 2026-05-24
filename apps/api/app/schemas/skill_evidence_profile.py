"""Schemas for the Skill Evidence Profile — per-project grouped view of extension proof evidence.

One profile per unique project URL groups all repeated submission attempts so the student's
profile page shows a clean project card instead of many duplicate rows.

Designed to be extensible: when GitHub evidence analysis ships, add `has_github_analysis`
and a new evidence level to EvidenceLevel without breaking existing callers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceLevel = Literal[
    "self_claimed",
    "workflow_evidence_complete",
    "workflow_analysis_ai_reviewed",
    "multi_source_ai_reviewed",
    "final_verification_ready",
]

EVIDENCE_LEVEL_LABELS: dict[str, str] = {
    "self_claimed":                  "Self Claimed",
    "workflow_evidence_complete":     "Workflow Evidence Complete",
    "workflow_analysis_ai_reviewed":  "Workflow Analysis — AI Reviewed",
    "multi_source_ai_reviewed":       "Multi-Source AI Reviewed",
    "final_verification_ready":       "Final Verification Ready",
}


class EvidenceSourceStatus(BaseModel):
    key: str
    label: str
    status: Literal["complete", "pending", "unavailable"]


class EvidenceAttemptSummary(BaseModel):
    evidence_id: str
    session_id: str | None = None
    session_status: str | None = None
    has_analysis: bool = False
    skill_name: str
    submitted_at: str


class SkillEvidenceProfile(BaseModel):
    """Clean per-project evidence profile, computed from raw DB records at request time."""

    profile_id: str
    primary_skill_name: str
    all_skill_names: list[str]

    proof_objective: str | None = None
    evidence_url: str | None = None
    github_url: str | None = None
    url_type: str = "invalid_url"

    evidence_level: EvidenceLevel
    evidence_level_label: str

    # Evidence availability flags
    has_workflow_proof: bool = False
    has_workflow_analysis: bool = False
    has_github_evidence: bool = False  # reserved for future GitHub analysis

    # From latest analysis
    confidence: str = "unknown"
    evidence_strength_score: int | None = None
    workflow_analysis_summary: str | None = None

    # Latest session for "Re-run Analysis" / "View Analysis" buttons
    latest_session_id: str | None = None
    latest_session_status: str | None = None

    # Checklist and gaps
    evidence_sources: list[EvidenceSourceStatus] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    # History / versioning
    submission_count: int = 1
    first_submitted_at: str
    last_updated_at: str
    history: list[EvidenceAttemptSummary] = Field(default_factory=list)
