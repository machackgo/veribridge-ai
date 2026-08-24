"""Typed contracts for recruiter Talent Pools (migration 070).

A Talent Pool is a recruiter-owned, role-independent candidate collection.
Pools, membership and notes are recruiter-private workflow data — never
written to any index, public projection, or candidate-facing surface.
Candidate identity is the SAME consented projection as the workspace card;
evidence context is live and fail-closed (None once unpublished).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.recruiter_comparisons import (
    ComparisonMatrix,
    ComparisonRequirementsView,
)
from app.schemas.recruiter_hiring_briefs import BriefCandidateIdentity

PoolStatus = Literal["active", "archived"]
# RECRUITER-PRIVATE workflow stage, scoped to one pool. Must stay in sync
# with the SQL CHECK (migration 072) and
# recruiter_talent_pool_service.POOL_CANDIDATE_STATUSES. This is the
# recruiter's process, never a judgement recorded against the candidate.
PoolCandidateStatus = Literal[
    "review", "shortlisted", "interview", "hold", "pass"
]
# 065 connection vocabulary + saved_search. Must stay in sync with the SQL
# CHECK and recruiter_talent_pool_service.POOL_CANDIDATE_SOURCES.
PoolCandidateSource = Literal[
    "qr_scan", "shared_link", "search", "role_match", "direct", "saved_search"
]


class CreateTalentPoolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=600)

    model_config = {"extra": "forbid"}


class UpdateTalentPoolRequest(BaseModel):
    """Partial update; omitted fields stay unchanged. ``clear_description``
    removes the description."""

    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=600)
    clear_description: bool = False
    status: PoolStatus | None = None

    model_config = {"extra": "forbid"}


class TalentPool(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str = "active"
    candidate_count: int = 0
    created_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class TalentPoolResponse(BaseModel):
    pool: TalentPool

    model_config = {"extra": "forbid"}


class TalentPoolListResponse(BaseModel):
    pools: list[TalentPool] = Field(default_factory=list)
    total: int = 0

    model_config = {"extra": "forbid"}


class TalentPoolDeleteResponse(BaseModel):
    deleted: bool = False

    model_config = {"extra": "forbid"}


class PoolCandidateEvidence(BaseModel):
    """Light LIVE evidence context from the fail-closed public projection —
    transparent counts and qualitative labels only, never a score."""

    skill_count: int = 0
    project_count: int = 0
    evidence_flags: dict[str, bool] = Field(default_factory=dict)
    top_skills: list[str] = Field(default_factory=list)
    public_slug: str | None = None

    model_config = {"extra": "forbid"}


class PoolCandidate(BaseModel):
    """One pool member. ``evidence`` is None once the candidate is no longer
    publicly live (unpublished / excluded / stale disclosure) — the identity
    card then carries the "no longer published" treatment."""

    student_user_id: str
    source: str = "direct"
    # ── recruiter-private judgement (never evidence, never candidate-visible)
    status: str = "review"
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    added_at: Any = None
    updated_at: Any = None
    # ── VeriBridge evidence domain (consented, live, fail-closed)
    candidate: BriefCandidateIdentity = Field(
        default_factory=BriefCandidateIdentity
    )
    evidence: PoolCandidateEvidence | None = None

    model_config = {"extra": "forbid"}


class RecruiterTag(BaseModel):
    """One entry in the caller's private tag vocabulary."""

    tag: str
    tag_key: str
    candidate_count: int = 0

    model_config = {"extra": "forbid"}


class PoolCandidateMatch(BaseModel):
    """WHY this candidate survived an evidence filter, reconstructed from the
    deterministic evaluation — never a score and never generated prose.

    ``match_type`` is the engine's existing classification: ``exact`` (every
    requirement evidenced) vs ``close`` (at least one missing, named in
    ``missing_requirements``). ``skills`` and ``projects`` carry the public
    proof entry points so the recruiter can open the evidence itself."""

    match_type: str = "match"
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    matched_reasons: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class FilteredPoolCandidate(PoolCandidate):
    """A pool card plus its evidence-match explanation (None when no
    evidence filter was applied)."""

    match: PoolCandidateMatch | None = None

    model_config = {"extra": "forbid"}


