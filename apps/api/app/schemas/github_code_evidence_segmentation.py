"""Schemas for segmented GitHub code evidence summaries."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubCodeEvidenceSegmentResponse(BaseModel):
    segment_index: int = Field(..., ge=1)
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    segment_type: str = Field(..., min_length=1, max_length=80)
    detected_signals: list[str] = Field(default_factory=list)
    summary: str = Field(..., min_length=1, max_length=500)
    supports_skill: bool
    confidence_hint: str = Field(..., min_length=1, max_length=16)


class GitHubCodeEvidenceSummaryResponse(BaseModel):
    available: bool
    overall_summary: str = Field(default="", max_length=1000)
    total_segments: int = Field(default=0, ge=0)
    segments: list[GitHubCodeEvidenceSegmentResponse] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)
