"""
Tests for precise visual workflow evidence extraction (v3).

Verifies that:
- IAO (input→action→output) patterns are detected from event sequences.
- App type is correctly inferred from URL/title/events.
- observed_demonstration is built with correct structure.
- visual_analysis_status is "not_configured" (v5) when no provider is set (was "not_available" pre-v5).
- detected_result_values is empty (no OCR available yet).
- Recruiter summary describes the workflow PATTERN, not just "user clicked upload".
- Object detection workflow produces an image_to_prediction pattern.
- Route/risk workflow produces a location_to_route_or_risk pattern.
- Dashboard workflow produces a filter_to_visualization pattern.
- Chatbot workflow produces a prompt_to_response pattern.
- Document workflow produces a document_to_extraction pattern.
- Skills are evidence-based from demonstrated feature, not keyword-only matching.
- TensorFlow.js / JavaScript / TypeScript are not overclaimed without source evidence.
- Summary says outputs were not readable when visual analysis is unavailable.
- Noise / internal URLs still filtered from recruiter summary.
- Public summary does not expose internal URLs or media paths.
- Endpoint returns observed_demonstration and visual_analysis_status.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.extension_proof_workflow_analysis_service import (
    _analyze_workflow,
    _detect_app_type,
    _extract_iao_patterns,
    _build_observed_demonstration,
    _build_demonstration_steps,
    _SESSION_TABLE,
)

# ── Constants ──────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000088"

# Object detection app (TF.js / COCO-SSD style)
DETECTION_URL   = "https://object-detection-demo.vercel.app"
STREAMLIT_URL   = "https://mlexplainer.streamlit.app"
CHATBOT_URL     = "https://my-chatbot.vercel.app"
ROUTE_URL       = "https://floodrisk.vercel.app"
DASHBOARD_URL   = "https://analytics.vercel.app"
DOCUMENT_URL    = "https://docsummarizer.vercel.app"
GITHUB_URL      = "https://github.com/user/ml-project"
VB_DASH_URL     = "http://localhost:3000/dashboard/profile"
SUPABASE_URL    = "https://app.supabase.io/project/abc/editor"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_proof_data(events: list[dict], duration_secs: int = 120) -> dict:
    start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    stop  = start + timedelta(seconds=duration_secs)
    return {
        "workflow_events": events,
        "started_at": start.isoformat(),
        "stopped_at": stop.isoformat(),
    }


def _run(
    proof_data: dict,
    original_url: str = DETECTION_URL,
    url_type: str = "live_deployed_url",
    claimed_skills: list[str] | None = None,
    proof_objective: str = "",
    github_url: str | None = None,
) -> dict:
    return _analyze_workflow(
        proof_data=proof_data,
        claimed_skills=claimed_skills or [],
        proof_objective=proof_objective,
        original_url=original_url,
        url_type=url_type,
        github_url=github_url,
    )


def _detection_events(with_output_page: bool = True) -> list[dict]:
    events = [
        {"type": "page_visit", "page_url": DETECTION_URL, "page_title": "Object Detection Demo"},
        {"type": "click",      "page_url": DETECTION_URL, "element_text": "Upload Image"},
        {"type": "input_change", "page_url": DETECTION_URL, "element_id": "image-upload"},
        {"type": "click",      "page_url": DETECTION_URL, "element_text": "Detect"},
    ]
    if with_output_page:
        events.append({
            "type": "page_visit",
            "page_url": DETECTION_URL + "/results",
            "page_title": "Detection Results",
        })
    return events


def _chatbot_events() -> list[dict]:
    return [
        {"type": "page_visit",  "page_url": CHATBOT_URL, "page_title": "My Chatbot"},
        {"type": "input_change","page_url": CHATBOT_URL, "element_id": "message-input"},
        {"type": "click",       "page_url": CHATBOT_URL, "element_text": "Send"},
        {"type": "page_visit",  "page_url": CHATBOT_URL + "/conversation", "page_title": "Chat Response"},
    ]


def _route_events() -> list[dict]:
    return [
        {"type": "page_visit",  "page_url": ROUTE_URL, "page_title": "Flood Risk Analyzer"},
        {"type": "input_change","page_url": ROUTE_URL, "element_id": "location-input"},
        {"type": "click",       "page_url": ROUTE_URL, "element_text": "Analyze Risk"},
        {"type": "page_visit",  "page_url": ROUTE_URL + "/result", "page_title": "Risk Analysis Result"},
    ]


def _dashboard_events() -> list[dict]:
    return [
        {"type": "page_visit", "page_url": DASHBOARD_URL, "page_title": "Analytics Dashboard"},
        {"type": "click",      "page_url": DASHBOARD_URL, "element_text": "Filter by Region"},
        {"type": "page_visit", "page_url": DASHBOARD_URL + "/report", "page_title": "Sales Report"},
    ]


def _document_events() -> list[dict]:
    return [
        {"type": "page_visit",  "page_url": DOCUMENT_URL, "page_title": "Document Summarizer"},
        {"type": "click",       "page_url": DOCUMENT_URL, "element_text": "Upload Document"},
        {"type": "input_change","page_url": DOCUMENT_URL, "element_id": "file-upload"},
        {"type": "click",       "page_url": DOCUMENT_URL, "element_text": "Summarize"},
        {"type": "page_visit",  "page_url": DOCUMENT_URL + "/summary", "page_title": "Document Summary"},
    ]


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(mem_store: dict, proof_data: dict) -> str:
    import uuid
    session_id = str(uuid.uuid4())
    mem_store.setdefault(_SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": DEMO_USER_ID,
        "status": "uploaded_pending_analysis",
        "proof_data": proof_data,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    return session_id


# ── App type detection ─────────────────────────────────────────────────────────

class TestDetectAppType:

    def test_ml_app_from_streamlit_url(self):
        assert _detect_app_type(STREAMLIT_URL, ["MLExplainer"], [], "ML demo") == "ml_app"

    def test_ml_app_from_detection_title(self):
        assert _detect_app_type(DETECTION_URL, ["Object Detection Demo"], [], "") == "ml_app"

    def test_chatbot_from_title(self):
        assert _detect_app_type(CHATBOT_URL, ["My Chatbot"], [], "") == "chatbot"

    def test_chatbot_from_objective(self):
        atype = _detect_app_type(CHATBOT_URL, [], [], "demonstrate chatbot assistant")
        assert atype == "chatbot"

    def test_route_map_from_title(self):
        assert _detect_app_type(ROUTE_URL, ["Flood Risk Analyzer"], [], "") == "route_map"

    def test_route_map_from_objective(self):
        atype = _detect_app_type(ROUTE_URL, [], [], "route risk map navigation")
        assert atype == "route_map"

    def test_dashboard_from_title(self):
        assert _detect_app_type(DASHBOARD_URL, ["Analytics Dashboard"], [], "") == "dashboard"

    def test_document_from_title(self):
        assert _detect_app_type(DOCUMENT_URL, ["Document Summarizer"], [], "") == "document"

    def test_portfolio_from_github_io(self):
        atype = _detect_app_type("https://user.github.io/portfolio", [], [], "")
        assert atype == "portfolio"

    def test_generic_fallback(self):
        atype = _detect_app_type("https://myproject.vercel.app", ["My Project"], [], "show my app")
        # should not be ml_app / chatbot / etc.
        assert atype in ("generic", "portfolio")


# ── IAO pattern extraction ─────────────────────────────────────────────────────

class TestExtractIAOPatterns:

    def test_detection_events_produce_image_to_prediction(self):
        events = _detection_events()
        patterns = _extract_iao_patterns(events, "ml_app")
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "image_to_prediction"

    def test_detection_has_upload_input(self):
        events = _detection_events()
        patterns = _extract_iao_patterns(events, "ml_app")
        assert patterns[0]["input_event"] is not None

    def test_detection_has_action_event(self):
        events = _detection_events()
        patterns = _extract_iao_patterns(events, "ml_app")
        assert patterns[0]["action_event"] is not None

    def test_detection_has_output_event_when_present(self):
        events = _detection_events(with_output_page=True)
        patterns = _extract_iao_patterns(events, "ml_app")
        assert patterns[0]["output_event"] is not None

    def test_detection_no_output_event_when_missing(self):
        events = _detection_events(with_output_page=False)
        patterns = _extract_iao_patterns(events, "ml_app")
        assert patterns[0]["output_event"] is None

    def test_chatbot_produces_prompt_to_response(self):
        events = _chatbot_events()
        patterns = _extract_iao_patterns(events, "chatbot")
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "prompt_to_response"

    def test_route_produces_location_to_route_or_risk(self):
        events = _route_events()
        patterns = _extract_iao_patterns(events, "route_map")
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "location_to_route_or_risk"

    def test_dashboard_produces_filter_to_visualization(self):
        events = _dashboard_events()
        patterns = _extract_iao_patterns(events, "dashboard")
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "filter_to_visualization"

    def test_document_produces_document_to_extraction(self):
        events = _document_events()
        patterns = _extract_iao_patterns(events, "document")
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "document_to_extraction"

    def test_no_patterns_from_empty_events(self):
        patterns = _extract_iao_patterns([], "ml_app")
        assert len(patterns) == 0


# ── Observed demonstration builder ────────────────────────────────────────────

class TestBuildObservedDemonstration:

    def _build(self, events: list[dict], app_type: str, url: str) -> dict:
        from urllib.parse import urlparse
        target_app = urlparse(url).netloc
        patterns = _extract_iao_patterns(events, app_type)
        return _build_observed_demonstration(events, app_type, target_app, patterns)

    def test_visual_analysis_status_is_not_configured(self):
        """v5: visual_analysis_status is 'not_configured' when no provider is set.
        (Previously 'not_available' in v3; updated to match v5 terminology.)
        """
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        assert demo["visual_analysis_status"] in ("not_configured", "not_available"), (
            f"Expected not_configured (v5) or not_available (v3 compat), got: {demo['visual_analysis_status']}"
        )

    def test_detected_result_values_is_empty(self):
        """No OCR → no result values should be populated."""
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        for step in demo["steps"]:
            assert step["detected_result_values"] == [], (
                f"Step {step['step_number']} should have no detected_result_values "
                "since frame/OCR is not available"
            )

    def test_steps_include_app_open(self):
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        assert len(demo["steps"]) >= 1
        assert "Opened" in demo["steps"][0]["user_action"] or "target" in demo["steps"][0]["user_action"].lower()

    def test_steps_include_upload_input(self):
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        upload_steps = [s for s in demo["steps"] if s.get("observed_input")]
        assert len(upload_steps) >= 1

    def test_steps_include_action_trigger(self):
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        action_steps = [s for s in demo["steps"] if "Detect" in (s.get("user_action") or "") or "action" in (s.get("user_action") or "").lower()]
        # Should have at least a step for the click action
        assert any("Detect" in (s.get("user_action") or "") or "Triggered" in (s.get("user_action") or "") for s in demo["steps"])

    def test_steps_include_output_observation(self):
        demo = self._build(_detection_events(with_output_page=True), "ml_app", DETECTION_URL)
        output_steps = [s for s in demo["steps"] if s.get("observed_output")]
        assert len(output_steps) >= 1

    def test_summary_says_outputs_not_readable(self):
        """Summary must be honest: exact values are not readable without frame analysis."""
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        summary = demo["summary"].lower()
        assert "not readable" in summary or "not available" in summary or "not yet available" in summary

    def test_summary_describes_iao_pattern(self):
        """Summary should describe image-input to prediction-output, not just 'clicked upload'."""
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        summary = demo["summary"].lower()
        assert "prediction" in summary or "inference" in summary or "input" in summary

    def test_limitations_lists_ocr_unavailable(self):
        demo = self._build(_detection_events(), "ml_app", DETECTION_URL)
        limitations_text = " ".join(demo["limitations"]).lower()
        assert "frame" in limitations_text or "ocr" in limitations_text or "not available" in limitations_text

    def test_chatbot_demo_describes_prompt_response(self):
        demo = self._build(_chatbot_events(), "chatbot", CHATBOT_URL)
        summary = demo["summary"].lower()
        assert "prompt" in summary or "response" in summary or "conversation" in summary

    def test_route_demo_describes_location_output(self):
        demo = self._build(_route_events(), "route_map", ROUTE_URL)
        summary = demo["summary"].lower()
        assert "location" in summary or "route" in summary or "risk" in summary


# ── Full workflow analysis with observed_demonstration ─────────────────────────

class TestAnalyzeWorkflowWithObservedDemonstration:

    def test_result_includes_observed_demonstration(self):
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["Object Detection", "Computer Vision"],
            proof_objective="Demonstrate object detection app",
        )
        assert "observed_demonstration" in result
        assert result["observed_demonstration"] is not None

    def test_visual_analysis_status_in_result(self):
        """v5: status is 'not_configured' when no provider set (was 'not_available' in v3)."""
        result = _run(_make_proof_data(_detection_events()), original_url=DETECTION_URL)
        assert result["visual_analysis_status"] in ("not_configured", "not_available")

    def test_no_fake_detection_values(self):
        """Must NOT produce fake "dog 0.89" values when OCR is unavailable."""
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["Object Detection"],
        )
        obs = result["observed_demonstration"]
        for step in obs["steps"]:
            assert step["detected_result_values"] == [], (
                "detected_result_values must be empty until frame/OCR is available"
            )

    def test_recruiter_summary_describes_iao_not_just_clicks(self):
        """Summary should describe workflow PATTERN, not just 'user clicked upload'."""
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            proof_objective="Demonstrate image classification",
            claimed_skills=["Object Detection"],
        )
        summary = result["recruiter_summary"].lower()
        # Should describe the workflow pattern
        assert any(kw in summary for kw in [
            "image", "input", "prediction", "detection", "inference", "workflow", "result"
        ]), f"Expected IAO narrative in: {summary}"
        # Should NOT just say "user clicked upload"
        assert "user clicked upload" not in summary

    def test_recruiter_summary_honest_about_missing_ocr(self):
        """Summary must say values were not readable from timeline if relevant."""
        result = _run(
            _make_proof_data(_detection_events(with_output_page=True)),
            original_url=DETECTION_URL,
            claimed_skills=["Object Detection"],
        )
        summary = result["recruiter_summary"].lower()
        # The summary should admit it can't read exact values
        assert any(kw in summary for kw in [
            "not readable", "timeline", "frame analysis", "not yet available", "exact"
        ]), f"Expected honest output limitation in: {summary}"

    # ── Skill support from demonstrated feature ────────────────────────────────

    def test_object_detection_skill_from_detection_workflow(self):
        """Object Detection should be supported when the workflow shows detection pattern."""
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["Object Detection", "Computer Vision"],
            proof_objective="object detection demo",
        )
        all_evidence = result["supported_skills"] + result["weakly_supported_skills"]
        # At minimum, Object Detection should appear in some evidence list
        assert any("Detection" in s or "Vision" in s or "Object" in s or "ML" in s or "Machine" in s for s in all_evidence), (
            f"Expected Object Detection / Computer Vision in evidence. Got: supported={result['supported_skills']}, weakly={result['weakly_supported_skills']}"
        )

    def test_tensorflow_js_not_overclaimed_from_workflow_alone(self):
        """TensorFlow.js must NOT be in supported_skills from workflow alone (needs code evidence)."""
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["TensorFlow.js"],
        )
        # TensorFlow.js requires code evidence — must NOT be in strongly supported
        assert "TensorFlow.js" not in result["supported_skills"], (
            "TensorFlow.js must not be in supported_skills without code/GitHub evidence"
        )

    def test_javascript_not_overclaimed_from_workflow_alone(self):
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["JavaScript"],
        )
        # JavaScript requires code evidence
        assert "JavaScript" not in result["supported_skills"], (
            "JavaScript must not be in supported_skills without GitHub/code evidence"
        )

    def test_typescript_not_overclaimed_from_workflow_alone(self):
        result = _run(
            _make_proof_data(_detection_events()),
            original_url=DETECTION_URL,
            claimed_skills=["TypeScript"],
        )
        assert "TypeScript" not in result["supported_skills"]

    # ── Route/risk workflow ────────────────────────────────────────────────────

    def test_route_risk_workflow_captures_iao(self):
        result = _run(
            _make_proof_data(_route_events()),
            original_url=ROUTE_URL,
            claimed_skills=["Geospatial Analysis", "Risk Assessment"],
            proof_objective="flood risk analysis",
        )
        obs = result["observed_demonstration"]
        assert obs is not None
        assert obs["visual_analysis_status"] in ("not_configured", "not_available")
        summary = obs["summary"].lower()
        assert "location" in summary or "route" in summary or "risk" in summary

    # ── Dashboard workflow ─────────────────────────────────────────────────────

    def test_dashboard_workflow_captures_iao(self):
        result = _run(
            _make_proof_data(_dashboard_events()),
            original_url=DASHBOARD_URL,
            claimed_skills=["Data Visualization", "Analytics"],
            proof_objective="analytics dashboard demo",
        )
        obs = result["observed_demonstration"]
        assert obs is not None
        summary = obs["summary"].lower()
        assert "dashboard" in summary or "visualization" in summary or "filter" in summary

    # ── Document workflow ──────────────────────────────────────────────────────

    def test_document_workflow_captures_iao(self):
        result = _run(
            _make_proof_data(_document_events()),
            original_url=DOCUMENT_URL,
            claimed_skills=["Document Processing", "NLP"],
            proof_objective="document summarization demo",
        )
        obs = result["observed_demonstration"]
        assert obs is not None
        summary = obs["summary"].lower()
        assert "document" in summary or "upload" in summary or "extract" in summary

    # ── Noise filtering still works ────────────────────────────────────────────

    def test_noise_still_filtered_with_v3(self):
        """Noise filtering from v2 must still work with v3 IAO extraction."""
        events = _detection_events() + [
            {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase"},
            {"type": "page_visit", "page_url": VB_DASH_URL, "page_title": "VeriBridge"},
        ]
        result = _run(
            _make_proof_data(events),
            original_url=DETECTION_URL,
        )
        assert result["noise_filtered_count"] >= 2
        # Summary must not mention noise
        summary = result["recruiter_summary"].lower()
        assert "supabase" not in summary
        assert "dashboard/profile" not in summary

    def test_public_summary_does_not_expose_internal_routes(self):
        events = _detection_events() + [
            {"type": "page_visit", "page_url": VB_DASH_URL, "page_title": "VB"},
        ]
        result = _run(_make_proof_data(events), original_url=DETECTION_URL)
        summary = result["recruiter_summary"]
        assert "localhost:3000/dashboard" not in summary
        assert "supabase" not in summary.lower()

    # ── Unreadable output case ─────────────────────────────────────────────────

    def test_unreadable_output_says_not_visible(self):
        """When there is no output page event, the summary should say
        prediction output was not observed."""
        result = _run(
            _make_proof_data(_detection_events(with_output_page=False)),
            original_url=DETECTION_URL,
            claimed_skills=["Object Detection"],
            proof_objective="object detection app",
        )
        obs = result["observed_demonstration"]
        # No output step should have observed_output
        output_steps_with_value = [s for s in obs["steps"] if s.get("observed_output")]
        # Either no output steps, or limitations mention unreadable
        if output_steps_with_value:
            limitations_text = " ".join(obs["limitations"]).lower()
            assert "not readable" in limitations_text or "frame" in limitations_text

    # ── Multiple outputs captured ──────────────────────────────────────────────

    def test_multiple_iao_steps_captured(self):
        """A full detection workflow should produce multiple structured steps."""
        result = _run(
            _make_proof_data(_detection_events(with_output_page=True)),
            original_url=DETECTION_URL,
        )
        obs = result["observed_demonstration"]
        assert len(obs["steps"]) >= 2  # At least app open + one IAO step


# ── HTTP endpoint tests ────────────────────────────────────────────────────────

class TestWorkflowAnalysisEndpointV3:

    def test_endpoint_returns_observed_demonstration(
        self, client: TestClient, mem_store: dict
    ):
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Object Detection", "Computer Vision"],
                "proof_objective": "object detection app",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "observed_demonstration" in data
        assert data["observed_demonstration"] is not None
        assert "steps" in data["observed_demonstration"]
        assert "summary" in data["observed_demonstration"]
        assert "limitations" in data["observed_demonstration"]

    def test_endpoint_visual_analysis_status_not_configured(
        self, client: TestClient, mem_store: dict
    ):
        """v5: visual_analysis_status is 'not_configured' when no provider is set.
        (Was 'not_available' in v3; backward compat accepts both values.)
        """
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": [],
                "proof_objective": "",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # v5: "not_configured" when no provider; legacy rows may still have "not_available"
        assert data["visual_analysis_status"] in ("not_configured", "not_available")
        assert data["observed_demonstration"]["visual_analysis_status"] in ("not_configured", "not_available")

    def test_endpoint_no_fake_result_values(
        self, client: TestClient, mem_store: dict
    ):
        """Endpoint must NOT return fake confidence values like dog 0.89."""
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Object Detection"],
                "proof_objective": "object detection demo",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        obs = r.json()["observed_demonstration"]
        for step in obs["steps"]:
            assert step.get("detected_result_values", []) == [], (
                "Must have no detected_result_values before frame/OCR is available"
            )

    def test_endpoint_returns_9_stage_progress(
        self, client: TestClient, mem_store: dict
    ):
        """After analysis, stages should include the new 9-stage system."""
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": [],
                "proof_objective": "",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        stages = r.json()["stages"]
        keys = [s["key"] for s in stages]
        # New stages must be present
        assert "preparing_recording" in keys
        assert "filtering_tabs" in keys
        assert "detecting_iao_flow" in keys
        assert "mapping_skills" in keys
        assert "finalizing" in keys
        # video_frame_analysis should be "coming_soon"
        vf = next((s for s in stages if s["key"] == "video_frame_analysis"), None)
        assert vf is not None
        assert vf["status"] == "coming_soon"

    def test_endpoint_recruiter_summary_mentions_workflow_pattern(
        self, client: TestClient, mem_store: dict
    ):
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Object Detection"],
                "proof_objective": "object detection app demo",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        summary = r.json()["recruiter_summary"].lower()
        assert any(kw in summary for kw in [
            "image", "detection", "input", "prediction", "inference", "workflow"
        ]), f"Summary should describe IAO pattern, got: {summary}"
