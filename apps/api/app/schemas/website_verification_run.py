"""Schemas for website verification execution runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


WebsiteVerificationRunStatus = Literal[
    "pending",
    "partial_verification",
    "static_verified",
    "failed_static_checks",
    "needs_browser_execution",
    "needs_review",
    "execution_error",
]
WebsiteVerificationRunCheckStatus = Literal["passed", "failed", "needs_review", "browser_required"]
WebsiteVerificationRunCheckType = Literal[
    "static_text_presence",
    "static_title_presence",
    "static_heading_presence",
    "expected_output_keyword_check",
    "manual/browser_required",
]


class WebsiteVerificationRunExecuteRequest(BaseModel):
    plan_id: str | None = Field(default=None)


class WebsiteVerificationRunCheckResponse(BaseModel):
    id: str
    run_id: str
    check_key: str
    check_label: str
    check_type: WebsiteVerificationRunCheckType
    expected_value: str | None = None
    observed_value: str | None = None
    check_status: WebsiteVerificationRunCheckStatus
    check_summary: str | None = None
    created_at: str


class WebsiteVerificationRunResponse(BaseModel):
    id: str
    evidence_id: str
    plan_id: str
    user_id: str
    execution_status: WebsiteVerificationRunStatus
    executor_version: str
    execution_summary: str | None = None
    checks_attempted: int
    checks_passed: int
    checks_failed: int
    checks_needing_review: int
    inspected_url: str | None = None
    inspected_title: str | None = None
    inspected_meta_description: str | None = None
    inspected_headings: list[str]
    inspected_visible_text_excerpt: str | None = None
    raw_executor_notes: dict[str, Any]
    created_at: str
    updated_at: str
    checks: list[WebsiteVerificationRunCheckResponse] = Field(default_factory=list)


class WebsiteVerificationRunCreateResponse(WebsiteVerificationRunResponse):
    pass


class WebsiteVerificationRunListResponse(BaseModel):
    runs: list[WebsiteVerificationRunResponse]
