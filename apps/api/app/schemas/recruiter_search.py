"""Typed contracts for the Recruiter Search & Discovery API (v1).

Everything in a search result is derived from the candidate's PUBLIC Work
Passport projection (see recruiter_search_service) — no emails, auth ids,
scores, or private evidence ever appear here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchSkill(BaseModel):
    """One evidence-backed public passport skill on a result card."""

    skill: str
    # Qualitative label only (Demonstrated / Evidence observed / …) — never
    # a numeric score.
    status: str
    evidence_sources: list[str] = Field(default_factory=list)
    matched: bool = False

    model_config = {"extra": "forbid"}


class SearchProject(BaseModel):
    """Compact public project reference on a result card."""

    title: str | None = None
    public_report_path: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    has_live_url: bool = False

    model_config = {"extra": "forbid"}


class MatchedReason(BaseModel):
    """One structured, evidence-traceable explanation of why this candidate
    matched THIS query. Types: skill | name | technology | headline |
    role_area | project | education | location."""

    type: str
    label: str
    term: str | None = None
    skill_status: str | None = None
    evidence_sources: list[str] | None = None
    project_title: str | None = None

    model_config = {"extra": "forbid"}


class SearchResultCandidate(BaseModel):
    """One search result — public identity + match evidence only."""

    public_slug: str
    display_name: str | None = None
    headline: str | None = None
    location: str | None = None
    availability_label: str | None = None
    institution: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    role_areas: list[str] = Field(default_factory=list)
    skills: list[SearchSkill] = Field(default_factory=list)
    skill_count: int = 0
    project_count: int = 0
    projects: list[SearchProject] = Field(default_factory=list)
    evidence_flags: dict[str, bool] = Field(default_factory=dict)
    matched_reasons: list[MatchedReason] = Field(default_factory=list)
    passport_published_at: str | None = None

    model_config = {"extra": "forbid"}


class SearchQueryEcho(BaseModel):
    """Normalized interpretation of the executed query (for the UI)."""

    q: str = ""
    terms: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    availability: str | None = None

    model_config = {"extra": "forbid"}


class RecruiterSearchResponse(BaseModel):
    results: list[SearchResultCandidate] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    has_more: bool = False
    query: SearchQueryEcho

    model_config = {"extra": "forbid"}


__all__ = [
    "MatchedReason",
    "RecruiterSearchResponse",
    "SearchProject",
    "SearchQueryEcho",
    "SearchResultCandidate",
    "SearchSkill",
]
