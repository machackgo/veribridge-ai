"""Schemas for admin quality review / moderation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


QualityCaseType = Literal[
    "privacy_flag",
    "suspicious_evidence",
    "low_confidence_ai_review",
    "recruiter_risk",
    "access_abuse",
    "student_report",
    "system_flag",
    "manual_review",
    "other",
]
QualityCaseStatus = Literal["open", "under_review", "needs_student_action", "resolved", "dismissed", "escalated"]
QualityCasePriority = Literal["low", "normal", "high", "urgent"]
QualityDecision = Literal[
    "safe_for_sharing",
    "needs_more_evidence",
    "privacy_blocked",
    "suspicious",
    "dismissed",
    "escalated_to_human_review",
    "no_action_needed",
]
QualityEventType = Literal[
    "case_created",
    "case_assigned",
    "case_status_changed",
    "admin_note_added",
    "decision_recorded",
    "student_action_requested",
    "case_resolved",
    "case_dismissed",
    "case_escalated",
]


class AdminQualityReviewCaseCreate(BaseModel):
    user_id: str | None = None
    proof_session_id: str | None = None
    passport_id: str | None = None
    access_request_id: str | None = None
    requester_profile_id: str | None = None
    case_type: QualityCaseType = "manual_review"
    status: QualityCaseStatus = "open"
    priority: QualityCasePriority = "normal"
    risk_score: int = 0
    risk_flags: list[str] = Field(default_factory=list)
    source: str = "admin"
    title: str | None = None
    summary: str | None = None
    assigned_admin_id: str | None = None
    admin_notes: str | None = None
    requested_student_actions: list[dict[str, Any] | str] = Field(default_factory=list)


class AdminQualityReviewCaseUpdate(BaseModel):
    status: QualityCaseStatus | None = None
    priority: QualityCasePriority | None = None
    assigned_admin_id: str | None = None
    admin_notes: str | None = None
    decision: QualityDecision | None = None
    decision_reason: str | None = None
    requested_student_actions: list[dict[str, Any] | str] | None = None


class AdminQualityReviewEventCreate(BaseModel):
    event_type: QualityEventType = "admin_note_added"
    event_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminQualityReviewEventResponse(BaseModel):
    id: str
    case_id: str
    event_type: QualityEventType
    actor_user_id: str | None = None
    actor_type: str
    event_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | str


class AdminQualityReviewCaseResponse(BaseModel):
    id: str
    user_id: str | None = None
    proof_session_id: str | None = None
    passport_id: str | None = None
    access_request_id: str | None = None
    requester_profile_id: str | None = None
    case_type: QualityCaseType
    status: QualityCaseStatus
    priority: QualityCasePriority
    risk_score: int
    risk_flags: list[str] = Field(default_factory=list)
    source: str
    title: str | None = None
    summary: str | None = None
    assigned_admin_id: str | None = None
    admin_notes: str | None = None
    decision: QualityDecision | None = None
    decision_reason: str | None = None
    requested_student_actions: list[dict[str, Any] | str] = Field(default_factory=list)
    resolved_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str
    events: list[AdminQualityReviewEventResponse] = Field(default_factory=list)


class AdminQualityReviewScanRequest(BaseModel):
    user_id: str | None = None
    proof_session_id: str | None = None


class AdminQualityReviewScanResponse(BaseModel):
    created_count: int
    existing_count: int
    cases: list[AdminQualityReviewCaseResponse] = Field(default_factory=list)
