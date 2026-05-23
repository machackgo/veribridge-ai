"""Schemas for Extension Proof Sessions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ExtensionProofSessionStatus = Literal["pending", "active", "completed", "expired"]


class ExtensionProofSessionCreate(BaseModel):
    skill_evidence_id: str = Field(..., min_length=1)

    @field_validator("skill_evidence_id", mode="before")
    @classmethod
    def _strip(cls, v: object) -> str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("skill_evidence_id must not be blank")
            return stripped
        return str(v).strip()


class ExtensionProofSessionResponse(BaseModel):
    id: str
    user_id: str
    skill_evidence_id: str
    status: ExtensionProofSessionStatus
    created_at: str
    updated_at: str
