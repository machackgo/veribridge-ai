"""Targeted tests for FinalEvidenceEvaluatorService — grouped skill evidence,
evidence objects, optional-module no-penalty, status-label wording, and
Qwen disabled/enabled representation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.final_evidence_evaluator_service import (
    FinalEvidenceEvaluatorService,
    GroupedSkillEvidence,
    EvidenceObject,
    DetectedSkillEntry,
    _skill_category,
    _sources_to_labels,
    _build_github_blob_url,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(wf=None, gh=None, lw=None, pd=None, kf_count=0):
    """Return a mock Supabase-style db whose table() calls return canned data."""
    db = MagicMock()

    def _table(name):
        tbl = MagicMock()
        chain = MagicMock()
        if name == "workflow_analysis_results":
            chain.execute.return_value.data = [wf] if wf else []
        elif name == "extension_proof_github_analysis":
            chain.execute.return_value.data = [gh] if gh else []
        elif name == "live_website_check_results":
            chain.execute.return_value.data = [lw] if lw else []
        elif name == "project_defense_analysis_results":
            chain.execute.return_value.data = [pd] if pd else []
        elif name == "workflow_visual_frame_evidence":
            chain.execute.return_value.data = [{}] * kf_count
            chain.execute.return_value.count = kf_count
        else:
            chain.execute.return_value.data = []
        tbl.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        return tbl

    db.table.side_effect = _table
    return db


def _svc(wf=None, gh=None, lw=None, pd=None, kf_count=0):
    return FinalEvidenceEvaluatorService(_make_db(wf, gh, lw, pd, kf_count))


# ── 1. grouped_skill_evidence is returned ──────────────────────────────────────

def test_grouped_skill_evidence_present_in_result():
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["navigate", "click", "scroll"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization", "JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization", "JavaScript"],
    )
    assert hasattr(result, "grouped_skill_evidence")
    assert isinstance(result.grouped_skill_evidence, list)
    # to_dict must include grouped_skill_evidence
    d = result.to_dict()
    assert "grouped_skill_evidence" in d
    assert isinstance(d["grouped_skill_evidence"], list)


def test_grouped_skill_evidence_non_empty_when_skills_detected():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["navigate"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization", "JavaScript", "Technical Documentation"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization", "JavaScript", "Technical Documentation"],
    )
    groups = result.grouped_skill_evidence
    assert len(groups) >= 1
    for g in groups:
        assert g.group_name
        assert g.category
        assert g.confidence in ("high", "medium", "low")
        assert isinstance(g.skills, list)
        assert len(g.skills) >= 1


# ── 2. Skills are grouped by category ─────────────────────────────────────────

def test_skill_category_mapping():
    assert _skill_category("Data Visualization") == "DATA"
    assert _skill_category("JavaScript") == "FRONTEND"
    assert _skill_category("Machine Learning") == "AI/ML"
    assert _skill_category("Technical Documentation") == "DOCUMENTATION"
    assert _skill_category("Open Source Project") == "OPEN_SOURCE"
    assert _skill_category("Backend API") == "BACKEND"
    assert _skill_category("DevOps Deployment") == "DEVOPS"


def test_skills_grouped_separately_by_category():
    wf = {
        "evidence_strength_score": 75,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["navigate"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization", "JavaScript", "Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization", "JavaScript", "Machine Learning"],
    )
    groups = result.grouped_skill_evidence
    categories = [g.category for g in groups]
    # Each category appears at most once
    assert len(categories) == len(set(categories))
    # DATA and FRONTEND and AI/ML should appear
    assert "DATA" in categories
    assert "FRONTEND" in categories
    assert "AI/ML" in categories


def test_source_labels_mapped_correctly():
    assert "Recording" in _sources_to_labels(["workflow"])
    assert "OCR" in _sources_to_labels(["OCR"])
    assert "Qwen" in _sources_to_labels(["Qwen"])
    assert "GitHub" in _sources_to_labels(["GitHub"])
    # "claimed" should NOT produce a label
    assert _sources_to_labels(["claimed"]) == []


def test_group_source_labels_populated_from_skills():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 5000],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
    )
    groups = result.grouped_skill_evidence
    assert len(groups) >= 1
    data_group = next((g for g in groups if g.category == "DATA"), None)
    assert data_group is not None
    assert "Recording" in data_group.source_labels


# ── 3. Optional modules do not reduce score ────────────────────────────────────

def test_optional_modules_absent_do_not_reduce_score():
    """Score with only workflow evidence should not be penalised by missing optional sources."""
    wf = {
        "evidence_strength_score": 72,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate", "scroll", "input"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    # No GitHub, no live check, no project defense (optional)
    result_without_optionals = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
    )
    score_without = result_without_optionals.final_score

    # Score must be > 0 (not dragged to 0 by absent optional modules)
    assert score_without > 0, "Score must not be zero with solid workflow evidence"

    # Adding GitHub (optional booster) must not reduce the score
    gh = {
        "status": "success",
        "confidence_score": 0.85,
        "matched_claimed_skills": ["Data Visualization"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript", "D3"],
        "github_url": "https://github.com/example/repo",
    }
    result_with_github = _svc(wf=wf, gh=gh).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
        github_url="https://github.com/example/repo",
    )
    assert result_with_github.final_score >= score_without, (
        "Adding GitHub evidence must not reduce score"
    )


def test_live_check_absent_does_not_penalise():
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["JavaScript"],
    )
    # live_website_check missing should appear as not_run, not penalise
    lw_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "live_website_check"),
        None,
    )
    assert lw_src is not None
    assert lw_src["status"] == "not_run"


def test_project_defense_absent_does_not_penalise():
    wf = {
        "evidence_strength_score": 68,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
    )
    pd_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "project_defense"),
        None,
    )
    assert pd_src is not None
    assert pd_src["status"] == "not_run"


# ── 4. Detected skills avoid the word "verified" ──────────────────────────────

def test_status_labels_never_use_word_verified():
    wf = {
        "evidence_strength_score": 80,
        "workflow_confidence": "strong",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Data Visualization", "JavaScript"],
        "weakly_supported_skills": ["Machine Learning"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["Data Visualization"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/example/repo",
    }
    result = _svc(wf=wf, gh=gh).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization", "JavaScript", "Machine Learning"],
        github_url="https://github.com/example/repo",
    )

    svc = _svc(wf=wf, gh=gh)
    entries = svc._collect_all_evidence_skills(
        ["Data Visualization", "JavaScript", "Machine Learning"], wf, gh
    )

    for entry in entries.values():
        label = entry.status_label.lower()
        assert "verified" not in label, (
            f"skill '{entry.skill}' status_label '{entry.status_label}' must not contain 'verified'"
        )

    # evidence_support strings must not contain "verified"
    for entry in entries.values():
        assert "verified" not in entry.evidence_support.lower(), (
            f"skill '{entry.skill}' evidence_support '{entry.evidence_support}' contains 'verified'"
        )


def test_evidence_support_wording_is_recruiter_safe():
    safe_phrases = [
        "evidence suggests", "strongly supported", "partially supported",
        "inferred", "detected", "supported by", "claimed",
    ]
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": ["JavaScript"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    svc = _svc(wf=wf)
    entries = svc._collect_all_evidence_skills(["Data Visualization", "JavaScript"], wf, None)
    for entry in entries.values():
        lower = entry.evidence_support.lower()
        assert any(p in lower for p in safe_phrases), (
            f"evidence_support '{entry.evidence_support}' does not use safe phrasing"
        )


# ── 5. Qwen disabled status represented safely ────────────────────────────────

def test_qwen_disabled_scores_not_available():
    """When visual_reasoning_summary.status == 'disabled', qwen source is not_available."""
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {"status": "disabled", "frames_analyzed": 0},
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
    )
    qwen_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning"),
        None,
    )
    assert qwen_src is not None
    assert qwen_src["status"] == "not_available"
    # Disabled Qwen must not contribute score
    assert qwen_src["score"] == 0


def test_qwen_enabled_and_analyzed_contributes_score():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "frames_analyzed": 2,
            "supported_signals": ["data visualization", "chart"],
            "summary": "Chart visible with axes labeled.",
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization"],
    )
    qwen_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning"),
        None,
    )
    assert qwen_src is not None
    assert qwen_src["status"] == "pass"
    assert qwen_src["score"] > 0


def test_qwen_disabled_does_not_reduce_score_vs_no_qwen():
    """Score with Qwen disabled must be >= score with no Qwen data at all."""
    base_wf: dict[str, Any] = {
        "evidence_strength_score": 68,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    wf_no_qwen = {**base_wf, "visual_reasoning_summary": None}
    wf_disabled_qwen = {**base_wf, "visual_reasoning_summary": {"status": "disabled", "frames_analyzed": 0}}

    score_no_qwen = _svc(wf=wf_no_qwen).evaluate(
        "u1", "s1", claimed_skills=["Data Visualization"]
    ).final_score

    score_disabled = _svc(wf=wf_disabled_qwen).evaluate(
        "u1", "s1", claimed_skills=["Data Visualization"]
    ).final_score

    assert score_disabled >= score_no_qwen - 1, (
        "Disabled Qwen must not reduce score compared to absent Qwen"
    )


def test_qwen_pending_scores_not_run_no_false_disabled_note():
    """When visual_reasoning_summary.status == 'pending', Qwen is enabled but not yet run.
    Must NOT show 'VISUAL_REASONING_ENABLED=false' and must not be 'not_available'."""
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "pending",
            "frames_analyzed": 0,
            "summary": "Qwen enabled but not yet run.",
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Machine Learning"],
    )
    qwen_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning"),
        None,
    )
    assert qwen_src is not None
    # pending = not_run (gray), NOT not_available (red/disabled)
    assert qwen_src["status"] == "not_run", f"expected not_run, got {qwen_src['status']}"
    # Must not show the false "VISUAL_REASONING_ENABLED=false" note
    assert "VISUAL_REASONING_ENABLED=false" not in (qwen_src.get("notes") or ""), (
        "pending Qwen must not show VISUAL_REASONING_ENABLED=false"
    )
    # Should mention processing/refresh
    assert "processing" in (qwen_src.get("notes") or "").lower() or \
           "refresh" in (qwen_src.get("notes") or "").lower(), (
        "pending Qwen notes should mention processing or refresh"
    )


def test_qwen_pending_does_not_reduce_score_vs_disabled():
    """Score with Qwen pending must be >= score with Qwen disabled (no extra penalty)."""
    base_wf: dict[str, Any] = {
        "evidence_strength_score": 68,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    wf_pending = {**base_wf, "visual_reasoning_summary": {"status": "pending", "frames_analyzed": 0}}
    wf_disabled = {**base_wf, "visual_reasoning_summary": {"status": "disabled", "frames_analyzed": 0}}

    score_pending = _svc(wf=wf_pending).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    ).final_score

    score_disabled = _svc(wf=wf_disabled).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    ).final_score

    assert score_pending >= score_disabled, (
        "Pending Qwen must not produce a lower score than disabled Qwen"
    )


def test_grouped_skill_evidence_count_matches_evidence_objects():
    """evidence_count in each grouped_skill_evidence group matches actual evidence_objects count."""
    wf = {
        "evidence_strength_score": 72,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["navigate", "click", "input_text"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["TensorFlow.js", "Machine Learning"],
        "weakly_supported_skills": ["JavaScript"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {
            "has_ocr_evidence": True,
            "ocr_provider": "tesseract",
            "frames_analyzed": 2,
            "top_ocr_snippets": ["TensorFlow", "model", "neural network"],
            "detected_page_context": "demo_content",
            "observed_summary": "TensorFlow.js demo UI visible",
            "what_was_not_observed": [],
            "skill_signals": [
                {"skill": "TensorFlow.js", "ocr_support": "partial", "reasoning": "TensorFlow found in OCR", "ocr_terms_found": ["TensorFlow"]},
            ],
        },
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 5000],
    }
    result = _svc(wf=wf, kf_count=2).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["TensorFlow.js", "Machine Learning"],
    )
    groups = result.grouped_skill_evidence or []
    assert len(groups) > 0, "Expected at least one grouped skill evidence group"
    for g in groups:
        # result.grouped_skill_evidence may be dataclasses or dicts depending on serialization
        g_dict = g if isinstance(g, dict) else vars(g) if hasattr(g, "__dict__") else {}
        skills_list = g_dict.get("skills", []) if isinstance(g_dict, dict) else getattr(g, "skills", [])
        actual_objs = sum(
            len(getattr(s, "evidence_objects", None) or []) if not isinstance(s, dict)
            else len(s.get("evidence_objects", []))
            for s in skills_list
        )
        ev_count = g_dict.get("evidence_count", 0) if isinstance(g_dict, dict) else getattr(g, "evidence_count", 0)
        group_name = g_dict.get("group_name", "") if isinstance(g_dict, dict) else getattr(g, "group_name", "")
        assert ev_count == actual_objs, (
            f"Group {group_name}: evidence_count={ev_count} "
            f"but actual evidence_objects sum={actual_objs}"
        )


def test_optional_modules_no_penalty():
    """Live website check, project defense, and documents must not reduce score when absent."""
    wf = {
        "evidence_strength_score": 75,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate", "input_text"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 3,
        "video_keyframe_timestamps_ms": [1000, 3000, 6000],
    }
    # Score with only workflow evidence (no optional modules)
    score_no_optional = _svc(wf=wf, kf_count=3).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    ).final_score

    # Score must be the same if we explicitly pass None for optional modules
    # (they are not run → weight excluded from denominator)
    assert score_no_optional > 0, "Score should be positive with workflow evidence"

    # Verify optional sources show as not_run (not missing/penalty)
    result = _svc(wf=wf, kf_count=3).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    )
    lw_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "live_website_check"),
        None,
    )
    assert lw_src is not None
    assert lw_src["status"] == "not_run", (
        f"live_website_check should be not_run when not executed, got {lw_src['status']}"
    )


# ── 6. Evidence objects are produced ──────────────────────────────────────────

def test_evidence_objects_populated_for_recording_skills():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1500, 4000],
    }
    svc = _svc(wf=wf)
    entries = svc._collect_all_evidence_skills(["Data Visualization"], wf, None)
    viz = entries.get("data visualization")
    assert viz is not None
    assert viz.evidence_count > 0
    assert any(e.evidence_type == "recording_keyframe" for e in viz.evidence_objects)
    # Keyframe evidence objects have timestamp_seconds
    kf_objs = [e for e in viz.evidence_objects if e.evidence_type == "recording_keyframe"]
    assert all(e.timestamp_seconds is not None for e in kf_objs)


def test_evidence_objects_github_skill():
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript", "D3"],
        "github_url": "https://github.com/example/repo",
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["JavaScript"], None, gh)
    js = entries.get("javascript")
    assert js is not None
    gh_objs = [e for e in js.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1
    assert all(e.recruiter_safe for e in gh_objs)


def test_evidence_objects_are_recruiter_safe():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 1,
        "video_keyframe_timestamps_ms": [2000],
    }
    svc = _svc(wf=wf)
    entries = svc._collect_all_evidence_skills(["Data Visualization"], wf, None)
    for entry in entries.values():
        for obj in entry.evidence_objects:
            assert obj.recruiter_safe is True


# ── 7. grouped_skill_evidence to_dict serialisation ───────────────────────────

def test_grouped_skill_evidence_serialises_to_dict():
    wf = {
        "evidence_strength_score": 72,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Data Visualization", "JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Data Visualization", "JavaScript"],
    )
    d = result.to_dict()
    groups = d["grouped_skill_evidence"]
    assert isinstance(groups, list)
    for g in groups:
        assert "group_name" in g
        assert "category" in g
        assert "confidence" in g
        assert "evidence_count" in g
        assert "sources_count" in g
        assert "source_labels" in g
        assert "skills" in g
        for sk in g["skills"]:
            assert "skill" in sk
            assert "category" in sk
            assert "source_labels" in sk
            assert "evidence_objects" in sk


# ── 8. Traceable evidence — GitHub file_path, provenance, evidence_kind ─────────

def test_github_evidence_includes_file_path_when_evidence_files_present():
    """When evidence_files is populated in GitHub analysis, evidence objects show file_path."""
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript", "D3"],
        "github_url": "https://github.com/example/repo",
        "evidence_files": ["src/index.js", "package.json"],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["JavaScript"], None, gh)
    js = entries.get("javascript")
    assert js is not None
    gh_objs = [e for e in js.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1
    # At least one should have file_path set
    file_paths = [e.file_path for e in gh_objs if e.file_path]
    assert len(file_paths) >= 1, "Expected at least one file_path in GitHub evidence objects"
    assert "src/index.js" in file_paths or "package.json" in file_paths
    # Should have provenance set
    assert all(e.provenance == "GitHub Evidence" for e in gh_objs)
    # Should have trace_action set
    assert all(e.trace_action == "open_github" for e in gh_objs)


def test_github_evidence_no_evidence_files_shows_repo_level():
    """When matched but no evidence_files, evidence object is repo-level (no file_path)."""
    gh = {
        "status": "success",
        "confidence_score": 0.85,
        "matched_claimed_skills": ["Python"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["Python"],
        "github_url": "https://github.com/example/repo",
        # no evidence_files key — should produce repo-level evidence object
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["Python"], None, gh)
    py = entries.get("python")
    assert py is not None
    gh_objs = [e for e in py.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1
    # No evidence_files → no file_path in evidence objects
    no_fp = [e for e in gh_objs if not e.file_path]
    assert len(no_fp) >= 1
    # Short summary should mention repository-level evidence or similar
    assert any(
        "repository" in (e.short_summary or "").lower()
        or "matched" in (e.short_summary or "").lower()
        for e in no_fp
    )


def test_ocr_evidence_includes_timestamp_and_provenance():
    """OCR evidence objects should include timestamp_seconds and provenance."""
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": [],
        "weakly_supported_skills": ["TensorFlow.js"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {
            "has_ocr_evidence": True,
            "ocr_provider": "tesseract",
            "frames_analyzed": 2,
            "top_ocr_snippets": ["TensorFlow"],
            "detected_page_context": "demo_content",
            "observed_summary": "TensorFlow demo visible",
            "what_was_not_observed": [],
            "skill_signals": [
                {
                    "skill": "TensorFlow.js",
                    "ocr_support": "partial",
                    "reasoning": "TensorFlow found in OCR text",
                    "ocr_terms_found": ["TensorFlow", "model"],
                },
            ],
        },
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 5000],
    }
    svc = _svc(wf=wf)
    entries = svc._collect_all_evidence_skills(["TensorFlow.js"], wf, None)
    tf = entries.get("tensorflow.js")
    assert tf is not None
    ocr_objs = [e for e in tf.evidence_objects if e.evidence_type == "ocr_text"]
    assert len(ocr_objs) >= 1
    # provenance must be set
    assert all(e.provenance == "OCR Evidence" for e in ocr_objs)
    # matched_keywords should be populated
    kw_objs = [e for e in ocr_objs if e.matched_keywords]
    assert len(kw_objs) >= 1
    assert any("TensorFlow" in kw for e in kw_objs for kw in e.matched_keywords)


def test_qwen_evidence_includes_evidence_kind():
    """Qwen evidence objects should include evidence_kind and provenance."""
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "frames_analyzed": 2,
            "supported_signals": ["machine learning"],
            "summary": "ML demo UI visible",
            "observations": [
                {
                    "timestamp_ms": 2000,
                    "detected_workflow_stage": "results_display",
                    "visual_summary": "Prediction result visible",
                    "detected_outputs": ["0.95 confidence"],
                    "confidence_score": 0.8,
                    "skill_evidence": {
                        "Machine Learning": {
                            "items_visible": ["prediction output"],
                            "verdict": "supported",
                        }
                    },
                }
            ],
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    svc = _svc(wf=wf)
    entries = svc._collect_all_evidence_skills(["Machine Learning"], wf, None)
    ml = entries.get("machine learning")
    assert ml is not None
    qwen_objs = [e for e in ml.evidence_objects if e.evidence_type == "qwen_visual"]
    assert len(qwen_objs) >= 1
    # evidence_kind must be populated
    assert all(e.evidence_kind != "" for e in qwen_objs)
    # provenance must be Advanced Visual Reasoning
    assert all(e.provenance == "Advanced Visual Reasoning" for e in qwen_objs)
    # When verdict=supported, evidence_kind should be direct_workflow
    direct = [e for e in qwen_objs if e.evidence_kind == "direct_workflow"]
    assert len(direct) >= 1, "Expected at least one direct_workflow Qwen evidence object"


def test_live_website_check_is_not_run_when_absent():
    """Live website check should appear as not_run (not penalised) when not executed."""
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["JavaScript"])
    lw_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "live_website_check"),
        None,
    )
    assert lw_src is not None
    assert lw_src["status"] == "not_run"
    assert lw_src["score"] == 0


def test_grouped_skill_confidence_uses_evidence_strength():
    """Group confidence should reflect evidence strength — strong GitHub + direct workflow = high."""
    wf = {
        "evidence_strength_score": 75,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 5000],
    }
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/example/repo",
        "evidence_files": ["src/app.js"],
    }
    result = _svc(wf=wf, gh=gh, kf_count=2).evaluate(
        "u1", "s1",
        claimed_skills=["JavaScript"],
        github_url="https://github.com/example/repo",
    )
    groups = result.grouped_skill_evidence or []
    fe_group = next((g for g in groups if g.category == "FRONTEND"), None)
    assert fe_group is not None
    # With strong GitHub file + direct workflow keyframes, confidence should be high or medium
    assert fe_group.confidence in ("high", "medium"), (
        f"Expected high or medium confidence for strong evidence group, got {fe_group.confidence}"
    )


def test_evidence_objects_have_provenance_fields():
    """All produced evidence objects must have provenance and evidence_kind fields."""
    wf = {
        "evidence_strength_score": 72,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Data Visualization"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [2000, 6000],
    }
    svc = _svc(wf=wf, kf_count=2)
    entries = svc._collect_all_evidence_skills(["Data Visualization"], wf, None)
    for entry in entries.values():
        for obj in entry.evidence_objects:
            # All evidence objects must have provenance set (non-empty string)
            assert obj.provenance, (
                f"Evidence object for '{entry.skill}' (type={obj.evidence_type}) missing provenance"
            )
            # evidence_kind should be set for recording keyframes
            if obj.evidence_type == "recording_keyframe":
                assert obj.evidence_kind != "", "Recording keyframe must have evidence_kind set"
                assert obj.trace_action != "", "Recording keyframe must have trace_action set"


# ── GitHub URL builder tests ───────────────────────────────────────────────────

def test_build_github_blob_url_file_only():
    """File-level blob URL has correct structure, no line anchor."""
    url = _build_github_blob_url(
        "https://github.com/tensorflow/tfjs-examples",
        "src/model.py",
    )
    assert url == "https://github.com/tensorflow/tfjs-examples/blob/main/src/model.py"
    assert "#L" not in url


def test_build_github_blob_url_with_single_line():
    """Single-line anchor uses #L{n} without dash."""
    url = _build_github_blob_url(
        "https://github.com/tensorflow/tfjs-examples",
        "src/model.py",
        line_start=42,
        line_end=42,
    )
    assert url is not None
    assert url.endswith("#L42")
    assert "-L" not in url


