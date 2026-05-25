"""Schemas for public work passports and protected evidence access."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


AccessRequestStatus = Literal["pending", "approved", "denied", "revoked"]


class PublicWorkPassportCreateRequest(BaseModel):
    is_public: bool = True
    public_title: str | None = Field(default=None, max_length=200)
    public_summary: str | None = Field(default=None, max_length=2000)
    field: str | None = Field(default=None, max_length=160)
    visible_sections: list[str] = Field(default_factory=list)


class PublicWorkPassportStudentResponse(BaseModel):
    id: str
    user_id: str
    proof_session_id: str
    public_slug: str
    is_public: bool
    public_title: str | None = None
    public_summary: str | None = None
    field: str | None = None
    visible_sections: list[str] = Field(default_factory=list)
    public_url_path: str
    created_at: datetime | str
    updated_at: datetime | str


class PublicPassportSafeResponse(BaseModel):
    id: str
    public_slug: str
    proof_session_id: str
    student_display_name: str | None = None
    field: str | None = None
    public_title: str | None = None
    public_summary: str | None = None
    visible_sections: list[str] = Field(default_factory=list)
    ai_reviewed_status: str | None = None
    ai_domain_review_summary: str | None = None
    ai_domain_reviewer_name: str | None = None
    ai_domain_review_status: str | None = None
    verified_skills: list[str] = Field(default_factory=list)
    partially_verified_skills: list[str] = Field(default_factory=list)
    skills_needing_more_evidence: list[str] = Field(default_factory=list)
    readiness_score: int | None = None
    readiness_level: str | None = None
    public_project_links: list[dict[str, str]] = Field(default_factory=list)
    disclosure_note: str
    access_request_available: bool = True


class AccessRequestCreate(BaseModel):
    requester_name: str = Field(..., min_length=1, max_length=160)
    requester_email: str = Field(..., min_length=3, max_length=320)
    requester_organization: str | None = Field(default=None, max_length=200)
    requester_role: str | None = Field(default=None, max_length=120)
    request_reason: str | None = Field(default=None, max_length=2000)
    requested_sections: list[str] = Field(default_factory=list)

    @field_validator("requester_email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise ValueError("requester_email must be a valid email address")
        return cleaned

    @field_validator("requester_name", "requester_organization", "requester_role", "request_reason", mode="before")
    @classmethod
    def _trim_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None


class AccessRequestDecision(BaseModel):
    decision_notes: str | None = Field(default=None, max_length=2000)
    sections: list[str] | None = None
    expires_at: datetime | None = None


class EvidenceAccessRequestResponse(BaseModel):
    id: str
    user_id: str
    proof_session_id: str
    passport_id: str
    requester_name: str
    requester_email: str
    requester_organization: str | None = None
    requester_role: str | None = None
    request_reason: str | None = None
    status: AccessRequestStatus
    requested_sections: list[str] = Field(default_factory=list)
    decision_notes: str | None = None
    decided_at: datetime | str | None = None
    expires_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str


class AccessRequestPublicResponse(BaseModel):
    id: str
    status: AccessRequestStatus
    message: str


class EvidenceAccessGrantResponse(BaseModel):
    id: str
    access_request_id: str
    user_id: str
    proof_session_id: str
    requester_email: str
    granted_sections: list[str] = Field(default_factory=list)
    access_token: str
    expires_at: datetime | str | None = None
    revoked_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str


class ProtectedEvidenceResponse(BaseModel):
    proof_session_id: str
    requester_email: str
    granted_sections: list[str]
    expires_at: datetime | str | None = None
    evidence: dict[str, Any]
    disclosure_note: str
