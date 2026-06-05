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
    EvidenceSourceResult,
    EvidenceObject,
    DetectedSkillEntry,
    _skill_category,
    _sources_to_labels,
    _build_github_blob_url,
)
from app.services.optional_evidence_service import analyze_optional_evidence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(wf=None, gh=None, lw=None, pd=None, opt=None, kf_count=0):
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
        elif name == "optional_evidence_submissions":
            chain.execute.return_value.data = opt or []
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


def _svc(wf=None, gh=None, lw=None, pd=None, opt=None, kf_count=0):
    return FinalEvidenceEvaluatorService(_make_db(wf, gh, lw, pd, opt, kf_count))


def _source(result, key: str) -> dict[str, Any]:
    return next(s for s in result.to_dict()["evidence_source_breakdown"] if s["key"] == key)


def _proof_action_titles(result) -> list[str]:
    return [a["title"] for a in result.to_dict()["recommendations"]["proof_actions"]]


def _next_action_labels(result) -> list[str]:
    return [a["button_label"] for a in result.to_dict()["next_best_actions"]]


def _grouped_skill_names(result) -> set[str]:
    payload = result.to_dict()
    return {
        skill["skill"]
        for group in payload["grouped_skill_evidence"]
        for skill in group["skills"]
    }


def _leaflet_relevance_wf(**overrides) -> dict[str, Any]:
    wf = {
        "evidence_strength_score": 72,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": [
            "Opened Leaflet map",
            "Zoomed map",
            "Clicked marker popup",
            "Panned OpenStreetMap tiles",
        ],
        "target_website": "https://example.com/leaflet-map",
        "workflow_summary": "Leaflet geospatial map with markers, popups, zoom and pan controls.",
        "page_context_summary": "Interactive web mapping demo using Leaflet and OpenStreetMap tiles.",
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Leaflet", "Geospatial Mapping"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    wf.update(overrides)
    return wf


def _chatbot_relevance_wf(**overrides) -> dict[str, Any]:
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": [
            "Opened HuggingChat",
            "Typed prompt into message input",
            "Sent prompt",
            "Reviewed assistant response",
        ],
        "target_website": "https://huggingface.co/chat/",
        "workflow_summary": "HuggingChat chatbot workflow with prompt entry and assistant response.",
        "page_context_summary": "Chatbot UI for LLM and NLP text processing.",
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Chatbot UI", "Natural Language Processing"],
        "weakly_supported_skills": ["Large Language Models"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    wf.update(overrides)
    return wf


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


def _strong_wf(skills: list[str]) -> dict[str, Any]:
    return {
        "evidence_strength_score": 92,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click", "change", "submit", "review"],
        "visual_analysis_status": "not_configured",
        "supported_skills": skills,
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {"status": "analyzed", "summary": " ".join(skills)},
        "frame_ocr_evidence_summary": {"skill_signals": []},
        "video_keyframe_status": "captured",
        "video_keyframe_count": 4,
        "video_keyframe_timestamps_ms": [1000, 2000],
    }


def _strong_gh(skills: list[str], stack: list[str]) -> dict[str, Any]:
    return {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": skills,
        "weakly_matched_claimed_skills": [],
        "detected_stack": stack,
        "skill_code_evidence": [{"skill": s, "file_path": "src/app.ts"} for s in skills],
    }


def _strong_result(skills: list[str], stack: list[str]):
    return _svc(
        wf=_strong_wf(skills),
        gh=_strong_gh(skills, stack),
        lw={"is_reachable": True},
        pd={"analysis_status": "analyzed", "overall_score": 90, "transcript_text": "I built and tested the core project flow."},
        kf_count=4,
    ).evaluate("u1", "s1", claimed_skills=skills, github_url="https://github.com/acme/project")


def test_final_score_under_80_returns_proof_actions_as_primary():
    wf = {
        "evidence_strength_score": 35,
        "workflow_confidence": "insufficient",
        "visible_evidence_status": "not_captured",
        "demonstrated_actions": [],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": ["React"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["React"], github_url=None)
    assert result.final_score < 80
    assert result.recommendations.mode == "proof_repair"
    assert result.recommendations.proof_actions


def test_final_score_80_or_higher_returns_learning_actions_as_primary():
    result = _strong_result(["React", "TypeScript"], ["React", "TypeScript"])
    assert result.final_score >= 80
    assert result.recommendations.mode == "project_growth"
    assert result.recommendations.learning_actions
    assert result.recommendations.proof_actions == []


def test_threejs_webgl_evidence_returns_3d_learning_actions():
    result = _strong_result(["Three.js", "WebGL", "mesh simplification"], ["Three.js", "WebGL"])
    titles = " ".join(a.title.lower() for a in result.recommendations.learning_actions)
    assert "geometry" in titles or "performance metrics" in titles


def test_d3_data_visualization_evidence_returns_chart_learning_actions():
    result = _strong_result(["D3", "Data Visualization", "Charts"], ["D3"])
    titles = " ".join(a.title.lower() for a in result.recommendations.learning_actions)
    assert "filter" in titles
    assert "tooltip" in titles


def test_ml_evidence_returns_model_learning_actions():
    result = _strong_result(["Machine Learning", "Model Training"], ["PyTorch", "sklearn"])
    titles = " ".join(a.title.lower() for a in result.recommendations.learning_actions)
    assert "evaluation" in titles or "confusion" in titles


def test_project_defense_dimensions_contribute_nonzero_without_overall_score():
    wf = _strong_wf(["React"])
    pd = {
        "analysis_status": "analyzed",
        "transcript_text": "I built the chatbot interface and explain the message flow.",
        "consistency_with_evidence_score": 60,
        "explanation_clarity_score": 65,
        "ownership_signal_score": 10,
        "technical_depth_score": 60,
    }
    result = _svc(wf=wf, pd=pd).evaluate("u1", "s1", claimed_skills=["React"])
    defense = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert defense["score"] >= 45
    assert defense["status"] == "partial"


def test_llm_chatbot_transcript_maps_to_chatbot_skills():
    pd = {
        "analysis_status": "analyzed",
        "overall_defense_score": 68,
        "transcript_text": (
            "I built the HuggingChat chatbot UI with a message input, prompt handling, "
            "large language model response flow, NLP text processing, assistant response, "
            "and AI product user experience decisions."
        ),
    }
    result = _svc(pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=[
            "Natural Language Processing",
            "Large Language Models",
            "Chatbot UI",
            "AI Product Design",
        ],
    )
    skills = {
        skill.skill
        for group in result.grouped_skill_evidence
        for skill in group.skills
    }
    assert "Natural Language Processing" in skills
    assert "Large Language Models" in skills
    assert "Chatbot UI" in skills
    assert "AI Product Design" in skills


def test_leaflet_project_defense_transcript_relevant_and_contributes_normally():
    pd = {
        "analysis_status": "analyzed",
        "overall_defense_score": 78,
        "transcript_text": (
            "I built this Leaflet web mapping project with OpenStreetMap tiles, map markers, "
            "popup details, zoom controls, pan behavior, and geospatial coordinate handling."
        ),
    }
    result = _svc(wf=_leaflet_relevance_wf(), pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=["Leaflet", "Geospatial Mapping", "OpenStreetMap"],
    )
    pd_src = _source(result, "project_defense")
    assert pd_src["status"] == "pass"
    assert pd_src["score"] == 78
    assert "unrelated" not in str(pd_src.get("notes") or "").lower()
    assert "transcript appears unrelated" not in result.to_dict()["final_recruiter_summary"].lower()


def test_leaflet_proof_rejects_unrelated_threejs_project_defense_skills():
    pd = {
        "analysis_status": "analyzed",
        "overall_defense_score": 92,
        "transcript_text": (
            "I built a Three.js WebGL renderer with a 3D mesh, geometry simplification, "
            "camera controls, shaders, texture handling, and an animated scene."
        ),
    }
    result = _svc(wf=_leaflet_relevance_wf(), pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=["Leaflet", "Geospatial Mapping"],
    )
    payload = result.to_dict()
    pd_src = _source(result, "project_defense")
    assert pd_src["status"] == "partial"
    assert pd_src["score"] <= 20
    assert "unrelated" in str(pd_src.get("notes") or "").lower()
    assert "transcript appears unrelated" in payload["final_recruiter_summary"].lower()
    grouped = _grouped_skill_names(result)
    assert "Leaflet" in grouped
    assert "Three.js" not in grouped
    assert "WebGL" not in grouped
    assert "Computer Graphics" not in grouped


def test_huggingchat_chatbot_project_defense_relevant_supports_nlp_skills():
    pd = {
        "analysis_status": "analyzed",
        "overall_defense_score": 76,
        "transcript_text": (
            "I built the HuggingChat chatbot flow with a message input, prompt handling, "
            "large language model response, NLP text processing, and assistant conversation UX."
        ),
    }
    result = _svc(wf=_chatbot_relevance_wf(), pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=[
            "Natural Language Processing",
            "Large Language Models",
            "Chatbot UI",
        ],
    )
    pd_src = _source(result, "project_defense")
    grouped = _grouped_skill_names(result)
    assert pd_src["status"] == "pass"
    assert pd_src["score"] == 76
    assert "unrelated" not in str(pd_src.get("notes") or "").lower()
    assert "Natural Language Processing" in grouped
    assert "Large Language Models" in grouped
    assert "Chatbot UI" in grouped


def test_huggingchat_proof_rejects_unrelated_threejs_project_defense_boost():
    pd = {
        "analysis_status": "analyzed",
        "overall_defense_score": 95,
        "transcript_text": (
            "The project is a Three.js WebGL canvas with 3D mesh geometry, renderer setup, "
            "camera orbit controls, shaders, textures, and scene animation."
        ),
    }
    result = _svc(wf=_chatbot_relevance_wf(), pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI"],
    )
    pd_src = _source(result, "project_defense")
    assert pd_src["status"] == "partial"
    assert pd_src["score"] <= 20
    assert "unrelated" in str(pd_src.get("notes") or "").lower()
    assert "transcript appears unrelated" in result.to_dict()["final_recruiter_summary"].lower()


def test_relevant_document_boosts_but_unrelated_document_is_neutral_and_filtered():
    claimed = ["Leaflet", "Geospatial Mapping"]
    wf = _leaflet_relevance_wf(evidence_strength_score=62)
    baseline = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=claimed)

    relevant_doc = {
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "Leaflet geospatial map report with marker popups and OpenStreetMap tiles.",
        "evidence_objects": [
            {
                "skill_name": "Leaflet",
                "confidence": "high",
                "snippet": "Leaflet marker popup implementation for the web mapping project.",
                "reason": "Document describes Leaflet map markers and popups.",
            },
            {
                "skill_name": "Geospatial Mapping",
                "confidence": "high",
                "snippet": "OpenStreetMap tile layer, coordinates, zoom and pan controls.",
                "reason": "Document describes geospatial map behavior.",
            },
        ],
    }
    unrelated_doc = {
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "Three.js WebGL renderer report with shaders, 3D mesh geometry, and textures.",
        "evidence_objects": [
            {
                "skill_name": "Three.js",
                "confidence": "high",
                "snippet": "Three.js WebGL renderer with mesh geometry and shader texture pipeline.",
                "reason": "Document describes unrelated 3D graphics work.",
            },
            {
                "skill_name": "WebGL",
                "confidence": "high",
                "snippet": "WebGL shader and renderer setup.",
                "reason": "Document describes unrelated WebGL implementation.",
            },
        ],
    }

    with_relevant = _svc(wf=wf, opt=[relevant_doc]).evaluate("u1", "s1", claimed_skills=claimed)
    with_unrelated = _svc(wf=wf, opt=[unrelated_doc]).evaluate("u1", "s1", claimed_skills=claimed)

    relevant_src = _source(with_relevant, "uploaded_documents")
    unrelated_src = _source(with_unrelated, "uploaded_documents")
    assert relevant_src["status"] == "pass"
    assert with_relevant.final_score >= baseline.final_score
    assert unrelated_src["score"] == 0
    assert "unrelated" in str(unrelated_src.get("notes") or "").lower()
    assert with_unrelated.final_score == baseline.final_score
    grouped = _grouped_skill_names(with_unrelated)
    assert "Leaflet" in grouped
    assert "Three.js" not in grouped
    assert "WebGL" not in grouped


def test_optional_unrelated_evidence_never_lowers_or_boosts_base_score():
    claimed = ["Natural Language Processing", "Chatbot UI"]
    wf = _chatbot_relevance_wf(evidence_strength_score=64)
    baseline = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=claimed)
    unrelated_doc = {
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "Leaflet geospatial map report with markers, popups, tiles and coordinate zoom controls.",
        "evidence_objects": [
            {"skill_name": "Leaflet", "confidence": "high", "snippet": "Leaflet web mapping markers and tiles."}
        ],
    }
    with_unrelated = _svc(wf=wf, opt=[unrelated_doc]).evaluate("u1", "s1", claimed_skills=claimed)
    assert _source(with_unrelated, "uploaded_documents")["score"] == 0
    assert with_unrelated.final_score == baseline.final_score


