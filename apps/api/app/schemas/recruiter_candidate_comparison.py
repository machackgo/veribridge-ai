"""Schemas for recruiter candidate comparison snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RecruiterCandidateComparisonRoleRequirements(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    field: str | None = None


class RecruiterCandidateComparisonCreate(BaseModel):
    requester_email: str = Field(..., min_length=3, max_length=320)
    comparison_name: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=200)
    role_requirements: RecruiterCandidateComparisonRoleRequirements | dict[str, Any] = Field(default_factory=dict)
    saved_passport_ids: list[str] = Field(default_factory=list)

    @field_validator("requester_email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise ValueError("requester_email must be a valid email address")
        return cleaned

    @field_validator("comparison_name", "role_title", mode="before")
    @classmethod
    def _trim_optional(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class RecruiterCandidateSnapshot(BaseModel):
    saved_passport_id: str
    passport_id: str
    public_slug: str | None = None
    student_display_name: str | None = None
    field: str | None = None
    overall_status: str | None = None
    readiness_score: int | None = None
    ai_domain_review_score: int | None = None
    ai_domain_reviewer_name: str | None = None
    strong_skill_count: int = 0
    partial_skill_count: int = 0
    missing_skill_count: int = 0
    matched_required_skills: list[str] = Field(default_factory=list)
    partially_matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    candidate_match_score: int = Field(ge=0, le=100)
    recruiter_fit_score: int | None = None
    recruiter_tags: list[str] = Field(default_factory=list)
    recruiter_status: str | None = None
    access_status: str | None = None
    last_viewed_at: datetime | str | None = None
    safe_summary: str | None = None
    recommended_follow_up: str | None = None


class RecruiterCandidateComparisonSnapshot(BaseModel):
    comparison_name: str | None = None
    role_title: str | None = None
    role_requirements: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime | str
    candidate_count: int = 0
    candidates: list[RecruiterCandidateSnapshot] = Field(default_factory=list)


class RecruiterCandidateComparisonResponse(BaseModel):
    id: str
    requester_profile_id: str
    requester_email: str
    comparison_name: str | None = None
    role_title: str | None = None
    role_requirements: dict[str, Any] = Field(default_factory=dict)
    candidate_passport_ids: list[str] = Field(default_factory=list)
    comparison_snapshot: RecruiterCandidateComparisonSnapshot
    status: str
    created_at: datetime | str
    updated_at: datetime | str

