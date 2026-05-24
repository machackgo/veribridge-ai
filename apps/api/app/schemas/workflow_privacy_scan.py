"""Schemas for Workflow Privacy Scan results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


WorkflowPrivacyScanStatus = Literal["clean", "redacted", "flagged"]


class WorkflowPrivacyScanResponse(BaseModel):
    id: str | None = None
    user_id: str
    proof_session_id: str
    status: WorkflowPrivacyScanStatus
    risk_flags: list[str] = Field(default_factory=list)
    redacted_fields_count: int = 0
    redacted_urls_count: int = 0
    contains_sensitive_data: bool = False
    scan_summary: str = ""
    created_at: str | None = None
    updated_at: str | None = None
