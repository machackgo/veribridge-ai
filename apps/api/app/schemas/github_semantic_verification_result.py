"""Schemas for GitHub claim-to-code semantic verification results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


GitHubSemanticVerificationStatus = Literal[
    "verified",
    "partially_verified",
    "not_verified",
    "needs_human_review",
    "insufficient_evidence",
    "evaluation_error",
]


class GitHubSemanticVerificationEvaluationRequest(BaseModel):
    pass


class GitHubSemanticMatchedSegmentResponse(BaseModel):
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    segment_type: str = Field(..., min_length=1, max_length=80)
    summary: str = Field(..., min_length=1, max_length=500)
    detected_signals: list[str] = Field(default_factory=list)
    semantic_score: float | None = Field(default=None, ge=0.0, le=1.0)
    semantic_label: str = Field(..., min_length=1, max_length=80)
    supports_skill: bool
    confidence_hint: str = Field(..., min_length=1, max_length=16)


class GitHubSemanticVerificationResultResponse(BaseModel):
    id: str
    evidence_id: str
    user_id: str
    semantic_status: GitHubSemanticVerificationStatus
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evaluator_version: str
    evaluator_provider: str
    recruiter_facing_summary: str | None = None
    evidence_summary: str | None = None
    limitations: str | None = None
    recommended_next_action: str | None = None
    strongest_matching_segment_start: int | None = None
    strongest_matching_segment_end: int | None = None
    strongest_matching_segment_summary: str | None = None
    matched_segments: list[GitHubSemanticMatchedSegmentResponse] = Field(default_factory=list)
    source_snapshot: dict[str, Any]
    created_at: str
    updated_at: str


class GitHubSemanticVerificationResultCreateResponse(GitHubSemanticVerificationResultResponse):
    pass


class GitHubSemanticVerificationResultListResponse(BaseModel):
    results: list[GitHubSemanticVerificationResultResponse]
