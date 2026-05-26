"""Schemas for centralized Work Passport status orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.skill_evidence_timeline import SkillEvidenceSummary


OverallWorkPassportStatus = Literal[
    "draft",
    "evidence_in_progress",
    "evidence_collected",
    "analysis_in_progress",
    "needs_more_evidence",
    "privacy_review_required",
    "ai_reviewed",
    "ai_domain_reviewed",
    "admin_review_pending",
    "approved_for_sharing",
    "public_passport_active",
    "access_requests_pending",
    "blocked",
    "archived",
]


class WorkPassportIssue(BaseModel):
    code: str
    label: str
    description: str
    source: str
    severity: Literal["info", "low", "normal", "high", "urgent"]
    recommended_fix: str | None = None


class WorkPassportStatusResponse(BaseModel):
    proof_session_id: str
    overall_status: OverallWorkPassportStatus
    status_label: str
    status_description: str
    readiness_score: int | None = None
    readiness_level: str | None = None
    ai_review_status: str | None = None
    ai_domain_review_status: str | None = None
    ai_domain_reviewer_name: str | None = None
    ai_domain_review_score: int | None = None
    project_defense_status: str | None = None
    project_defense_score: int | None = None
    privacy_status: str | None = None
    public_passport_status: str | None = None
    public_slug: str | None = None
    active_version_id: str | None = None
    active_version_number: int | None = None
    admin_review_status: str | None = None
    open_admin_case_count: int
    pending_access_request_count: int
    active_access_grant_count: int
    unread_notification_count: int
    skill_evidence_summary: SkillEvidenceSummary | None = None
    blocking_issues: list[WorkPassportIssue] = Field(default_factory=list)
    warnings: list[WorkPassportIssue] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    missing_steps: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = None
    recruiter_safe_summary: str
    student_next_steps: list[str] = Field(default_factory=list)
    generated_at: datetime | str


class PublicWorkPassportStatusResponse(BaseModel):
    overall_status: OverallWorkPassportStatus
    status_label: str
    readiness_level: str | None = None
    ai_review_status: str | None = None
    ai_domain_review_status: str | None = None
    privacy_status: str | None = None
    public_passport_status: str | None = None
    recruiter_safe_summary: str
    generated_at: datetime | str
