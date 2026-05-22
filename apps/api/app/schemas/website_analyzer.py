"""Pydantic schemas for the Website AI Analyzer (Phase J4D/J4E)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WebsiteAnalysisCandidate(BaseModel):
    candidate_id: str
    skill_name: str
    skill_category: str
    confidence: Literal["high", "medium", "low"]
    evidence_title: str
    evidence_summary: str
    source_url: str
    route_path: str        # "/", "/docs", "/openapi.json", "src/api.py L12–L40", etc.
    evidence_snippet: str
    evidence_type: Literal[
        "deployed_website", "api_docs", "api_endpoint", "website_content",
        "github_repo", "combined",
    ]
    action_label: str      # "Open Live Website", "Open API Docs", "Open GitHub Evidence", etc.
    suggested_status: Literal["suggested", "needs_review"]
    # J4E: source metadata
    evidence_source: Literal["website", "github_repo", "combined"] = "website"
    is_combined: bool = False
    related_source_url: str | None = None   # for combined: the other source URL


class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    skill_focus: str | None = Field(default=None, max_length=500)
    # J4E: optional connected GitHub repo
    github_repo_url: str | None = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def _require_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("github_repo_url")
    @classmethod
    def _validate_repo_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("GitHub repo URL must start with http:// or https://")
        return v


class WebsiteAnalyzeResponse(BaseModel):
    base_url: str
    candidates: list[WebsiteAnalysisCandidate]
    checked_urls: list[str]
    warnings: list[str]
    candidate_count: int
    # J4E: source counts for the review summary
    website_candidate_count: int = 0
    repo_candidate_count: int = 0
    combined_candidate_count: int = 0
    github_repo_url: str | None = None
