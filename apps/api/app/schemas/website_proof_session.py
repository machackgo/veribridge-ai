"""Schemas for the controlled browser proof session (Manual Login Handoff)."""

from __future__ import annotations

from pydantic import BaseModel


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
