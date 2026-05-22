"""Pydantic schemas for the GitHub Portfolio Scan API (Phase J3B)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

GitHubPortfolioSuggestedStatus = Literal["suggested", "needs_review", "skipped"]
GitHubPortfolioConfidenceLabel = Literal["high", "medium", "low"]

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_PROFILE_URL_RE = re.compile(r"(?:https?://)?github\.com/([a-zA-Z0-9_-]+)/?$")


def extract_github_username(profile_url: str | None, username: str | None) -> str | None:
    """Return a clean GitHub username from a profile URL or a raw username string."""
    if username:
        clean = username.strip().lstrip("@")
        if _USERNAME_RE.match(clean):
            return clean
    if profile_url:
        m = _PROFILE_URL_RE.match(profile_url.strip())
        if m:
            return m.group(1)
    return None


class GitHubPortfolioScanRequest(BaseModel):
    github_profile_url: str | None = Field(default=None, max_length=500)
    github_username: str | None = Field(default=None, max_length=100)
    max_repos: int = Field(default=10, ge=1, le=150)
    include_forks: bool = False
    include_archived: bool = False
    smart_scan: bool = Field(
        default=True,
        description=(
            "When True, repos are ranked by evidence-richness signals "
            "(has description, has topics, stars) before the max_repos cap is applied. "
            "This prioritizes the most likely proof-bearing repositories for large profiles."
        ),
    )

    @model_validator(mode="after")
    def _require_identifier(self) -> "GitHubPortfolioScanRequest":
        username = extract_github_username(self.github_profile_url, self.github_username)
        if not username:
            raise ValueError(
                "Provide a valid GitHub profile URL (https://github.com/username) "
                "or a github_username."
            )
        return self


class GitHubPortfolioScanCandidate(BaseModel):
    candidate_id: str
    repo_name: str
    repo_url: str
    project_title: str
    skill_label: str
    evidence_description: str
    student_claim: str
    file_path: str
    line_start: int = Field(gt=0)
    line_end: int = Field(gt=0)
    github_highlight_url: str
    confidence_label: GitHubPortfolioConfidenceLabel = "medium"
    selection_reason: str
    website_url: str | None = None
    suggested_status: GitHubPortfolioSuggestedStatus = "suggested"
    warnings: list[str] = Field(default_factory=list)
    import_key: str


class GitHubPortfolioScanResponse(BaseModel):
    github_username: str
    # ── Repo metadata (accurate counts for frontend messaging) ────────────────
    repos_available_count: int = 0   # repos returned by GitHub API after fork/archived filter
    repos_selected_count: int = 0    # repos actually attempted after smart_scan + max_repos cap
    repo_count_scanned: int = 0      # repos that produced ≥1 evidence candidate (legacy, kept for compat)
    # ── Evidence metadata ─────────────────────────────────────────────────────
    candidate_count: int
    detected_skill_count: int
    proof_candidates: list[GitHubPortfolioScanCandidate]


class GitHubPortfolioImportRequest(BaseModel):
    proof_candidates: list[GitHubPortfolioScanCandidate] = Field(min_length=1)


class GitHubPortfolioCandidateResult(BaseModel):
    candidate_id: str
    skill_label: str
    repo_name: str
    status: Literal["imported", "skipped_duplicate", "failed"]
    evidence_id: str | None = None
    message: str


class GitHubPortfolioImportResponse(BaseModel):
    imported_count: int
    skipped_duplicate_count: int
    failed_count: int
    imported_evidence_ids: list[str]
    per_candidate_results: list[GitHubPortfolioCandidateResult]
