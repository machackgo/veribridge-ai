"""Typed contracts for recruiter talent pools (v2, migration 068).

Pools are recruiter-private groupings of saved candidates. Members are
exposed as stable student user ids only — the UI joins them against the
recruiter's own workspace listing for identity.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreatePoolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    model_config = {"extra": "forbid"}


class AddPoolMemberRequest(BaseModel):
    """Members are added through one of the caller's OWN saved-candidate
    connections — a recruiter can only pool candidates they saved."""

    connection_id: str = Field(min_length=1, max_length=64)

    model_config = {"extra": "forbid"}


class TalentPool(BaseModel):
    id: str
    name: str
    member_user_ids: list[str] = Field(default_factory=list)
    member_count: int = 0
    created_at: Any = None
    updated_at: Any = None

    model_config = {"extra": "forbid"}


class TalentPoolListResponse(BaseModel):
    pools: list[TalentPool] = Field(default_factory=list)
    total: int = 0

    model_config = {"extra": "forbid"}


class PoolDeleteResponse(BaseModel):
    deleted: bool = False

    model_config = {"extra": "forbid"}


__all__ = [
    "AddPoolMemberRequest",
    "CreatePoolRequest",
    "PoolDeleteResponse",
    "TalentPool",
    "TalentPoolListResponse",
]