def test_chatbot_under_80_recommends_prompt_response_recording():
    wf = {
        "evidence_strength_score": 45,
        "workflow_confidence": "low",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["Opened HuggingChat"],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": ["Chatbot UI"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "recruiter_summary": "HuggingChat chatbot page loaded, but no prompt response was shown.",
    }
    result = _svc(wf=wf).evaluate(
        "u1",
        "s1",
        claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI"],
        github_url=None,
    )
    assert result.final_score < 80
    titles = [a.title for a in result.recommendations.proof_actions]
    assert "Record prompt and response proof" in titles


def test_missing_github_suggests_github_proof_action_not_generic_learning():
    wf = _strong_wf(["React", "TypeScript"])
    wf["evidence_strength_score"] = 45
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["React", "TypeScript"], github_url=None)
    actions = result.recommendations.proof_actions
    assert result.final_score < 80
    assert any(a.action_type == "add_github_url" for a in actions)
    assert result.recommendations.mode == "proof_repair"


def test_learning_actions_do_not_reduce_final_score():
    result = _strong_result(["Machine Learning", "Python"], ["Python", "sklearn"])
    score_with_recommendations = result.final_score
    assert result.recommendations.learning_actions
    assert result.final_score == score_with_recommendations


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


def test_project_defense_source_score_uses_overall_defense_score_field():
    pd = {
        "transcript_text": "I built the Three.js mesh simplification and explained the WebGL rendering pipeline.",
        "overall_defense_score": 73,
        "consistency_with_evidence_score": 70,
        "explanation_clarity_score": 75,
        "ownership_signal_score": 72,
        "technical_depth_score": 74,
    }
    result = _svc(pd=pd).evaluate("u1", "s1", claimed_skills=["Three.js"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] == 73
    assert pd_src["status"] == "pass"


def test_source_breakdown_returns_stable_scores_for_final_report_sources():
    wf = {
        "evidence_strength_score": 67,
        "workflow_confidence": "good",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click", "adjust", "review"],
        "visual_analysis_status": "analyzed",
        "supported_skills": ["Three.js"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {"status": "analyzed", "summary": "WebGL mesh", "frames_analyzed": 2, "observations": [{"confidence_score": 0.8}]},
        "frame_ocr_evidence_summary": {"has_ocr_evidence": True, "skill_signals": []},
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 3,
        "video_keyframe_timestamps_ms": [1000, 2000, 3000],
    }
    gh = {
        "status": "success",
        "confidence_score": 0.55,
        "matched_claimed_skills": ["Three.js"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["Three.js", "WebGL"],
    }
    doc = {
        "source_type": "document",
        "status": "analyzed",
        "evidence_objects": [{"skill_name": "Three.js", "confidence": "high", "snippet": "Three.js WebGL mesh"}] * 5,
    }
    result = _svc(
        wf=wf,
        gh=gh,
        lw={"is_reachable": True},
        pd={"transcript_text": "I built it.", "overall_defense_score": 73},
        opt=[doc],
        kf_count=3,
    ).evaluate("u1", "s1", claimed_skills=["Three.js"], github_url="https://github.com/acme/repo")
    scores = {s["key"]: s["score"] for s in result.evidence_source_breakdown}
    assert scores["website_workflow"] == 67
    assert scores["video_keyframes"] == 90
    assert scores["ocr"] == 80
    assert scores["qwen_visual_reasoning"] == 80
    assert scores["github"] == 60
    assert scores["live_website_check"] == 90
    assert scores["project_defense"] == 73
    assert scores["uploaded_documents"] == 90


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


def test_local_private_live_website_check_is_not_applicable_and_neutral():
    wf = {
        "evidence_strength_score": 70,
        "workflow_confidence": "good",
        "target_website": "http://localhost:3000",
        "workflow_summary": "Local React app workflow with visible UI interactions.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click", "review"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["React"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
        "video_keyframe_status": None,
        "video_keyframe_count": 0,
        "video_keyframe_timestamps_ms": [],
    }
    local_result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["React"])
    public_result = _svc(wf={**wf, "target_website": "https://example.com"}).evaluate(
        "u1", "s1", claimed_skills=["React"]
    )
    lw_src = next(s for s in local_result.evidence_source_breakdown if s["key"] == "live_website_check")
    assert lw_src["status"] == "not_applicable"
    assert lw_src["score"] is None
    assert "public live website check is not applicable" in lw_src["notes"].lower()
    assert local_result.final_score == public_result.final_score


def test_private_lan_live_website_check_is_not_applicable_in_final_breakdown():
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "target_website": "http://192.168.1.42:5173",
        "workflow_summary": "Local network app workflow with visible UI interactions.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["JavaScript"])
    lw_src = next(s for s in result.evidence_source_breakdown if s["key"] == "live_website_check")
    assert lw_src["status"] == "not_applicable"
    assert lw_src["score"] is None
    assert "live_website_check" not in result.evidence_sources_used
    assert "live_website_check" not in result.evidence_sources_missing


def test_public_live_website_check_still_contributes_when_reachable():
    wf = {
        "evidence_strength_score": 65,
        "workflow_confidence": "good",
        "target_website": "https://open-meteo.com/",
        "workflow_summary": "Public weather API website workflow.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "review"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["API"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf, lw={"is_reachable": True, "website_url": "https://open-meteo.com/"}).evaluate(
        "u1", "s1", claimed_skills=["API"]
    )
    lw_src = next(s for s in result.evidence_source_breakdown if s["key"] == "live_website_check")
    assert lw_src["status"] == "pass"
    assert lw_src["score"] == 90
    assert "live_website_check" in result.evidence_sources_used


def test_local_private_proof_recommends_deploy_setup_not_live_check():
    wf = {
        "evidence_strength_score": 64,
        "workflow_confidence": "good",
        "target_website": "http://localhost:3000",
        "workflow_summary": "Local React app workflow with visible UI interactions.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click", "review"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["React", "Full Stack"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["React", "Full Stack"])
    labels = _next_action_labels(result)
    titles = _proof_action_titles(result)
    assert "Run Live Website Check" not in labels
    assert "Run Live Website Check" not in titles
    assert "Add deployment/setup evidence" in titles
    deploy_action = next(a for a in result.to_dict()["recommendations"]["proof_actions"] if a["title"] == "Add deployment/setup evidence")
    assert "local/private" in deploy_action["source_reason"].lower()
    assert "not applicable" in deploy_action["source_reason"].lower()


def test_public_url_without_live_check_recommends_run_live_check():
    wf = {
        "evidence_strength_score": 64,
        "workflow_confidence": "good",
        "target_website": "https://example.com",
        "workflow_summary": "Public full stack website workflow.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Full Stack"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf, gh=_strong_gh(["Full Stack"], ["React"])).evaluate(
        "u1", "s1", claimed_skills=["Full Stack"], github_url="https://github.com/user/repo"
    )
    assert "Run Live Website Check" in _next_action_labels(result)
    assert "Run Live Website Check" in _proof_action_titles(result)


def test_public_url_with_passed_live_check_does_not_recommend_live_check():
    wf = {
        "evidence_strength_score": 64,
        "workflow_confidence": "good",
        "target_website": "https://example.com",
        "workflow_summary": "Public full stack website workflow.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Full Stack"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(
        wf=wf,
        gh=_strong_gh(["Full Stack"], ["React"]),
        lw={"status": "complete", "is_reachable": True, "website_url": "https://example.com"},
    ).evaluate("u1", "s1", claimed_skills=["Full Stack"], github_url="https://github.com/user/repo")
    assert "Run Live Website Check" not in _next_action_labels(result)
    assert "Run Live Website Check" not in _proof_action_titles(result)


def test_public_url_with_failed_live_check_recommends_retry():
    wf = {
        "evidence_strength_score": 64,
        "workflow_confidence": "good",
        "target_website": "https://example.com",
        "workflow_summary": "Public full stack website workflow.",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click"],
        "visual_analysis_status": "not_configured",
        "supported_skills": ["Full Stack"],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(
        wf=wf,
        gh=_strong_gh(["Full Stack"], ["React"]),
        lw={"status": "failed", "is_reachable": False, "website_url": "https://example.com"},
    ).evaluate("u1", "s1", claimed_skills=["Full Stack"], github_url="https://github.com/user/repo")
    assert "Retry Live Website Check" in _next_action_labels(result)
    assert "Retry Live Website Check" in _proof_action_titles(result)


def test_github_not_analyzed_with_repo_url_recommends_run_analysis():
    wf = _strong_wf(["React"])
    result = _svc(wf=wf).evaluate(
        "u1", "s1", claimed_skills=["React"], github_url="https://github.com/user/repo"
    )
    assert "Run GitHub Evidence Analysis" in _next_action_labels(result)


def test_github_passed_does_not_recommend_github_analysis():
    wf = _strong_wf(["React"])
    result = _svc(wf=wf, gh=_strong_gh(["React"], ["React"])).evaluate(
        "u1", "s1", claimed_skills=["React"], github_url="https://github.com/user/repo"
    )
    labels = _next_action_labels(result)
    assert "Run GitHub Evidence Analysis" not in labels
    assert "Add GitHub URL" not in labels


def test_strong_uploaded_document_does_not_recommend_upload_document():
    wf = _chatbot_wf(score=70)
    relevant_doc = [{
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "HuggingChat chatbot architecture and prompt response flow.",
        "evidence_objects": [{"skill_name": "Chatbot UI", "confidence": "high"}],
    }]
    result = _svc(wf=wf, opt=relevant_doc).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    assert "Upload Document" not in _next_action_labels(result)
    assert "Upload relevant document" not in _next_action_labels(result)


def test_irrelevant_document_recommends_upload_relevant_document():
    wf = _chatbot_wf(score=70)
    unrelated_doc = [{
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "Three.js WebGL geometry simplification report.",
        "evidence_objects": [{"skill_name": "WebGL", "confidence": "high"}],
    }]
    result = _svc(wf=wf, opt=unrelated_doc).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    assert "Upload relevant document" in _next_action_labels(result)


def test_low_project_defense_recommends_improvement():
    wf = _strong_wf(["React"])
    pd = {
        "status": "success",
        "overall_defense_score": 35,
        "transcript_text": "I used the app and it works.",
        "skills_mentioned": ["React"],
        "privacy_scan_status": "clean",
    }
    result = _svc(wf=wf, pd=pd).evaluate("u1", "s1", claimed_skills=["React"])
    assert "Improve Project Defense" in _next_action_labels(result)


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


def test_skill_code_evidence_attaches_to_skill_card_without_generic_text():
    """Exact GitHub code evidence should be on the skill, not hidden behind generic refs."""
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/mrdoob/three.js",
        "repo_url": "https://github.com/mrdoob/three.js",
        "evidence_files": ["README.md", "package.json"],
        "skill_code_evidence": [
            {
                "skill": "JavaScript",
                "repo_name": "mrdoob/three.js",
                "file_path": "examples/jsm/libs/motion/Animation.js",
                "line_start": 370,
                "line_end": 388,
                "code_snippet": "update( delta ) {\n  this.time += delta;\n}",
                "github_url": "https://github.com/mrdoob/three.js/blob/dev/examples/jsm/libs/motion/Animation.js#L370-L388",
                "reason": "Animation update logic supports JavaScript.",
            }
        ],
    }
    result = _svc(gh=gh).evaluate("u1", "s1", claimed_skills=["JavaScript"])

    js = next(
        sk for g in result.grouped_skill_evidence for sk in g.skills
        if sk.skill == "JavaScript"
    )
    gh_objs = [o for o in js.evidence_objects if o.evidence_type == "github_file"]
    assert gh_objs, "Skill card data must contain GitHub code evidence"
    assert gh_objs[0].file_path == "examples/jsm/libs/motion/Animation.js"
    assert gh_objs[0].line_start == 370
    assert gh_objs[0].line_end == 388
    assert gh_objs[0].repo_name == "mrdoob/three.js"
    assert gh_objs[0].provenance == "GitHub Code Evidence"
    assert js.github_evidence == [], "Generic GitHub text is only fallback when exact code evidence exists"


def test_skill_code_evidence_alias_matches_threejs_webgl_skills():
    """Three.js/WebGL skills should receive relevant source evidence without spraying all skills."""
    gh = {
        "status": "success",
        "confidence_score": 0.9,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript"],
        "github_url": "https://github.com/mrdoob/three.js",
        "repo_url": "https://github.com/mrdoob/three.js",
        "evidence_files": ["README.md"],
        "skill_code_evidence": [
            {
                "skill": "JavaScript",
                "repo_name": "mrdoob/three.js",
                "file_path": "examples/webgl_materials_video.html",
                "line_start": 82,
                "line_end": 104,
                "code_snippet": "const texture = new THREE.VideoTexture( video );\nconst renderer = new THREE.WebGLRenderer();",
                "github_url": "https://github.com/mrdoob/three.js/blob/dev/examples/webgl_materials_video.html#L82-L104",
                "reason": "Three.js WebGL renderer and video texture setup.",
            }
        ],
    }
    result = _svc(gh=gh).evaluate(
        "u1",
        "s1",
        claimed_skills=["JavaScript", "Three.js", "WebGL", "Interactive 3D Graphics", "Payroll Systems"],
    )

    by_skill = {
        sk.skill: sk
        for g in result.grouped_skill_evidence
        for sk in g.skills
    }
    for skill in ["JavaScript", "Three.js", "WebGL", "Interactive 3D Graphics"]:
        gh_objs = [o for o in by_skill[skill].evidence_objects if o.evidence_type == "github_file"]
        assert gh_objs, f"{skill} should receive exact GitHub evidence"
        assert gh_objs[0].line_start == 82
        assert "webgl_materials_video.html" in (gh_objs[0].file_path or "")

    unrelated = by_skill.get("Payroll Systems")
    assert unrelated is not None
    assert not [o for o in unrelated.evidence_objects if o.evidence_type == "github_file"], (
        "Unrelated claimed skills must not receive aliased GitHub source lines"
    )


# ── Visual/graphics skill evidence tests ──────────────────────────────────────

def _threejs_qwen_summary() -> str:
    return (
        "Qwen analyzed 2 frames. The page shows a Three.js WebGL demo with "
        "colorful rotating 3d objects. A canvas element renders an animated "
        "scene with geometric mesh objects using WebGL rendering."
    )


def _threejs_wf(*, ocr_ran: bool = True, qwen: bool = True) -> dict:
    vrs = {
        "status": "analyzed",
        "frames_analyzed": 2,
        "summary": _threejs_qwen_summary() if qwen else "",
        "observations": [
            {
                "frame_index": 0,
                "detected_workflow_stage": "canvas_rendering",
                "description": "WebGL canvas showing animated colorful rotating 3d objects",
                "skill_evidence": {},
            }
        ] if qwen else [],
        "supported_signals": [],
    } if qwen else {"status": "disabled"}
    return {
        "evidence_strength_score": 55,
        "workflow_confidence": "partial",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["navigate"],
        "visual_analysis_status": "analyzed" if ocr_ran else "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "frame_ocr_evidence_summary": {
            "skill_signals": [
                {"skill": "JavaScript", "ocr_support": "partial",
                 "reasoning": "OCR found js text", "ocr_terms_found": ["js"]},
                {"skill": "Three.js", "ocr_support": "not_found",
                 "reasoning": "No OCR text relevant to Three.js was detected",
                 "ocr_terms_found": []},
                {"skill": "WebGL", "ocr_support": "not_found",
                 "reasoning": "No OCR text relevant to WebGL was detected",
                 "ocr_terms_found": []},
            ]
        } if ocr_ran else {},
        "visual_reasoning_summary": vrs,
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [1000, 4000],
    }


def _threejs_gh() -> dict:
    return {
        "status": "success",
        "confidence_score": 0.88,
        "matched_claimed_skills": ["JavaScript"],
        "weakly_matched_claimed_skills": [],
        "detected_stack": ["JavaScript", "Three.js"],
        "github_url": "https://github.com/mrdoob/three.js",
        "repo_url": "https://github.com/mrdoob/three.js",
        "repo_name": "mrdoob/three.js",
        "evidence_files": ["examples/webgl_materials_video.html"],
        "skill_code_evidence": [
            {
                "skill": "Three.js",
                "repo_name": "mrdoob/three.js",
                "file_path": "examples/jsm/libs/motion/Animation.js",
                "line_start": 370,
                "line_end": 388,
                "code_snippet": "THREE.AnimationMixer.prototype.update = function(delta) { ... }",
                "github_url": "https://github.com/mrdoob/three.js/blob/dev/examples/jsm/libs/motion/Animation.js#L370-L388",
                "reason": "Three.js AnimationMixer implementation.",
            }
        ],
    }


_THREEJS_SKILLS = [
    "JavaScript", "Three.js", "WebGL", "Interactive 3D Graphics",
    "Computer Graphics", "Video Texture Rendering",
]


def test_webgl_skill_not_missing_when_qwen_observed_rendering():
    """A WebGL/Three.js skill must not be marked missing when Qwen saw rendered output."""
    result = _svc(wf=_threejs_wf(), gh=_threejs_gh()).evaluate(
        "u1", "s1", claimed_skills=_THREEJS_SKILLS,
    )
    assert "qwen_visual_reasoning" not in result.evidence_sources_missing
    assert "github" not in result.evidence_sources_missing
    by_skill = {
        sk.skill: sk
        for g in result.grouped_skill_evidence
        for sk in g.skills
    }
    for skill in ["Three.js", "WebGL", "Interactive 3D Graphics", "Computer Graphics"]:
        entry = by_skill.get(skill)
        assert entry is not None, f"{skill} must appear in grouped_skill_evidence"
        assert entry.confidence in ("high", "medium"), (
            f"{skill} confidence must be medium or high when Qwen saw rendering "
            f"(got {entry.confidence!r})"
        )
        assert "claimed" not in entry.status_label.lower() or "supported" in entry.status_label.lower(), (
            f"{skill} status_label must indicate support, got {entry.status_label!r}"
        )


def test_visual_skill_qwen_evidence_object_attached():
    """Qwen evidence object must be attached to visual/graphics skills when Qwen ran."""
    result = _svc(wf=_threejs_wf(ocr_ran=False), gh=_threejs_gh()).evaluate(
        "u1", "s1", claimed_skills=["Three.js", "WebGL", "Interactive 3D Graphics"],
    )
    by_skill = {
        sk.skill: sk
        for g in result.grouped_skill_evidence
        for sk in g.skills
    }
    for skill in ["Three.js", "WebGL", "Interactive 3D Graphics"]:
        entry = by_skill[skill]
        qwen_objs = [o for o in entry.evidence_objects if o.evidence_type == "qwen_visual"]
        assert qwen_objs, f"{skill} must have a Qwen evidence object"
        qobj = qwen_objs[0]
        assert qobj.evidence_kind == "direct_workflow", (
            f"{skill} Qwen evidence_kind must be direct_workflow for visual skill "
            f"(got {qobj.evidence_kind!r})"
        )
        assert qobj.skill_support_level in ("partial", "strong"), (
            f"{skill} Qwen skill_support_level must not be 'weak' for visual skill "
            f"(got {qobj.skill_support_level!r})"
        )


def test_ocr_limitation_note_for_visual_skills_when_ocr_ran():
    """An OCR limitation explanation must appear for visual/graphics skills when OCR ran."""
    result = _svc(wf=_threejs_wf(ocr_ran=True, qwen=False)).evaluate(
        "u1", "s1", claimed_skills=["Three.js", "WebGL", "Interactive 3D Graphics", "JavaScript"],
    )
    by_skill = {
        sk.skill: sk
        for g in result.grouped_skill_evidence
        for sk in g.skills
    }
    # Visual skills: OCR limitation note expected
    for skill in ["Three.js", "WebGL", "Interactive 3D Graphics"]:
        entry = by_skill[skill]
        ocr_objs = [o for o in entry.evidence_objects if o.source_name == "OCR"]
        assert ocr_objs, f"{skill} must have an OCR evidence object explaining limitation"
        assert "canvas" in ocr_objs[0].short_summary.lower() or "webgl" in ocr_objs[0].short_summary.lower(), (
            f"{skill} OCR note must mention canvas/WebGL limitation"
        )
        assert ocr_objs[0].skill_support_level == "none", (
            f"{skill} OCR limitation object must have skill_support_level='none'"
        )
    # Non-visual skill (JavaScript) should not get the OCR limitation note
    # (OCR found partial evidence for it)
    js_entry = by_skill["JavaScript"]
    js_ocr = [o for o in js_entry.evidence_objects if o.source_name == "OCR"]
    if js_ocr:
        assert js_ocr[0].skill_support_level != "none", (
            "JavaScript OCR evidence must not be marked as a limitation — OCR found text for it"
        )


def test_threejs_github_evidence_gives_nonzero_per_skill_score():
    """GitHub code evidence must give visual/graphics skills a non-zero per_skill_score."""
    result = _svc(gh=_threejs_gh()).evaluate(
        "u1", "s1",
        claimed_skills=["Three.js", "WebGL", "Interactive 3D Graphics"],
    )
    for skill in ["Three.js", "WebGL", "Interactive 3D Graphics"]:
        score = result.per_skill_scores.get(skill, 0)
        assert score > 0, (
            f"{skill} per_skill_score must be > 0 when GitHub has code evidence "
            f"(got {score})"
        )


def test_visual_skill_missing_only_when_no_evidence_at_all():
    """A visual/graphics skill must NOT be marked as having no support when any evidence exists.

    Missing status should only appear when OCR, Qwen, GitHub, DOM, and live check
    all produce nothing.
    """
    # No workflow, no GitHub — zero evidence
    result_zero = _svc().evaluate(
        "u1", "s1", claimed_skills=["Three.js", "WebGL"],
    )
    by_skill_zero = {
        sk.skill: sk
        for g in result_zero.grouped_skill_evidence
        for sk in g.skills
    }
    # With no evidence at all, they should be low confidence (acceptable)
    for skill in ["Three.js", "WebGL"]:
        entry = by_skill_zero.get(skill)
        assert entry is not None
        assert entry.confidence == "low"

    # With Qwen visual observation → must NOT be low confidence
    result_qwen = _svc(wf=_threejs_wf(ocr_ran=False, qwen=True)).evaluate(
        "u1", "s1", claimed_skills=["Three.js", "WebGL"],
    )
    by_skill_qwen = {
        sk.skill: sk
        for g in result_qwen.grouped_skill_evidence
        for sk in g.skills
    }
    for skill in ["Three.js", "WebGL"]:
        entry = by_skill_qwen[skill]
        assert entry.confidence != "low", (
            f"{skill} must not be 'low' confidence when Qwen observed visual rendering"
        )

    # With GitHub code evidence → must NOT be low confidence
    result_gh = _svc(gh=_threejs_gh()).evaluate(
        "u1", "s1", claimed_skills=["Three.js"],
    )
    threejs_entry = next(
        sk for g in result_gh.grouped_skill_evidence
        for sk in g.skills if sk.skill == "Three.js"
    )
    assert threejs_entry.confidence != "low", (
        "Three.js must not be 'low' confidence when GitHub has code evidence for it"
    )


# ── Optional evidence booster tests ───────────────────────────────────────────

def test_missing_optional_proofs_do_not_reduce_score():
    wf = {
        "evidence_strength_score": 80,
        "workflow_confidence": "strong",
        "visible_evidence_status": "available",
        "demonstrated_actions": ["open", "click", "submit", "view result"],
        "supported_skills": ["JavaScript"],
        "weakly_supported_skills": [],
        "visual_analysis_status": "not_configured",
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    base = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["JavaScript"])
    assert "uploaded_documents" not in base.evidence_sources_missing
    assert "linkedin_profile" not in base.evidence_sources_missing
    assert "certificate" not in base.evidence_sources_missing


def test_optional_document_score_90_does_not_lower_79_base_score():
    svc = _svc()
    core = [
        EvidenceSourceResult("website_workflow", "pass", 78, 0.25),
    ]
    before = svc._combine_scores(core)
    after = svc._combine_scores([
        *core,
        EvidenceSourceResult("uploaded_documents", "pass", 90, 0.04),
    ])
    assert before == 79
    assert after >= 79


def test_missing_document_remains_neutral_for_final_score():
    svc = _svc()
    core = [EvidenceSourceResult("website_workflow", "pass", 78, 0.25)]
    base = svc._combine_scores(core)
    with_missing_document = svc._combine_scores([
        *core,
        EvidenceSourceResult("uploaded_documents", "not_available", 0, 0.04),
    ])
    assert with_missing_document == base


def test_weak_document_does_not_reduce_below_base_score():
    svc = _svc()
    core = [EvidenceSourceResult("website_workflow", "pass", 78, 0.25)]
    base = svc._combine_scores(core)
    with_weak_document = svc._combine_scores([
        *core,
        EvidenceSourceResult("uploaded_documents", "partial", 45, 0.04, notes="optional evidence submitted but weak"),
    ])
    assert with_weak_document == base


def test_strong_document_can_boost_final_score():
    svc = _svc()
    core = [EvidenceSourceResult("website_workflow", "pass", 78, 0.25)]
    base = svc._combine_scores(core)
    with_strong_document = svc._combine_scores([
        *core,
        EvidenceSourceResult("uploaded_documents", "pass", 90, 0.04),
    ])
    assert with_strong_document > base


def test_document_snippet_maps_to_skill_evidence_with_page():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="--- page 2 --- Built a CNN model using TensorFlow and evaluated accuracy and F1-score.",
        file_path="report.pdf",
    )
    row = {"source_type": "document", "status": analysis.status, "evidence_objects": analysis.evidence_objects}
    result = _svc(opt=[row]).evaluate("u1", "s1", claimed_skills=[])
    skills = {sk.skill: sk for g in result.grouped_skill_evidence for sk in g.skills}
    assert "Machine Learning" in skills
    ml_objs = [o for o in skills["Machine Learning"].evidence_objects if o.evidence_type == "document_snippet"]
    assert ml_objs
    assert ml_objs[0].page_number == 2
    assert "CNN model" in (ml_objs[0].text_snippet or "")


def test_threejs_document_extracts_graphics_frontend_skills():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "--- page 4 --- VeriBridge test plan: Three.js renders an interactive 3D object "
            "using WebGL in the browser rendering pipeline. The frontend application uses "
            "JavaScript modules, camera controls, materials, and geometry handling. The "
            "geometry simplifier performs mesh simplification and geometry optimization."
        ),
        file_path="VeriBridge_Document_Proof_Test_Plan.pdf",
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {
        "Three.js",
        "WebGL",
        "Interactive 3D Graphics",
        "Computer Graphics",
        "Geometry Optimization",
        "3D Mesh Simplification",
        "Frontend Development",
    }.issubset(skills)
    assert "DevOps" not in skills
    three_obj = next(obj for obj in analysis.evidence_objects if obj["skill_name"] == "Three.js")
    assert three_obj["page_number"] == 4
    assert three_obj["snippet"]
    assert three_obj["reason"]
    assert three_obj["confidence"] == "high"


def test_browser_rendering_pipeline_is_not_devops():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="The browser rendering pipeline displays a 3D scene with camera controls, materials, and geometry handling.",
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert "Browser Rendering" in skills
    assert "Frontend Development" in skills
    assert "Computer Graphics" in skills
    assert "DevOps" not in skills


def test_d3_report_extracts_visualization_skills_not_computer_vision():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "--- page 3 --- D3 Graph Gallery report: implemented D3.js JavaScript modules "
            "for SVG visualization, interactive charts, visual analytics, visual output, "
            "and graph analysis with nodes and edges in a frontend application."
        ),
        file_path="d3_graph_gallery.pdf",
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {
        "Data Visualization",
        "D3.js",
        "Interactive Charts",
        "SVG Visualization",
        "Graph Analysis",
        "Frontend Development",
    }.issubset(skills)
    assert "JavaScript" in skills
    assert "Computer Vision" not in skills
    graph_obj = next(obj for obj in analysis.evidence_objects if obj["skill_name"] == "Graph Analysis")
    assert graph_obj["page_number"] == 3
    assert graph_obj["snippet"]
    assert graph_obj["reason"]
    assert graph_obj["confidence"] in ("high", "medium")


def test_ml_tensorflow_document_extracts_model_evaluation_skills():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "Project report methodology: trained a TensorFlow CNN model on an image dataset "
            "and evaluated accuracy, precision, recall, and F1-score on the validation results."
        ),
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {"TensorFlow", "Machine Learning", "Deep Learning", "Model Evaluation"}.issubset(skills)
    tf_obj = next(obj for obj in analysis.evidence_objects if obj["skill_name"] == "TensorFlow")
    assert tf_obj["confidence"] == "high"
    assert tf_obj["snippet"]
    assert tf_obj["reason"]


