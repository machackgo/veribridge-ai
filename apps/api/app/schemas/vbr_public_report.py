"""Schemas for the public VBR report read endpoint (T7B)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VBRPublicReportClaim(BaseModel):
    claim_text: str | None = None
    judgment: str | None = None
    rationale: str | None = None
    evidence_count: int = 0


class VBRPublicReportResponse(BaseModel):
    project_title: str | None = None
    repo_full_name: str | None = None
    status: str
    published_at: str | None = None
    claim_count: int = 0
    evidence_count: int | None = None
    claims: list[VBRPublicReportClaim] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    verification_note: str
    # When this legacy report's project has an ACTIVE canonical public report,
    # the client redirects to this ``/vbr/report/{token}`` path (else null).
    canonical_report_path: str | None = None
