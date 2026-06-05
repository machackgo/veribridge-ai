"""Schemas for Extension Proof Live Website Check."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LiveWebsiteCheckConfidence = Literal["high", "medium", "low", "failed", "not_applicable"]

LiveWebsiteCheckStatus = Literal["complete", "failed", "not_applicable"]

LiveCheckStageStatus = Literal["pending", "in_progress", "complete", "failed"]


class LiveWebsiteCheckStage(BaseModel):
    key: str
    label: str
    status: LiveCheckStageStatus


class LiveWebsiteCheckRequest(BaseModel):
    website_url: str = Field(..., min_length=1, description="The URL to check")


class LiveWebsiteCheckResponse(BaseModel):
    id: str
    proof_session_id: str
    status: LiveWebsiteCheckStatus = "complete"
    website_url: str
    final_url: str | None = None
    status_code: int | None = None
    response_time_ms: int | None = None
    content_type: str | None = None
    page_title: str | None = None
    is_reachable: bool
    confidence: LiveWebsiteCheckConfidence
    risk_flags: list[str] = Field(default_factory=list)
    recruiter_summary: str
    error_message: str | None = None
    checked_at: str

    # Progress tracking — computed at response time, not stored.
    progress: int = Field(default=100, ge=0, le=100)
    current_stage: str = "Complete"
    stages: list[LiveWebsiteCheckStage] = Field(default_factory=list)