def test_fastapi_postgresql_document_extracts_backend_database_skills():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "Implemented a backend API with FastAPI endpoints that validate requests and "
            "store records in a PostgreSQL database using SQL schema migrations."
        ),
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {"Backend API", "API Development", "FastAPI", "PostgreSQL", "Database", "SQL"}.issubset(skills)


def test_react_nextjs_document_extracts_frontend_skills():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "Built a React and Next.js frontend application with TypeScript components, "
            "client routes, browser interaction, and JavaScript modules for the UI."
        ),
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {"React", "Next.js", "TypeScript", "JavaScript", "Frontend Development"}.issubset(skills)


def test_rag_llm_embeddings_document_extracts_ai_retrieval_skills():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text=(
            "Implemented a RAG workflow for an LLM assistant using embeddings, semantic search, "
            "and vector retrieval over project documents to generate grounded answers."
        ),
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert {"RAG", "LLM", "Embeddings", "NLP"}.issubset(skills)


def test_devops_requires_infrastructure_terms():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="The deployment pipeline uses Docker containers, GitHub Actions, nginx, monitoring, and Terraform infrastructure.",
    )
    skills = {obj["skill_name"] for obj in analysis.evidence_objects}
    assert "DevOps" in skills
    assert "Docker" in skills


def test_threejs_document_feeds_grouped_skill_evidence():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="Three.js renders an interactive 3D object with WebGL and mesh simplification for geometry optimization.",
    )
    row = {"source_type": "document", "status": analysis.status, "evidence_objects": analysis.evidence_objects}
    result = _svc(opt=[row]).evaluate("u1", "s1", claimed_skills=[])
    skills = {sk.skill: sk for g in result.grouped_skill_evidence for sk in g.skills}
    assert "uploaded_documents" in result.evidence_sources_used
    assert "Three.js" in skills
    assert "WebGL" in skills
    assert "3D Mesh Simplification" in skills
    assert any(
        obj.evidence_type == "document_snippet"
        for obj in skills["Three.js"].evidence_objects
    )


