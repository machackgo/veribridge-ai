"""Schemas for Extension Proof Sessions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ExtensionProofSessionStatus = Literal[
    "created",
    "waiting_for_extension",
    "recording",
    "uploaded_pending_analysis",
    "analyzing",
    "completed",
    "expired",
]


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
    started_at: str | None = None
    proof_upload_id: str | None = None
    created_at: str
    updated_at: str


class ExtensionProofStartResponse(ExtensionProofSessionResponse):
    pass


class ExtensionProofUploadRequest(BaseModel):
    workflow_events: list[dict[str, Any]] = Field(default_factory=list)
    screenshots: list[dict[str, Any]] | None = None
    browser_metadata: dict[str, Any] | None = None
    extension_version: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    student_final_note: str | None = Field(default=None, max_length=2000)
    # Multi-tab tracking metadata from the extension background service worker
    tracked_tab_count: int | None = None
    tracked_urls: list[str] | None = None
    external_tabs_opened: int | None = None


class ExtensionProofUploadResponse(BaseModel):
    id: str
    user_id: str
    skill_evidence_id: str
    status: ExtensionProofSessionStatus
    started_at: str | None = None
    proof_upload_id: str
    created_at: str
    updated_at: str


class ExtensionProofCompleteResponse(ExtensionProofSessionResponse):
    pass