def test_build_github_blob_url_with_line_range():
    """Line-range anchor uses #L{start}-L{end} format."""
    url = _build_github_blob_url(
        "https://github.com/tensorflow/tfjs-examples",
        "src/model.py",
        line_start=10,
        line_end=25,
    )
    assert url is not None
    assert "#L10-L25" in url


def test_build_github_blob_url_invalid_repo_url():
    """Returns None for a non-GitHub URL."""
    url = _build_github_blob_url("https://example.com/foo/bar", "file.py")
    assert url is None


def test_build_github_blob_url_strips_leading_slash():
    """Leading slash in file_path is handled correctly."""
    url = _build_github_blob_url(
        "https://github.com/owner/repo",
        "/dir/file.ts",
    )
    assert url is not None
    assert "//dir" not in url
    assert "/dir/file.ts" in url


def test_github_evidence_file_level_has_file_path_and_blob_url():
    """File-level GitHub evidence sets file_path and a blob URL (no line numbers)."""
    gh = {
        "status": "success",
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "matched_claimed_skills": ["Machine Learning"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["TensorFlow.js"],
        "evidence_files": ["src/train.py"],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["Machine Learning"], None, gh)
    ml_entry = entries.get("machine learning")
    assert ml_entry is not None
    gh_objs = [o for o in ml_entry.evidence_objects if o.evidence_type == "github_file"]
    assert gh_objs, "Expected at least one github_file evidence object"
    file_obj = gh_objs[0]
    assert file_obj.file_path == "src/train.py"
    assert file_obj.github_url is not None
    assert "blob" in file_obj.github_url
    assert "src/train.py" in file_obj.github_url
    assert "#L" not in file_obj.github_url  # no fake line numbers


def test_github_evidence_no_fake_line_numbers():
    """line_start and line_end are always None on current GitHub evidence objects."""
    gh = {
        "status": "success",
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "matched_claimed_skills": ["TensorFlow.js"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["TensorFlow.js"],
        "evidence_files": ["src/index.js", "src/model.js"],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["TensorFlow.js"], None, gh)
    assert entries, "Expected at least one entry"
    for entry in entries.values():
        for obj in entry.evidence_objects:
            if obj.evidence_type == "github_file":
                assert obj.line_start is None, "Must not fake line_start"
                assert obj.line_end is None, "Must not fake line_end"


def test_github_evidence_repo_only_has_no_file_path():
    """When skill is matched but no evidence_files, file_path is absent on evidence object."""
    gh = {
        "status": "success",
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "matched_claimed_skills": ["TensorFlow.js"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": [],
        "evidence_files": [],  # no files
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["TensorFlow.js"], None, gh)
    tf_entry = entries.get("tensorflow.js")
    assert tf_entry is not None
    gh_objs = [o for o in tf_entry.evidence_objects if o.evidence_type == "github_file"]
    assert gh_objs, "Expected at least one github_file evidence object"
    repo_obj = gh_objs[0]
    assert repo_obj.file_path is None, "Repo-only evidence must not set file_path"
    assert repo_obj.github_url == "https://github.com/tensorflow/tfjs-examples"


# ── Transcript quote evidence (Project Defense NLP) ────────────────────────────

def test_transcript_quote_evidence_added_when_pd_has_transcript():
    """When project defense has a transcript mentioning a skill, transcript_quote evidence objects appear."""
    pd = {
        "analysis_status": "analyzed",
        "overall_score": 70,
        "transcript_text": (
            "I built a machine learning model using TensorFlow. "
            "I trained it on labelled data and deployed it as a FastAPI endpoint."
        ),
        "transcript_segments": [],
    }
    svc = _svc(pd=pd)
    entries = svc._collect_all_evidence_skills(
        ["Machine Learning", "TensorFlow", "FastAPI"], None, None, pd
    )
    ml_entry = entries.get("machine learning")
    assert ml_entry is not None
    tx_objs = [o for o in ml_entry.evidence_objects if o.evidence_type == "transcript_quote"]
    assert tx_objs, "Expected at least one transcript_quote evidence object for Machine Learning"
    obj = tx_objs[0]
    assert obj.recruiter_safe is True
    assert obj.evidence_kind == "direct_workflow"
    assert obj.text_snippet is not None and len(obj.text_snippet) > 0


def test_transcript_quote_has_no_fabricated_timestamps_when_no_segments():
    """Without segment timestamps, transcript_quote should not show fake timestamps."""
    pd = {
        "transcript_text": "I built a Python API with FastAPI for the backend.",
        "transcript_segments": [],
    }
    svc = _svc(pd=pd)
    entries = svc._collect_all_evidence_skills(["FastAPI"], None, None, pd)
    fastapi_entry = entries.get("fastapi")
    assert fastapi_entry is not None
    tx_objs = [o for o in fastapi_entry.evidence_objects if o.evidence_type == "transcript_quote"]
    assert tx_objs
    obj = tx_objs[0]
    # No timestamp when segments are empty
    assert obj.timestamp_seconds is None
    assert obj.line_range is None


def test_transcript_quote_uses_segment_timestamps_when_available():
    """When transcript_segments have start/end times, evidence objects include them."""
    pd = {
        "transcript_text": "I trained a TensorFlow model in the browser.",
        "transcript_segments": [
            {"start_time": 12.5, "end_time": 20.1, "text": "I trained a TensorFlow model in the browser."},
        ],
    }
    svc = _svc(pd=pd)
    entries = svc._collect_all_evidence_skills(["TensorFlow"], None, None, pd)
    tf_entry = entries.get("tensorflow")
    assert tf_entry is not None
    tx_objs = [o for o in tf_entry.evidence_objects if o.evidence_type == "transcript_quote"]
    assert tx_objs, "Expected transcript_quote from segment"
    obj = tx_objs[0]
    assert obj.timestamp_seconds == 12.5
    assert obj.line_range is not None
    assert "00:12" in obj.line_range  # 12.5s → 00:12


def test_no_transcript_evidence_when_pd_absent():
    """When pd is None, no transcript_quote evidence objects are added."""
    svc = _svc()
    entries = svc._collect_all_evidence_skills(["Python"], None, None, pd=None)
    py_entry = entries.get("python")
    if py_entry:
        tx_objs = [o for o in py_entry.evidence_objects if o.evidence_type == "transcript_quote"]
        assert tx_objs == [], "No transcript_quote when pd is absent"


def test_no_transcript_evidence_when_transcript_text_empty():
    """When transcript_text is empty, no transcript_quote evidence objects are added."""
    pd = {"transcript_text": "", "transcript_segments": []}
    svc = _svc(pd=pd)
    entries = svc._collect_all_evidence_skills(["Python"], None, None, pd)
    py_entry = entries.get("python")
    if py_entry:
        tx_objs = [o for o in py_entry.evidence_objects if o.evidence_type == "transcript_quote"]
        assert tx_objs == []


def test_transcript_quote_recruiter_safe_wording():
    """transcript_quote evidence must not use the word 'verified'."""
    pd = {
        "transcript_text": "I built a React frontend with TypeScript for this project.",
        "transcript_segments": [],
    }
    svc = _svc(pd=pd)
    entries = svc._collect_all_evidence_skills(["React", "TypeScript"], None, None, pd)
    for entry in entries.values():
        for obj in entry.evidence_objects:
            if obj.evidence_type == "transcript_quote":
                assert "verified" not in obj.short_summary.lower(), (
                    f"transcript_quote short_summary must not say 'verified': {obj.short_summary}"
                )


def test_project_defense_transcript_in_grouped_skill_evidence():
    """Grouped skill evidence should include transcript source label when pd has transcript."""
    pd = {
        "analysis_status": "analyzed",
        "overall_score": 65,
        "transcript_text": "I built a data visualization dashboard using JavaScript and D3.",
        "transcript_segments": [],
    }
    result = _svc(pd=pd).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["JavaScript", "Data Visualization"],
    )
    # At least one grouped skill should have "Transcript" in source_labels
    all_source_labels = [
        lbl
        for grp in result.grouped_skill_evidence
        for lbl in grp.source_labels
    ]
    assert "Transcript" in all_source_labels, (
        "Expected 'Transcript' in grouped skill evidence source labels when pd has transcript"
    )


def test_find_transcript_quotes_helper_with_segments():
    """_find_transcript_quotes returns segment-level quotes with timestamps."""
    from app.services.final_evidence_evaluator_service import _find_transcript_quotes

    segments = [
        {"start_time": 5.0, "end_time": 12.0, "text": "I trained a neural network."},
        {"start_time": 12.0, "end_time": 20.0, "text": "I used TensorFlow for the model."},
        {"start_time": 20.0, "end_time": 28.0, "text": "The accuracy was 97 percent."},
    ]
    results = _find_transcript_quotes("TensorFlow", "full transcript text", segments)
    assert results, "Expected at least one matching quote"
    q = results[0]
    assert q["has_timestamp"] is True
    assert q["start_time"] == 12.0
    assert "TensorFlow" in q["text"]


def test_find_transcript_quotes_helper_without_segments():
    """_find_transcript_quotes falls back to sentence splitting when no segments."""
    from app.services.final_evidence_evaluator_service import _find_transcript_quotes

    transcript = (
        "I built a REST API with FastAPI. "
        "The database is PostgreSQL. "
        "I deployed it on AWS."
    )
    results = _find_transcript_quotes("FastAPI", transcript, [])
    assert results, "Expected a matching sentence"
    q = results[0]
    assert q["has_timestamp"] is False
    assert "FastAPI" in q["text"]


def test_local_whisper_transcript_segments_have_required_fields():
    """TranscriptSegment dataclass has start_time, end_time, text (unit test)."""
    from app.services.transcription_service import TranscriptSegment
    seg = TranscriptSegment(start_time=1.5, end_time=4.2, text="Hello world")
    assert seg.start_time == 1.5
    assert seg.end_time == 4.2
    assert seg.text == "Hello world"
    assert seg.confidence is None  # optional field


# ── BUG 1: Qwen not_configured status ────────────────────────────────────────

def test_qwen_not_configured_scores_not_available_no_false_disabled_note():
    """When visual_reasoning_summary.status == 'not_configured', evaluator must:
    - Score as not_available (not missing, not pending)
    - NOT show 'VISUAL_REASONING_ENABLED=false' note (Qwen IS enabled, just packages missing)
    """
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "not_configured",
            "frames_analyzed": 0,
            "summary": "Qwen enabled but packages not installed.",
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    result = _svc(wf=wf).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Machine Learning"],
    )
    qwen_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning"),
        None,
    )
    assert qwen_src is not None
    assert qwen_src["status"] == "not_available", (
        f"not_configured Qwen must be not_available, got {qwen_src['status']}"
    )
    # Must NOT show the false "VISUAL_REASONING_ENABLED=false" note — Qwen IS enabled
    notes = qwen_src.get("notes") or ""
    assert "VISUAL_REASONING_ENABLED=false" not in notes, (
        "not_configured Qwen must not show VISUAL_REASONING_ENABLED=false "
        "(Qwen is enabled — packages just not installed)"
    )