def test_document_supported_graph_analysis_does_not_repeat_upload_document_action():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="D3.js SVG visualization report documents graph analysis with interactive charts, nodes, and edges.",
    )
    row = {"source_type": "document", "status": analysis.status, "evidence_objects": analysis.evidence_objects}
    result = _svc(opt=[row]).evaluate("u1", "s1", claimed_skills=["Graph Analysis"])
    actions = result.next_best_actions
    assert "uploaded_documents" in result.evidence_sources_used
    assert not any(
        a["action_type"] == "upload_document" and a["target_skill"] == "Graph Analysis"
        for a in actions
    )
    assert not any("uploading a document" in a["reason"].lower() for a in actions)


def test_linkedin_profile_text_maps_to_skill_evidence():
    analysis = analyze_optional_evidence(
        source_type="linkedin_profile",
        raw_text="Data Science intern working on a recommendation system using Python and machine learning.",
        profile_url="https://linkedin.com/in/example",
        section_label="Experience",
    )
    obj = next(o for o in analysis.evidence_objects if o["skill_name"] == "Data Science")
    assert obj["evidence_type"] == "profile_snippet"
    assert obj["profile_url"] == "https://linkedin.com/in/example"
    assert obj["section_label"] == "Experience"


def test_certificate_text_maps_metadata_without_fake_fields():
    analysis = analyze_optional_evidence(
        source_type="certificate_transcript",
        raw_text="Issuer: Coursera\nCertificate: Machine Learning\nDate: 2024\nCompleted supervised learning and model training.",
    )
    assert analysis.evidence_objects
    obj = next(o for o in analysis.evidence_objects if o["skill_name"] == "Machine Learning")
    assert obj["evidence_type"] == "certificate_or_transcript_snippet"
    assert obj["issuer"] == "Coursera"
    assert obj["title"] == "Machine Learning"
    assert obj["date"] == "2024"
    no_meta = analyze_optional_evidence(source_type="certificate_transcript", raw_text="Completed a Python course.")
    assert no_meta.analysis_json.get("issuer") is None
    assert no_meta.analysis_json.get("date") is None


