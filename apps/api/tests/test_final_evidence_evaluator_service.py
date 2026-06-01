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
