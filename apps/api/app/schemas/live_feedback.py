"""Schemas for the Live Proof Feedback Agent."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Inbound: lightweight live signals from extension ──────────────────────────

class LiveSignalsInput(BaseModel):
    """Lightweight live signals pushed by the Chrome extension during recording."""

    claimed_skills: list[str] = Field(default_factory=list)
    current_url: str = ""
    page_title: str = ""
    dom_text_snippets: list[str] = Field(default_factory=list)
    click_count: int = 0
    input_count: int = 0
    form_submit_count: int = 0
    output_block_count: int = 0
    canvas_count: int = 0
    svg_count: int = 0
    github_url_seen: bool = False
    recording_duration_s: float = 0.0
    sensitive_warning_seen: bool = False


# ── Evidence checklist ────────────────────────────────────────────────────────

class EvidenceChecklist(BaseModel):
    website_loaded: bool = False
    dom_text_seen: bool = False
    interaction_seen: bool = False
    form_input_seen: bool = False
    output_or_result_seen: bool = False
    chart_or_visual_seen: bool = False
    code_or_repo_seen: bool = False
    github_seen: bool = False
    sensitive_warning: bool = False


SupportLevel = Literal["missing", "partial", "likely"]


class SkillSupport(BaseModel):
    skill: str
    support_level: SupportLevel
    evidence_source: str
    short_reason: str


# ── Outbound: live feedback state ─────────────────────────────────────────────

class LiveFeedbackState(BaseModel):
    session_id: str
    recording_status: Literal["recording", "stopped", "analyzing"] = "recording"
    checklist: EvidenceChecklist
    live_score: int = Field(ge=0, le=100)
    claimed_skill_support: list[SkillSupport] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    sensitive_warning: bool = False
    last_updated_at: datetime
