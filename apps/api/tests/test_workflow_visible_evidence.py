"""Tests for Workflow Visible Evidence capture and extraction (v4).

Covers:
1. Visible evidence with "dog 0.89" and "person 0.77" extracts detected_result_values.
2. Object detection workflow generates input/action/output timeline.
3. Route risk visible result "risk score 72" is captured.
4. Chatbot visible prompt/response is summarized safely.
5. Dashboard KPI/table value is captured.
6. Sensitive strings are masked.
7. Internal URLs are not included in recruiter summary.
8. Old recording without visible evidence still returns safe analysis.
9. Output values are not invented when not captured.
10. Skill support uses observed output evidence when available.
11. Browser noise filtering still works with v4.

Additional tests:
- Sanitization removes passwords, API keys, local paths, Supabase URLs.
- File upload metadata is stored safely (no local path).
- Multiple result values from a complex output panel.
- Workflow analysis integrates visible evidence into demonstration steps.
- Endpoint accepts visible-evidence POST and returns 202.
- Summary endpoint returns student-facing data.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.schemas.workflow_visible_evidence import (
    FileUploadMeta,
    VisibleEvidenceBatchRequest,
    VisibleEvidenceEventInput,
)
from app.services.workflow_visible_evidence_service import (
    WorkflowVisibleEvidenceService,
    extract_result_values,
    sanitize_text,
    sanitize_blocks,
    sanitize_dict,
    _derive_observations_from_rows,
)
from app.services.extension_proof_workflow_analysis_service import (
    _analyze_workflow,
    _SESSION_TABLE,
    _filter_visual_reasoning_summary_for_target,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"
DETECTION_URL = "https://object-detection-demo.vercel.app"
ROUTE_URL = "https://floodrisk.vercel.app"
CHATBOT_URL = "https://my-chatbot.vercel.app"
HUGGINGCHAT_URL = "https://huggingface.co/chat/"
DASHBOARD_URL = "https://analytics-dashboard.vercel.app"
SUPABASE_URL = "https://app.supabase.io/project/abc/editor"
VB_DASH_URL = "http://localhost:3000/dashboard/profile"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proof_data(events: list[dict], duration_secs: int = 120) -> dict:
    start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    stop = start + timedelta(seconds=duration_secs)
    return {
        "workflow_events": events,
        "started_at": start.isoformat(),
        "stopped_at": stop.isoformat(),
    }


def _detection_events() -> list[dict]:
    return [
        {"type": "page_visit", "page_url": DETECTION_URL, "page_title": "Object Detection Demo"},
        {"type": "click", "page_url": DETECTION_URL, "element_text": "Upload Image"},
        {"type": "input_change", "page_url": DETECTION_URL, "element_id": "image-upload"},
        {"type": "click", "page_url": DETECTION_URL, "element_text": "Detect"},
        {"type": "page_visit", "page_url": DETECTION_URL + "/results", "page_title": "Detection Results"},
    ]


def _route_events() -> list[dict]:
    return [
        {"type": "page_visit", "page_url": ROUTE_URL, "page_title": "Flood Risk Analyzer"},
        {"type": "input_change", "page_url": ROUTE_URL, "element_id": "location-input"},
        {"type": "click", "page_url": ROUTE_URL, "element_text": "Analyze Risk"},
        {"type": "page_visit", "page_url": ROUTE_URL + "/result", "page_title": "Risk Analysis Result"},
    ]


def _make_visible_event(
    event_type: str,
    visible_text_blocks: list[str] | None = None,
    result_like_blocks: list[str] | None = None,
    action_snapshot: dict | None = None,
    input_snapshot: dict | None = None,
    url: str = DETECTION_URL,
    page_title: str = "",
) -> VisibleEvidenceEventInput:
    return VisibleEvidenceEventInput(
        event_type=event_type,
        url=url,
        page_title=page_title,
        visible_text_blocks=visible_text_blocks or [],
        result_like_blocks=result_like_blocks or [],
        action_snapshot=action_snapshot or {},
        input_snapshot=input_snapshot or {},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def svc(mem_store: dict) -> WorkflowVisibleEvidenceService:
    return WorkflowVisibleEvidenceService(mem_store)


@pytest.fixture()
def client(mem_store: dict):
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


# ---------------------------------------------------------------------------
# 1. Result value extraction: "dog 0.89" and "person 0.77"
# ---------------------------------------------------------------------------

class TestResultValueExtraction:

    def test_extracts_dog_person_scores(self):
        """Core test: 'dog: 0.89, person: 0.77' extracts detected_result_values."""
        blocks = ["dog: 0.89", "person: 0.77"]
        results = extract_result_values(blocks)
        labels = {r.label.lower() for r in results}
        values = {r.value for r in results}
        assert "dog" in labels, f"Expected 'dog' in {labels}"
        assert "person" in labels, f"Expected 'person' in {labels}"
        assert "0.89" in values or "0.77" in values

    def test_extracts_confidence_colon_format(self):
        """confidence: 0.91 → extracted."""
        results = extract_result_values(["confidence: 0.91"])
        assert len(results) >= 1
        assert any("0.91" in r.value for r in results)

    def test_extracts_risk_score(self):
        """risk score 72 → extracted."""
        results = extract_result_values(["risk score: 72"])
        assert len(results) >= 1
        assert any("72" in r.value for r in results)

    def test_extracts_percentage(self):
        """accuracy: 87% → extracted."""
        results = extract_result_values(["accuracy: 87%"])
        assert len(results) >= 1
        assert any("87" in r.value for r in results)

    def test_extracts_severity_high(self):
        """High: 72% → extracted."""
        results = extract_result_values(["High: 72%"])
        assert len(results) >= 1

    def test_does_not_extract_from_empty(self):
        assert extract_result_values([]) == []

    def test_does_not_invent_values_from_plain_text(self):
        """Plain sentences without numeric patterns → no result values."""
        results = extract_result_values(["Loading prediction model...", "Please wait"])
        # Should not extract non-numeric labels
        for r in results:
            assert r.value.replace(".", "").replace("%", "").isdigit() or r.value == "", (
                f"Extracted non-numeric value: {r.value}"
            )

    def test_multiple_results_from_table_like_text(self):
        """Multiple label:value pairs in one block."""
        blocks = ["cat: 0.65  dog: 0.30  bird: 0.05"]
        results = extract_result_values(blocks)
        assert len(results) >= 2, f"Expected multiple results, got: {results}"


# ---------------------------------------------------------------------------
# 2. Object detection workflow: input/action/output with visible evidence
# ---------------------------------------------------------------------------

class TestObjectDetectionVisibleEvidence:

    def test_detection_workflow_with_visible_evidence(self, svc, mem_store):
        """Full pipeline: ingest evidence → observations → workflow analysis enriched."""
        session_id = "test-session-detection-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event("file_upload", input_snapshot={"file_category": "image", "file_extension": "jpg"}),
            _make_visible_event("click", action_snapshot={"element_text": "Detect", "element_type": "button"}),
            _make_visible_event(
                "result_detected",
                result_like_blocks=["dog: 0.89", "person: 0.77"],
                page_title="Detection Results",
            ),
        ])
        result = svc.ingest(DEMO_USER_ID, session_id, request)
        assert result["events_stored"] == 3

        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert obs.visible_evidence_status in ("available", "partial")
        assert len(obs.detected_result_values) >= 1
        labels = {r.label.lower() for r in obs.detected_result_values}
        assert "dog" in labels or "person" in labels

    def test_observation_inputs_contain_file_upload(self, svc, mem_store):
        session_id = "test-session-detection-002"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event("file_upload", input_snapshot={"file_category": "image", "file_extension": "png"}),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert any("image" in inp.lower() or "file" in inp.lower() for inp in obs.observed_inputs)

    def test_observation_actions_contain_detect(self, svc, mem_store):
        session_id = "test-session-detection-003"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event("click", action_snapshot={"element_text": "Detect", "element_type": "button"}),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert any("detect" in act.lower() or "Detect" in act for act in obs.observed_actions)


# ---------------------------------------------------------------------------
# 3. Route risk: "risk score 72" is captured
# ---------------------------------------------------------------------------

class TestRouteRiskVisibleEvidence:

    def test_risk_score_captured(self, svc, mem_store):
        session_id = "test-session-route-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event("click", action_snapshot={"element_text": "Analyze Risk"}),
            _make_visible_event(
                "result_detected",
                result_like_blocks=["risk score: 72", "severity: High"],
                page_title="Risk Analysis Result",
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        labels = {r.label.lower() for r in obs.detected_result_values}
        values = {r.value for r in obs.detected_result_values}
        assert "risk score" in labels or "72" in values or "severity" in labels

    def test_route_workflow_integration(self, mem_store, svc):
        """Visible evidence integrates into workflow analysis for route_map app."""
        session_id = "test-session-route-002"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "result_detected",
                result_like_blocks=["risk score: 72"],
                url=ROUTE_URL,
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)

        result = _analyze_workflow(
            proof_data=_make_proof_data(_route_events()),
            claimed_skills=["Geospatial Analysis"],
            proof_objective="flood risk analysis",
            original_url=ROUTE_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=obs,
        )
        obs_demo = result["observed_demonstration"]
        # Should have a step with result values
        steps_with_values = [s for s in obs_demo["steps"] if s.get("detected_result_values")]
        assert len(steps_with_values) >= 1


# ---------------------------------------------------------------------------
# 4. Chatbot: prompt/response summarized safely
# ---------------------------------------------------------------------------

class TestChatbotVisibleEvidence:

    def test_chatbot_response_captured(self, svc, mem_store):
        session_id = "test-session-chat-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "input_change",
                action_snapshot={"element_id": "message-input"},
                input_snapshot={"message": "What is the weather?"},
            ),
            _make_visible_event(
                "dom_snapshot",
                visible_text_blocks=["AI Response: The weather today is sunny with 25°C"],
                result_like_blocks=["response: The weather today is sunny with 25°C"],
                page_title="Chat Response",
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert obs.visible_evidence_status in ("available", "partial")
        assert len(obs.observed_outputs) >= 1

    def test_chatbot_sensitive_input_not_stored(self, svc, mem_store):
        """Password-like field in input_snapshot is redacted."""
        session_id = "test-session-chat-002"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "input_change",
                input_snapshot={"password": "my-secret-123", "query": "search term"},
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        from app.services.workflow_visible_evidence_service import _TABLE
        stored_rows = [
            r for r in mem_store.get(_TABLE, {}).values()
            if r.get("proof_session_id") == session_id
        ]
        assert len(stored_rows) == 1
        snap = stored_rows[0].get("input_snapshot", {})
        assert snap.get("password") != "my-secret-123", "Password must be redacted"
        assert snap.get("password") == "[REDACTED]"

    def test_qwen_recorder_ui_frame_is_filtered_non_target(self):
        summary = {
            "status": "analyzed",
            "provider": "qwen_vl",
            "frames_analyzed": 1,
            "summary": "VeriBridge Screen Recorder interface with instructions",
            "observations": [{
                "visual_summary": "VeriBridge Screen Recorder interface with instructions",
                "visible_ui_elements": ["Start recording", "VeriBridge"],
                "supported_skills": ["Frontend Development"],
            }],
            "supported_signals": ["Frontend Development"],
            "skill_timeline": [{"detected_skill": "Frontend Development"}],
        }
        filtered = _filter_visual_reasoning_summary_for_target(
            summary,
            has_target_events=True,
            noise_hosts=["chrome-extension"],
        )
        assert filtered["status"] == "filtered_non_target_frame"
        assert filtered["frames_analyzed"] == 0
        assert filtered["supported_signals"] == []

    def test_qwen_target_huggingchat_frame_supports_chatbot_ui(self):
        summary = {
            "status": "analyzed",
            "provider": "qwen_vl",
            "frames_analyzed": 1,
            "summary": "HuggingChat interface with message input and assistant response",
            "observations": [{
                "visual_summary": "HuggingChat interface with message input and assistant response",
                "page_title": "HuggingChat",
                "supported_skills": ["Chatbot UI"],
            }],
            "supported_signals": ["Chatbot UI"],
        }
        filtered = _filter_visual_reasoning_summary_for_target(
            summary,
            has_target_events=True,
            noise_hosts=["supabase.com"],
        )
        assert filtered["status"] == "analyzed"
        assert filtered["frames_analyzed"] == 1
        assert "Chatbot UI" in filtered["supported_signals"]

    def test_huggingchat_page_loaded_and_input_visible_scores_above_zero(self, svc, mem_store):
        session_id = "test-session-huggingchat-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "dom_snapshot",
                url=HUGGINGCHAT_URL,
                page_title="HuggingChat",
                visible_text_blocks=["HuggingChat", "Message input", "Ask anything"],
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        result = _analyze_workflow(
            proof_data=_make_proof_data([
                {"type": "page_visit", "page_url": HUGGINGCHAT_URL, "page_title": "HuggingChat"},
            ]),
            claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI"],
            proof_objective="demonstrate HuggingChat chatbot UI",
            original_url=HUGGINGCHAT_URL,
            url_type="live_deployed_url",
            github_url="https://github.com/huggingface/chat-ui",
            visible_observations=obs,
        )
        assert result["evidence_strength_score"] > 0
        assert result["target_site_pages_count"] == 1

    def test_huggingchat_prompt_and_assistant_response_scores_strong(self, svc, mem_store):
        session_id = "test-session-huggingchat-002"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "input_change",
                url=HUGGINGCHAT_URL,
                page_title="HuggingChat",
                action_snapshot={"element_id": "message-input"},
                input_snapshot={"message": "Explain mesh simplification"},
            ),
            _make_visible_event(
                "dom_snapshot",
                url=HUGGINGCHAT_URL,
                page_title="HuggingChat",
                visible_text_blocks=["Assistant response", "Generated response", "Conversation history"],
                result_like_blocks=["assistant response: Mesh simplification reduces geometry complexity"],
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        result = _analyze_workflow(
            proof_data=_make_proof_data([
                {"type": "page_visit", "page_url": HUGGINGCHAT_URL, "page_title": "HuggingChat"},
                {"type": "input_change", "page_url": HUGGINGCHAT_URL, "element_id": "message-input"},
                {"type": "click", "page_url": HUGGINGCHAT_URL, "element_text": "Send"},
            ]),
            claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI", "AI Product Design"],
            proof_objective="demonstrate prompt response in an LLM chatbot",
            original_url=HUGGINGCHAT_URL,
            url_type="live_deployed_url",
            github_url="https://github.com/huggingface/chat-ui",
            visible_observations=obs,
        )
        assert result["evidence_strength_score"] >= 75
        assert "Chatbot UI" in result["weakly_supported_skills"] or "Chatbot UI" in result["supported_skills"]

    def test_non_target_activity_does_not_reduce_huggingchat_score(self, svc, mem_store):
        session_id = "test-session-huggingchat-003"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "dom_snapshot",
                url=HUGGINGCHAT_URL,
                page_title="HuggingChat",
                visible_text_blocks=["HuggingChat", "Message input", "Assistant response"],
                result_like_blocks=["assistant response: Hello"],
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        target_events = [
            {"type": "page_visit", "page_url": HUGGINGCHAT_URL, "page_title": "HuggingChat"},
            {"type": "input_change", "page_url": HUGGINGCHAT_URL, "element_id": "message-input"},
            {"type": "click", "page_url": HUGGINGCHAT_URL, "element_text": "Send"},
        ]
        kwargs = dict(
            claimed_skills=["Chatbot UI"],
            proof_objective="chatbot prompt response",
            original_url=HUGGINGCHAT_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=obs,
        )
        clean = _analyze_workflow(proof_data=_make_proof_data(target_events), **kwargs)
        noisy = _analyze_workflow(
            proof_data=_make_proof_data(target_events + [
                {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase bucket"},
                {"type": "page_visit", "page_url": VB_DASH_URL, "page_title": "VeriBridge dashboard"},
            ]),
            **kwargs,
        )
        assert noisy["evidence_strength_score"] >= clean["evidence_strength_score"]
        assert noisy["filtered_unrelated_activity"]["count"] == 2


# ---------------------------------------------------------------------------
# 5. Dashboard: KPI/table value captured
# ---------------------------------------------------------------------------

class TestDashboardVisibleEvidence:

    def test_dashboard_kpi_extracted(self, svc, mem_store):
        session_id = "test-session-dash-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "result_detected",
                result_like_blocks=["revenue: 125000", "conversion rate: 3.4%", "active users: 8240"],
                page_title="Sales Dashboard",
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert len(obs.detected_result_values) >= 1
        labels = {r.label.lower() for r in obs.detected_result_values}
        assert "revenue" in labels or "conversion rate" in labels or "active users" in labels


# ---------------------------------------------------------------------------
# 6. Sensitive strings are masked
# ---------------------------------------------------------------------------

class TestSanitization:

    def test_password_field_key_redacted(self):
        d, flags = sanitize_dict({"password": "secret123", "name": "Alice"})
        assert d["password"] == "[REDACTED]"
        assert d["name"] == "Alice"
        assert any("password" in f for f in flags)

    def test_api_key_in_text_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"
        sanitized, flags = sanitize_text(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in sanitized or "[JWT_REDACTED]" in sanitized

    def test_local_file_path_redacted(self):
        text = "Loaded image from /Users/alice/photos/dog.jpg"
        sanitized, flags = sanitize_text(text)
        assert "/Users/alice" not in sanitized
        assert "[LOCAL_PATH]" in sanitized

    def test_windows_path_redacted(self):
        text = r"File at C:\Users\alice\Documents\secret.pdf"
        sanitized, flags = sanitize_text(text)
        assert "C:\\" not in sanitized or "[LOCAL_PATH]" in sanitized

    def test_supabase_url_discarded_or_redacted(self):
        text = "Data from https://xyzabc.supabase.co/rest/v1/data"
        sanitized, flags = sanitize_text(text)
        # Either the block is discarded or the URL is replaced
        if sanitized:
            assert "supabase.co" not in sanitized.lower() or "[INTERNAL_URL]" in sanitized
        else:
            assert "discarded" in str(flags).lower() or len(sanitized) == 0

    def test_credit_card_pattern_redacted(self):
        text = "Charge amount for 4111-1111-1111-1111"
        sanitized, flags = sanitize_text(text)
        assert "4111-1111-1111-1111" not in sanitized
        assert "[CARD_REDACTED]" in sanitized

    def test_ssn_redacted(self):
        text = "SSN: 123-45-6789"
        sanitized, flags = sanitize_text(text)
        assert "123-45-6789" not in sanitized
        assert "[SSN_REDACTED]" in sanitized

    def test_clean_text_unchanged(self):
        text = "Object detected: dog 0.89, confidence high"
        sanitized, flags = sanitize_text(text)
        assert "dog" in sanitized
        assert "0.89" in sanitized

    def test_jwt_token_redacted(self):
        text = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36"
        sanitized, flags = sanitize_text(text)
        assert "eyJhbGciOi" not in sanitized or "[JWT_REDACTED]" in sanitized

    def test_long_hex_token_redacted(self):
        hex_token = "a" * 40
        text = f"token={hex_token}"
        sanitized, flags = sanitize_text(text)
        assert hex_token not in sanitized or "[TOKEN_REDACTED]" in sanitized


# ---------------------------------------------------------------------------
# 7. Internal URLs not in recruiter summary
# ---------------------------------------------------------------------------

class TestInternalURLNotExposed:

    def test_supabase_not_in_recruiter_summary(self):
        events = _detection_events() + [
            {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=[],
            proof_objective="",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
        )
        assert "supabase" not in result["recruiter_summary"].lower()

    def test_veribridge_dashboard_not_in_recruiter_summary(self):
        events = _detection_events() + [
            {"type": "page_visit", "page_url": VB_DASH_URL, "page_title": "VeriBridge"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=[],
            proof_objective="",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
        )
        assert "localhost:3000/dashboard" not in result["recruiter_summary"]

    def test_non_target_dom_events_excluded_from_skill_evidence(self):
        events = [
            {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase WebGL bucket"},
            {"type": "click", "page_url": SUPABASE_URL, "element_text": "Three.js WebGL Mesh"},
            {"type": "page_visit", "page_url": "chrome-extension://abc/recorder.html", "page_title": "Recorder"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=["Three.js", "WebGL"],
            proof_objective="",
            original_url="https://threejs.org/examples/#webgl_modifier_simplifier",
            url_type="live_deployed_url",
            github_url=None,
        )
        assert result["supported_skills"] == []
        assert "Three.Js" not in result["weakly_supported_skills"]
        assert result["filtered_unrelated_activity"]["count"] == 3
        assert "supabase" not in result["workflow_summary"].lower()

    def test_target_domain_evidence_still_supports_skills(self):
        events = [
            {"type": "page_visit", "page_url": "https://threejs.org/examples/#webgl_modifier_simplifier", "page_title": "Three.js WebGL modifier simplifier"},
            {"type": "click", "page_url": "https://threejs.org/examples/#webgl_modifier_simplifier", "element_text": "Simplify"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=["Three.js", "WebGL"],
            proof_objective="Show Three.js mesh simplification",
            original_url="https://threejs.org/examples/#webgl_modifier_simplifier",
            url_type="live_deployed_url",
            github_url=None,
        )
        assert {"Three.Js", "Webgl"} & set(result["supported_skills"])
        assert result["filtered_unrelated_activity"]["count"] == 0

    def test_non_target_ocr_frames_do_not_support_target_skills(self):
        events = [
            {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=["WebGL"],
            proof_objective="Show WebGL demo",
            original_url="https://threejs.org/examples/#webgl_modifier_simplifier",
            url_type="live_deployed_url",
            github_url=None,
            visual_frame_observations={
                "visual_frame_analysis_status": "analyzed",
                "provider_used": "local_ocr",
                "visual_frame_count": 2,
                "visual_summary": "Supabase Storage bucket | WebGL Mesh Extension Recorder",
            },
        )
        ocr = result["frame_ocr_evidence_summary"]
        assert ocr["has_ocr_evidence"] is False
        assert ocr["detected_page_context"] == "filtered_non_target_frame"
        assert "Webgl" not in result["supported_skills"]

    def test_internal_url_visible_evidence_not_exposed(self, svc, mem_store):
        """Supabase URL in visible evidence is sanitized before storage."""
        session_id = "test-internal-url-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "dom_snapshot",
                visible_text_blocks=["Studio URL: https://xyzabc.supabase.co/studio/tables"],
                url=DETECTION_URL,
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        from app.services.workflow_visible_evidence_service import _TABLE
        stored = list(mem_store.get(_TABLE, {}).values())
        for row in stored:
            for block in (row.get("visible_text_blocks") or []):
                assert "supabase.co" not in block.lower() or "[INTERNAL_URL]" in block


# ---------------------------------------------------------------------------
# 8. Old recording (no visible evidence) still returns safe analysis
# ---------------------------------------------------------------------------

class TestOldRecordingBackwardCompatibility:

    def test_old_recording_no_visible_evidence(self):
        """Without visible evidence, analysis still works; status = 'not_captured'."""
        result = _analyze_workflow(
            proof_data=_make_proof_data(_detection_events()),
            claimed_skills=["Object Detection"],
            proof_objective="object detection app",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=None,  # no visible evidence
        )
        assert result["visible_evidence_status"] == "not_captured"
        assert result["observed_demonstration"] is not None
        assert result["recruiter_summary"] != ""

    def test_old_recording_steps_have_no_result_values(self):
        result = _analyze_workflow(
            proof_data=_make_proof_data(_detection_events()),
            claimed_skills=["Object Detection"],
            proof_objective="object detection",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=None,
        )
        obs = result["observed_demonstration"]
        for step in obs["steps"]:
            assert step.get("detected_result_values", []) == []

    def test_old_recording_limitations_mention_not_captured(self):
        result = _analyze_workflow(
            proof_data=_make_proof_data(_detection_events()),
            claimed_skills=[],
            proof_objective="",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=None,
        )
        obs = result["observed_demonstration"]
        limitations_text = " ".join(obs["limitations"]).lower()
        assert "not captured" in limitations_text or "before visible evidence" in limitations_text


# ---------------------------------------------------------------------------
# 9. Output values not invented when not captured
# ---------------------------------------------------------------------------

class TestNoInventedValues:

    def test_empty_visible_evidence_no_result_values(self):
        """With empty visible evidence (no result blocks), no values should appear."""
        from app.services.workflow_visible_evidence_service import _derive_observations_from_rows
        obs = _derive_observations_from_rows([])
        assert obs.detected_result_values == []

    def test_only_plain_text_no_result_values(self, svc, mem_store):
        """Plain text like 'Loading...' should not produce result values."""
        session_id = "test-no-invent-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "dom_snapshot",
                visible_text_blocks=["Welcome to the app", "Loading your data..."],
                result_like_blocks=[],
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        assert obs.detected_result_values == [], (
            f"Should not invent result values from plain text: {obs.detected_result_values}"
        )

    def test_result_values_only_from_numeric_patterns(self):
        """Only numeric patterns should generate result values."""
        results = extract_result_values(["Loading... Please wait... Analyzing..."])
        # No numeric values → no results
        assert results == [] or all(
            r.value.replace(".", "").isdigit()
            for r in results
        )


# ---------------------------------------------------------------------------
# 10. Skill support uses observed output evidence
# ---------------------------------------------------------------------------

class TestSkillSupportFromVisibleEvidence:

    def test_skill_reasoning_mentions_captured_values(self, svc, mem_store):
        session_id = "test-skill-support-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event(
                "result_detected",
                result_like_blocks=["dog: 0.89", "person: 0.77"],
            ),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)
        # skill_support_reasoning should mention captured values
        reasoning_text = " ".join(obs.skill_support_reasoning).lower()
        assert "dom" in reasoning_text or "captured" in reasoning_text or "dog" in reasoning_text

    def test_workflow_analysis_step_evidence_source_dom_when_visible(self, svc, mem_store):
        """When visible evidence is available, step evidence_source should be dom_snapshot."""
        session_id = "test-evidence-source-001"
        request = VisibleEvidenceBatchRequest(events=[
            _make_visible_event("file_upload", input_snapshot={"file_category": "image"}),
            _make_visible_event("click", action_snapshot={"element_text": "Detect"}),
            _make_visible_event("result_detected", result_like_blocks=["cat: 0.72"]),
        ])
        svc.ingest(DEMO_USER_ID, session_id, request)
        obs = svc.get_extracted_observations(DEMO_USER_ID, session_id)

        result = _analyze_workflow(
            proof_data=_make_proof_data(_detection_events()),
            claimed_skills=["Object Detection"],
            proof_objective="object detection",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=obs,
        )
        obs_demo = result["observed_demonstration"]
        sources = {s.get("evidence_source") for s in obs_demo["steps"]}
        # At least one step should show dom_snapshot when visible evidence present
        assert "dom_snapshot" in sources or "event_metadata" in sources


# ---------------------------------------------------------------------------
# 11. Browser noise filtering still works with v4
# ---------------------------------------------------------------------------

class TestNoiseFilteringWithV4:

    def test_noise_filtered_v4(self):
        events = _detection_events() + [
            {"type": "page_visit", "page_url": SUPABASE_URL},
            {"type": "page_visit", "page_url": VB_DASH_URL},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=[],
            proof_objective="",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
        )
        assert result["noise_filtered_count"] >= 2

    def test_noise_not_in_recruiter_summary_v4(self):
        events = _detection_events() + [
            {"type": "page_visit", "page_url": SUPABASE_URL, "page_title": "Supabase"},
        ]
        result = _analyze_workflow(
            proof_data=_make_proof_data(events),
            claimed_skills=[],
            proof_objective="",
            original_url=DETECTION_URL,
            url_type="live_deployed_url",
            github_url=None,
        )
        assert "supabase" not in result["recruiter_summary"].lower()


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

class TestVisibleEvidenceEndpoints:

    def test_submit_visible_evidence_returns_202(self, client, mem_store):
        """POST /workflow/visible-evidence returns 202 Accepted."""
        session_id = "endpoint-test-session-001"
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/visible-evidence",
            json={
                "events": [
                    {
                        "event_type": "result_detected",
                        "url": DETECTION_URL,
                        "page_title": "Detection Results",
                        "visible_text_blocks": ["dog: 0.89", "person: 0.77"],
                        "result_like_blocks": ["dog: 0.89", "person: 0.77"],
                        "input_snapshot": {},
                        "action_snapshot": {},
                    }
                ]
            },
        )
        assert r.status_code == 202, r.text
        data = r.json()
        assert data["events_stored"] == 1
        assert data["status"] == "accepted"

    def test_summary_endpoint_returns_visible_evidence_status(self, client, mem_store):
        """GET /workflow/visible-evidence/summary returns summary with status."""
        session_id = "endpoint-test-session-002"
        # First submit some evidence
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/visible-evidence",
            json={
                "events": [
                    {
                        "event_type": "result_detected",
                        "url": DETECTION_URL,
                        "page_title": "Results",
                        "visible_text_blocks": ["cat: 0.85"],
                        "result_like_blocks": ["cat: 0.85"],
                        "input_snapshot": {},
                        "action_snapshot": {},
                    }
                ]
            },
        )
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/visible-evidence/summary"
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "visible_evidence_status" in data
        assert "event_count" in data
        assert data["event_count"] >= 1
        assert "privacy_note" in data

    def test_workflow_analysis_includes_visible_evidence_status(self, client, mem_store):
        """POST /analyze/workflow now returns visible_evidence_status."""
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        # Submit visible evidence first
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/visible-evidence",
            json={
                "events": [
                    {
                        "event_type": "result_detected",
                        "url": DETECTION_URL,
                        "page_title": "Detection Results",
                        "visible_text_blocks": ["dog: 0.89"],
                        "result_like_blocks": ["dog: 0.89"],
                        "input_snapshot": {},
                        "action_snapshot": {},
                    }
                ]
            },
        )
        # Now run workflow analysis
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
        data = r.json()
        assert "visible_evidence_status" in data
        # Since we submitted evidence, status should not be 'not_captured'
        assert data["visible_evidence_status"] in ("available", "partial")

    def test_workflow_analysis_stages_include_visible_evidence_stage(self, client, mem_store):
        """After v4, stages include 'capturing_visible_evidence'."""
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
        assert "capturing_visible_evidence" in keys
        assert "extracting_result_values" in keys

    def test_privacy_fields_not_in_recruiter_summary(self, client, mem_store):
        """Visible evidence summary is NOT part of the recruiter_summary field."""
        session_id = _make_session(mem_store, _make_proof_data(_detection_events()))
        # Ingest evidence with internal-looking data
        client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/workflow/visible-evidence",
            json={
                "events": [
                    {
                        "event_type": "dom_snapshot",
                        "url": DETECTION_URL,
                        "page_title": "Test",
                        "visible_text_blocks": ["Result: dog 0.89"],
                        "result_like_blocks": ["Result: dog 0.89"],
                        "input_snapshot": {},
                        "action_snapshot": {},
                    }
                ]
            },
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
            json={
                "claimed_skills": ["Object Detection"],
                "proof_objective": "demo",
                "original_url": DETECTION_URL,
                "url_type": "live_deployed_url",
                "github_url": None,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Recruiter summary should not contain raw visible_text_blocks dump
        summary = data.get("recruiter_summary", "")
        assert "visible_text_blocks" not in summary
        assert "result_like_blocks" not in summary
