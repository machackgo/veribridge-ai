"""Schemas for VBR project claim and question generation endpoints (T3 skeleton)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VBRClaimResponse(BaseModel):
    id: str
    project_id: str
    claim_text: str
    source: str
    status: str
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    skill_refs: list[Any] = Field(default_factory=list)
    sort_order: int
    created_at: str
    updated_at: str


class VBRClaimPatchRequest(BaseModel):
    claim_text: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Literal["proposed", "confirmed", "dropped"] | None = Field(default=None)


class VBRGenerateClaimsResponse(BaseModel):
    project_id: str
    status: str
    claims: list[VBRClaimResponse]


class VBRSessionQuestionResponse(BaseModel):
    id: str
    session_id: str
    sort_order: int
    question_text: str
    target_ref: dict[str, Any] = Field(default_factory=dict)
    claim_ids: list[str] = Field(default_factory=list)
    asked_at_s: float | None = None
    answered: bool
    created_at: str


class VBRGenerateQuestionsResponse(BaseModel):
    project_id: str
    session_id: str
    status: str
    questions: list[VBRSessionQuestionResponse]


class VBRQuestionsListResponse(BaseModel):
    project_id: str
    session_id: str | None = None
    questions: list[VBRSessionQuestionResponse]
