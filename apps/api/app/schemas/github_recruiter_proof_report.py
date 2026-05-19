"""Schemas for recruiter-friendly GitHub proof reports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


GitHubRecruiterProofReportStatus = Literal[
    "verified",
    "partially_verified",
    "not_verified",
    "needs_human_review",
    "insufficient_evidence",
    "report_error",
]


class GitHubRecruiterProofReportGenerateRequest(BaseModel):
    semantic_result_id: str | None = Field(default=None, min_length=1)


class GitHubRecruiterProofSupportingLineRangeResponse(BaseModel):
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    segment_type: str = Field(..., min_length=1, max_length=80)
    summary: str = Field(..., min_length=1, max_length=500)
    detected_signals: list[str] = Field(default_factory=list)
    supports_claim: bool
    semantic_score: float | None = Field(default=None, ge=0.0, le=1.0)


class GitHubRecruiterProofConfirmedCapabilityResponse(BaseModel):
    requirement_key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=160)
    supporting_line_range: str = Field(..., min_length=1, max_length=40)


class GitHubRecruiterProofMissingCapabilityResponse(BaseModel):
    requirement_key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=160)
    importance: str = Field(..., min_length=1, max_length=40)


class GitHubRecruiterProofReportResponse(BaseModel):
    id: str
    evidence_id: str
    github_semantic_result_id: str
    user_id: str
    report_status: GitHubRecruiterProofReportStatus
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    report_version: str
    student_claim: str | None = None
    headline: str | None = None
    recruiter_summary: str | None = None
    evidence_summary: str | None = None
    limitations: str | None = None
    recommended_next_action: str | None = None
    confirmed_capabilities: list[GitHubRecruiterProofConfirmedCapabilityResponse] = Field(default_factory=list)
    missing_capabilities: list[GitHubRecruiterProofMissingCapabilityResponse] = Field(default_factory=list)
    supporting_line_ranges: list[GitHubRecruiterProofSupportingLineRangeResponse] = Field(default_factory=list)
    report_snapshot: dict[str, Any]
    created_at: str
    updated_at: str


class GitHubRecruiterProofReportCreateResponse(GitHubRecruiterProofReportResponse):
    pass


class GitHubRecruiterProofReportListResponse(BaseModel):
    results: list[GitHubRecruiterProofReportResponse]
