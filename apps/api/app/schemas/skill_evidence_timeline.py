"""Schemas for skill-level evidence timelines."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SupportLevel = Literal["strong", "partial", "weak", "missing"]
EvidenceType = Literal[
    "workflow",
    "github",
    "live_website",
    "project_defense",
    "ai_domain_review",
    "privacy_scan",
    "readiness_report",
    "version_snapshot",
    "future_upload",
]


class SkillEvidenceItem(BaseModel):
    evidence_type: EvidenceType
    source_label: str
    summary: str
    support_strength: Literal["strong", "partial", "weak"]
    confidence_score: int = Field(ge=0, le=100)
    created_at: datetime | str | None = None
    public_safe: bool
    protected: bool
    reference_id: str | None = None
    evidence_url: str | None = None
    limitations: list[str] = Field(default_factory=list)


class SkillEvidenceRecord(BaseModel):
    skill_name: str
    normalized_skill_name: str
    support_level: SupportLevel
    confidence_score: int = Field(ge=0, le=100)
    evidence_count: int
    evidence_sources: list[str] = Field(default_factory=list)
    public_safe: bool
    recruiter_visible: bool
    evidence_items: list[SkillEvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    last_updated_at: datetime | str | None = None


class SkillEvidenceTimelineResponse(BaseModel):
    proof_session_id: str
    skills: list[SkillEvidenceRecord] = Field(default_factory=list)
    generated_at: datetime | str


class SkillEvidenceSummary(BaseModel):
    strong_skill_count: int = 0
    partial_skill_count: int = 0
    missing_skill_count: int = 0