class PoolFilterEcho(BaseModel):
    """Exactly what was applied, echoed back for honest display."""

    q: str = ""
    evidence: list[str] = Field(default_factory=list)
    status: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PoolFilterResponse(BaseModel):
    """Pool members surviving the filter.

    ``unavailable_excluded`` counts members who could not be evidence-matched
    because their evidence is no longer publicly live — surfaced so the UI can
    say so rather than silently shrinking the pool. Absence of VeriBridge
    evidence is never presented as a judgement about a candidate."""

    pool: TalentPool
    candidates: list[FilteredPoolCandidate] = Field(default_factory=list)
    total: int = 0
    # Candidates who satisfied SOME but not every requirement. Kept out of
    # `candidates` so a filter means what it says, and surfaced separately
    # with the gap already named rather than silently promoted or dropped.
    close_candidates: list[FilteredPoolCandidate] = Field(default_factory=list)
    close_total: int = 0
    pool_total: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    tag_vocabulary: list[RecruiterTag] = Field(default_factory=list)
    filters: PoolFilterEcho = Field(default_factory=PoolFilterEcho)
    # "Understood as …" — what the engine actually executed, including terms
    # it could NOT turn into a requirement. None when no query was given.
    interpretation: dict[str, Any] | None = None
    unavailable_excluded: int = 0

    model_config = {"extra": "forbid"}


class PoolComparisonRequest(BaseModel):
    """Compare 2–5 members of this pool. ``q`` is optional: with it the axis
    is the recruiter's stated requirements; without it the axis is derived
    from the selected candidates' own published evidence."""

    student_user_ids: list[str] = Field(min_length=1, max_length=5)
    q: str | None = Field(default=None, max_length=320)

    model_config = {"extra": "forbid"}


class PoolComparisonResponse(BaseModel):
    pool: TalentPool
    matrix: ComparisonMatrix
    query: str | None = None
    requirements_view: ComparisonRequirementsView = Field(
        default_factory=ComparisonRequirementsView
    )

    model_config = {"extra": "forbid"}


class RecruiterTagsResponse(BaseModel):
    tags: list[RecruiterTag] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class TalentPoolDetailResponse(BaseModel):
    pool: TalentPool
    candidates: list[PoolCandidate] = Field(default_factory=list)
    total: int = 0
    # {workflow status -> member count}. A plain mapping rather than a model
    # because one of the closed status values ("pass") is a Python keyword
    # and cannot be a field name; the vocabulary is pinned by
    # PoolCandidateStatus and the migration-072 CHECK.
    status_counts: dict[str, int] = Field(default_factory=dict)
    tag_vocabulary: list[RecruiterTag] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AddPoolCandidatesRequest(BaseModel):
    """Add candidates to the pool. ``candidate_slugs`` must be actively
    published passports; ``connection_ids`` the caller's own connections;
    ``student_user_ids`` are accepted only when already visible to the
    caller (saved-search flow). Re-adds are idempotent."""

    candidate_slugs: list[str] = Field(default_factory=list, max_length=20)
    connection_ids: list[str] = Field(default_factory=list, max_length=20)
    student_user_ids: list[str] = Field(default_factory=list, max_length=20)
    source: PoolCandidateSource = "direct"

    model_config = {"extra": "forbid"}


class AddPoolCandidatesResponse(BaseModel):
    added: int = 0
    already_in_pool: int = 0
    candidates: list[PoolCandidate] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class UpdatePoolCandidateRequest(BaseModel):
    """Update one member's RECRUITER-PRIVATE workflow metadata. Omitted
    fields stay unchanged; ``clear_note`` removes the note; ``tags``
    REPLACES the caller's tag set for this candidate.

    Nothing here can alter evidence, verification state, a Work Passport, a
    Verified Build Report or any public projection."""

    note: str | None = Field(default=None, max_length=4000)
    clear_note: bool = False
    status: PoolCandidateStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=24)

    model_config = {"extra": "forbid"}


class PoolCandidateResponse(BaseModel):
    candidate: PoolCandidate

    model_config = {"extra": "forbid"}


class RemovePoolCandidateResponse(BaseModel):
    removed: bool = False

    model_config = {"extra": "forbid"}


class PoolMembershipsResponse(BaseModel):
    """{student_user_id → [pool ids]} across the caller's OWN pools."""

    memberships: dict[str, list[str]] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


__all__ = [
    "AddPoolCandidatesRequest",
    "AddPoolCandidatesResponse",
    "CreateTalentPoolRequest",
    "FilteredPoolCandidate",
    "PoolCandidate",
    "PoolCandidateMatch",
    "PoolComparisonRequest",
    "PoolComparisonResponse",
    "PoolFilterEcho",
    "PoolFilterResponse",
    "PoolCandidateEvidence",
    "PoolCandidateResponse",
    "PoolMembershipsResponse",
    "RecruiterTag",
    "RecruiterTagsResponse",
    "RemovePoolCandidateResponse",
    "TalentPool",
    "TalentPoolDeleteResponse",
    "TalentPoolDetailResponse",
    "TalentPoolListResponse",
    "TalentPoolResponse",
    "UpdatePoolCandidateRequest",
    "UpdateTalentPoolRequest",
]
