"""Schemas for VeriBridge AI Domain Reviewer Agents.

AI Domain Review is not human verification. Responses must keep that trust
boundary visible and must never mark proof as human verified.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AiDomainReviewStatus = Literal[
    "ai_domain_reviewed",
    "needs_more_evidence",
    "human_review_recommended",
    "privacy_blocked",
]

ConfidenceLevel = Literal["high", "medium", "low"]


class AiDomainCriterionResult(BaseModel):
    criterion_name: str
    score: int = Field(..., ge=0)
    max_score: int = Field(..., ge=1)
    justification: str
    evidence_sources_used: list[str] = Field(default_factory=list)
    evidence_snippets_or_references: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class AiDomainReviewResultResponse(BaseModel):
    id: str
    user_id: str
    proof_session_id: str
    reviewer_name: str
    reviewer_role: str
    domain: str
    ai_domain_review_status: AiDomainReviewStatus
    domain_review_score: int = Field(..., ge=0, le=100)
    confidence_level: ConfidenceLevel
    verified_skills: list[str] = Field(default_factory=list)
    partially_verified_skills: list[str] = Field(default_factory=list)
    skills_needing_more_evidence: list[str] = Field(default_factory=list)
    domain_specific_strengths: list[str] = Field(default_factory=list)
    domain_specific_concerns: list[str] = Field(default_factory=list)
    criterion_scores: list[AiDomainCriterionResult] = Field(default_factory=list)
    evidence_sources_reviewed: list[str] = Field(default_factory=list)
    human_review_recommended: bool = False
    human_review_reason: str | None = None
    recruiter_summary: str
    student_next_steps: list[str] = Field(default_factory=list)
    review_limitations: str
    disclosure_note: str
    llm_used: bool = False
    fallback_reason: str | None = None
    human_ai_agreement_score: float | None = None
    calibration_status: str | None = None
    reviewed_against_human_baseline: bool | None = None
    created_at: datetime | str
    updated_at: datetime | str


AiDomainReviewRow = dict[str, Any]