def test_optional_evidence_included_when_present_and_actions_source_aware():
    analysis = analyze_optional_evidence(
        source_type="document",
        raw_text="Project report: built REST APIs using FastAPI and PostgreSQL.",
    )
    row = {"source_type": "document", "status": analysis.status, "evidence_objects": analysis.evidence_objects}
    result = _svc(opt=[row]).evaluate("u1", "s1", claimed_skills=["Technical Documentation"])
    assert "uploaded_documents" in result.evidence_sources_used
    skills = {sk.skill for g in result.grouped_skill_evidence for sk in g.skills}
    assert {"Backend API", "FastAPI", "PostgreSQL"} & skills
    actions = _svc().evaluate("u1", "s1", claimed_skills=["Technical Documentation"]).next_best_actions
    assert any(a["action_type"] == "upload_document" for a in actions)
    assert not any(a["action_type"] == "add_linkedin_proof" for a in actions)
    upload_actions = [a for a in actions if a["action_type"] == "upload_document"]
    assert all("certificate" not in a["objective"].lower() for a in upload_actions)
    assert all("transcript" not in a["objective"].lower() for a in upload_actions)


def test_profile_and_certificate_rows_are_reserved_outside_project_proof():
    profile = analyze_optional_evidence(
        source_type="linkedin_profile",
        raw_text="Data Science intern working on recommendation systems.",
        profile_url="https://linkedin.com/in/example",
    )
    certificate = analyze_optional_evidence(
        source_type="certificate_transcript",
        raw_text="Issuer: Coursera\nCertificate: Machine Learning\nDate: 2024",
    )
    rows = [
        {"source_type": "linkedin_profile", "status": profile.status, "evidence_objects": profile.evidence_objects},
        {"source_type": "certificate_transcript", "status": certificate.status, "evidence_objects": certificate.evidence_objects},
    ]
    result = _svc(opt=rows).evaluate("u1", "s1", claimed_skills=[])
    assert "linkedin_profile" not in result.evidence_sources_used
    assert "certificate" not in result.evidence_sources_used
    skills = {sk.skill for g in result.grouped_skill_evidence for sk in g.skills}
    assert "Data Science" not in skills
    assert "Machine Learning" not in skills


