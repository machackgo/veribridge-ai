"""Schemas for standalone GitHub proof submissions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.github_evidence_service import parse_github_repo_url


class GitHubProofSubmissionCreate(BaseModel):
    repo_url: str = Field(..., min_length=10, max_length=2000)
    proof_session_id: str | None = None
    submitted_skill_claims: list[str] = Field(default_factory=list)

    @field_validator("repo_url")
    @classmethod
    def _validate_repo_url(cls, value: str) -> str:
        cleaned = value.strip()
        if parse_github_repo_url(cleaned) is None:
            raise ValueError("repo_url must be a supported public GitHub repository URL")
        return cleaned


class GitHubProofSubmissionResponse(BaseModel):
    id: str
    user_id: str
    proof_session_id: str | None = None
    repo_url: str
    repo_owner: str | None = None
    repo_name: str | None = None
    default_branch: str | None = None
    visibility: str | None = None
    status: str
    submitted_skill_claims: list[str] = Field(default_factory=list)
    detected_skills: list[str] = Field(default_factory=list)
    repo_metadata: dict[str, Any] = Field(default_factory=dict)
    analysis_summary: str | None = None
    evidence_strength: str | None = None
    confidence_score: int | None = None
    risk_flags: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    public_safe_summary: str | None = None
    analysis_snapshot: dict[str, Any] = Field(default_factory=dict)
    last_analyzed_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str
    # Canonical project relationship — a read-only projection of the SAME rows
    # the Passport / report attachment index reads (normalized 058 rows plus the
    # projects' legacy attached-proof metadata). Stays "vault_only" until the
    # owner explicitly finalizes this proof against an owned project.
    project_id: str | None = None
    project_title: str | None = None
    project_relationship_state: str = "vault_only"


class GitHubProofPublicResponse(BaseModel):
    id: str
    proof_session_id: str | None = None
    repo_url: str
    repo_owner: str | None = None
    repo_name: str | None = None
    default_branch: str | None = None
    visibility: str | None = None
    status: str
    submitted_skill_claims: list[str] = Field(default_factory=list)
    detected_skills: list[str] = Field(default_factory=list)
    analysis_summary: str | None = None
    evidence_strength: str | None = None
    confidence_score: int | None = None
    public_safe_summary: str | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    last_analyzed_at: datetime | str | None = None
    created_at: datetime | str
    updated_at: datetime | str