def test_qwen_not_configured_does_not_reduce_score_vs_disabled():
    """Score with Qwen not_configured must be >= score with Qwen disabled (no extra penalty)."""
    base_wf: dict[str, Any] = {
        "evidence_strength_score": 68,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "navigate"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    wf_not_cfg = {**base_wf, "visual_reasoning_summary": {"status": "not_configured", "frames_analyzed": 0}}
    wf_disabled = {**base_wf, "visual_reasoning_summary": {"status": "disabled", "frames_analyzed": 0}}

    score_not_cfg = _svc(wf=wf_not_cfg).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    ).final_score
    score_disabled = _svc(wf=wf_disabled).evaluate(
        "u1", "s1", claimed_skills=["Machine Learning"]
    ).final_score

    assert score_not_cfg >= score_disabled, (
        "not_configured Qwen must not produce a lower score than disabled Qwen"
    )


def test_qwen_enabled_frames_analyzed_contributes_score():
    """When Qwen analyzes 2 frames successfully, score is > 0 and status is pass."""
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "provider": "qwen_vl",
            "frames_analyzed": 2,
            "supported_signals": ["machine learning"],
            "summary": "ML demo visible",
            "observations": [],
            "missing_claims": [],
            "limitations": [],
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 3000],
    }
    result = _svc(wf=wf, kf_count=2).evaluate(
        user_id="u1", session_id="s1",
        claimed_skills=["Machine Learning"],
    )
    qwen_src = next(
        (s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning"),
        None,
    )
    assert qwen_src is not None
    assert qwen_src["status"] == "pass", f"analyzed Qwen should be pass, got {qwen_src['status']}"
    assert qwen_src["score"] > 0, "Qwen analyzed must contribute a positive score"


# ── BUG 2: GitHub traceback — inferred skill uses evidence files ──────────────

def test_github_inferred_skill_with_evidence_files_shows_file_link():
    """When a claimed skill is in detected_stack (inferred from tech — not directly matched)
    but evidence_files are available, the evidence object must include file_path and a blob URL.

    Setup: claimed skill "TensorFlow.js" appears in detected_stack but NOT in
    matched_claimed_skills, so is_direct_match=False. The elif gh_stack: branch should
    produce a file-level evidence object using evidence_files.
    """
    gh = {
        "status": "success",
        "confidence_score": 0.75,
        "matched_claimed_skills": [],          # not directly matched
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["TensorFlow.js", "JavaScript"],
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "evidence_files": ["package.json", "README.md"],
    }
    svc = _svc(gh=gh)
    # "TensorFlow.js" is in detected_stack so it gets source="GitHub" as an inferred skill.
    # claimed_skills includes it so it also gets source="claimed".
    entries = svc._collect_all_evidence_skills(["TensorFlow.js"], None, gh)
    tf_entry = entries.get("tensorflow.js")
    assert tf_entry is not None
    assert "GitHub" in tf_entry.sources, "TensorFlow.js from detected_stack should have GitHub source"
    gh_objs = [o for o in tf_entry.evidence_objects if o.evidence_type == "github_file"]
    assert gh_objs, "Expected github_file evidence objects for stack-inferred skill"
    # At least one should have file_path set (file-level link, not repo-only)
    file_level = [o for o in gh_objs if o.file_path]
    assert file_level, (
        "Stack-inferred skill with evidence_files must produce file-level evidence (file_path set)"
    )
    obj = file_level[0]
    assert obj.file_path == "package.json"
    assert obj.github_url is not None
    assert "blob" in obj.github_url, f"Expected blob URL, got {obj.github_url}"
    assert "package.json" in obj.github_url
    # No fake line numbers
    assert obj.line_start is None
    assert obj.line_end is None


def test_github_inferred_skill_without_evidence_files_shows_repo_link():
    """When skill is in detected_stack but evidence_files is empty, repo-level link only."""
    gh = {
        "status": "success",
        "confidence_score": 0.60,
        "matched_claimed_skills": [],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["Python", "TensorFlow"],
        "repo_url": "https://github.com/example/ml-project",
        "evidence_files": [],          # no files
    }
    svc = _svc(gh=gh)
    # "Python" is in detected_stack — gets source="GitHub" as inferred
    entries = svc._collect_all_evidence_skills(["Python"], None, gh)
    py_entry = entries.get("python")
    assert py_entry is not None
    assert "GitHub" in py_entry.sources, "Python from detected_stack should have GitHub source"
    gh_objs = [o for o in py_entry.evidence_objects if o.evidence_type == "github_file"]
    assert gh_objs, "Expected at least one github_file evidence object"
    # No evidence_files → all should be repo-level (no file_path)
    assert all(o.file_path is None for o in gh_objs), (
        "Empty evidence_files → all GitHub evidence objects must be repo-level (file_path=None)"
    )


def test_github_evidence_build_blob_url_with_line_range():
    """_build_github_blob_url correctly generates #L fragment when line numbers provided."""
    url = _build_github_blob_url(
        "https://github.com/tensorflow/tfjs-examples",
        "src/index.js",
        line_start=42,
        line_end=58,
    )
    assert url is not None
    assert url == "https://github.com/tensorflow/tfjs-examples/blob/main/src/index.js#L42-L58"


def test_github_evidence_build_blob_url_file_only():
    """_build_github_blob_url without line numbers gives file URL with no #L fragment."""
    url = _build_github_blob_url(
        "https://github.com/tensorflow/tfjs-examples",
        "package.json",
    )
    assert url is not None
    assert "blob/main/package.json" in url
    assert "#L" not in url


def test_github_evidence_build_blob_url_invalid_repo():
    """_build_github_blob_url returns None for invalid repo URLs."""
    url = _build_github_blob_url("not-a-valid-url", "src/index.js")
    assert url is None


# ══════════════════════════════════════════════════════════════════════════════
# BUG FIX TESTS — Part C of the root-cause debugging task
# ══════════════════════════════════════════════════════════════════════════════


# ── Qwen status tests ─────────────────────────────────────────────────────────

def test_qwen_frames_exist_analyzed_status_not_pending():
    """frames exist + configured + Qwen result saved → score > 0, NOT pending."""
    wf = {
        "evidence_strength_score": 60,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "provider": "qwen_vl",
            "frames_analyzed": 2,
            "summary": "ML model visible",
            "observations": [],
            "supported_signals": ["Machine Learning"],
            "missing_claims": [],
            "limitations": [],
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 3000],
    }
    svc = _svc(wf=wf, kf_count=2)
    result = svc.evaluate(user_id="u1", session_id="s1", claimed_skills=["Machine Learning"])
    d = result.to_dict()
    breakdown = {b["key"]: b for b in d["evidence_source_breakdown"]}
    qwen_entry = breakdown.get("qwen_visual_reasoning")
    assert qwen_entry is not None
    assert qwen_entry["status"] == "pass", f"Expected pass, got {qwen_entry['status']}"
    assert qwen_entry["score"] > 0, "Qwen score must be > 0 when analyzed"