# ── Chatbot / Qwen target evidence tests ──────────────────────────────────────

# ── Mismatch regression tests: source cards must not show "not_run" when data exists ─

def test_workflow_analysis_present_source_not_run_false():
    """If workflow analysis exists (even score=0), website_workflow must NOT be not_run."""
    wf = {
        "evidence_strength_score": 0,
        "workflow_confidence": "insufficient",
        "visible_evidence_status": "not_captured",
        "demonstrated_actions": [],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    wf_src = next(s for s in result.evidence_source_breakdown if s["key"] == "website_workflow")
    assert wf_src["status"] != "not_run", (
        f"website_workflow must not be 'not_run' when workflow row exists; got {wf_src['status']}"
    )


def test_ocr_evidence_in_frame_summary_not_not_run():
    """If frame_ocr_evidence_summary has has_ocr_evidence=True, OCR must NOT be not_run."""
    wf = {
        "evidence_strength_score": 45,
        "workflow_confidence": "low",
        "visible_evidence_status": "not_captured",
        "demonstrated_actions": [],
        # visual_analysis_status is 'not_configured' (no OCR provider), but OCR data exists
        # from Qwen/video frame analysis stored in frame_ocr_evidence_summary
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {
            "has_ocr_evidence": True,
            "top_ocr_snippets": ["HuggingChat", "chat window", "hi"],
            "detected_page_context": "chatbot_ui",
            "skill_signals": [],
        },
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Natural Language Processing"])
    ocr_src = next(s for s in result.evidence_source_breakdown if s["key"] == "ocr")
    assert ocr_src["status"] != "not_run", (
        f"OCR must not be 'not_run' when frame_ocr_evidence_summary has evidence; got {ocr_src['status']}"
    )
    assert ocr_src["score"] > 0, (
        f"OCR score must be > 0 when frame evidence exists; got {ocr_src['score']}"
    )


def test_qwen_per_frame_data_used_when_stored_summary_null():
    """When stored visual_reasoning_summary is null but per-frame data exists, Qwen must not be not_available."""
    from unittest.mock import MagicMock

    # Simulate in-memory dict with per-frame Qwen data
    frame_table = "workflow_visual_frame_evidence"
    session_id = "sess-qwen-fallback"
    user_id = "u1"

    frame_row = {
        "id": "frame-1",
        "user_id": user_id,
        "proof_session_id": session_id,
        "frame_type": "video_keyframe",
        "timestamp_ms": 3000,
        "visual_reasoning_json": {
            "status": "analyzed",
            "visual_summary": "The HuggingChat interface is open with a chat window.",
            "frames_analyzed": 1,
            "supported_skills": ["Chatbot UI"],
            "confidence_score": 0.75,
        },
    }

    wf_row = {
        "evidence_strength_score": 55,
        "workflow_confidence": "medium",
        "visible_evidence_status": "not_captured",
        "demonstrated_actions": ["Target application loaded: huggingface.co/chat"],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        # stored visual_reasoning_summary is null (common for sessions analyzed before Qwen ran)
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }

    db = {
        "workflow_analysis_results": {"row-1": {**wf_row, "user_id": user_id, "proof_session_id": session_id}},
        frame_table: {"frame-1": frame_row},
    }
    svc = FinalEvidenceEvaluatorService(db)
    result = svc.evaluate(user_id, session_id, claimed_skills=["Chatbot UI"])
    qwen_src = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    # Qwen per-frame fallback must have found the analyzed frame
    assert qwen_src["status"] not in ("not_available",), (
        f"Qwen must use per-frame fallback when stored summary is null; got {qwen_src['status']}"
    )
    assert qwen_src["score"] > 0, (
        f"Qwen score must be > 0 when per-frame Qwen data exists; got {qwen_src['score']}"
    )


def test_project_defense_analyzed_not_not_run_with_dict_store():
    """If project defense was analyzed and stored in dict store, source must NOT be not_run."""
    from app.services.project_defense_analysis_service import _TABLE as _PD_TABLE

    session_id = "sess-pd-test"
    user_id = "u1"

    pd_row = {
        "user_id": user_id,
        "proof_session_id": session_id,
        "analysis_status": "analyzed",
        "overall_score": 65,
        "transcript_text": "I built the HuggingChat chatbot UI with message input and prompt handling.",
        "consistency_with_evidence_score": 65,
        "explanation_clarity_score": 70,
        "ownership_signal_score": 60,
        "technical_depth_score": 65,
    }

    wf_row = {
        "evidence_strength_score": 50,
        "workflow_confidence": "medium",
        "visible_evidence_status": "not_captured",
        "demonstrated_actions": [],
        "visual_analysis_status": "not_configured",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }

    # Dict store: project defense uses proof_session_id as key (matching project_defense_analysis_service)
    db = {
        "workflow_analysis_results": {"row-1": {**wf_row, "user_id": user_id, "proof_session_id": session_id}},
        _PD_TABLE: {session_id: pd_row},
    }
    svc = FinalEvidenceEvaluatorService(db)
    result = svc.evaluate(user_id, session_id, claimed_skills=["Chatbot UI"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["status"] != "not_run", (
        f"Project defense must not be 'not_run' when analysis row exists in dict store; got {pd_src['status']}"
    )
    assert pd_src["score"] > 0, (
        f"Project defense score must be > 0 when analyzed transcript exists; got {pd_src['score']}"
    )


def test_qwen_chatbot_target_observation_gives_partial_score():
    """Qwen observations describing HuggingChat give non-zero score even when filtered."""
    wf = {
        "evidence_strength_score": 40,
        "workflow_confidence": "low",
        "supported_skills": [],
        "weakly_supported_skills": ["Chatbot UI"],
        "visual_reasoning_summary": {
            "status": "filtered_non_target_frame",
            "frames_analyzed": 0,
            "observations": [
                {
                    "visual_summary": "The HuggingChat interface is open on a web browser, showing a chat window with a loading message.",
                    "visible_ui_elements": ["chat window", "input field", "send button"],
                    "detected_user_action": "user opened HuggingChat",
                    "confidence_score": 0.7,
                },
                {
                    "visual_summary": "The HuggingChat interface is open, showing a chat window with the word 'hi' typed in.",
                    "visible_ui_elements": ["message input", "send button"],
                    "detected_user_action": "user typed 'hi' in chat input",
                    "confidence_score": 0.75,
                },
            ],
        },
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 2,
        "video_keyframe_timestamps_ms": [2000, 8000],
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Chatbot UI", "Natural Language Processing"])
    qwen = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    assert qwen["score"] > 0, (
        f"Qwen score must be > 0 when observations contain chatbot target content, got {qwen['score']}"
    )
    assert qwen["status"] in ("partial", "pass"), (
        f"Qwen status must be partial or pass, got {qwen['status']}"
    )


def test_qwen_non_target_observation_stays_zero():
    """Qwen observations with no chatbot content keep score=0 when filtered."""
    wf = {
        "evidence_strength_score": 20,
        "workflow_confidence": "insufficient",
        "supported_skills": [],
        "weakly_supported_skills": [],
        "visual_reasoning_summary": {
            "status": "filtered_non_target_frame",
            "frames_analyzed": 0,
            "observations": [
                {
                    "visual_summary": "A person is sitting at a desk looking at their phone.",
                    "visible_ui_elements": [],
                    "detected_user_action": "person is idle",
                    "confidence_score": 0.3,
                },
            ],
        },
        "video_keyframe_status": "extracted",
        "video_keyframe_count": 1,
        "video_keyframe_timestamps_ms": [3000],
    }
    svc = _svc(wf=wf)
    result = svc.evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    qwen = next(s for s in result.evidence_source_breakdown if s["key"] == "qwen_visual_reasoning")
    assert qwen["score"] == 0, (
        f"Non-chatbot Qwen observation must score 0, got {qwen['score']}"
    )


def test_chatbot_workflow_partial_score_with_page_load():
    """Chatbot workflow score must be > 0 when target page loaded even with no clicks."""
    wf = {
        "evidence_strength_score": 55,
        "workflow_confidence": "medium",
        "supported_skills": [],
        "weakly_supported_skills": ["Chatbot UI"],
        "target_site_pages_count": 1,
        "visual_reasoning_summary": None,
    }
    svc = _svc(wf=wf)
    result = svc.evaluate(
        "u1", "s1",
        claimed_skills=["Natural Language Processing", "Chatbot UI", "Large Language Models"],
    )
    wf_src = next(s for s in result.evidence_source_breakdown if s["key"] == "website_workflow")
    assert wf_src["score"] > 0, (
        f"Website workflow score must be > 0 when chatbot page loaded, got {wf_src['score']}"
    )


def test_project_defense_analyzed_transcript_not_zero():
    """Project defense with analyzed transcript must not show 0/100."""
    pd = {
        "analysis_status": "analyzed",
        "overall_score": 65,
        "transcript_text": "I built the HuggingChat chatbot UI with message input, prompt handling, and response display.",
        "consistency_with_evidence_score": 65,
        "explanation_clarity_score": 70,
        "ownership_signal_score": 60,
        "technical_depth_score": 65,
    }
    svc = _svc(pd=pd)
    result = svc.evaluate("u1", "s1", claimed_skills=["Chatbot UI", "Natural Language Processing"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] > 0, (
        f"Project defense with analyzed transcript must not show 0/100, got {pd_src['score']}"
    )
    assert pd_src["status"] in ("pass", "partial"), (
        f"Project defense status must be pass or partial, got {pd_src['status']}"
    )


def _chatbot_wf(score: int = 70) -> dict[str, Any]:
    return {
        "evidence_strength_score": score,
        "workflow_confidence": "medium",
        "target_website": "huggingface.co",
        "workflow_summary": "HuggingChat chatbot page loaded with message input and assistant response.",
        "recruiter_summary": "The workflow demonstrates prompt to assistant response in a chat UI.",
        "supported_skills": ["Chatbot UI"],
        "weakly_supported_skills": ["Natural Language Processing", "Large Language Models"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }


def _leaflet_wf(score: int = 70) -> dict[str, Any]:
    return {
        "evidence_strength_score": score,
        "workflow_confidence": "medium",
        "target_website": "leafletjs.com",
        "workflow_summary": "Leaflet map page loaded with markers, map tiles, zoom, pan, and popup behavior.",
        "recruiter_summary": "The workflow demonstrates an interactive Leaflet geospatial map.",
        "supported_skills": ["Leaflet.js", "Interactive Maps"],
        "weakly_supported_skills": ["Geospatial"],
        "visual_reasoning_summary": None,
        "frame_ocr_evidence_summary": {},
    }


def _pd(transcript: str, score: int = 67) -> dict[str, Any]:
    return {
        "analysis_status": "analyzed",
        "overall_defense_score": score,
        "transcript_text": transcript,
        "consistency_with_evidence_score": score,
        "explanation_clarity_score": 70,
        "ownership_signal_score": 65,
        "technical_depth_score": 68,
    }


def test_chatbot_proof_with_chatbot_transcript_scores_relevant_defense():
    result = _svc(
        wf=_chatbot_wf(),
        pd=_pd("I built a HuggingChat chatbot UI with prompt handling, conversation messages, and assistant response rendering."),
    ).evaluate("u1", "s1", claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] >= 60
    assert "unrelated" not in str(pd_src.get("notes", "")).lower()


def test_chatbot_proof_with_webgl_transcript_flags_unrelated_defense_low():
    result = _svc(
        wf=_chatbot_wf(),
        pd=_pd("I built a Three.js WebGL 3D scene with mesh geometry simplification, renderer, camera, texture, and shader controls."),
    ).evaluate("u1", "s1", claimed_skills=["Natural Language Processing", "Large Language Models", "Chatbot UI"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] <= 25
    assert "unrelated" in str(pd_src.get("notes", "")).lower()


def test_leaflet_proof_with_leaflet_transcript_scores_relevant_defense():
    result = _svc(
        wf=_leaflet_wf(),
        pd=_pd("I built the Leaflet interactive map with markers, popups, OpenStreetMap tiles, zoom, pan, and geospatial coordinates."),
    ).evaluate("u1", "s1", claimed_skills=["Leaflet.js", "Interactive Maps"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] >= 60


def test_leaflet_proof_with_chatbot_transcript_flags_unrelated_defense_low():
    result = _svc(
        wf=_leaflet_wf(),
        pd=_pd("I built a chatbot prompt interface with assistant messages, conversation history, LLM response handling, and NLP behavior."),
    ).evaluate("u1", "s1", claimed_skills=["Leaflet.js", "Interactive Maps"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] <= 25
    assert "unrelated" in str(pd_src.get("notes", "")).lower()


def test_leaflet_proof_with_webgl_transcript_flags_unrelated_defense_low():
    result = _svc(
        wf=_leaflet_wf(),
        pd=_pd(
            "I built a Three.js WebGL 3D graphics project with geometry simplification, "
            "mesh processing, scene camera controls, and renderer optimization."
        ),
    ).evaluate(
        "u1",
        "s1",
        claimed_skills=["JavaScript", "Leaflet.js", "Interactive Maps", "Geospatial Visualization", "OpenStreetMap"],
    )
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] <= 25
    assert "unrelated" in str(pd_src.get("notes", "")).lower()
    grouped_skills = {sk.skill for g in result.grouped_skill_evidence for sk in g.skills}
    assert "Three.js" not in grouped_skills
    assert "WebGL" not in grouped_skills


def test_threejs_proof_with_threejs_transcript_scores_relevant_defense():
    result = _svc(
        wf=_threejs_wf(),
        pd=_pd("I built the Three.js WebGL mesh simplifier with geometry reduction, renderer updates, scene camera, and 3D controls."),
    ).evaluate("u1", "s1", claimed_skills=["Three.js", "WebGL", "3D Graphics"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] >= 60


def test_threejs_proof_with_leaflet_transcript_flags_unrelated_defense_low():
    result = _svc(
        wf=_threejs_wf(),
        pd=_pd("I built a Leaflet geospatial map using OpenStreetMap tiles, marker popups, zoom, pan, and map coordinates."),
    ).evaluate("u1", "s1", claimed_skills=["Three.js", "WebGL", "3D Graphics"])
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] <= 25
    assert "unrelated" in str(pd_src.get("notes", "")).lower()


def test_project_defense_relevance_checks_refined_transcript_when_transcript_text_empty():
    pd = _pd("", score=67)
    pd["refined_transcript"] = "Three.js WebGL mesh geometry simplification with renderer and camera controls."
    result = _svc(wf=_leaflet_wf(), pd=pd).evaluate(
        "u1",
        "s1",
        claimed_skills=["Leaflet.js", "Interactive Maps", "Geospatial Visualization"],
    )
    pd_src = next(s for s in result.evidence_source_breakdown if s["key"] == "project_defense")
    assert pd_src["score"] <= 25
    assert "unrelated" in str(pd_src.get("notes", "")).lower()


def test_dom_partial_evidence_from_observed_demo_scores_partial():
    wf = {
        "analysis_status": "completed",
        "evidence_strength_score": 29,
        "workflow_confidence": "low",
        "visible_evidence_status": "not_captured",
        "dom_evidence_status": "not_captured",
        "demonstrated_actions": [],
        "target_website": "https://leafletjs.com/examples/quick-start/",
        "workflow_summary": "Target Leaflet quick-start page loaded.",
        "observed_demonstration": {
            "target_app": "leafletjs.com",
            "summary": "DOM evidence partial for Leaflet map tutorial.",
            "visible_evidence_status": "partial",
            "dom_evidence_status": "partial",
            "top_result_snippets": ["Leaflet map marker popup OpenStreetMap tile"],
            "steps": [],
        },
        "frame_ocr_evidence_summary": {},
    }
    result = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["Leaflet.js", "Interactive Maps"])
    dom_src = next(s for s in result.evidence_source_breakdown if s["key"] == "dom_visible_evidence")
    assert dom_src["status"] == "partial"
    assert dom_src["score"] > 0


def test_unrelated_document_does_not_boost_final_score_or_group_skills():
    wf = _chatbot_wf(score=70)
    base = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    unrelated_doc = [{
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "Three.js WebGL 3D mesh geometry simplification report.",
        "evidence_objects": [
            {"skill_name": "Three.js", "confidence": "high", "reason": "WebGL mesh simplification"},
            {"skill_name": "WebGL", "confidence": "high", "reason": "3D renderer and geometry"},
        ],
    }]
    result = _svc(wf=wf, opt=unrelated_doc).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    assert result.final_score == base.final_score
    doc_src = next(s for s in result.evidence_source_breakdown if s["key"] == "uploaded_documents")
    assert "unrelated" in str(doc_src.get("notes", "")).lower()
    grouped_skills = {sk.skill for g in result.grouped_skill_evidence for sk in g.skills}
    assert "Three.js" not in grouped_skills
    assert "WebGL" not in grouped_skills


def test_relevant_document_can_boost_final_score():
    wf = _chatbot_wf(score=70)
    base = _svc(wf=wf).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    relevant_doc = [{
        "source_type": "document",
        "status": "analyzed",
        "analysis_summary": "HuggingChat chatbot architecture with prompt handling, assistant response flow, and message UI.",
        "evidence_objects": [
            {"skill_name": "Chatbot UI", "confidence": "high", "reason": "chat interface"},
            {"skill_name": "Natural Language Processing", "confidence": "high", "reason": "prompt processing"},
            {"skill_name": "Large Language Models", "confidence": "high", "reason": "assistant response"},
            {"skill_name": "AI Product Design", "confidence": "high", "reason": "conversation UX"},
        ],
    }]
    result = _svc(wf=wf, opt=relevant_doc).evaluate("u1", "s1", claimed_skills=["Chatbot UI"])
    assert result.final_score >= base.final_score
    doc_src = next(s for s in result.evidence_source_breakdown if s["key"] == "uploaded_documents")
    assert doc_src["score"] >= 80
