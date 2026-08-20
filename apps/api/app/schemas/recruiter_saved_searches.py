"""Typed contracts for recruiter Saved Searches (migration 070).

A Saved Search persists the canonical requirement plan plus a small closed
``filters`` shape. Results are ALWAYS recomputed live by the search engine;
the stored match rows only power the "new / updated since last review"
annotations — hashes, keys and timestamps, never prose or identity.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.recruiter_comparisons import ComparisonRequirementsView
from app.schemas.recruiter_search import (
    QueryInterpretation,
    SearchResultCandidate,
)

SavedSearchStatus = Literal["active", "paused"]


class SavedSearchFilters(BaseModel):
    """The explicit filter chips a saved search re-applies on every run —
    sanitized server-side against the closed vocabularies."""

    skills: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    availability: str | None = Field(default=None, max_length=40)

    model_config = {"extra": "forbid"}


class CreateSavedSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=320)
    name: str | None = Field(default=None, max_length=120)
    filters: SavedSearchFilters | None = None

    model_config = {"extra": "forbid"}


class UpdateSavedSearchRequest(BaseModel):
    """Partial update; omitted fields stay unchanged. Editing ``q`` or
    ``filters`` re-parses, wipes tracked matches, and re-baselines — a
    changed search never fakes "new" candidates."""

    name: str | None = Field(default=None, max_length=120)
    status: SavedSearchStatus | None = None
    q: str | None = Field(default=None, max_length=320)
    filters: SavedSearchFilters | None = None

    model_config = {"extra": "forbid"}


class SavedSearchListItem(BaseModel):
    """One saved search. ``tracking`` is False when the plan has no hard
    requirements (savable, honestly untracked). Counts are None while
    paused — a paused search is not reconciled, so counts would be stale."""

    id: str
    name: str
    query_text: str | None = None
    status: str = "active"
    requirements: ComparisonRequirementsView = Field(
        default_factory=ComparisonRequirementsView
    )
    tracking: bool = False
    new_count: int | None = None
    updated_count: int | None = None
    match_count: int | None = None
    last_evaluated_at: Any = None
    last_reviewed_at: Any = None
    created_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class SavedSearchResponse(BaseModel):
    saved_search: SavedSearchListItem

    model_config = {"extra": "forbid"}


class SavedSearchListResponse(BaseModel):
    saved_searches: list[SavedSearchListItem] = Field(default_factory=list)
    total: int = 0

    model_config = {"extra": "forbid"}


class SavedSearchAnnotation(BaseModel):
    """Per-candidate discovery state, keyed by public slug in the results
    response. ``changed_requirements`` are display names reconstructed live
    from the plan — never persisted prose."""

    is_new: bool = False
    evidence_updated: bool = False
    changed_requirements: list[str] = Field(default_factory=list)
    first_matched_at: Any = None

    model_config = {"extra": "forbid"}


class SavedSearchResultsResponse(BaseModel):
    """Live results (same shape as recruiter search) + discovery
    annotations. ``truncated`` is True when the exact-match set exceeded the
    tracking bound — stated, never silent."""

    saved_search: SavedSearchListItem
    results: list[SearchResultCandidate] = Field(default_factory=list)
    total: int = 0
    exact_total: int = 0
    close_total: int = 0
    page: int = 1
    page_size: int = 10
    has_more: bool = False
    interpretation: QueryInterpretation = Field(default_factory=QueryInterpretation)
    annotations: dict[str, SavedSearchAnnotation] = Field(default_factory=dict)
    truncated: bool = False

    model_config = {"extra": "forbid"}


class SavedSearchDeleteResponse(BaseModel):
    deleted: bool = False

    model_config = {"extra": "forbid"}


__all__ = [
    "CreateSavedSearchRequest",
    "SavedSearchAnnotation",
    "SavedSearchDeleteResponse",
    "SavedSearchFilters",
    "SavedSearchListItem",
    "SavedSearchListResponse",
    "SavedSearchResponse",
    "SavedSearchResultsResponse",
    "UpdateSavedSearchRequest",
]
