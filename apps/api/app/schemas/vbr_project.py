"""Schemas for Verified Build Report (VBR) project endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VBRProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    repo_url: str = Field(..., min_length=1, max_length=500)
    repo_full_name: str | None = Field(default=None, max_length=200)
    deployed_url: str | None = Field(default=None, max_length=500)


class VBRProjectResponse(BaseModel):
    id: str
    title: str
    repo_url: str
    repo_full_name: str | None = None
    deployed_url: str | None = None
    head_sha: str | None = None
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VBRRepoAnalysisResponse(BaseModel):
    id: str
    project_id: str
    head_sha: str | None = None
    facts: dict
    fork: bool | None = None
    authorship_match_pct: float | None = None
    computed_at: str


class VBRDeployedUrlCheckResponse(BaseModel):
    id: str
    project_id: str
    url: str
    status_code: int | None = None
    title: str | None = None
    result: str
    detail: str | None = None
    checked_at: str
