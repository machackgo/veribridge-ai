"""Schemas for recruiter-safe direct evidence access links."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EvidenceAccessLinkAvailabilityStatus = Literal[
    "available",
    "unavailable",
    "invalid_source",
    "insufficient_data",
]

EvidenceAccessLinkAccessType = Literal[
    "github_exact_lines",
    "live_website",
]

EvidenceAccessLinkSourceReportType = Literal[
    "github_recruiter_proof_report",
    "website_semantic_verification_result",
    "direct_skill_evidence",
    "none",
]

EvidenceAccessLinkSourceType = Literal[
    "github",
    "website",
]


class EvidenceAccessLinkGenerateRequest(BaseModel):
    source_report_id: str | None = Field(default=None, min_length=1)


class EvidenceAccessLinkResponse(BaseModel):
    id: str
    evidence_id: str
    source_report_type: EvidenceAccessLinkSourceReportType
    source_report_id: str | None = None
    access_type: EvidenceAccessLinkAccessType
    label: str = Field(..., min_length=1, max_length=160)
    url: str = Field(..., min_length=0, max_length=2000)
    source_type: EvidenceAccessLinkSourceType
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    availability_status: EvidenceAccessLinkAvailabilityStatus
    notes: str | None = None
    created_at: str
    updated_at: str


class EvidenceAccessLinkCreateResponse(BaseModel):
    results: list[EvidenceAccessLinkResponse]


class EvidenceAccessLinkListResponse(BaseModel):
    results: list[EvidenceAccessLinkResponse]
