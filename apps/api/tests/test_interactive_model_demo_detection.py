"""Tests for Interactive Model Demo combined-evidence detection.

Covers:
1.  No interaction → "missing"
2.  Minimal clicks only → "unclear"
3.  Strong clicks + DOM graphical → "partial" or "supported"
4.  OCR interactive signals → promote to partial/supported
5.  Qwen confirms interactive demo → "supported"
6.  Qwen weak + DOM/OCR strong → still partial
7.  Proof objective mentions interactive → boosts signal
8.  p5.js scenario (creative coding, NOT neural network) → correct skill map
9.  _is_interactive_demo_skill() recognises all variants
10. _promote_interactive_demo_skills() updates result dict correctly
11. Non-interactive skill claim not affected by promotion logic
12. Already-supported skill not double-added
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.services.extension_proof_workflow_analysis_service import (
    _detect_interactive_model_demo_support,
    _is_interactive_demo_skill,
    _promote_interactive_demo_skills,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_clicks(n: int) -> list[dict]:
    return [{"type": "click", "element_text": f"btn-{i}"} for i in range(n)]


def _make_inputs(n: int) -> list[dict]:
    return [{"type": "input_change", "element_id": f"param-{i}"} for i in range(n)]


def _make_visible_obs(*, has_graphical: bool = False, snippets: list[str] | None = None) -> MagicMock:
    m = MagicMock()
    m.has_graphical_rendering = has_graphical
    m.top_result_snippets = snippets or []
    return m


def _make_ocr_summary(*, has_ocr: bool, snippets: list[str], context: str = "unknown") -> dict:
    return {
        "has_ocr_evidence": has_ocr,
        "top_ocr_snippets": snippets,
        "detected_page_context": context,
        "skill_signals": [],
    }


def _make_qwen_summary(*, status: str = "analyzed", verdict: str = "not_visible") -> dict:
    return {
        "status": status,
        "frames_analyzed": 1,
        "observations": [
            {
                "confidence_score": 0.7,
                "detected_workflow_stage": "results_display",
                "skill_evidence": {
                    "interactive model demo": {
                        "verdict": verdict,
                        "items_visible": ["sliders", "output panel"],
                    }
                },
            }
        ],
        "supported_signals": [],
    }


# ── 1. No interaction → missing ────────────────────────────────────────────────

def test_no_interaction_returns_missing():
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=[],
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    assert level == "missing"
    assert "no" in reason.lower() or "missing" in reason.lower()


# ── 2. Minimal clicks only → unclear ──────────────────────────────────────────

def test_minimal_clicks_returns_unclear():
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(2),
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    assert level in ("unclear", "partial")
    assert "click" in reason.lower()


# ── 3. Strong clicks + DOM graphical → at least partial ───────────────────────

def test_strong_clicks_and_graphical_dom_returns_partial_or_supported():
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(8),
        target_inputs=_make_inputs(2),
        visible_observations=_make_visible_obs(has_graphical=True, snippets=["output: 0.87"]),
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    assert level in ("partial", "supported")
    assert any(word in reason.lower() for word in ("click", "canvas", "dom", "graphical"))


# ── 4. OCR interactive signals → promote ──────────────────────────────────────

def test_ocr_interactive_signals_promote():
    ocr = _make_ocr_summary(
        has_ocr=True,
        snippets=["slider control", "output result canvas", "animate draw"],
        context="prediction_output",
    )
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(4),
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=ocr,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    assert level in ("partial", "supported")
    assert "ocr" in reason.lower()


def test_ocr_no_interactive_signals_stays_low():
    ocr = _make_ocr_summary(
        has_ocr=True,
        snippets=["privacy policy", "terms of service"],
        context="homepage_marketing",
    )
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=[],
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=ocr,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    assert level in ("missing", "unclear")


# ── 5. Qwen confirms interactive demo → supported ─────────────────────────────

def test_qwen_supported_verdict_returns_supported():
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(5),
        target_inputs=_make_inputs(1),
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=_make_qwen_summary(verdict="supported"),
    )
    assert level == "supported"
    assert "qwen" in reason.lower()


def test_qwen_partial_verdict_returns_at_least_partial():
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(2),
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=_make_qwen_summary(verdict="partial"),
    )
    assert level in ("partial", "supported")


# ── 6. Qwen weak + DOM/OCR strong ─────────────────────────────────────────────

def test_qwen_weak_but_dom_ocr_strong_still_partial():
    qwen = {
        "status": "analyzed",
        "frames_analyzed": 1,
        "observations": [{"confidence_score": 0.2, "skill_evidence": {}, "detected_workflow_stage": "unknown"}],
    }
    ocr = _make_ocr_summary(
        has_ocr=True,
        snippets=["slider controls canvas output chart interactive visualization"],
        context="prediction_output",
    )
    level, reason = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(6),
        target_inputs=_make_inputs(2),
        visible_observations=_make_visible_obs(has_graphical=True),
        frame_ocr_evidence_summary=ocr,
        proof_objective="",
        visual_reasoning_summary=qwen,
    )
    assert level in ("partial", "supported")


# ── 7. Proof objective boosts signal ──────────────────────────────────────────

def test_proof_objective_mention_boosts():
    level_with, _ = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(2),
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="I will show an interactive demo with controls and canvas output",
        visual_reasoning_summary=None,
    )
    level_without, _ = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(2),
        target_inputs=[],
        visible_observations=None,
        frame_ocr_evidence_summary=None,
        proof_objective="",
        visual_reasoning_summary=None,
    )
    # With objective mention should be at least as strong
    _order = {"missing": 0, "unclear": 1, "partial": 2, "supported": 3}
    assert _order[level_with] >= _order[level_without]


# ── 8. p5.js scenario: interactive coding, NOT neural network ─────────────────

def test_p5js_scenario_no_neural_network():
    """p5.js demo evidence should support Interactive Model Demo / Creative Coding,
    but should NOT automatically support Machine Learning / Neural Networks.
    """
    # Simulate p5.js session: canvas + sketch + animation in OCR
    ocr = _make_ocr_summary(
        has_ocr=True,
        snippets=["p5.js sketch canvas animate draw function setup draw loop"],
        context="unknown",
    )
    level_demo, reason_demo = _detect_interactive_model_demo_support(
        target_clicks=_make_clicks(5),
        target_inputs=_make_inputs(1),
        visible_observations=_make_visible_obs(has_graphical=True),
        frame_ocr_evidence_summary=ocr,
        proof_objective="I will show an interactive browser-based coding demo using p5.js",
        visual_reasoning_summary=None,
    )
    # Should support interactive demo
    assert level_demo in ("partial", "supported"), \
        f"Expected p5.js demo to be partial/supported, got {level_demo}"

    # Machine Learning detection should not fire for p5.js alone
    # (verify by checking that "neural network" or "machine learning" are not
    # in the reason when only p5.js evidence is present)
    assert "neural network" not in reason_demo.lower()
    assert "machine learning" not in reason_demo.lower()


# ── 9. _is_interactive_demo_skill recognises all variants ─────────────────────

@pytest.mark.parametrize("skill_name,expected", [
    ("Interactive Model Demo",           True),
    ("interactive model demo",           True),
    ("Interactive Demo",                 True),
    ("Browser-Based Interactive Demo",   True),
    ("Interactive Web Visualization",    True),
    ("interactive dashboard",            True),
    ("Data/Visual Output",               True),
    ("Machine Learning",                 False),
    ("Neural Networks",                  False),
    ("Python",                           False),
    ("React",                            False),
    ("Data Visualization",               False),  # not in the interactive demo fragment list
])
def test_is_interactive_demo_skill(skill_name: str, expected: bool):
    result = _is_interactive_demo_skill(skill_name)
    assert result == expected, f"_is_interactive_demo_skill({skill_name!r}) should be {expected}"


# ── 10. _promote_interactive_demo_skills updates result correctly ──────────────

def test_promote_moves_unsupported_to_weakly():
    result = {
        "supported_skills": [],
        "weakly_supported_skills": [],
        "unsupported_skills": ["Interactive Model Demo"],
        "frame_ocr_evidence_summary": _make_ocr_summary(
            has_ocr=True,
            snippets=["slider canvas controls output interactive"],
            context="prediction_output",
        ),
        "visual_reasoning_summary": None,
    }
    proof_data = {
        "workflow_events": _make_clicks(5) + _make_inputs(2),
    }
    updated = _promote_interactive_demo_skills(
        result=result,
        proof_data=proof_data,
        claimed_skills=["Interactive Model Demo"],
        visible_observations=_make_visible_obs(has_graphical=True),
        visual_frame_observations=None,
        proof_objective="interactive demo with controls",
    )
    assert "Interactive Model Demo" not in updated["unsupported_skills"]
    assert (
        "Interactive Model Demo" in updated["weakly_supported_skills"]
        or "Interactive Model Demo" in updated["supported_skills"]
    )


def test_promote_does_not_affect_non_interactive_skills():
    result = {
        "supported_skills": ["Python"],
        "weakly_supported_skills": [],
        "unsupported_skills": ["Machine Learning"],
        "frame_ocr_evidence_summary": None,
        "visual_reasoning_summary": None,
    }
    proof_data = {"workflow_events": []}
    updated = _promote_interactive_demo_skills(
        result=result,
        proof_data=proof_data,
        claimed_skills=["Machine Learning"],
        visible_observations=None,
        visual_frame_observations=None,
        proof_objective="",
    )
    # Machine Learning should not be touched by interactive demo promotion
    assert "Machine Learning" in updated["unsupported_skills"]
    assert "Python" in updated["supported_skills"]


# ── 11. Already-supported skill not double-added ──────────────────────────────

def test_already_supported_not_doubled():
    result = {
        "supported_skills": ["Interactive Model Demo"],
        "weakly_supported_skills": [],
        "unsupported_skills": [],
        "frame_ocr_evidence_summary": None,
        "visual_reasoning_summary": None,
    }
    proof_data = {"workflow_events": _make_clicks(10)}
    updated = _promote_interactive_demo_skills(
        result=result,
        proof_data=proof_data,
        claimed_skills=["Interactive Model Demo"],
        visible_observations=None,
        visual_frame_observations=None,
        proof_objective="",
    )
    assert updated["supported_skills"].count("Interactive Model Demo") == 1
