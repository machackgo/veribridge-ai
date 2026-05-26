"""Schemas for proof evidence versioning and resubmission."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ProofEvidenceVersionStatus = Literal[
    "draft",
    "submitted",
    "analyzed",
    "needs_more_evidence",
    "ai_domain_reviewed",
    "approved_for_sharing",
    "archived",
]


class ProofEvidenceVersionCreateRequest(BaseModel):
    change_summary: str | None = Field(default=None, max_length=2000)
    resubmission_reason: str | None = Field(default=None, max_length=2000)


class ProofEvidenceVersionResponse(BaseModel):
    id: str
    user_id: str
    proof_session_id: str
    version_number: int
    version_label: str | None = None
    status: ProofEvidenceVersionStatus
    change_summary: str | None = None
    resubmission_reason: str | None = None
    evidence_snapshot: dict[str, Any] = Field(default_factory=dict)
    analysis_snapshot: dict[str, Any] = Field(default_factory=dict)
    readiness_score: int | None = None
    ai_domain_review_score: int | None = None
    project_defense_score: int | None = None
    privacy_status: str | None = None
    created_from_version_id: str | None = None
    is_active: bool
    submitted_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str
