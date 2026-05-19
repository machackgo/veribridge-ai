"""Schemas for Skill Proof Evidence."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.github_code_evidence_segmentation import GitHubCodeEvidenceSummaryResponse


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
WebsiteVerificationPlanStatus = Literal["ready", "needs_more_detail", "unsupported"]
_MIN_FEATURE_TO_VERIFY_WORDS = 20
_MIN_EXPECTED_OUTPUT_WORDS = 8
_FEATURE_DETAIL_MESSAGE = "Feature description must contain at least 20 words so VeriBridge can verify it accurately."
_EXPECTED_OUTPUT_DETAIL_MESSAGE = "Expected output must contain at least 8 words so VeriBridge can compare the result reliably."


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text or ""))


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
    github_code_evidence_summary: GitHubCodeEvidenceSummaryResponse | None = None
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
    github_inspection_used: bool = False
    website_inspection_used: bool = False
    verifier_version: str
    created_at: str


SampleInputs = list[dict[str, Any]] | dict[str, Any]


class WebsiteVerificationGuideBase(BaseModel):
    project_overview: str | None = Field(default=None, max_length=4000)
    feature_to_verify: str = Field(..., min_length=1, max_length=500)
    verification_steps: list[str] = Field(..., min_length=1, max_length=50)
    sample_inputs: SampleInputs | None = None
    expected_output: str = Field(..., min_length=1, max_length=4000)
    login_required: bool = False
    login_notes: str | None = Field(default=None, max_length=2000)
    access_notes: str | None = Field(default=None, max_length=2000)
    known_limitations: str | None = Field(default=None, max_length=3000)
    additional_notes: str | None = Field(default=None, max_length=3000)

    @field_validator(
        "project_overview",
        "feature_to_verify",
        "expected_output",
        "login_notes",
        "access_notes",
        "known_limitations",
        "additional_notes",
        mode="before",
    )
    @classmethod
    def _trim_optional_guide_strings(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return str(value).strip() or None

    @field_validator("verification_steps", mode="before")
    @classmethod
    def _trim_verification_steps(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("verification_steps must be a list of strings")
        steps = [str(step).strip() for step in value if str(step).strip()]
        if not steps:
            raise ValueError("verification_steps must include at least one non-empty step")
        return steps

    @field_validator("feature_to_verify")
    @classmethod
    def _validate_feature_detail(cls, value: str) -> str:
        if count_words(value) < _MIN_FEATURE_TO_VERIFY_WORDS:
            raise ValueError(_FEATURE_DETAIL_MESSAGE)
        return value

    @field_validator("expected_output")
    @classmethod
    def _validate_expected_output_detail(cls, value: str) -> str:
        if count_words(value) < _MIN_EXPECTED_OUTPUT_WORDS:
            raise ValueError(_EXPECTED_OUTPUT_DETAIL_MESSAGE)
        return value


class WebsiteVerificationGuideCreate(WebsiteVerificationGuideBase):
    pass


class WebsiteVerificationGuideResponse(WebsiteVerificationGuideBase):
    id: str
    user_id: str
    skill_evidence_id: str
    created_at: str
    updated_at: str


class WebsiteVerificationPlanResponse(BaseModel):
    id: str
    user_id: str
    skill_evidence_id: str
    website_url: str
    feature_to_verify: str
    plan_status: WebsiteVerificationPlanStatus
    normalized_test_steps: list[str]
    expected_output: str
    sample_inputs: SampleInputs | None = None
    inferred_action_candidates: list[dict[str, Any]]
    validation_warnings: list[str]
    agent_notes: str
    requires_login: bool
    can_attempt_automated_execution: bool
    planner_version: str
    created_at: str
