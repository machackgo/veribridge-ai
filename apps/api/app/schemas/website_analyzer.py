"""Pydantic schemas for the Website AI Analyzer (Phase J4D / J4E / J4F / J4G)."""

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
    route_path: str        # "/", "/docs", "/openapi.json", "src/api.py L12–L40", etc.
    evidence_snippet: str
    evidence_type: Literal[
        "deployed_website", "api_docs", "api_endpoint", "website_content",
        "github_repo", "combined",
    ]
    action_label: str      # "Open Live Website", "Open API Docs", "Open GitHub Evidence", etc.
    suggested_status: Literal["suggested", "needs_review"]
    # J4E: source metadata
    evidence_source: Literal["website", "github_repo", "combined"] = "website"
    is_combined: bool = False
    related_source_url: str | None = None   # for combined: the other source URL


# ── J4F: Functional verification candidate ────────────────────────────────────

# ── J4H: Functional test plan (user-provided, optional) ──────────────────────

class FunctionalTestPlan(BaseModel):
    """User-supplied test plan for transparent functional verification.

    J4J: run_api_verification and run_browser_verification explicitly control
    which verification paths run. The test_mode field is kept for backward compat
    but the boolean flags take precedence when both are present.
    """
    what_to_test: str | None = Field(default=None, max_length=500)
    test_input: str | None = Field(default=None, max_length=2000)  # JSON or key=value
    expected_output: str | None = Field(default=None, max_length=500)
    # Kept for backward compat; new callers use the boolean flags below
    test_mode: Literal["auto", "api_endpoint", "browser_ui", "plan_only"] = "auto"
    # J4I: browser UI workflow screenshot fields
    frontend_url: str | None = Field(default=None, max_length=2000)
    browser_workflow_instructions: str | None = Field(default=None, max_length=2000)
    # J4J: explicit verification flags — both can be True simultaneously
    run_api_verification: bool = Field(default=True)
    run_browser_verification: bool = Field(default=True)


# ── J4I: Browser UI workflow verification result ──────────────────────────────

class BrowserWorkflowVerificationResult(BaseModel):
    """Result of a Playwright-based browser UI workflow screenshot capture."""
    success: bool
    frontend_url: str
    steps_run: list[str]
    expected_output_found: bool
    screenshot_data_url: str | None = None   # "data:image/jpeg;base64,..."
    screenshot_caption: str | None = None
    error_message: str | None = None
    no_ui_detected: bool = False
    screenshot_status: Literal["captured", "not_captured", "no_ui", "error"] = "not_captured"
    # J4J: richer result fields
    output_text_found: str | None = None
    output_terms_found: list[str] = Field(default_factory=list)
    browser_workflow_status: Literal["passed", "partial", "failed"] = "failed"
    proof_summary: str = ""


class FunctionalVerificationCandidate(BaseModel):
    candidate_id: str
    skill_name: str
    skill_category: str
    confidence: Literal["high", "medium", "low"]
    evidence_title: str
    evidence_summary: str
    endpoint_url: str
    method: str                      # "GET", "POST"
    request_summary: str
    response_fields_found: list[str]
    status_code: int | None = None
    verified: bool
    verification_message: str
    evidence_type: Literal["verified_workflow"] = "verified_workflow"
    action_label: str = "View Endpoint"
    suggested_status: Literal["suggested", "needs_review"] = "suggested"
    # J4H: transparency fields
    test_input_source: Literal["auto_generated", "user_provided", "schema_example"] = "auto_generated"
    is_user_guided: bool = False
    verification_label: str = "Auto-detected API test"
    request_body_summary: str = ""   # "origin=Fenway Park; destination=Logan Airport; num_segments=5"
    what_to_test: str | None = None
    expected_output_description: str | None = None
    # Actual response captured from the live endpoint
    response_preview: dict | None = None      # key-value pairs extracted from JSON response
    response_summary: str = ""                # "risk_class: High; confidence: 0.82; routes_count: 3"
    raw_response_json: str | None = None      # JSON string, capped at 3 000 chars
    response_truncated: bool = False          # True when raw_response_json was capped
    # J4I: screenshot / browser workflow proof
    screenshot_url: str | None = None
    screenshot_caption: str | None = None
    screenshot_status: Literal["unavailable", "manual", "auto_captured"] = "unavailable"
    browser_workflow_status: Literal["not_started", "pending", "completed", "failed"] = "not_started"
    browser_workflow_notes: str | None = None


# ── J4G: High-level grouped skill evidence ────────────────────────────────────

class GroupedWebsiteSkill(BaseModel):
    group_id: str
    skill_name: str           # "Machine Learning Engineering"
    category: str             # same as skill_name by default
    confidence: Literal["high", "medium", "low"]
    sources: list[Literal["website", "github_repo", "functional", "combined"]]
    subskills: list[str]      # atomic skill names that contribute to this group
    evidence_count: int
    website_count: int
    repo_count: int
    functional_count: int
    combined_count: int
    candidate_ids: list[str]            # all underlying candidate IDs (atomic + functional)
    functional_candidate_ids: list[str] # only functional verification candidate IDs
    system_graph_nodes: list[str]
    system_graph_edges: list[tuple[str, str]]
    suggested_status: Literal["suggested", "needs_review"]
    # Honesty / partial-proof fields (J4H)
    is_partial: bool = False
    partial_proof_message: str | None = None
    missing_proof_suggestions: list[str] = Field(default_factory=list)
    inferred_cloud_platform: str | None = None


# ── Request / Response ────────────────────────────────────────────────────────

class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    skill_focus: str | None = Field(default=None, max_length=500)
    github_repo_url: str | None = Field(default=None, max_length=2000)
    run_safe_tests: bool = Field(default=True)
    functional_test_plan: FunctionalTestPlan | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def _require_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("github_repo_url")
    @classmethod
    def _validate_repo_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("GitHub repo URL must start with http:// or https://")
        return v


class WebsiteAnalyzeResponse(BaseModel):
    base_url: str
    candidates: list[WebsiteAnalysisCandidate]
    # J4F: functional verification results
    functional_candidates: list[FunctionalVerificationCandidate] = Field(default_factory=list)
    # J4G: high-level grouped skill cards
    grouped_skills: list[GroupedWebsiteSkill] = Field(default_factory=list)
    # J4I: browser UI workflow screenshot result
    browser_workflow_result: BrowserWorkflowVerificationResult | None = None
    checked_urls: list[str]
    warnings: list[str]
    candidate_count: int
    # J4E: source counts
    website_candidate_count: int = 0
    repo_candidate_count: int = 0
    combined_candidate_count: int = 0
    # J4F: functional verification counts
    functional_candidate_count: int = 0
    functional_verification_available: bool = False
    github_repo_url: str | None = None
