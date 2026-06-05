"""Endpoint-level integration tests for the Final Evidence Score source cards.

These tests exercise the LIVE API payload path (not helper functions):

    POST /api/v1/student/extension-proof/sessions/{id}/analyze/workflow
    POST /api/v1/student/extension-proof/sessions/{id}/evaluate/final

They seed the in-memory dict store with the same shapes the individual evidence
services persist, then assert that the evidence_source_breakdown returned by the
evaluate/final endpoint matches the analyzed sections — i.e. a source that has
analyzed evidence must NOT report "not_run".

Root-cause guard: the final evaluator's data loaders must read the in-memory dict
store the same way the per-source services write it (workflow/github/PD keyed
appropriately, live-check/optional/keyframes iterated).  When that contract breaks,
every source silently reports "not_run" — exactly the product bug these tests pin.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.extension_proof_workflow_analysis_service import _SESSION_TABLE
from app.services.final_evidence_evaluator_service import (
    _WF_TABLE,
    _GH_TABLE,
    _LW_TABLE,
    _PD_TABLE,
    _VF_TABLE,
    _OPT_TABLE,
)

DEMO_USER_ID = "00000000-0000-0000-0000-000000000099"

HUGGINGCHAT_URL = "https://huggingface.co/chat/"
THREEJS_URL = "https://example-threejs-demo.vercel.app"
D3_URL = "https://example-d3-dashboard.vercel.app"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(mem_store: dict, proof_data: dict | None = None) -> str:
    session_id = str(uuid.uuid4())
    mem_store.setdefault(_SESSION_TABLE, {})[session_id] = {
        "id": session_id,
        "user_id": DEMO_USER_ID,
        "status": "uploaded_pending_analysis",
        "proof_data": proof_data or {},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    return session_id


def _seed_workflow_row(mem_store: dict, session_id: str, **overrides) -> None:
    """Seed a completed workflow_analysis_results row (mirrors analyze + enrich)."""
    row = {
        "id": str(uuid.uuid4()),
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "evidence_strength_score": 55,
        "workflow_confidence": "medium",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["Target application loaded", "User interactions: 2 click(s)"],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "unsupported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "created_at": "2024-01-01T00:00:00Z",
    }
    row.update(overrides)
    mem_store.setdefault(_WF_TABLE, {})[row["id"]] = row


def _seed_qwen_frames(mem_store: dict, session_id: str, observations: list[dict]) -> None:
    """Seed per-frame visual_reasoning_json rows (what Qwen writes after analysis)."""
    store = mem_store.setdefault(_VF_TABLE, {})
    for i, obs in enumerate(observations):
        fid = f"frame-{session_id[:6]}-{i}"
        store[fid] = {
            "id": fid,
            "user_id": DEMO_USER_ID,
            "proof_session_id": session_id,
            "frame_type": "video_keyframe",
            "timestamp_ms": 1000 * (i + 1),
            "visual_reasoning_json": {"status": "analyzed", **obs},
        }


def _evaluate(client: TestClient, session_id: str, claimed_skills: list[str], github_url=None) -> dict:
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/evaluate/final",
        json={"claimed_skills": claimed_skills, "github_url": github_url},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _src(payload: dict, key: str) -> dict:
    return next(s for s in payload["evidence_source_breakdown"] if s["key"] == key)


# ── 1. Workflow source card reflects analyzed workflow ────────────────────────

def test_workflow_section_analyzed_source_card_not_not_run(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(mem_store, session_id, evidence_strength_score=55)
    payload = _evaluate(client, session_id, ["Chatbot UI"])
    wf = _src(payload, "website_workflow")
    assert wf["status"] != "not_run", f"workflow analyzed but card says not_run: {wf}"
    assert wf["score"] > 0


# ── 2. OCR snippets exist → OCR card not not_run ──────────────────────────────

def test_ocr_snippets_exist_source_card_not_not_run(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(
        mem_store, session_id,
        visual_analysis_status="not_configured",  # no traditional OCR provider
        frame_ocr_evidence_summary={
            "has_ocr_evidence": True,
            "top_ocr_snippets": ["HuggingChat", "chat window", "hi"],
            "detected_page_context": "chatbot_ui",
            "skill_signals": [],
        },
    )
    payload = _evaluate(client, session_id, ["Natural Language Processing"])
    ocr = _src(payload, "ocr")
    assert ocr["status"] != "not_run", f"OCR snippets exist but card says not_run: {ocr}"
    assert ocr["score"] > 0
    assert "ocr" in payload["evidence_sources_used"]
    assert _src(payload, "website_workflow")["score"] > 0


# ── 3. Qwen target observations exist → Qwen card not not_run ─────────────────

def test_qwen_target_observation_source_card_not_not_run(client, mem_store):
    session_id = _make_session(mem_store)
    # Stored workflow summary is null (Qwen ran AFTER analysis) — fallback must kick in.
    _seed_workflow_row(mem_store, session_id, visual_reasoning_summary=None)
    _seed_qwen_frames(mem_store, session_id, [
        {
            "visual_summary": "The HuggingChat interface is open, showing a chat window with 'hi' typed.",
            "visible_ui_elements": ["chat window", "input field"],
            "detected_user_action": "user typed 'hi' in message input",
            "supported_skills": ["Chatbot UI"],
            "confidence_score": 0.75,
        },
    ])
    payload = _evaluate(client, session_id, ["Chatbot UI"])
    qwen = _src(payload, "qwen_visual_reasoning")
    assert qwen["status"] not in ("not_run", "not_available"), (
        f"Qwen observations exist but card says {qwen['status']}: {qwen}"
    )
    assert qwen["score"] > 0
    assert "qwen_visual_reasoning" in payload["evidence_sources_used"]
    assert _src(payload, "website_workflow")["score"] > 0


# ── 3b. DOM partial evidence → DOM card partial, not not_run ─────────────────

def test_dom_partial_evidence_source_card_is_partial_not_not_run(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(
        mem_store,
        session_id,
        evidence_strength_score=32,
        workflow_confidence="low",
        visible_evidence_status="not_captured",
        dom_evidence_status="not_captured",
        demonstrated_actions=[],
        target_website="https://leafletjs.com/examples/quick-start/",
        workflow_summary="Leaflet quick-start map page loaded.",
        observed_demonstration={
            "target_app": "leafletjs.com",
            "summary": "DOM evidence partial for a Leaflet map tutorial.",
            "visible_evidence_status": "partial",
            "dom_evidence_status": "partial",
            "top_result_snippets": ["Leaflet map marker popup OpenStreetMap tile"],
            "steps": [],
        },
    )
    payload = _evaluate(client, session_id, ["Leaflet.js", "Interactive Maps"])
    dom = _src(payload, "dom_visible_evidence")
    assert dom["status"] == "partial", f"DOM partial evidence must render as partial: {dom}"
    assert dom["score"] > 0
    assert dom["status"] != "not_run"
    assert "not detected" not in str(dom.get("notes") or "").lower()


# ── 4. Project Defense analyzed → PD card not 0/not_run ───────────────────────

def test_project_defense_analyzed_source_card_not_zero(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(mem_store, session_id)
    mem_store.setdefault(_PD_TABLE, {})[session_id] = {
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "analysis_status": "analyzed",
        "overall_score": 68,
        "transcript_text": "I built the HuggingChat chatbot UI with message input and prompt handling.",
        "consistency_with_evidence_score": 68,
        "explanation_clarity_score": 70,
        "ownership_signal_score": 65,
        "technical_depth_score": 66,
    }
    payload = _evaluate(client, session_id, ["Chatbot UI"])
    pd = _src(payload, "project_defense")
    assert pd["status"] not in ("not_run",), f"PD analyzed but card says not_run: {pd}"
    assert pd["score"] > 0


# ── 5. Live website check exists → consistent score/status ────────────────────

def test_live_website_check_source_card_consistent(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(mem_store, session_id)
    lw_id = str(uuid.uuid4())
    mem_store.setdefault(_LW_TABLE, {})[lw_id] = {
        "id": lw_id,
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "is_reachable": True,
        "confidence": "high",
    }
    payload = _evaluate(client, session_id, ["Chatbot UI"])
    lw = _src(payload, "live_website_check")
    assert lw["status"] == "pass", f"reachable live check should be pass: {lw}"
    assert lw["score"] > 0


def test_local_private_live_website_source_card_not_applicable(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(
        mem_store,
        session_id,
        target_website="http://127.0.0.1:5173",
        workflow_summary="Local Vite app workflow with visible UI interactions.",
        evidence_strength_score=58,
        supported_skills=["JavaScript"],
    )
    payload = _evaluate(client, session_id, ["JavaScript"])
    lw = _src(payload, "live_website_check")
    assert lw["status"] == "not_applicable"
    assert lw["score"] is None
    assert "public live website check is not applicable" in lw["notes"].lower()
    assert "live_website_check" not in payload["evidence_sources_used"]
    assert "live_website_check" not in payload["evidence_sources_missing"]


# ── 6. Document evidence is additive — never lowers score ─────────────────────

def test_document_evidence_additive_never_lowers_score(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(mem_store, session_id, evidence_strength_score=55)
    baseline = _evaluate(client, session_id, ["Chatbot UI"])["final_score"]

    # Add a document submission and re-evaluate.
    opt_id = str(uuid.uuid4())
    mem_store.setdefault(_OPT_TABLE, {})[opt_id] = {
        "id": opt_id,
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "source_type": "document",
        "status": "analyzed",
        "evidence_objects": [
            {"skill_name": "Chatbot UI", "confidence": "high", "snippet": "chat interface design doc"}
        ],
    }
    with_doc = _evaluate(client, session_id, ["Chatbot UI"])["final_score"]
    assert with_doc >= baseline, (
        f"document evidence must be additive: baseline={baseline} with_doc={with_doc}"
    )


# ── 7. Non-target evidence excluded from workflow scoring ─────────────────────

def test_non_target_pages_do_not_pollute_workflow(client, mem_store):
    """Full-screen recordings capture unrelated tabs; only target events score."""
    proof_data = {
        "workflow_events": [
            {"type": "page_visit", "page_url": HUGGINGCHAT_URL, "page_title": "HuggingChat"},
            {"type": "input_change", "page_url": HUGGINGCHAT_URL, "element_id": "message-input"},
            # Noise — VeriBridge dashboard + Supabase + unrelated tab
            {"type": "page_visit", "page_url": "http://localhost:3000/dashboard/profile", "page_title": "VB"},
            {"type": "page_visit", "page_url": "https://app.supabase.io/project/x/editor", "page_title": "Supabase"},
            {"type": "page_visit", "page_url": "https://news.ycombinator.com", "page_title": "HN"},
        ],
        "started_at": "2024-01-01T10:00:00+00:00",
        "stopped_at": "2024-01-01T10:02:00+00:00",
    }
    session_id = _make_session(mem_store, proof_data)
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
        json={
            "claimed_skills": ["Chatbot UI", "Natural Language Processing"],
            "proof_objective": "Demonstrate HuggingChat chatbot",
            "original_url": HUGGINGCHAT_URL,
            "url_type": "live_deployed_url",
            "github_url": None,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["noise_filtered_count"] >= 2, "non-target tabs must be filtered"
    assert data["target_site_pages_count"] >= 1
    # Recruiter summary must not mention noise hosts
    assert "supabase" not in data["recruiter_summary"].lower()
    assert "ycombinator" not in data["recruiter_summary"].lower()


# ── 8. Chatbot page loaded + input → workflow partial via live endpoint ───────

def test_chatbot_page_load_endpoint_gives_partial_workflow(client, mem_store):
    proof_data = {
        "workflow_events": [
            {"type": "page_visit", "page_url": HUGGINGCHAT_URL, "page_title": "HuggingChat"},
            {"type": "input_change", "page_url": HUGGINGCHAT_URL, "element_id": "message-input"},
            {"type": "click", "page_url": HUGGINGCHAT_URL, "element_text": "Send"},
        ],
        "started_at": "2024-01-01T10:00:00+00:00",
        "stopped_at": "2024-01-01T10:02:00+00:00",
    }
    session_id = _make_session(mem_store, proof_data)
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/analyze/workflow",
        json={
            "claimed_skills": ["Chatbot UI", "Natural Language Processing", "Large Language Models"],
            "proof_objective": "Demonstrate HuggingChat chatbot",
            "original_url": HUGGINGCHAT_URL,
            "url_type": "live_deployed_url",
            "github_url": None,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["evidence_strength_score"] >= 40

    # And the final evaluation workflow source card reflects it.
    payload = _evaluate(client, session_id, ["Chatbot UI", "Natural Language Processing"])
    wf = _src(payload, "website_workflow")
    assert wf["status"] != "not_run"
    assert wf["score"] >= 40


# ── 9. Project-type coverage: 3D/WebGL uses Qwen+GitHub, not OCR ──────────────

def test_webgl_project_scores_via_qwen_and_github_not_ocr(client, mem_store):
    session_id = _make_session(mem_store)
    # OCR not configured (canvas/WebGL is unreadable by OCR) but Qwen + GitHub carry it.
    _seed_workflow_row(
        mem_store, session_id,
        evidence_strength_score=60,
        supported_skills=["Three.js"],
        visual_analysis_status="not_configured",
        frame_ocr_evidence_summary={},
        visual_reasoning_summary={
            "status": "analyzed",
            "frames_analyzed": 2,
            "summary": "A rotating 3D WebGL mesh is rendered on a canvas.",
            "observations": [{"confidence_score": 0.8, "visual_summary": "rotating 3D mesh on canvas"}],
            "supported_signals": ["Three.js"],
        },
    )
    mem_store.setdefault(_GH_TABLE, {})[session_id] = {
        "id": str(uuid.uuid4()),
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "status": "success",
        "confidence_score": 0.6,
        "matched_claimed_skills": ["Three.js"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["Three.js", "WebGL"],
    }
    payload = _evaluate(client, session_id, ["Three.js"], github_url="https://github.com/acme/threejs")
    qwen = _src(payload, "qwen_visual_reasoning")
    gh = _src(payload, "github")
    ocr = _src(payload, "ocr")
    assert qwen["status"] == "pass" and qwen["score"] > 0
    assert gh["status"] in ("pass", "partial") and gh["score"] > 0
    # OCR is correctly not_run for a WebGL project — and is excluded from dilution.
    assert ocr["status"] in ("not_run", "not_available")
    assert payload["final_score"] > 0


# ── 10. Project-type coverage: D3 data-viz uses DOM/OCR + GitHub ──────────────

def test_d3_dataviz_project_scores_via_dom_and_github(client, mem_store):
    session_id = _make_session(mem_store)
    _seed_workflow_row(
        mem_store, session_id,
        evidence_strength_score=58,
        visible_evidence_status="available",
        demonstrated_actions=["open chart", "hover tooltip", "change filter", "review"],
        supported_skills=["Data Visualization"],
        visual_analysis_status="analyzed",
        frame_ocr_evidence_summary={
            "has_ocr_evidence": True,
            "top_ocr_snippets": ["GDP per capita", "axis", "legend"],
            "skill_signals": [],
        },
    )
    mem_store.setdefault(_GH_TABLE, {})[session_id] = {
        "id": str(uuid.uuid4()),
        "user_id": DEMO_USER_ID,
        "proof_session_id": session_id,
        "status": "success",
        "confidence_score": 0.55,
        "matched_claimed_skills": ["Data Visualization"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["D3", "JavaScript"],
    }
    payload = _evaluate(client, session_id, ["Data Visualization", "D3"], github_url="https://github.com/acme/d3")
    dom = _src(payload, "dom_visible_evidence")
    ocr = _src(payload, "ocr")
    gh = _src(payload, "github")
    assert dom["status"] in ("pass", "partial") and dom["score"] > 0
    assert ocr["status"] == "pass" and ocr["score"] > 0
    assert gh["status"] in ("pass", "partial") and gh["score"] > 0
    assert payload["final_score"] > 0
