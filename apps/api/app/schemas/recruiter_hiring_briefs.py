"""Typed contracts for recruiter Hiring Briefs (migration 068).

The Hiring Brief is the recruiter-owned source of truth for one hiring
need: the role text, the structured requirement plan, and the role-scoped
candidate pool with per-(brief, candidate) review status. Briefs, their
requirements, statuses and notes are recruiter-private workflow data —
never written to any index, embedding, or candidate-facing surface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.recruiter_comparisons import (
    ColumnCounts,
    ComparisonMatrix,
    ComparisonRequirementsInput,
    ComparisonRequirementsView,
)

BriefStatus = Literal["draft", "active", "paused", "closed"]
# The ROLE-SCOPED 9-stage pipeline (migration 069; strict superset of V3).
# Must stay in sync with the SQL CHECK and BRIEF_CANDIDATE_STATUSES.
BriefCandidateStatus = Literal[
    "saved",
    "reviewing",
    "shortlisted",
    "contacted",
    "interview",
    "decision",
    "hired",
    "passed",
    "archived",
]


class CreateHiringBriefRequest(BaseModel):
    """Create a Hiring Brief. ``requirements`` (edited chips) wins over
    ``role_text`` (natural language) when both are present; both are
    deterministic. Title defaults from the parsed role when omitted."""

    title: str | None = Field(default=None, max_length=120)
    role_text: str | None = Field(default=None, max_length=600)
    requirements: ComparisonRequirementsInput | None = None
    status: BriefStatus = "active"

    model_config = {"extra": "forbid"}


class UpdateHiringBriefRequest(BaseModel):
    """Partial update; omitted fields stay unchanged. Sending ``role_text``
    re-parses the brief; sending ``requirements`` applies edited chips."""

    title: str | None = Field(default=None, max_length=120)
    role_text: str | None = Field(default=None, max_length=600)
    requirements: ComparisonRequirementsInput | None = None
    status: BriefStatus | None = None

    model_config = {"extra": "forbid"}


class BriefCandidateStatusCounts(BaseModel):
    """Transparent pool counts by role-scoped pipeline stage — never a
    score. One explicit field per stage (closed shape)."""

    saved: int = 0
    reviewing: int = 0
    shortlisted: int = 0
    contacted: int = 0
    interview: int = 0
    decision: int = 0
    hired: int = 0
    passed: int = 0
    archived: int = 0

    model_config = {"extra": "forbid"}


class HiringBrief(BaseModel):
    id: str
    title: str
    role_text: str | None = None
    status: str = "active"
    requirements_view: ComparisonRequirementsView = Field(
        default_factory=ComparisonRequirementsView
    )
    candidate_count: int = 0
    status_counts: BriefCandidateStatusCounts = Field(
        default_factory=BriefCandidateStatusCounts
    )
    created_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class HiringBriefResponse(BaseModel):
    brief: HiringBrief

    model_config = {"extra": "forbid"}


class HiringBriefListItem(BaseModel):
    id: str
    title: str
    role: str | None = None
    status: str = "active"
    candidate_count: int = 0
    shortlisted_count: int = 0
    created_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class HiringBriefListResponse(BaseModel):
    briefs: list[HiringBriefListItem] = Field(default_factory=list)
    total: int = 0

    model_config = {"extra": "forbid"}


class HiringBriefDeleteResponse(BaseModel):
    deleted: bool = False

    model_config = {"extra": "forbid"}


class BriefCandidateIdentity(BaseModel):
    """Consented public identity — same projection as the workspace card.
    ``public_slug`` goes dark (None) while the candidate is unpublished."""

    display_name: str | None = None
    headline: str | None = None
    summary: str | None = None
    availability_label: str | None = None
    location: str | None = None
    role_areas: list[str] = Field(default_factory=list)
    public_slug: str | None = None
    is_published: bool = False

    model_config = {"extra": "forbid"}


class BriefCandidateEvaluation(BaseModel):
    """Lightweight live evaluation of the candidate against the brief's
    requirements: transparent counts + missing displays, no matrix cells.
    ``available=False`` means the candidate's evidence is no longer
    publicly comparable (unpublished / excluded / stale disclosure)."""

    available: bool = False
    counts: ColumnCounts = Field(default_factory=ColumnCounts)
    missing_required: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    excluded_hits: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class BriefCandidate(BaseModel):
    student_user_id: str
    status: str = "saved"
    note: str | None = None
    connection_id: str | None = None
    candidate: BriefCandidateIdentity = Field(
        default_factory=BriefCandidateIdentity
    )
    evaluation: BriefCandidateEvaluation | None = None
    added_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class BriefCandidatesResponse(BaseModel):
    candidates: list[BriefCandidate] = Field(default_factory=list)
    total: int = 0
    status_counts: BriefCandidateStatusCounts = Field(
        default_factory=BriefCandidateStatusCounts
    )

    model_config = {"extra": "forbid"}


class AddBriefCandidatesRequest(BaseModel):
    """Add candidates to the brief's role-scoped pool. Candidates come from
    the recruiter's own workspace (``connection_ids``) and/or published
    passports (``candidate_slugs``); duplicates collapse by stable candidate
    identity and re-adds are idempotent."""

    connection_ids: list[str] = Field(default_factory=list, max_length=20)
    candidate_slugs: list[str] = Field(default_factory=list, max_length=20)

    model_config = {"extra": "forbid"}


class AddBriefCandidatesResponse(BaseModel):
    added: int = 0
    already_in_brief: int = 0
    candidates: list[BriefCandidate] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class UpdateBriefCandidateRequest(BaseModel):
    """Partial update of one pool row's ROLE-SCOPED status / private note.
    Omitted fields stay unchanged; ``clear_note`` removes the note."""

    status: BriefCandidateStatus | None = None
    note: str | None = Field(default=None, max_length=2000)
    clear_note: bool = False

    model_config = {"extra": "forbid"}


class BriefCandidateResponse(BaseModel):
    candidate: BriefCandidate

    model_config = {"extra": "forbid"}


class RemoveBriefCandidateResponse(BaseModel):
    removed: bool = False

    model_config = {"extra": "forbid"}


class BriefComparisonResponse(BaseModel):
    """The brief's live evidence matrix over 2–5 of its pool candidates.
    Re-evaluated from live public evidence on every load."""

    brief: HiringBriefListItem
    matrix: ComparisonMatrix

    model_config = {"extra": "forbid"}


__all__ = [
    "AddBriefCandidatesRequest",
    "AddBriefCandidatesResponse",
    "BriefCandidate",
    "BriefCandidateEvaluation",
    "BriefCandidateIdentity",
    "BriefCandidateResponse",
    "BriefCandidateStatusCounts",
    "BriefComparisonResponse",
    "CreateHiringBriefRequest",
    "HiringBrief",
    "HiringBriefDeleteResponse",
    "HiringBriefListItem",
    "HiringBriefListResponse",
    "HiringBriefResponse",
    "RemoveBriefCandidateResponse",
    "UpdateBriefCandidateRequest",
    "UpdateHiringBriefRequest",
]
