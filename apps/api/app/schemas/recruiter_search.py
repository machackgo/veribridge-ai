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
    structured (requirement semantics active). Intents: candidate_search
    (find people) | evidence_search (open the proof behind a claim) |
    project_search (which project proves it)."""

    mode: str = "lexical"
    intent: str = "candidate_search"
    required: list[InterpretationChip] = Field(default_factory=list)
    preferred: list[InterpretationChip] = Field(default_factory=list)
    excluded: list[InterpretationChip] = Field(default_factory=list)
    evidence: list[EvidenceExpectation] = Field(default_factory=list)
    preferred_evidence: list[EvidenceExpectation] = Field(default_factory=list)
    role: str | None = None
    seniority: str | None = None
    location: str | None = None
    remote: bool = False
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
    # V3 — set only on brief-scoped searches: whether this candidate is
    # already in the driving Hiring Brief, and their role-scoped status.
    in_brief: bool = False
    brief_status: str | None = None

    model_config = {"extra": "forbid"}


class SearchQueryEcho(BaseModel):
    """Normalized interpretation of the executed query (for the UI)."""

    q: str = ""
    terms: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    availability: str | None = None

    model_config = {"extra": "forbid"}


# ── Evidence Discovery (V1.6) ────────────────────────────────────────────────
# Every field below is a projection of PUBLIC Work Passport data: titles,
# published report paths, closed proof-type labels, qualitative statuses, and
# the already-sanitized public trace previews. Nothing here can reference a
# private artifact — the index it reads from is derived exclusively from
# build_public_passport() output and re-validated live per request.


class EvidenceProjectRef(BaseModel):
    """One published project supporting a proof item."""

    title: str | None = None
    public_report_path: str | None = None
    # Qualitative per-project label for this skill (or "Claimed").
    skill_status: str | None = None
    proof_types: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceTracePreview(BaseModel):
    """One sanitized public evidence trace (same data served at /p/{slug})."""

    source_type: str | None = None
    source_title: str | None = None
    summary: str | None = None
    public_url: str | None = None

    model_config = {"extra": "forbid"}


class EvidenceItem(BaseModel):
    """One proof unit: a skill's published evidence (tier="skill") or a
    clearly-labeled project technology claim (tier="claimed" — never
    presented as verified evidence)."""

    tier: str = "skill"
    requirement: str | None = None
    requirement_display: str | None = None
    related_to: str | None = None
    skill: str
    skill_slug: str
    status: str
    direct: bool = True
    note: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    # The public per-skill evidence drilldown (/p/{slug}/skills/{skill_slug}).
    proof_path: str | None = None
    projects: list[EvidenceProjectRef] = Field(default_factory=list)
    traces: list[EvidenceTracePreview] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceCandidateGroup(BaseModel):
    """One candidate's proof items — many proof items, ONE identity."""

    public_slug: str
    display_name: str | None = None
    headline: str | None = None
    passport_path: str
    items: list[EvidenceItem] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class UnmatchedEvidenceRequirement(BaseModel):
    """A requirement with ZERO published proof — stated explicitly, never
    silently substituted with something else."""

    requirement: str
    display: str
    note: str

    model_config = {"extra": "forbid"}


class RelatedEvidenceHint(BaseModel):
    """Explicitly-labeled RELATED evidence for an unmatched requirement —
    a hint, never proof of the requirement itself."""

    requirement_display: str
    related_display: str
    candidate_names: list[str] = Field(default_factory=list)
    note: str

    model_config = {"extra": "forbid"}


class EvidenceCandidateFilter(BaseModel):
    """Echo of a candidate-context restriction (name terms / explicit slug)."""

    terms: list[str] = Field(default_factory=list)
    matched_candidates: list[str] = Field(default_factory=list)
    ambiguous: bool = False

    model_config = {"extra": "forbid"}


class EvidenceResults(BaseModel):
    total_items: int = 0
    groups: list[EvidenceCandidateGroup] = Field(default_factory=list)
    unmatched: list[UnmatchedEvidenceRequirement] = Field(default_factory=list)
    related: list[RelatedEvidenceHint] = Field(default_factory=list)
    evidence_types: list[EvidenceExpectation] = Field(default_factory=list)
    candidate_filter: EvidenceCandidateFilter | None = None
    notes: list[str] = Field(default_factory=list)

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
    # Present when the query's intent is evidence/project discovery.
    evidence: EvidenceResults | None = None
    query: SearchQueryEcho

    model_config = {"extra": "forbid"}


class RecruiterEvidenceResponse(BaseModel):
    """The structured View-proof drilldown response."""

    evidence: EvidenceResults
    skill: str | None = None
    candidate: str | None = None

    model_config = {"extra": "forbid"}


__all__ = [
    "EvidenceCandidateFilter",
    "EvidenceCandidateGroup",
    "EvidenceExpectation",
    "EvidenceItem",
    "EvidenceProjectRef",
    "EvidenceResults",
    "EvidenceTracePreview",
    "InterpretationChip",
    "MatchedReason",
    "QueryInterpretation",
    "RecruiterEvidenceResponse",
    "RecruiterSearchResponse",
    "RelatedEvidenceHint",
    "RequirementMatch",
    "SearchProject",
    "SearchQueryEcho",
    "SearchResultCandidate",
    "SearchSkill",
    "UnmatchedEvidenceRequirement",
]
