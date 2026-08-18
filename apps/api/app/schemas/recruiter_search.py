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


class RequirementMatch(BaseModel):
    """One recruiter requirement verified against this candidate's PUBLISHED
    evidence. ``satisfied`` is decided exclusively by indexed public data —
    never inferred, never generated. Kinds: concept (a skill/technology
    requirement), evidence (an evidence-type expectation like "live deployed
    project"), context (soft role/seniority/location signal — informational,
    never a gate)."""

    kind: str
    requirement: str
    display: str
    required: bool = True
    satisfied: bool = False
    # How it was satisfied: "skill" (evidence-backed passport skill) or
    # "technology" (claimed on a published project).
    via: str | None = None
    matched_label: str | None = None
    skill_status: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    project_titles: list[str] = Field(default_factory=list)
    note: str | None = None

    model_config = {"extra": "forbid"}


class InterpretationChip(BaseModel):
    """One interpreted requirement chip ("Python", "Python or Go")."""

    display: str
    concepts: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceExpectation(BaseModel):
    key: str
    display: str

    model_config = {"extra": "forbid"}


class QueryInterpretation(BaseModel):
    """What the engine understood and executed — surfaced to the recruiter
    so interpretation is transparent, never a silent guess. Modes:
    browse (empty query) | lexical (no recognizable intent — V1 matching) |
    structured (requirement semantics active)."""

    mode: str = "lexical"
    required: list[InterpretationChip] = Field(default_factory=list)
    preferred: list[InterpretationChip] = Field(default_factory=list)
    excluded: list[InterpretationChip] = Field(default_factory=list)
    evidence: list[EvidenceExpectation] = Field(default_factory=list)
    preferred_evidence: list[EvidenceExpectation] = Field(default_factory=list)
    role: str | None = None
    seniority: str | None = None
    location: str | None = None
    residual_terms: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class SearchResultCandidate(BaseModel):
    """One search result — public identity + match evidence only."""

    # exact (every hard requirement evidenced) | close (missing ≥1, stated
    # explicitly in missing_requirements) | match (no hard requirements in
    # the query — lexical/browse/soft-signal result).
    match_type: str = "match"
    requirements: list[RequirementMatch] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
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
    exact_total: int = 0
    close_total: int = 0
    page: int = 1
    page_size: int = 10
    has_more: bool = False
    interpretation: QueryInterpretation = Field(default_factory=QueryInterpretation)
    query: SearchQueryEcho

    model_config = {"extra": "forbid"}


__all__ = [
    "EvidenceExpectation",
    "InterpretationChip",
    "MatchedReason",
    "QueryInterpretation",
    "RequirementMatch",
    "RecruiterSearchResponse",
    "SearchProject",
    "SearchQueryEcho",
    "SearchResultCandidate",
    "SearchSkill",
]
