"""
Evidence label honesty — backend regression tests.

Production runs in degraded mode (no AI provider keys): the workflow analyzer
only ever stores ``analysis_type = "timeline_only"`` (deterministic
browser-event/timeline analysis — no AI runs). The API previously hardcoded
``current_stage = "AI reviewed"`` on EVERY workflow analysis response,
falsely implying an AI model reviewed timeline-only evidence.

Contract under test:
  1. Every ``WorkflowAnalysisType`` value maps to an honest stage label.
  2. Unknown/legacy values fall back to a neutral honest label.
  3. A timeline_only response can never carry an AI-implying stage label
     (checked at the helper level AND on the serialized API response).
  4. Skill-evidence-profile labels never claim an unconditional AI review.
"""

from __future__ import annotations

import re
from typing import get_args

from app.api.v1.endpoints.extension_proof_workflow_analysis import _to_response
from app.schemas.extension_proof_workflow_analysis import (
    ANALYSIS_REVIEW_STAGE_LABELS,
    WorkflowAnalysisType,
    analysis_review_stage_label,
)
from app.schemas.skill_evidence_profile import EVIDENCE_LEVEL_LABELS

_AI_CLAIM_RE = re.compile(r"\bAI[\s-]?(reviewed|review|analyzed|analysed)\b", re.IGNORECASE)


def _minimal_row(analysis_type: str) -> dict:
    return {
        "id": "analysis-1",
        "proof_session_id": "session-1",
        "analysis_type": analysis_type,
        "analyzer_version": "workflow-analysis-v4",
        "workflow_summary": "Recording shows a walkthrough.",
        "demonstrated_actions": [],
        "supported_skills": [],
        "weakly_supported_skills": [],
        "unsupported_skills": [],
        "evidence_strength_score": 57,
        "workflow_confidence": "high",
        "missing_evidence": [],
        "risk_flags": [],
        "recruiter_summary": "Walkthrough recorded.",
        "student_improvement_suggestions": [],
        "human_review_needed": False,
        "created_at": "2026-07-21T00:00:00+00:00",
    }


class TestAnalysisReviewStageLabel:
    def test_timeline_only_is_honest(self) -> None:
        assert analysis_review_stage_label("timeline_only") == "Timeline evidence reviewed"

    def test_video_frame_analysis_is_honest(self) -> None:
        assert analysis_review_stage_label("video_frame_analysis") == "Video frame evidence reviewed"

    def test_full_multimodal_may_claim_ai(self) -> None:
        assert analysis_review_stage_label("full_multimodal_analysis") == "AI reviewed"

    def test_unknown_and_missing_fall_back_honestly(self) -> None:
        assert analysis_review_stage_label("something_new") == "Analysis complete"
        assert analysis_review_stage_label("") == "Analysis complete"
        assert analysis_review_stage_label(None) == "Analysis complete"

    def test_every_enumerated_type_has_an_explicit_label(self) -> None:
        for value in get_args(WorkflowAnalysisType):
            assert value in ANALYSIS_REVIEW_STAGE_LABELS

    def test_only_full_multimodal_implies_ai(self) -> None:
        for value in get_args(WorkflowAnalysisType):
            label = analysis_review_stage_label(value)
            if value == "full_multimodal_analysis":
                assert _AI_CLAIM_RE.search(label)
            else:
                assert not _AI_CLAIM_RE.search(label), (
                    f"{value!r} must never get an AI-implying label, got {label!r}"
                )
        assert not _AI_CLAIM_RE.search(analysis_review_stage_label("unknown_value"))


class TestSerializedResponseHonesty:
    def test_timeline_only_response_never_says_ai_reviewed(self) -> None:
        resp = _to_response(_minimal_row("timeline_only"))
        assert resp.current_stage == "Timeline evidence reviewed"
        assert not _AI_CLAIM_RE.search(resp.current_stage)

    def test_full_multimodal_response_keeps_ai_reviewed(self) -> None:
        resp = _to_response(_minimal_row("full_multimodal_analysis"))
        assert resp.current_stage == "AI reviewed"

    def test_missing_analysis_type_defaults_to_timeline_only_stage(self) -> None:
        row = _minimal_row("timeline_only")
        del row["analysis_type"]
        resp = _to_response(row)
        # Serializer defaults a missing analysis_type to timeline_only —
        # the stage label must match that honest default.
        assert resp.current_stage == "Timeline evidence reviewed"


class TestSkillEvidenceProfileLabels:
    def test_profile_labels_never_claim_unconditional_ai_review(self) -> None:
        # The profile level is computed from has_analysis only — it cannot know
        # whether an AI provider ran, so no level label may claim an AI review.
        for key, label in EVIDENCE_LEVEL_LABELS.items():
            assert not _AI_CLAIM_RE.search(label), (
                f"EVIDENCE_LEVEL_LABELS[{key!r}] claims an AI review: {label!r}"
            )
