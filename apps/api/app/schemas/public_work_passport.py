"""Schemas for public work passports and protected evidence access."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


AccessRequestStatus = Literal["pending", "approved", "denied", "revoked"]
RequesterType = Literal[
    "recruiter",
    "hiring_manager",
    "faculty",
    "mentor",
    "company_reviewer",
    "domain_expert",
    "other",
]
RequesterVerificationStatus = Literal[
    "unverified",
    "email_pending",
    "email_verified",
    "domain_verified",
    "trusted",
    "suspicious",
    "blocked",
]


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
    requester_profile_id: str | None = None
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
    # access_token is returned ONLY once when the grant is first created (approve_request).
    # All subsequent responses (revoke, re-read) set this field to None so the
    # plaintext token is never re-exposed after the initial issuance.
    access_token: str | None = None
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


class RecruiterRequesterProfileResponse(BaseModel):
    requester_profile_id: str
    email: str
    full_name: str | None = None
    organization_name: str | None = None
    organization_domain: str | None = None
    requester_role: str | None = None
    requester_type: RequesterType
    verification_status: RequesterVerificationStatus
    email_verified: bool
    domain_verified: bool
    total_access_requests: int
    approved_access_requests: int
    denied_access_requests: int
    risk_score: int
    risk_flags: list[str] = Field(default_factory=list)
    last_seen_at: datetime | str


class AdminRequesterVerificationUpdate(BaseModel):
    verification_status: RequesterVerificationStatus
    notes: str | None = Field(default=None, max_length=4000)
    domain_verified: bool | None = None
    email_verified: bool | None = None


class RecruiterSessionCreate(BaseModel):
    """Request body for creating a recruiter session token."""

    requester_email: str = Field(..., min_length=3, max_length=320)

    @field_validator("requester_email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise ValueError("requester_email must be a valid email address")
        return cleaned


class RecruiterSessionResponse(BaseModel):
    """Response containing the one-time session token for recruiter private operations.

    Store this token securely (e.g. localStorage / cookie).  Pass it on every
    private recruiter request as the ``X-Recruiter-Token`` header.
    """

    session_token: str
    requester_email: str
    expires_in_days: int = 30


# ── Recruiter-safe Work Passport view ─────────────────────────────────────────


class RecruiterSkillResponse(BaseModel):
    """A single skill entry safe for recruiter display."""

    skill: str
    confidence: Literal["high", "medium", "low"]
    status_label: str
    source_labels: list[str] = Field(default_factory=list)


class RecruiterSkillGroupResponse(BaseModel):
    """A category group of skills with source attribution."""

    group_name: str
    category: str
    confidence: Literal["high", "medium", "low"]
    evidence_count: int
    source_labels: list[str] = Field(default_factory=list)
    skills: list[RecruiterSkillResponse] = Field(default_factory=list)


class RecruiterProofSourceResponse(BaseModel):
    """A single evidence source status safe for recruiter display."""

    key: str
    label: str
    status: str
    score: int
    is_run: bool


class RecruiterPassportViewResponse(BaseModel):
    """Recruiter-safe, evidence-enriched Work Passport view.

    Aggregates public passport metadata, final evidence scores, grouped skill
    evidence with source attribution, and recruiter decision helpers.

    Privacy guarantees:
    - No media_storage_path, raw transcript text, access tokens, or debug data.
    - skill_groups only include public-safe status labels and source names.
    - All fields are safe to render in an unauthenticated recruiter context.
    """

    public_slug: str
    student_display_name: str | None = None
    field: str | None = None
    public_title: str | None = None
    public_summary: str | None = None

    overall_score: int
    evidence_confidence: Literal["high", "medium", "low"]
    verification_status: str | None = None
    readiness_level: str | None = None

    skill_groups: list[RecruiterSkillGroupResponse] = Field(default_factory=list)
    verified_skills: list[str] = Field(default_factory=list)
    partially_verified_skills: list[str] = Field(default_factory=list)
    skills_needing_review: list[str] = Field(default_factory=list)

    proof_sources: list[RecruiterProofSourceResponse] = Field(default_factory=list)

    why_credible: list[str] = Field(default_factory=list)
    strongest_skills: list[str] = Field(default_factory=list)
    areas_needing_review: list[str] = Field(default_factory=list)
    suggested_interview_questions: list[str] = Field(default_factory=list)

    public_project_links: list[dict[str, str]] = Field(default_factory=list)
    project_type: str | None = None

    access_request_available: bool = True
    has_protected_evidence: bool = True

    disclosure_note: str
