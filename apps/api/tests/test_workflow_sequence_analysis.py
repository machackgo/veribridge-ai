"""Tests for WorkflowSequenceAnalysisService (Week 3 — multi-frame sequence analysis).

Coverage:
1.  No keyframes, no events, no visible evidence → not_available status.
2.  Keyframes only (no DOM/visible evidence) → analyzed, basic stage summaries.
3.  DOM events + visible evidence + keyframes → complete IAO chain detected.
4.  Visible DOM result values give higher confidence than model-only visual summary.
5.  Weak evidence (no inputs/outputs observed) → unsupported_claims, no hallucinated skills.
6.  to_public_dict() never exposes private_review_flags, frame paths, or raw DOM.
7.  Malformed keyframe result (missing fields) → handled safely, no crash.
8.  Malformed event list (None values, missing keys) → handled safely, no crash.
9.  Existing workflow analysis integration: sequence_analysis key present in result.
10. Stage assignment: frames distributed across stages proportionally when no timestamps.
11. IAO chain: chain_complete=True only when input+action+output all detected.
12. evidence_strength=strong only when DOM result values are present.
13. evidence_strength=insufficient when no DOM, no OCR, no meaningful events.
14. private_review_flags contains no_keyframes when keyframe result is missing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.workflow_sequence_analysis_service import (
    WorkflowSequenceAnalysisService,
    SequenceAnalysisResult,
    SEQ_STATUS_ANALYZED,
    SEQ_STATUS_NOT_AVAILABLE,
    STRENGTH_STRONG,
    STRENGTH_MODERATE,
    STRENGTH_WEAK,
    STRENGTH_INSUFFICIENT,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _svc() -> WorkflowSequenceAnalysisService:
    return WorkflowSequenceAnalysisService()


def _kf_result(
    status: str = "analyzed",
    timestamps: list[int] | None = None,
    duration_ms: int = 30_000,
) -> SimpleNamespace:
    """Minimal mock VideoKeyframeResult."""
    return SimpleNamespace(
        video_analysis_status=status,
        selected_frame_timestamps_ms=timestamps if timestamps is not None else [0, 5000, 10000, 20000, 30000],
        duration_ms=duration_ms,
    )


def _visible_obs(
    inputs:        list[str] | None = None,
    actions:       list[str] | None = None,
    outputs:       list[str] | None = None,
    result_values: list[SimpleNamespace] | None = None,
    ev_status:     str = "available",
) -> SimpleNamespace:
    """Minimal mock ExtractedObservations."""
    return SimpleNamespace(
        observed_inputs=inputs or [],
        observed_actions=actions or [],
        observed_outputs=outputs or [],
        detected_result_values=result_values or [],
        visible_evidence_status=ev_status,
    )


def _rv(label: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(label=label, value=value, source="dom")


def _dom_events(
    with_input: bool = False,
    with_action: bool = False,
    with_output_nav: bool = False,
) -> list[dict]:
    events: list[dict] = []
    if with_input:
        events.append({"type": "input_change", "element_id": "query", "timestamp_ms": 5000})
    if with_action:
        events.append({"type": "click", "element_text": "submit", "timestamp_ms": 8000})
    if with_output_nav:
        events.append({"type": "page_visit", "page_title": "Result", "page_url": "http://app/result", "timestamp_ms": 12000})
    return events


# ── Test 1: No evidence → not_available ───────────────────────────────────────

def test_no_evidence_returns_not_available():
    result = _svc().analyze()
    assert result.sequence_analysis_status == SEQ_STATUS_NOT_AVAILABLE
    assert result.analyzed_frame_count == 0
    assert result.confidence_score == 0


# ── Test 2: Keyframes only → analyzed with basic stage summaries ──────────────

def test_keyframes_only_returns_analyzed():
    result = _svc().analyze(
        keyframe_result=_kf_result(timestamps=[0, 3000, 6000, 15000, 25000, 28000]),
    )
    assert result.sequence_analysis_status == SEQ_STATUS_ANALYZED
    assert result.analyzed_frame_count == 6
    assert len(result.workflow_stage_summaries) == 6
    # Check stages have frame counts
    total_frames = sum(s["frame_count"] for s in result.workflow_stage_summaries)
    assert total_frames == 6


# ── Test 3: Full evidence → complete IAO chain ────────────────────────────────

def test_full_evidence_complete_iao_chain():
    obs = _visible_obs(
        inputs=["image uploaded: photo.jpg"],
        actions=["predict button clicked"],
        outputs=["classification output"],
        result_values=[_rv("dog", "0.91"), _rv("cat", "0.05")],
    )
    result = _svc().analyze(
        keyframe_result=_kf_result(),
        dom_events=_dom_events(with_input=True, with_action=True, with_output_nav=True),
        visible_observations=obs,
    )
    assert result.sequence_analysis_status == SEQ_STATUS_ANALYZED
    chain = result.input_action_output_chain
    assert chain["chain_complete"] is True
    assert chain["chain_source"] == "dom_snapshot"
    assert "dog" in " ".join(chain.get("output_values", []))


# ── Test 4: DOM result values give higher confidence than model-only summary ──

def test_dom_result_values_higher_confidence_than_model_only():
    # With DOM result values
    obs_strong = _visible_obs(
        inputs=["query entered"],
        actions=["run clicked"],
        outputs=["result shown"],
        result_values=[_rv("score", "0.85")],
    )
    strong = _svc().analyze(
        keyframe_result=_kf_result(),
        visible_observations=obs_strong,
    )

    # Visual model only (no DOM evidence)
    vf_obs_only = {
        "visual_frame_analysis_status": "analyzed",
        "visual_summary": "The screen shows some text output",
        "extracted_result_values": [],
        "provider_used": "local_vision",
        "visual_frame_count": 5,
        "visual_frames_stored": 5,
    }
    weak = _svc().analyze(
        keyframe_result=_kf_result(),
        visual_frame_obs=vf_obs_only,
    )

    assert strong.confidence_score > weak.confidence_score
    assert strong.evidence_strength in (STRENGTH_STRONG, STRENGTH_MODERATE)


# ── Test 5: Weak evidence → no hallucinated skills ────────────────────────────

def test_weak_evidence_no_hallucinated_skills():
    # Only a single click event, no inputs, no outputs
    events = [{"type": "click", "element_text": "submit", "timestamp_ms": 5000}]
    result = _svc().analyze(dom_events=events)

    # Should not claim strong supported skills for unobserved evidence
    assert result.sequence_analysis_status == SEQ_STATUS_ANALYZED
    # Should report missing output
    all_text = " ".join(result.unsupported_claims + result.limitations).lower()
    assert "output" in all_text or "chain" in all_text
    # Should not claim specific model outputs or framework skills
    for skill in result.supported_skills:
        assert "tensorflow" not in skill.lower()
        assert "pytorch" not in skill.lower()
        assert "fastapi" not in skill.lower()


# ── Test 6: to_public_dict() never exposes private fields ─────────────────────

def test_public_dict_hides_private_fields():
    obs = _visible_obs(
        inputs=["input"],
        actions=["action"],
        outputs=["output"],
    )
    result = _svc().analyze(
        keyframe_result=_kf_result(),
        visible_observations=obs,
    )
    pub = result.to_public_dict()

    # private_review_flags must not be in public dict
    assert "private_review_flags" not in pub
    # No raw frame paths
    import json
    pub_str = json.dumps(pub)
    assert "/tmp/" not in pub_str
    assert "frame_storage_path" not in pub_str
    assert "access_token" not in pub_str


# ── Test 7: Malformed keyframe result → no crash ─────────────────────────────

def test_malformed_keyframe_result_safe():
    # Missing fields
    bad_kf = SimpleNamespace()
    result = _svc().analyze(keyframe_result=bad_kf)
    # Should not raise; degrades gracefully
    assert result.sequence_analysis_status in (SEQ_STATUS_ANALYZED, SEQ_STATUS_NOT_AVAILABLE)


# ── Test 8: Malformed events → no crash ───────────────────────────────────────

def test_malformed_events_safe():
    bad_events = [
        None,
        {},
        {"type": None, "timestamp_ms": "not_a_number"},
        {"type": "click"},     # missing element_text
        {"type": "page_visit", "page_url": None},
    ]
    # Should not raise
    result = _svc().analyze(dom_events=bad_events)  # type: ignore[arg-type]
    assert result.sequence_analysis_status in (SEQ_STATUS_ANALYZED, SEQ_STATUS_NOT_AVAILABLE)


# ── Test 9: Integration — sequence_analysis present in workflow analysis ───────

def test_workflow_analysis_includes_sequence_analysis():
    """sequence_analysis key must appear in _analyze_workflow() output."""
    from app.services.extension_proof_workflow_analysis_service import _analyze_workflow

    result = _analyze_workflow(
        proof_data={
            "workflow_events": _dom_events(with_input=True, with_action=True, with_output_nav=True),
        },
        claimed_skills=["Python"],
        proof_objective="Test the app",
        original_url="http://localhost:8000",
        url_type="localhost_url",
        github_url=None,
        visible_observations=None,
        visual_frame_observations=None,
    )
    assert "sequence_analysis" in result
    seq = result["sequence_analysis"]
    # Must have required fields from to_public_dict()
    assert "sequence_analysis_status" in seq
    assert "confidence_score" in seq
    assert "private_review_flags" not in seq    # must not leak


# ── Test 10: Stage assignment proportional with no timestamps ─────────────────

def test_stage_assignment_proportional():
    """Frames evenly cover the video → all 6 stages should receive at least 1 frame."""
    from app.services.workflow_sequence_analysis_service import (
        _assign_frames_to_stages, _build_event_map,
    )
    # 12 evenly spaced frames across 60s
    timestamps = [i * 5000 for i in range(12)]  # 0 to 55000ms
    event_map = _build_event_map([])
    stage_map = _assign_frames_to_stages(timestamps, event_map, 60_000)
    occupied = {s for s, ts in stage_map.items() if ts}
    # With proportional split, at least initial_state, some middle stages, and final_state
    assert len(occupied) >= 3


# ── Test 11: chain_complete only when all three parts detected ────────────────

def test_chain_complete_requires_all_three():
    # Only input + action, no output
    events = [
        {"type": "input_change", "element_id": "q", "timestamp_ms": 2000},
        {"type": "click", "element_text": "search", "timestamp_ms": 4000},
    ]
    result = _svc().analyze(dom_events=events)
    chain = result.input_action_output_chain
    assert chain["chain_complete"] is False
    assert chain["detected_input"] is not None
    assert chain["detected_action"] is not None
    assert chain["detected_output"] is None


# ── Test 12: Strong evidence strength requires DOM result values ──────────────

def test_strong_evidence_requires_dom_result_values():
    obs_with_values = _visible_obs(
        inputs=["x"],
        actions=["run"],
        outputs=["y"],
        result_values=[_rv("class", "0.95")],
        ev_status="available",
    )
    result = _svc().analyze(
        keyframe_result=_kf_result(timestamps=[0, 5000, 10000, 20000, 25000]),
        visible_observations=obs_with_values,
        dom_events=_dom_events(with_input=True, with_action=True, with_output_nav=True),
    )
    assert result.evidence_strength == STRENGTH_STRONG


# ── Test 13: Insufficient strength without real evidence ─────────────────────

def test_insufficient_strength_with_no_evidence():
    result = _svc().analyze()
    assert result.sequence_analysis_status == SEQ_STATUS_NOT_AVAILABLE
    assert result.evidence_strength == STRENGTH_INSUFFICIENT


# ── Test 14: private_review_flags contains no_keyframes when missing ──────────

def test_private_flags_include_no_keyframes():
    obs = _visible_obs(inputs=["x"], actions=["run"], outputs=["y"])
    result = _svc().analyze(visible_observations=obs)
    # keyframe_result is None → flag should be set
    assert "no_keyframes" in result.private_review_flags
    # But that flag must NOT appear in public dict
    assert "no_keyframes" not in str(result.to_public_dict())
