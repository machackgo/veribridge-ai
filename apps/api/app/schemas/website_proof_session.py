"""Schemas for the controlled browser proof session (Manual Login Handoff)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebsiteProofSessionCreateRequest(BaseModel):
    website_url: str
    frontend_url: str | None = None
    auth_mode: str = "manual_login_handoff"
    test_input: str | None = None
    expected_output: str | None = None
    workflow_instructions: str | None = None


class WebsiteProofSessionResumeResponse(BaseModel):
    session_id: str
    status: str
    auth_mode: str
    login_url: str | None = None
    login_screenshot: str | None = None
    final_screenshot: str | None = None
    final_page_text: str | None = None
    steps_run: list[str] = []
    proof_summary: str | None = None
    error_message: str | None = None
    expires_at: str
    created_at: str


class WebsiteProofSummaryResponse(BaseModel):
    """Safe summary of a completed Website Proof session.

    Never includes screenshots, storage paths, signed URLs, tokens, or raw
    transcripts — used for listing a student's own Website Proofs (e.g. to
    attach to a Project Defense).
    """

    proof_session_id: str
    target_website: str = ""
    evidence_strength_score: int = 0
    workflow_confidence: str = "insufficient"
    supported_skills: list[str] = Field(default_factory=list)
    created_at: str = ""
