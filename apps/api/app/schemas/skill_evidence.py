"""Schemas for Skill Proof Evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


VerificationStatus = Literal[
    "pending_review",
    "verified",
    "skill_usage_not_found",
    "needs_review",
]
ProofVisibility = Literal["public", "private"]
PublicVerificationStatus = Literal[
    "pending",
    "weak_match",
    "plausible_match",
    "strong_match",
    "rejected",
]


class _SkillEvidenceBase(BaseModel):
    skill_name: str | None = Field(default=None, min_length=1, max_length=160)
    evidence_type: str | None = Field(default=None, min_length=1, max_length=160)
    evidence_url: str | None = Field(default=None, max_length=1200)
    repository_url: str | None = Field(default=None, max_length=1200)
    file_path: str | None = Field(default=None, max_length=1000)
    line_start: int | None = Field(default=None, gt=0)
    line_end: int | None = Field(default=None, gt=0)
    evidence_description: str | None = Field(default=None, max_length=4000)
    proof_visibility: ProofVisibility | None = "public"
    metadata: dict[str, Any] | None = None

    @field_validator(
        "skill_name",
        "evidence_type",
        "evidence_url",
        "repository_url",
        "file_path",
        "evidence_description",
        "proof_visibility",
        mode="before",
    )
    @classmethod
    def _trim_empty_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return str(value).strip() or None

    @model_validator(mode="after")
    def _validate_line_range(self) -> "_SkillEvidenceBase":
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class SkillEvidenceCreate(_SkillEvidenceBase):
    skill_name: str = Field(..., min_length=1, max_length=160)
    evidence_type: str = Field(..., min_length=1, max_length=160)

    @model_validator(mode="after")
    def _require_evidence_detail(self) -> "SkillEvidenceCreate":
        if not any([self.evidence_url, self.repository_url, self.file_path, self.evidence_description]):
            raise ValueError(
                "At least one of evidence_url, repository_url, file_path, or evidence_description must be provided"
            )
        return self


class SkillEvidenceUpdate(_SkillEvidenceBase):
    verification_status: VerificationStatus | None = None
    verification_summary: str | None = Field(default=None, max_length=4000)
    verifier_version: str | None = Field(default=None, max_length=80)

    @field_validator("verification_summary", "verifier_version", mode="before")
    @classmethod
    def _trim_optional_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return str(value).strip() or None


class SkillEvidenceResponse(BaseModel):
    id: str
    user_id: str
    skill_name: str
    evidence_type: str
    evidence_url: str | None = None
    repository_url: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    evidence_description: str | None = None
    proof_visibility: ProofVisibility = "public"
    metadata: dict[str, Any] = Field(default_factory=dict)
    verification_status: VerificationStatus
    verification_summary: str | None = None
    verifier_version: str | None = None
    created_at: str
    updated_at: str


class SkillEvidenceVerifyResponse(BaseModel):
    id: str
    verification_status: VerificationStatus
    verification_summary: str
    verifier_version: str
    evidence: SkillEvidenceResponse


class PublicProofVerificationResponse(BaseModel):
    id: str
    user_id: str
    skill_evidence_id: str
    verification_status: PublicVerificationStatus
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evidence_summary: str
    matched_signals: list[str]
    missing_signals: list[str]
    verifier_notes: str
    needs_human_review: bool
    verifier_version: str
    created_at: str
