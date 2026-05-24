"""Schemas for Extension Proof GitHub Analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExtensionProofGitHubAnalysisStatus = Literal[
    "success",
    "failed",
    "private_or_unavailable",
]


class ExtensionProofGitHubAnalyzeRequest(BaseModel):
    github_url: str = Field(..., min_length=1, description="Public GitHub repository URL to analyze")
    claimed_skills: list[str] = Field(
        default_factory=list,
        description="Skills to match against the detected stack",
    )
    live_website_url: str = Field(default="", description="Live URL of the deployed project (for contextual matching)")
    live_page_title: str = Field(default="", description="Page title of the live site (for domain skill inference)")
    proof_objective: str = Field(default="", description="Workflow proof objective text (for domain skill inference)")


class ExtensionProofGitHubAnalysisResponse(BaseModel):
    id: str
    proof_session_id: str
    repo_url: str
    status: ExtensionProofGitHubAnalysisStatus
    detected_stack: list[str]
    detected_features: list[str]
    matched_claimed_skills: list[str]
    weakly_matched_claimed_skills: list[str] = []
    missing_claimed_skills: list[str]
    evidence_files: list[str]
    confidence_score: float
    warnings: list[str]
    recruiter_summary: str
    created_at: str
    updated_at: str | None = None
