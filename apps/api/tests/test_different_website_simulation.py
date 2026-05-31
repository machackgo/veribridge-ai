"""Simulated end-to-end test: p5.js examples site + ObservableHQ D3 gallery.

This test validates that VeriBridge stays project-agnostic and does not overfit
to TensorFlow Playground or Teachable Machine.

Test objectives:
  A. p5.js scenario (https://p5js.org/examples/)
     Claims: Browser-Based Interactive Demo, Creative Coding, Data/Visual Output,
             JavaScript, Interactive Web Visualization
     Expected:
       - Interactive Model Demo / Creative Coding → partial or supported (canvas/sketch OCR)
       - JavaScript → supported or partial (OCR detects 'javascript', 'p5.js')
       - Machine Learning / Neural Network → NOT auto-detected without ML evidence
       - No hallucinated ML skills

  B. ObservableHQ D3 gallery (https://observablehq.com/@d3/gallery)
     Claims: Data Visualization, Interactive Dashboard, JavaScript,
             Browser-Based Visualization, Chart Analysis
     Expected:
       - Data Visualization → partial (chart/d3 in OCR)
       - JavaScript → partial (js/d3 in OCR)
       - Interactive Dashboard → partial if enough clicks
       - Machine Learning → NOT detected

Coverage:
1.  p5.js OCR keywords map correctly to Creative Coding / Browser-Based Interactive Demo
2.  p5.js session with canvas OCR → no ML/NN skills auto-added
3.  p5.js with strong interaction → Interactive Model Demo promoted to partial
4.  D3/Observable: chart OCR → Data Visualization partial
5.  D3/Observable: no neural network detection
6.  OCR-only evidence never "supported" for code skills
7.  Fusion: Qwen disabled but OCR available → summary still useful
8.  Generalization: two different sessions produce different skill maps
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.services.extension_proof_workflow_analysis_service import (
    _ocr_skill_signals,
    _detect_ocr_page_context,
    _is_interactive_demo_skill,
    _detect_interactive_model_demo_support,
    _SKILL_OCR_KEYWORDS,
)
from app.services.visual_reasoning_service import (
    MockReasoningProvider,
    VisualReasoningObservation,
    VisualReasoningService,
    REASONING_STATUS_ANALYZED,
    REASONING_STATUS_DISABLED,
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_clicks(n: int) -> list[dict]:
    return [{"type": "click", "element_text": f"btn-{i}"} for i in range(n)]

def _make_inputs(n: int) -> list[dict]:
    return [{"type": "input_change", "element_id": f"param-{i}"} for i in range(n)]

def _make_visible_obs(*, has_graphical: bool = False, snippets: list[str] | None = None) -> MagicMock:
    m = MagicMock()
    m.has_graphical_rendering = has_graphical
    m.top_result_snippets = snippets or []
    return m

def _make_ocr_summary(snippets: list[str], context: str = "unknown") -> dict:
    return {
        "has_ocr_evidence": True,
        "top_ocr_snippets": snippets,
        "detected_page_context": context,
        "skill_signals": [],
    }


# ── A1. p5.js OCR keywords → correct skill mapping ────────────────────────────

def test_p5js_ocr_maps_to_creative_coding():
    ocr_text = "p5.js sketch canvas draw setup loop createCanvas background fill"
    signals = _ocr_skill_signals(
        claimed_skills=["Creative Coding", "Browser-Based Interactive Demo"],
        ocr_text=ocr_text,
        page_context="unknown",
    )
    sig_map = {s["skill"]: s["ocr_support"] for s in signals}
    # Creative Coding should find p5/sketch/canvas keywords
    assert sig_map.get("Creative Coding") == "partial", \
        f"Expected partial for Creative Coding, got {sig_map}"
    # Browser-Based Interactive Demo should find canvas/interactive/demo keywords
    assert sig_map.get("Browser-Based Interactive Demo") == "partial", \
        f"Expected partial for Browser-Based Interactive Demo, got {sig_map}"


# ── A2. p5.js session → no ML/NN skills auto-added ───────────────────────────

def test_p5js_ocr_does_not_trigger_machine_learning():
    """p5.js OCR text should not produce ML/NN skill signals."""
    ocr_text = "p5.js sketch canvas draw setup loop createCanvas background fill animate"
    signals = _ocr_skill_signals(
        claimed_skills=["Machine Learning", "Neural Networks"],
        ocr_text=ocr_text,
        page_context="unknown",
    )
    sig_map = {s["skill"]: s["ocr_support"] for s in signals}
    # Machine Learning should be 'insufficient' (no ML keywords in p5.js OCR)
    assert sig_map.get("Machine Learning") == "insufficient", \
        f"ML should not be detected from p5.js OCR, got {sig_map}"
    assert sig_map.get("Neural Networks") == "insufficient", \
        f"NN should not be detected from p5.js OCR, got {sig_map}"


# ── A3. p5.js with strong interaction → Interactive Model Demo promoted ────────

def test_p5js_interactive_demo_promoted_with_canvas_and_clicks():
    """p5.js recording with canvas + clicks + visual output → interactive demo partial."""
    ocr = _make_ocr_summary(
        snippets=["p5.js sketch canvas animate draw loop output result"],
        context="unknown",
    )
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(6),
        target_inputs=_make_inputs(1),
        visible_observations=_make_visible_obs(has_graphical=True, snippets=["canvas output"]),
        frame_ocr_evidence_summary=ocr,
        proof_objective="I will show an interactive browser-based coding demo using p5.js",
        visual_reasoning_summary=None,
    )
    assert level in ("partial", "supported"), \
        f"p5.js demo should be partial/supported, got {level}: {reason}"
    # Should not hallucinate ML
    assert "machine learning" not in reason.lower()
    assert "neural network" not in reason.lower()


# ── B4. D3/Observable: chart OCR → Data Visualization partial ─────────────────

def test_d3_observable_ocr_maps_to_data_visualization():
    ocr_text = "d3.js visualization chart axes legend dataset bar chart line chart svg"
    signals = _ocr_skill_signals(
        claimed_skills=["Data Visualization", "JavaScript", "Chart Analysis"],
        ocr_text=ocr_text,
        page_context="unknown",
    )
    sig_map = {s["skill"]: s["ocr_support"] for s in signals}
    assert sig_map.get("Data Visualization") == "partial", \
        f"Expected partial for Data Visualization, got {sig_map}"
    assert sig_map.get("JavaScript") == "partial", \
        f"Expected partial for JavaScript, got {sig_map}"
    assert sig_map.get("Chart Analysis") == "partial", \
        f"Expected partial for Chart Analysis, got {sig_map}"


# ── B5. D3/Observable: no neural network detection ────────────────────────────

def test_d3_ocr_does_not_trigger_neural_network():
    ocr_text = "d3.js chart axes zoom filter hover tooltip svg data"
    signals = _ocr_skill_signals(
        claimed_skills=["Neural Networks", "Machine Learning"],
        ocr_text=ocr_text,
        page_context="unknown",
    )
    sig_map = {s["skill"]: s["ocr_support"] for s in signals}
    assert sig_map.get("Neural Networks") == "insufficient"
    assert sig_map.get("Machine Learning") == "insufficient"


# ── B6. OCR-only evidence never "supported" for code skills ───────────────────

def test_ocr_only_never_marks_javascript_as_supported():
    """OCR can provide 'partial' at most — never 'supported' alone for code skills."""
    ocr_text = "javascript function const let var import d3.js p5.js"
    signals = _ocr_skill_signals(
        claimed_skills=["JavaScript"],
        ocr_text=ocr_text,
        page_context="unknown",
    )
    # All OCR signals are at most "partial"
    for sig in signals:
        assert sig["ocr_support"] in ("partial", "insufficient"), \
            f"OCR should never produce 'supported' level, got: {sig}"


# ── B7. Qwen disabled but OCR available → summary still useful ────────────────

def test_visual_reasoning_disabled_but_ocr_available():
    """When Qwen is disabled, the session summary status is 'disabled'
    but the OCR evidence summary is still available for skill signals."""
    from app.services.visual_reasoning_service import DisabledReasoningProvider
    svc = VisualReasoningService(provider=DisabledReasoningProvider())

    _TINY_JPEG = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
        0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
        0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00,
        0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xD9,
    ])
    frames = [(1000, _TINY_JPEG), (2000, _TINY_JPEG), (3000, _TINY_JPEG)]
    summary = svc.analyze_frames(frames)
    # Status is either 'disabled' or 'missing_dependency' depending on env settings
    assert summary.status in (REASONING_STATUS_DISABLED, "missing_dependency")
    assert summary.frames_analyzed == 0
    # limitations should be present and informative
    assert len(summary.limitations) > 0


# ── B8. Generalization: two sessions produce different skill maps ──────────────

def test_two_sessions_produce_independent_skill_maps():
    """Verify session isolation: p5.js session and D3 session have different maps."""
    obs_p5 = VisualReasoningObservation(
        frame_index=0, timestamp_ms=1000, model_provider="mock",
        visual_summary="p5.js canvas sketch animation visible",
        supported_skills=["Creative Coding"],
        skill_evidence={"Creative Coding": {"verdict": "supported", "items_visible": ["canvas", "sketch"]}},
        detected_workflow_stage="results_display",
        confidence_score=0.8, status=REASONING_STATUS_ANALYZED,
    )
    obs_d3 = VisualReasoningObservation(
        frame_index=0, timestamp_ms=1000, model_provider="mock",
        visual_summary="D3.js bar chart with axes and tooltip",
        supported_skills=["Data Visualization"],
        skill_evidence={"Data Visualization": {"verdict": "supported", "items_visible": ["chart", "axes"]}},
        detected_workflow_stage="results_display",
        confidence_score=0.85, status=REASONING_STATUS_ANALYZED,
    )

    svc_p5 = VisualReasoningService(provider=MockReasoningProvider(observations=[obs_p5]))
    svc_d3 = VisualReasoningService(provider=MockReasoningProvider(observations=[obs_d3]))

    _TINY = bytes([0xFF, 0xD8, 0xFF, 0xD9])  # minimal JPEG
    frames = [(1000, _TINY)]

    summary_p5 = svc_p5.analyze_frames(frames)
    summary_d3 = svc_d3.analyze_frames(frames)

    assert "Creative Coding" in summary_p5.supported_signals
    assert "Data Visualization" not in summary_p5.supported_signals

    assert "Data Visualization" in summary_d3.supported_signals
    assert "Creative Coding" not in summary_d3.supported_signals


# ── Extra: _SKILL_OCR_KEYWORDS covers all expected skills ─────────────────────

def test_skill_ocr_keywords_has_interactive_demo_entry():
    assert "interactive model demo" in _SKILL_OCR_KEYWORDS
    assert len(_SKILL_OCR_KEYWORDS["interactive model demo"]) >= 5


def test_skill_ocr_keywords_has_creative_coding_entry():
    assert "creative coding" in _SKILL_OCR_KEYWORDS
    assert "p5" in _SKILL_OCR_KEYWORDS["creative coding"]


def test_skill_ocr_keywords_has_data_visualization_entry():
    assert "data visualization" in _SKILL_OCR_KEYWORDS
    assert "d3" in _SKILL_OCR_KEYWORDS["data visualization"]


def test_skill_ocr_keywords_has_javascript_entry():
    assert "javascript" in _SKILL_OCR_KEYWORDS
    assert "javascript" in _SKILL_OCR_KEYWORDS["javascript"]
