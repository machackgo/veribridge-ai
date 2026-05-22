"""Pydantic schemas for the Website AI Analyzer (Phase J4D / J4E / J4F / J4G)."""

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


# ── J4F: Functional verification candidate ────────────────────────────────────

class FunctionalVerificationCandidate(BaseModel):
    candidate_id: str
    skill_name: str
    skill_category: str
    confidence: Literal["high", "medium", "low"]
    evidence_title: str
    evidence_summary: str
    endpoint_url: str
    method: str                      # "GET", "POST"
    request_summary: str
    response_fields_found: list[str]
    status_code: int | None = None
    verified: bool
    verification_message: str
    evidence_type: Literal["verified_workflow"] = "verified_workflow"
    action_label: str = "View Endpoint"
    suggested_status: Literal["suggested", "needs_review"] = "suggested"


# ── J4G: High-level grouped skill evidence ────────────────────────────────────

class GroupedWebsiteSkill(BaseModel):
    group_id: str
    skill_name: str           # "Machine Learning Engineering"
    category: str             # same as skill_name by default
    confidence: Literal["high", "medium", "low"]
    sources: list[Literal["website", "github_repo", "functional", "combined"]]
    subskills: list[str]      # atomic skill names that contribute to this group
    evidence_count: int
    website_count: int
    repo_count: int
    functional_count: int
    combined_count: int
    candidate_ids: list[str]            # all underlying candidate IDs (atomic + functional)
    functional_candidate_ids: list[str] # only functional verification candidate IDs
    system_graph_nodes: list[str]
    system_graph_edges: list[tuple[str, str]]
    suggested_status: Literal["suggested", "needs_review"]


# ── Request / Response ────────────────────────────────────────────────────────

class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    skill_focus: str | None = Field(default=None, max_length=500)
    github_repo_url: str | None = Field(default=None, max_length=2000)
    run_safe_tests: bool = Field(default=True)

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
    # J4F: functional verification results
    functional_candidates: list[FunctionalVerificationCandidate] = Field(default_factory=list)
    # J4G: high-level grouped skill cards
    grouped_skills: list[GroupedWebsiteSkill] = Field(default_factory=list)
    checked_urls: list[str]
    warnings: list[str]
    candidate_count: int
    # J4E: source counts
    website_candidate_count: int = 0
    repo_candidate_count: int = 0
    combined_candidate_count: int = 0
    # J4F: functional verification counts
    functional_candidate_count: int = 0
    functional_verification_available: bool = False
    github_repo_url: str | None = None
