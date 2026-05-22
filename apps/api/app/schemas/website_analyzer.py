"""Pydantic schemas for the Website AI Analyzer (Phase J4D)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WebsiteAnalysisCandidate(BaseModel):
    candidate_id: str
    skill_name: str
    skill_category: str
    confidence: Literal["high", "medium", "low"]
    evidence_title: str
    evidence_summary: str
    source_url: str
    route_path: str                           # e.g. "/", "/docs", "/openapi.json"
    evidence_snippet: str
    evidence_type: Literal["deployed_website", "api_docs", "api_endpoint", "website_content"]
    action_label: str                         # "Open Live Website", "Open API Docs", etc.
    suggested_status: Literal["suggested", "needs_review"]


class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    skill_focus: str | None = Field(default=None, max_length=500)

    @field_validator("url")
    @classmethod
    def _require_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class WebsiteAnalyzeResponse(BaseModel):
    base_url: str
    candidates: list[WebsiteAnalysisCandidate]
    checked_urls: list[str]
    warnings: list[str]
    candidate_count: int
