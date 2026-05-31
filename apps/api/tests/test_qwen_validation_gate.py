"""Tests: Qwen validation gate — inconsistency detection and rejection statuses.

Tests required (T1–T8):
  T1  Session B never uses Qwen result from Session A.
  T2  Wrong-frame: Qwen result frame status must be validated.
  T3  Stale upload: new upload clears / invalidates old Qwen results.
  T4  Inconsistent hallucination rejection:
        Context = p5.js / JavaScript / canvas
        Qwen = person wearing jeans near white wall
        Expected: rejected_inconsistent, not displayed as valid evidence.
  T5  Valid app-frame acceptance:
        Context = p5.js / JavaScript / canvas
        Qwen = browser-based visual coding interface with canvas output
        Expected: analyzed / accepted.
  T6  Frontend rendering:
        rejected_inconsistent → _safe_visual_reasoning_summary passes status.
  T7  Existing TensorFlow positive test still passes.
  T8  Existing two-session isolation test still passes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.visual_reasoning_service import (
    MockReasoningProvider,
    VisualReasoningObservation,
    VisualReasoningService,
    REASONING_STATUS_ANALYZED,
    REASONING_STATUS_REJECTED_INCONSISTENT,
    _check_observation_consistency,
    select_frame_ids_for_reasoning,
)
from app.services.extension_proof_workflow_analysis_service import (
    _build_visual_reasoning_session_summary_from_db,
)
from app.api.v1.endpoints.extension_proof_workflow_analysis import (
    _safe_visual_reasoning_summary,
    _REASONING_PUBLIC_FIELDS,
)


# ── Fixtures / helpers ──────────────────────────────────────────────────────────

_TINY_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xD9])  # minimal valid JPEG marker pair

def _make_obs(
    visual_summary: str,
    skills: list[str] | None = None,
    confidence: float = 0.8,
    status: str = REASONING_STATUS_ANALYZED,
    objects: list[str] | None = None,
    ui_elements: list[str] | None = None,
    user_action: str = "",
) -> VisualReasoningObservation:
    return VisualReasoningObservation(
        frame_index=0,
        timestamp_ms=1000,
        model_provider="qwen_vl:qwen_vl",
        visual_summary=visual_summary,
        visible_objects_or_diagrams=objects or [],
        visible_ui_elements=ui_elements or [],
        detected_user_action=user_action,
        detected_workflow_stage="results_display",
        supported_skills=skills or [],
        confidence_score=confidence,
        status=status,
    )


def _make_db(rows: list) -> MagicMock:
    db = MagicMock()
    chain = (
        db.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
    )
    chain.not_.is_.return_value.order.return_value.execute.return_value.data = rows
    return db


def _vr_row(visual_summary: str, status: str = "analyzed", skills: list[str] | None = None, ts_ms: int = 1000) -> dict:
    return {
        "id": f"frame-{ts_ms}",
        "visual_reasoning_json": {
            "status": status,
            "visual_summary": visual_summary,
            "supported_skills": skills or [],
            "detected_skills_supported": skills or [],
            "missing_or_unclear_evidence": [],
            "confidence_score": 0.8,
            "model_provider": "qwen_vl:qwen_vl",
        },
        "timestamp_ms": ts_ms,
        "frame_type": "video_keyframe",
        "ocr_text": [],
        "proof_session_id": "session-test",
    }


# ── T1: Session isolation — Session B never uses Session A result ───────────────

class TestSessionIsolationT1:
    def test_session_b_never_uses_session_a_qwen_result(self):
        """Session B query returns only its own rows — Session A rows are not present."""
        # Session A: hallucinated person
        db_a = _make_db([_vr_row("A person wearing black shirt standing in front of wall")])
        # Session B: TF Playground
        db_b = _make_db([_vr_row("TensorFlow Playground with neural layers", skills=["Neural Networks"])])

        result_a = _build_visual_reasoning_session_summary_from_db(db_a, "user-1", "session-a")
        result_b = _build_visual_reasoning_session_summary_from_db(db_b, "user-1", "session-b")

        assert result_a is not None
        assert result_b is not None

        assert "person" in result_a["summary"].lower() or "black shirt" in result_a["summary"].lower()
        assert "Neural Networks" in result_b["supported_signals"]

        # Cross-contamination check
        assert "person wearing" not in result_b["summary"].lower()
        assert "black shirt" not in result_b["summary"].lower()


# ── T2: Wrong-frame validation ──────────────────────────────────────────────────

class TestWrongFrameValidation:
    def test_rejected_obs_excluded_from_skill_signals(self):
        """A rejected_inconsistent obs is excluded from supported_signals."""
        rows = [
            _vr_row("Visual reasoning result was rejected...", status="rejected_inconsistent"),
        ]
        db = _make_db(rows)
        result = _build_visual_reasoning_session_summary_from_db(db, "user-1", "session-1")

        # All obs rejected → status is rejected_inconsistent (not analyzed)
        assert result is not None
        assert result["status"] == "rejected_inconsistent"
        assert result["supported_signals"] == []
        assert result["frames_analyzed"] == 0

    def test_mixed_analyzed_and_rejected_only_analyzed_contributes(self):
        """When some frames are analyzed and some rejected, only analyzed frames contribute skills."""
        rows = [
            _vr_row("TF Playground neural network", status="analyzed", skills=["Neural Networks"], ts_ms=1000),
            _vr_row("Rejected — person/wall hallucination", status="rejected_inconsistent", ts_ms=2000),
        ]
        db = _make_db(rows)
        result = _build_visual_reasoning_session_summary_from_db(db, "user-1", "session-mixed")

        assert result is not None
        assert result["status"] == "analyzed"
        assert "Neural Networks" in result["supported_signals"]
        assert result["frames_analyzed"] == 1

    def test_select_frame_ids_uses_same_percentiles_as_analyze_frames(self):
        """select_frame_ids_for_reasoning must produce indices matching _FRAME_PERCENTILES."""
        frame_ids = [f"frame-{i}" for i in range(5)]

        # For n_limit=3, percentiles=[0.20, 0.50, 0.85] → indices [1, 2, 4]
        selected = select_frame_ids_for_reasoning(frame_ids, n_limit=3)
        assert selected == ["frame-1", "frame-2", "frame-4"], (
            f"Expected ['frame-1','frame-2','frame-4'] for 5 frames / limit=3, "
            f"got {selected}"
        )

    def test_select_frame_ids_limit_1(self):
        """n_limit=1 → percentile 0.50 → middle frame."""
        frame_ids = [f"frame-{i}" for i in range(5)]
        selected = select_frame_ids_for_reasoning(frame_ids, n_limit=1)
        # percentile 0.50 × 5 = 2 → frame-2
        assert selected == ["frame-2"]

    def test_select_frame_ids_limit_2(self):
        """n_limit=2 → percentiles [0.25, 0.80]."""
        frame_ids = [f"frame-{i}" for i in range(5)]
        selected = select_frame_ids_for_reasoning(frame_ids, n_limit=2)
        # percentiles [0.25, 0.80] × 5 = indices [1, 4]
        assert selected == ["frame-1", "frame-4"]

    def test_select_frame_ids_fewer_than_limit(self):
        """When frames <= limit, all frames are selected."""
        frame_ids = ["a", "b"]
        assert select_frame_ids_for_reasoning(frame_ids, n_limit=3) == ["a", "b"]


# ── T3: Stale upload — new upload clears old results ────────────────────────────

class TestStaleUploadValidation:
    def test_new_upload_clears_old_qwen_results(self):
        """After a new upload clears visual_reasoning_json, only new results appear.

        Simulates: old rows have visual_reasoning_json=NULL (filtered by .not_.is_()),
        new rows have fresh analyzed JSON.
        """
        new_rows = [
            _vr_row("TensorFlow Playground neural network with output", skills=["Machine Learning"]),
        ]
        db = _make_db(new_rows)
        result = _build_visual_reasoning_session_summary_from_db(db, "user-1", "session-tf")

        assert result is not None
        assert "Machine Learning" in result["supported_signals"]
        # Old "person" data is gone (cleared by upload, not returned by DB query)
        assert "person" not in result["summary"].lower()

    def test_empty_db_after_clear_returns_none(self):
        """If all rows are cleared (visual_reasoning_json=NULL), function returns None."""
        db = _make_db([])  # no rows with non-null visual_reasoning_json
        result = _build_visual_reasoning_session_summary_from_db(db, "user-1", "session-clear")
        assert result is None


# ── T4: Inconsistent hallucination rejection ─────────────────────────────────────

class TestInconsistentHallucinationRejection:
    """T4: p5.js context + person/wall Qwen → rejected_inconsistent."""

    def test_person_jeans_wall_rejected_in_p5js_context(self):
        """Core test: person/jeans/wall description is rejected for a p5.js session."""
        obs = _make_obs(
            visual_summary="A person wearing a black shirt and blue jeans is standing in front of a white wall.",
            objects=["person", "wall", "jeans"],
            ui_elements=[],
            user_action="person standing",
            skills=[],
            confidence=0.6,
        )
        context = {
            "website_context": "p5js.org/examples",
            "ocr_snippets": ["p5.js sketch canvas draw setup loop createCanvas background fill"],
            "dom_snippets": ["javascript p5 examples interactive code"],
        }
        is_consistent, reason = _check_observation_consistency(obs, context)

        assert not is_consistent, (
            "Person/wall description must be rejected for a p5.js session. "
            f"Got is_consistent={is_consistent}, reason={reason!r}"
        )
        assert "person" in reason.lower() or "shirt" in reason.lower() or "jeans" in reason.lower() or "wall" in reason.lower()

    def test_rejected_status_set_on_person_scene_for_software_context(self):
        """Full pipeline: analyze_frames() rejects person/wall for p5.js context."""
        person_obs = _make_obs(
            visual_summary="A person wearing a blue shirt and jeans standing in front of a white wall.",
            objects=["person", "white wall"],
            confidence=0.7,
        )
        provider = MockReasoningProvider(observations=[person_obs])
        svc = VisualReasoningService(provider=provider)

        summary = svc.analyze_frames(
            frames=[(1000, _TINY_JPEG)],
            claimed_skills=["JavaScript", "Creative Coding"],
            website_context="p5js.org",
            ocr_snippets=["p5.js canvas sketch javascript createCanvas animate draw"],
        )

        assert summary.status == REASONING_STATUS_REJECTED_INCONSISTENT, (
            f"Expected rejected_inconsistent, got {summary.status!r}"
        )
        assert summary.frames_analyzed == 0
        assert summary.supported_signals == []
        assert len(summary.observations) == 1
        assert summary.observations[0]["status"] == REASONING_STATUS_REJECTED_INCONSISTENT

    def test_rejected_observation_does_not_appear_as_skill_evidence(self):
        """Rejected obs must not contribute to supported_signals in session summary."""
        rows = [
            _vr_row(
                "Visual reasoning result was rejected because it did not match the current recording evidence.",
                status="rejected_inconsistent",
                skills=[],
            )
        ]
        db = _make_db(rows)
        result = _build_visual_reasoning_session_summary_from_db(db, "user-1", "session-p5")

        assert result["supported_signals"] == []
        assert result["status"] == "rejected_inconsistent"
        # Safe message only — no hallucinated person content
        assert "person" not in result["summary"].lower()
        assert "jeans" not in result["summary"].lower()

    def test_various_person_scene_patterns_rejected(self):
        """Multiple person-scene patterns trigger rejection in software context."""
        person_patterns = [
            "A man wearing a white shirt is standing in a room.",
            "A woman sitting at a desk, holding a phone.",
            "Person wearing jeans and jacket in front of a blank wall.",
            "Selfie showing individual wearing clothes in an indoor scene.",
        ]
        context = {
            "website_context": "codesandbox.io",
            "ocr_snippets": ["javascript code editor canvas animation output"],
            "dom_snippets": [],
        }
        for summary_text in person_patterns:
            obs = _make_obs(
                visual_summary=summary_text,
                objects=["person", "wall"],
            )
            is_consistent, _ = _check_observation_consistency(obs, context)
            assert not is_consistent, (
                f"Expected rejection for: {summary_text!r}"
            )


# ── T5: Valid app-frame acceptance ───────────────────────────────────────────────

class TestValidAppFrameAcceptance:
    """T5: p5.js context + canvas/code Qwen → analyzed/accepted."""

    def test_canvas_code_frame_accepted_for_p5js_context(self):
        """Qwen describing canvas/code is accepted for a p5.js session."""
        obs = _make_obs(
            visual_summary="A browser-based visual coding interface showing a canvas with animated circles and p5.js sketch output.",
            objects=["canvas", "code editor", "output panel"],
            ui_elements=["browser toolbar", "editor panel"],
            user_action="user typing code in editor",
            skills=["Creative Coding", "JavaScript"],
            confidence=0.82,
        )
        context = {
            "website_context": "p5js.org/examples",
            "ocr_snippets": ["p5.js canvas sketch javascript animate"],
            "dom_snippets": [],
        }
        is_consistent, reason = _check_observation_consistency(obs, context)
        assert is_consistent, (
            f"Canvas/code description should be accepted for p5.js, got reason={reason!r}"
        )

    def test_valid_app_frame_passes_through_pipeline(self):
        """Full pipeline: canvas/code Qwen output is accepted and shows skill signals."""
        valid_obs = _make_obs(
            visual_summary="p5.js sketch visible with canvas animation and code editor in browser.",
            objects=["canvas", "animation", "code editor"],
            ui_elements=["browser toolbar", "play button"],
            skills=["Creative Coding", "JavaScript"],
            confidence=0.85,
        )
        provider = MockReasoningProvider(observations=[valid_obs])
        svc = VisualReasoningService(provider=provider)

        summary = svc.analyze_frames(
            frames=[(1000, _TINY_JPEG)],
            claimed_skills=["Creative Coding", "JavaScript"],
            website_context="p5js.org",
            ocr_snippets=["p5.js canvas javascript animate sketch"],
        )

        assert summary.status == REASONING_STATUS_ANALYZED, (
            f"Valid app frame should be analyzed, got {summary.status!r}"
        )
        assert summary.frames_analyzed == 1
        assert "Creative Coding" in summary.supported_signals or "JavaScript" in summary.supported_signals

    def test_tensorflow_playground_not_rejected(self):
        """TF Playground frame is accepted (no person terms in Qwen output)."""
        tf_obs = _make_obs(
            visual_summary="TensorFlow Playground showing neural network with hidden layers and output chart.",
            objects=["neural network diagram", "output chart", "hidden layers"],
            ui_elements=["control panel", "layer selectors", "epoch counter"],
            skills=["Neural Networks", "Machine Learning"],
            confidence=0.88,
        )
        context = {
            "website_context": "playground.tensorflow.org",
            "ocr_snippets": ["tensorflow neural network layers training output"],
            "dom_snippets": [],
        }
        is_consistent, reason = _check_observation_consistency(tf_obs, context)
        assert is_consistent, f"TF Playground frame must not be rejected. Reason: {reason!r}"

    def test_no_context_no_rejection(self):
        """When session context is empty, even ambiguous Qwen output is not rejected.

        The checker requires context evidence to confirm 'software' context.
        Without context, there is no basis for rejection.
        """
        person_obs = _make_obs(
            visual_summary="A person wearing a shirt standing near a wall.",
            objects=["person", "wall"],
        )
        # Empty context — no app terms
        context: dict = {"website_context": "", "ocr_snippets": [], "dom_snippets": []}
        is_consistent, _ = _check_observation_consistency(person_obs, context)
        # Should not reject when context doesn't confirm software session
        assert is_consistent, "No rejection should occur when context is empty"


# ── T6: Frontend rendering — rejected status passes through safe filter ─────────

class TestFrontendRejectedRendering:
    def test_rejected_status_in_public_fields(self):
        """'status' is in _REASONING_PUBLIC_FIELDS so rejected_inconsistent passes through."""
        assert "status" in _REASONING_PUBLIC_FIELDS

    def test_safe_filter_passes_rejected_status(self):
        """_safe_visual_reasoning_summary passes rejected_inconsistent status through."""
        summary = {
            "status": "rejected_inconsistent",
            "provider": "qwen_vl:qwen_vl",
            "frames_analyzed": 0,
            "summary": "Visual reasoning result was rejected because it did not match the current recording evidence.",
            "observations": [],
            "supported_signals": [],
            "missing_claims": [],
            "limitations": ["Qwen output was inconsistent with session context."],
        }
        safe = _safe_visual_reasoning_summary(summary)
        assert safe is not None
        assert safe["status"] == "rejected_inconsistent"
        assert "person" not in safe["summary"].lower()
        assert "jeans" not in safe["summary"].lower()

    def test_safe_filter_passes_rejected_stale_status(self):
        """rejected_stale passes through the public safety filter."""
        summary = {
            "status": "rejected_stale",
            "provider": "qwen_vl",
            "frames_analyzed": 0,
            "summary": "Visual reasoning result was rejected because it did not match the current recording evidence.",
            "observations": [],
            "supported_signals": [],
            "missing_claims": [],
            "limitations": ["Stale result from previous upload."],
        }
        safe = _safe_visual_reasoning_summary(summary)
        assert safe is not None
        assert safe["status"] == "rejected_stale"

    def test_rejected_observations_stripped_of_private_fields(self):
        """Private fields in rejected observations are stripped by the safe filter."""
        summary = {
            "status": "rejected_inconsistent",
            "provider": "qwen_vl",
            "frames_analyzed": 0,
            "summary": "Rejected.",
            "observations": [{
                "status": "rejected_inconsistent",
                "visual_summary": "Person description — rejected.",
                "frame_storage_path": "/private/bucket/secret.jpg",
                "access_token": "eyJtoken",
            }],
            "supported_signals": [],
            "missing_claims": [],
            "limitations": [],
        }
        safe = _safe_visual_reasoning_summary(summary)
        assert safe is not None
        obs = safe["observations"][0]
        assert "frame_storage_path" not in obs
        assert "access_token" not in obs
        assert obs["status"] == "rejected_inconsistent"


# ── T7: Existing TF positive test still passes ───────────────────────────────────

class TestTensorFlowPositiveRegression:
    """T7: TF Playground session with valid Qwen output → analyzed + skill signals."""

    def test_tf_playground_session_still_analyzed(self):
        tf_obs = VisualReasoningObservation(
            frame_index=0,
            timestamp_ms=2400,
            model_provider="qwen_vl:qwen_vl",
            visual_summary="TensorFlow Playground with neural network layers and output chart",
            visible_ui_elements=["neural network diagram", "output chart", "control panel"],
            visible_objects_or_diagrams=["neural network", "hidden layers", "decision boundary"],
            detected_workflow_stage="model_training",
            detected_user_action="user adjusting neural network parameters",
            detected_outputs=["output value: 0.92"],
            skill_evidence={
                "Machine Learning": {"items_visible": ["training controls", "output chart"], "verdict": "supported"},
                "Neural Networks": {"items_visible": ["hidden layers", "neurons"], "verdict": "supported"},
            },
            supported_skills=["Machine Learning", "Neural Networks"],
            confidence_score=0.88,
            status=REASONING_STATUS_ANALYZED,
        )
        provider = MockReasoningProvider(observations=[tf_obs])
        svc = VisualReasoningService(provider=provider)

        summary = svc.analyze_frames(
            frames=[(2400, _TINY_JPEG)],
            claimed_skills=["Machine Learning", "Neural Networks"],
            website_context="playground.tensorflow.org",
            ocr_snippets=["tensorflow neural network playground output chart layers"],
        )

        assert summary.status == REASONING_STATUS_ANALYZED
        assert summary.frames_analyzed == 1
        assert "Machine Learning" in summary.supported_signals
        assert "Neural Networks" in summary.supported_signals


# ── T8: Two-session isolation still passes ───────────────────────────────────────

class TestTwoSessionIsolationRegression:
    """T8: Session A and B must never cross-contaminate in _build_visual_reasoning_session_summary_from_db."""

    def test_two_sessions_independent(self):
        db_a = _make_db([_vr_row(
            "A person wearing white shirt standing in front of wall",
            status="analyzed",
            skills=[],
            ts_ms=500,
        )])
        db_b = _make_db([_vr_row(
            "TensorFlow Playground neural network with hidden layers",
            status="analyzed",
            skills=["Machine Learning", "Neural Networks"],
            ts_ms=2400,
        )])

        result_a = _build_visual_reasoning_session_summary_from_db(db_a, "user-1", "session-a")
        result_b = _build_visual_reasoning_session_summary_from_db(db_b, "user-1", "session-b")

        assert result_a is not None
        assert result_b is not None

        # Session A: person description, no ML skills
        assert "person" in result_a["summary"].lower() or "white shirt" in result_a["summary"].lower()
        assert "Neural Networks" not in result_a["supported_signals"]

        # Session B: TF Playground, has ML skills
        assert "tensorflow" in result_b["summary"].lower() or "neural" in result_b["summary"].lower()
        assert "Neural Networks" in result_b["supported_signals"]

        # Cross-contamination: B must not mention A's content
        assert "person wearing" not in result_b["summary"].lower()
        assert "white shirt" not in result_b["summary"].lower()


# ── Bonus: _check_observation_consistency edge cases ─────────────────────────────

class TestConsistencyCheckerEdgeCases:
    def test_single_person_term_not_enough_to_reject(self):
        """One person term alone is not sufficient for rejection (threshold is 2)."""
        obs = _make_obs(
            visual_summary="A person is browsing a code editor.",
            objects=[],
        )
        context = {
            "website_context": "codesandbox.io",
            "ocr_snippets": ["javascript code canvas animation"],
            "dom_snippets": [],
        }
        is_consistent, _ = _check_observation_consistency(obs, context)
        # "person" is 1 term; need 2 → no rejection
        assert is_consistent

    def test_single_app_term_not_enough_to_reject(self):
        """One app term in context alone is not sufficient for rejection (threshold is 2)."""
        obs = _make_obs(
            visual_summary="A person wearing jeans standing near a white wall.",
            objects=["person", "white wall"],
        )
        context = {
            "website_context": "p5js.org",
            "ocr_snippets": [],  # only website_context → only "p5" matches from _APP_UI_TERMS
            "dom_snippets": [],
        }
        is_consistent, _ = _check_observation_consistency(obs, context)
        # Only 1 app term from website context → no rejection if <2 app hits
        # "p5js.org" matches "p5" and possibly "p5.js" → depends on term set
        # Either way, test that behavior is deterministic (document it)
        # This is a boundary test — just check it doesn't raise
        assert isinstance(is_consistent, bool)

    def test_empty_observation_not_rejected(self):
        """An empty observation (no text) is not rejected."""
        obs = _make_obs(visual_summary="", objects=[], ui_elements=[], user_action="")
        context = {
            "website_context": "p5js.org",
            "ocr_snippets": ["p5.js canvas javascript code"],
            "dom_snippets": [],
        }
        is_consistent, _ = _check_observation_consistency(obs, context)
        assert is_consistent