def test_qwen_frames_exist_failed_status_not_pending():
    """frames exist + configured + Qwen errors → failed/skipped, NOT pending."""
    wf = {
        "evidence_strength_score": 55,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "failed",
            "provider": "qwen_vl",
            "frames_analyzed": 0,
            "summary": "Qwen ran but failed",
            "observations": [],
            "supported_signals": [],
            "missing_claims": [],
            "limitations": ["inference error"],
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 3000],
    }
    svc = _svc(wf=wf, kf_count=2)
    result = svc.evaluate(user_id="u1", session_id="s1", claimed_skills=["Machine Learning"])
    d = result.to_dict()
    breakdown = {b["key"]: b for b in d["evidence_source_breakdown"]}
    qwen_entry = breakdown.get("qwen_visual_reasoning")
    assert qwen_entry is not None
    # "failed" status → goes to missing (score=20), NOT pending/not_run
    assert qwen_entry["status"] in ("missing", "not_run"), (
        f"Expected missing or not_run for failed Qwen, got {qwen_entry['status']}"
    )


def test_qwen_no_frames_status_not_run_not_pending_forever():
    """no frames (no video uploaded) → qwen status not_run, not pending indefinitely."""
    wf = {
        "evidence_strength_score": 40,
        "workflow_confidence": "partial",
        "visible_evidence_status": "partial",
        "demonstrated_actions": [],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    svc = _svc(wf=wf, kf_count=0)
    result = svc.evaluate(user_id="u1", session_id="s1", claimed_skills=["Machine Learning"])
    d = result.to_dict()
    breakdown = {b["key"]: b for b in d["evidence_source_breakdown"]}
    qwen_entry = breakdown.get("qwen_visual_reasoning")
    assert qwen_entry is not None
    assert qwen_entry["status"] in ("not_run", "not_available"), (
        f"No frames → qwen should be not_run, got {qwen_entry['status']}"
    )


def test_qwen_and_final_evaluator_agree_on_session_id():
    """final evaluator reads qwen status from the same session's wf row."""
    wf_analyzed = {
        "evidence_strength_score": 75,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["click", "type"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["TensorFlow.js"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "provider": "qwen_vl",
            "frames_analyzed": 3,
            "summary": "TF.js model demo visible",
            "observations": [],
            "supported_signals": ["TensorFlow.js"],
            "missing_claims": [],
            "limitations": [],
        },
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 3,
        "video_keyframe_timestamps_ms": [1000, 2000, 3000],
    }
    svc = _svc(wf=wf_analyzed, kf_count=3)
    result = svc.evaluate(user_id="u1", session_id="s1", claimed_skills=["TensorFlow.js"])
    d = result.to_dict()
    breakdown = {b["key"]: b for b in d["evidence_source_breakdown"]}
    qwen_entry = breakdown.get("qwen_visual_reasoning")
    assert qwen_entry["status"] == "pass"
    assert qwen_entry["score"] == 90  # min(90, 50 + 3*15) = 90


# ── GitHub deep evidence tests ────────────────────────────────────────────────

def test_github_skill_code_evidence_preferred_over_evidence_files():
    """When skill_code_evidence present, it is used instead of shallow evidence_files."""
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["TensorFlow.js"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript", "TensorFlow.js"],
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "evidence_files": ["README.md"],  # shallow — should be overridden by skill_code_evidence
        "skill_code_evidence": [
            {
                "skill": "TensorFlow.js",
                "file_path": "mnist/src/index.ts",
                "line_start": 42,
                "line_end": 55,
                "code_snippet": "const model = tf.sequential();",
                "github_url": "https://github.com/tensorflow/tfjs-examples/blob/master/mnist/src/index.ts#L42-L55",
                "reason": "Found 'tf.sequential' at line 42 — evidence for TensorFlow.js",
            }
        ],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["TensorFlow.js"], None, gh)
    tfjs = entries.get("tensorflow.js")
    assert tfjs is not None, "TensorFlow.js entry must exist"
    gh_objs = [e for e in tfjs.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1, "Must have at least one GitHub evidence object"
    # Must use the deep evidence (not README.md)
    deep = [e for e in gh_objs if e.file_path and e.file_path != "README.md"]
    assert len(deep) >= 1, (
        f"Expected deep code file evidence, got: {[e.file_path for e in gh_objs]}"
    )
    first = deep[0]
    assert first.file_path == "mnist/src/index.ts"
    assert first.line_start == 42
    assert first.line_end == 55
    assert first.code_snippet and "tf.sequential" in first.code_snippet


def test_github_skill_code_evidence_with_line_range_builds_exact_blob_url():
    """Evidence with file_path + line_start + line_end produces exact GitHub blob URL."""
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["Machine Learning"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/tensorflow/tfjs-examples",
        "evidence_files": [],
        "skill_code_evidence": [
            {
                "skill": "Machine Learning",
                "file_path": "mobilenet/src/index.js",
                "line_start": 10,
                "line_end": 20,
                "code_snippet": "await mobilenet.load()",
                "github_url": "https://github.com/tensorflow/tfjs-examples/blob/main/mobilenet/src/index.js#L10-L20",
                "reason": "Found 'mobilenet.load' at line 10",
            }
        ],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["Machine Learning"], None, gh)
    ml = entries.get("machine learning")
    assert ml is not None
    gh_objs = [e for e in ml.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1
    obj = gh_objs[0]
    assert obj.github_url is not None
    assert "#L10" in obj.github_url, f"Expected line anchor in URL, got: {obj.github_url}"
    assert obj.line_start == 10
    assert obj.line_end == 20


def test_github_evidence_falls_back_to_evidence_files_when_no_skill_code_evidence():
    """Without skill_code_evidence, evidence_files is used as before (no regression)."""
    gh = {
        "status": "success",
        "confidence_score": 0.8,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/example/repo",
        "evidence_files": ["src/index.js", "package.json"],
        # no skill_code_evidence key
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["JavaScript"], None, gh)
    js = entries.get("javascript")
    assert js is not None
    gh_objs = [e for e in js.evidence_objects if e.evidence_type == "github_file"]
    assert len(gh_objs) >= 1
    # Falls back to evidence_files
    assert any(e.file_path in ("src/index.js", "package.json") for e in gh_objs)
    # line_start should be None (no deep evidence)
    assert all(e.line_start is None for e in gh_objs)


def test_github_evidence_readme_only_shows_repo_level():
    """When only README.md is in evidence_files (no source files), show repo-level link.

    README mentions of skill terms are not code evidence — the button should say
    'Open GitHub repo', not 'Open GitHub file', so we must NOT pass file_path.
    """
    gh = {
        "status": "success",
        "confidence_score": 0.6,
        "matched_claimed_skills": ["Python"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["Python"],
        "github_url": "https://github.com/example/repo",
        "repo_url": "https://github.com/example/repo",
        "evidence_files": ["README.md"],
        # no skill_code_evidence
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["Python"], None, gh)
    py = entries.get("python")
    assert py is not None
    gh_objs = [e for e in py.evidence_objects if e.evidence_type == "github_file"]
    # Must still produce an evidence object (repo-level)
    assert len(gh_objs) >= 1, "Must have at least one github_file evidence object"
    # Must NOT use README.md as the file_path (would show wrong 'Open GitHub file' button)
    readme_objs = [o for o in gh_objs if o.file_path == "README.md"]
    assert len(readme_objs) == 0, (
        "README.md must not appear as a file-level evidence object. "
        "It should fall through to repo-level (no file_path)."
    )


def test_website_proof_single_repo_deep_github_evidence():
    """Website Proof using deep GitHub engine output shows correct line links.

    Given a single repo URL with skill_code_evidence (file_path + line_start + line_end),
    the grouped evidence must show 'Open GitHub lines' button (line_start set),
    not a repo-level or README fallback.
    """
    gh = {
        "status": "success",
        "confidence_score": 0.85,
        "matched_claimed_skills": ["Machine Learning", "JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/ml5js/ml5-library",
        "repo_url": "https://github.com/ml5js/ml5-library",
        "evidence_files": ["README.md", "package.json", "src/index.js"],
        "skill_code_evidence": [
            {
                "skill": "Machine Learning",
                "file_path": "src/NeuralNetwork/index.js",
                "line_start": 44,
                "line_end": 60,
                "code_snippet": "async train(optionsOrCallback, callback) {\n  await this.neuralNetworkData.loadData();",
                "github_url": "https://github.com/ml5js/ml5-library/blob/main/src/NeuralNetwork/index.js#L44-L60",
                "reason": "Found 'train(' at line 44 — evidence for Machine Learning",
            },
            {
                "skill": "JavaScript",
                "file_path": "src/index.js",
                "line_start": 12,
                "line_end": 18,
                "code_snippet": "export const imageClassifier = (modelOrOptions, optionsOrCb, cb) => {",
                "github_url": "https://github.com/ml5js/ml5-library/blob/main/src/index.js#L12-L18",
                "reason": "Found 'export ' at line 12 — evidence for JavaScript",
            },
        ],
    }
    svc = _svc(gh=gh)
    result = svc.evaluate("u1", "s1", claimed_skills=["Machine Learning", "JavaScript"])

    grouped = result.grouped_skill_evidence
    assert grouped, "grouped_skill_evidence must not be empty"

    all_ev_objs = [obj for g in grouped for sk in g.skills for obj in sk.evidence_objects]
    gh_file_objs = [o for o in all_ev_objs if o.evidence_type == "github_file"]
    assert gh_file_objs, "No github_file evidence objects found"

    # Machine Learning must point to real source file with line numbers
    ml_obj = next((o for o in gh_file_objs if "NeuralNetwork" in (o.file_path or "")), None)
    assert ml_obj is not None, "Expected NeuralNetwork source file for Machine Learning"
    assert ml_obj.line_start == 44
    assert ml_obj.line_end == 60
    assert ml_obj.github_url is not None
    assert "#L44" in ml_obj.github_url, f"Expected line anchor, got: {ml_obj.github_url}"

    # README.md must not appear as a file-level evidence object
    readme_objs = [o for o in gh_file_objs if o.file_path == "README.md"]
    assert len(readme_objs) == 0, "README.md must not appear as file-level evidence"


def test_website_proof_readme_fallback_only_when_no_source_code_evidence():
    """When GitHub analysis finds only README evidence (no source files), show repo-level link.

    This verifies Website Proof does not demote to README file links when no
    deep source code evidence is available — it falls back to repo-level only.
    """
    gh = {
        "status": "success",
        "confidence_score": 0.4,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/ml5js/ml5-library",
        "repo_url": "https://github.com/ml5js/ml5-library",
        "evidence_files": ["README.md", "package.json"],
        # no skill_code_evidence — simulates shallow-only scan result
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["JavaScript"], None, gh)
    js = entries.get("javascript")
    assert js is not None

    gh_objs = [e for e in js.evidence_objects if e.evidence_type == "github_file"]
    assert gh_objs, "Must produce at least one github_file evidence object"

    # None of the objects should point to README.md or package.json as file_path
    bad_paths = {o.file_path for o in gh_objs if o.file_path in ("README.md", "package.json")}
    assert not bad_paths, (
        f"Generic meta files must not appear as file-level evidence: {bad_paths}"
    )


def test_single_repo_url_not_whole_profile():
    """Website Proof scans only the single repo URL, not all repos.

    The GitHub evidence for a session must come from one repo only.
    Verified by checking that github_url in evidence_objects matches the session repo.
    """
    session_repo = "https://github.com/ml5js/ml5-library"
    gh = {
        "status": "success",
        "confidence_score": 0.8,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": session_repo,
        "repo_url": session_repo,
        "evidence_files": ["src/index.js"],
        "skill_code_evidence": [
            {
                "skill": "JavaScript",
                "file_path": "src/index.js",
                "line_start": 1,
                "line_end": 5,
                "code_snippet": "export const imageClassifier = ...",
                "github_url": f"{session_repo}/blob/main/src/index.js#L1-L5",
                "reason": "Found 'export ' at line 1 — evidence for JavaScript",
            }
        ],
    }
    svc = _svc(gh=gh)
    entries = svc._collect_all_evidence_skills(["JavaScript"], None, gh)
    js = entries.get("javascript")
    assert js is not None

    gh_objs = [e for e in js.evidence_objects if e.evidence_type == "github_file"]
    assert gh_objs

    # All GitHub evidence URLs must belong to the session repo (not other repos)
    for obj in gh_objs:
        if obj.github_url:
            assert obj.github_url.startswith(session_repo) or obj.github_url == session_repo, (
                f"Evidence URL {obj.github_url!r} does not belong to session repo {session_repo!r}"
            )


# ── Task E tests ──────────────────────────────────────────────────────────────

def test_qwen_skipped_no_frames_not_penalty():
    """skipped_no_frames must score not_run, not missing — no penalty."""
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "strong",
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {"status": "skipped_no_frames", "frames_analyzed": 0},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Machine Learning"])
    qwen = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    assert qwen["status"] == "not_run", f"expected not_run, got {qwen['status']}"
    assert qwen["score"] == 0


def test_qwen_failed_not_pending():
    """failed Qwen status must score missing (partial penalty), not pending/not_run."""
    wf = {
        "evidence_strength_score": 60,
        "workflow_confidence": "moderate",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {"status": "failed", "frames_analyzed": 0},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 3,
        "video_keyframe_timestamps_ms": [1000, 5000, 9000],
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Python"])
    qwen = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    assert qwen["status"] == "missing", f"expected missing, got {qwen['status']}"


def test_qwen_analyzed_shows_in_final_evaluator():
    """Analyzed Qwen results must produce pass status with non-zero score."""
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "strong",
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "analyzed",
            "frames_analyzed": 2,
            "supported_signals": ["JavaScript"],
            "provider": "qwen_vl",
        },
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [2000, 8000],
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["JavaScript"])
    qwen = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    assert qwen["status"] == "pass", f"expected pass, got {qwen['status']}"
    assert qwen["score"] > 0


def test_skill_code_evidence_maps_to_grouped_evidence():
    """skill_code_evidence items must appear as github_file evidence_objects in grouped evidence."""
    gh = {
        "status": "success",
        "confidence_score": 0.8,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/ml5js/ml5-library",
        "repo_url": "https://github.com/ml5js/ml5-library",
        "evidence_files": ["src/index.js"],
        "skill_code_evidence": [
            {
                "skill": "JavaScript",
                "file_path": "src/index.js",
                "line_start": 12,
                "line_end": 18,
                "code_snippet": "export function createClassifier() {",
                "github_url": "https://github.com/ml5js/ml5-library/blob/main/src/index.js#L12-L18",
                "reason": "Found 'export ' at line 12 — evidence for JavaScript",
            }
        ],
    }
    svc = _svc(gh=gh)
    result = svc.evaluate("u1", "s1", claimed_skills=["JavaScript"])

    grouped = result.grouped_skill_evidence
    assert grouped, "grouped_skill_evidence must not be empty"
    all_ev_objs = [obj for g in grouped for sk in g.skills for obj in sk.evidence_objects]
    gh_file_objs = [o for o in all_ev_objs if o.evidence_type == "github_file"]
    assert gh_file_objs, "No github_file evidence objects found in grouped evidence"
    src_obj = next((o for o in gh_file_objs if o.file_path == "src/index.js"), None)
    assert src_obj is not None, "src/index.js not found in github_file evidence objects"
    assert src_obj.line_start == 12
    assert "L12" in (src_obj.github_url or ""), "github_url must contain line anchor"
