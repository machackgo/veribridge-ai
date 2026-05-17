"""Schemas for semantic website verification results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


WebsiteSemanticVerificationStatus = Literal[
    "verified",
    "partially_verified",
    "not_verified",
    "needs_human_review",
    "insufficient_evidence",
    "evaluation_error",
]


class WebsiteSemanticVerificationEvaluationRequest(BaseModel):
    plan_id: str | None = Field(default=None)
    static_run_id: str | None = Field(default=None)
    browser_run_id: str | None = Field(default=None)


class WebsiteSemanticVerificationResultResponse(BaseModel):
    id: str
    evidence_id: str
    plan_id: str
    static_run_id: str | None = None
    browser_run_id: str | None = None
    user_id: str
    semantic_status: WebsiteSemanticVerificationStatus
    confidence_score: float | None = None
    evaluator_version: str
    evaluator_provider: str
    recruiter_facing_summary: str | None = None
    evidence_summary: str | None = None
    limitations: str | None = None
    recommended_next_action: str | None = None
    source_snapshot: dict[str, Any]
    created_at: str
    updated_at: str


class WebsiteSemanticVerificationResultCreateResponse(WebsiteSemanticVerificationResultResponse):
    pass


class WebsiteSemanticVerificationResultListResponse(BaseModel):
    results: list[WebsiteSemanticVerificationResultResponse]
