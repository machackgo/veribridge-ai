"""Typed contracts for the recruiter ↔ candidate connection API (v1).

The candidate payload is deliberately the consented PUBLIC identity only —
no emails, auth ids, or private profile fields ever appear here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SaveCandidateRequest(BaseModel):
    """Save the owner of a published public passport into the workspace."""

    passport_slug: str = Field(min_length=1, max_length=128)
    # Closed vocabulary (see recruiter_connection_service.CONNECTION_SOURCES);
    # unknown values are normalized server-side, never rejected.
    source: str | None = Field(default=None, max_length=32)
    source_context: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class ConnectionCandidate(BaseModel):
    """Public, consented identity of a saved candidate."""

    display_name: str | None = None
    headline: str | None = None
    summary: str | None = None
    availability_label: str | None = None
    location: str | None = None
    role_areas: list[str] = Field(default_factory=list)
    public_slug: str | None = None
    is_published: bool = False

    model_config = {"extra": "forbid"}


class RecruiterConnection(BaseModel):
    """One saved recruiter ↔ candidate relationship."""

    id: str
    source: str
    created_at: str | None = None
    candidate: ConnectionCandidate

    model_config = {"extra": "forbid"}


class SaveCandidateResponse(RecruiterConnection):
    """Save ack; ``already_saved`` distinguishes a repeat click from a first save."""

    saved: bool = True
    already_saved: bool = False


class RecruiterConnectionListResponse(BaseModel):
    connections: list[RecruiterConnection] = Field(default_factory=list)
    total: int = 0

    model_config = {"extra": "forbid"}


class ConnectionStatusResponse(BaseModel):
    saved: bool = False
    connection_id: str | None = None

    model_config = {"extra": "forbid"}


class ConnectionDeleteResponse(BaseModel):
    deleted: bool = False

    model_config = {"extra": "forbid"}


__all__ = [
    "ConnectionCandidate",
    "ConnectionDeleteResponse",
    "ConnectionStatusResponse",
    "RecruiterConnection",
    "RecruiterConnectionListResponse",
    "SaveCandidateRequest",
    "SaveCandidateResponse",
]
