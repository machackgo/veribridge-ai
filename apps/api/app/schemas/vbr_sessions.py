"""Schemas for VBR session recording/upload endpoints (T4A skeleton)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.vbr_questions import VBRSessionQuestionResponse


class VBRSessionResponse(BaseModel):
    id: str
    project_id: str
    attempt_no: int
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: int | None = None
    webcam_present: bool
    chunk_count: int
    created_at: str
    updated_at: str


class VBRSessionDetailResponse(VBRSessionResponse):
    questions: list[VBRSessionQuestionResponse] = Field(default_factory=list)


class VBRConsentRequest(BaseModel):
    text_version: str | None = Field(default=None, min_length=1, max_length=100)


class VBRConsentResponse(BaseModel):
    id: str
    user_id: str
    kind: str
    granted: bool
    text_version: str
    created_at: str


class VBRChunkUploadRequest(BaseModel):
    chunk_index: int = Field(..., ge=0)
    storage_path: str = Field(..., min_length=1, max_length=500)
    bytes: int = Field(..., gt=0)
    sha256: str | None = Field(default=None, max_length=128)


class VBRChunkResponse(BaseModel):
    id: str
    session_id: str
    chunk_index: int
    bytes: int | None = None
    sha256: str | None = None
    received_at: str


class VBRTelemetryRequest(BaseModel):
    telemetry: dict[str, Any] = Field(default_factory=dict)
    merge: bool = Field(default=True)


class VBRTelemetryResponse(BaseModel):
    session_id: str
    telemetry: dict[str, Any] = Field(default_factory=dict)


class VBRFinalizeRequest(BaseModel):
    duration_s: int | None = Field(default=None, ge=0)
