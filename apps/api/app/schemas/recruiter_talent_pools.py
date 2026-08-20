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

from app.schemas.recruiter_hiring_briefs import BriefCandidateIdentity

PoolStatus = Literal["active", "archived"]
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
    note: str | None = None
    added_at: Any = None
    candidate: BriefCandidateIdentity = Field(
        default_factory=BriefCandidateIdentity
    )
    evidence: PoolCandidateEvidence | None = None

    model_config = {"extra": "forbid"}


class TalentPoolDetailResponse(BaseModel):
    pool: TalentPool
    candidates: list[PoolCandidate] = Field(default_factory=list)
    total: int = 0

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
    """Update one member's recruiter-private note. ``clear_note`` removes it."""

    note: str | None = Field(default=None, max_length=4000)
    clear_note: bool = False

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
    "PoolCandidate",
    "PoolCandidateEvidence",
    "PoolCandidateResponse",
    "PoolMembershipsResponse",
    "RemovePoolCandidateResponse",
    "TalentPool",
    "TalentPoolDeleteResponse",
    "TalentPoolDetailResponse",
    "TalentPoolListResponse",
    "TalentPoolResponse",
    "UpdatePoolCandidateRequest",
    "UpdateTalentPoolRequest",
]
