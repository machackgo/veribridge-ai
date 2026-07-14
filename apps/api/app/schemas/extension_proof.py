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
    # Explicit project context is the canonical path for a countable Website
    # Proof. The route verifies ownership before the service persists the link.
    # Older clients may omit it; those proofs remain vault-only/suggested and are
    # never silently attached from skill-name overlap.
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    parent_proof_session_id: str | None = None
    followup_target_skill: str | None = Field(default=None, max_length=200)
    followup_objective: str | None = Field(default=None, max_length=1000)
    proof_attempt_type: Literal["original", "followup"] = "original"
    website_url: str | None = Field(default=None, max_length=1200)
    github_url: str | None = Field(default=None, max_length=1200)
    claimed_skills: list[str] | None = None
    proof_objective: str | None = Field(default=None, max_length=2000)

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
    project_id: str | None = None
    project_relationship_state: str = "vault_only"
    website_url: str | None = None
    github_url: str | None = None
    claimed_skills: list[str] = Field(default_factory=list)
    proof_objective: str | None = None
    # Set only after the completed proof has crossed the shared canonical
    # finalization boundary.  This is deliberately distinct from merely
    # selecting a project while creating the recording session.
    finalized_at: str | None = None
    finalized_project_id: str | None = None
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
    # Privacy Guard: scan result injected after upload (optional — no-op for old clients)
    privacy_scan_status: str | None = None    # 'clean' | 'redacted' | 'flagged'
    privacy_scan_summary: str | None = None


class ExtensionProofCompleteResponse(ExtensionProofSessionResponse):
    pass
