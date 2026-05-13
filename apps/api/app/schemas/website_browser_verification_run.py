"""Schemas for safe browser website verification runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


WebsiteBrowserVerificationRunStatus = Literal[
    "pending",
    "browser_verified",
    "browser_partially_verified",
    "browser_failed",
    "needs_human_review",
    "blocked_by_login",
    "unsupported_plan",
    "execution_timeout",
    "execution_error",
]
WebsiteBrowserVerificationStepAction = Literal[
    "navigate",
    "wait_for_selector",
    "click",
    "fill",
    "select",
    "wait_for_text",
    "assert_text_present",
    "assert_selector_present",
    "screenshot",
    "unsupported",
    "skipped",
]
WebsiteBrowserVerificationStepStatus = Literal[
    "passed",
    "failed",
    "skipped",
    "unsupported",
    "needs_review",
    "blocked_by_login",
    "timeout",
]


class WebsiteBrowserVerificationExecutionRequest(BaseModel):
    plan_id: str | None = Field(default=None)


class WebsiteBrowserVerificationStepResponse(BaseModel):
    id: str
    run_id: str
    step_index: int
    plan_step_key: str | None = None
    action_type: WebsiteBrowserVerificationStepAction
    action_target: str | None = None
    action_value: str | None = None
    expected_result: str | None = None
    observed_result: str | None = None
    step_status: WebsiteBrowserVerificationStepStatus
    step_summary: str | None = None
    screenshot_storage_path: str | None = None
    created_at: str


class WebsiteBrowserVerificationRunResponse(BaseModel):
    id: str
    evidence_id: str
    plan_id: str
    user_id: str
    browser_execution_status: WebsiteBrowserVerificationRunStatus
    executor_version: str
    execution_summary: str | None = None
    inspected_url: str | None = None
    final_url: str | None = None
    page_title: str | None = None
    screenshot_storage_path: str | None = None
    html_snapshot_storage_path: str | None = None
    safe_text_snapshot: str | None = None
    steps_attempted: int
    steps_passed: int
    steps_failed: int
    steps_skipped: int
    steps_needing_review: int
    browser_metadata: dict[str, Any]
    created_at: str
    updated_at: str
    steps: list[WebsiteBrowserVerificationStepResponse] = Field(default_factory=list)


class WebsiteBrowserVerificationRunListResponse(BaseModel):
    runs: list[WebsiteBrowserVerificationRunResponse]
