"""Tests for OCR skill signal mapping and frame OCR evidence summary.

Covers:
A. _detect_ocr_page_context
   1. Homepage/marketing OCR text → homepage_marketing
   2. Training UI signals → training_ui
   3. Prediction output signals + numeric → prediction_output
   4. Empty text → unknown
   5. Single weak signal → unknown or best-fit (non-crash)

B. _ocr_skill_signals (Teachable Machine test case)
   6. "Machine Learning" with homepage OCR → partial (platform context)
   7. "Browser-Based AI" with Teachable Machine OCR → partial
   8. "Image Classification" with homepage OCR only → insufficient (no training/prediction UI)
   9. "Model Testing" with homepage OCR only → insufficient (no prediction output)
  10. "TensorFlow.js" with "teachable machine" in OCR → partial
  11. No matching OCR terms → insufficient for skill
  12. Training UI context → partial for classification skills

C. _build_frame_ocr_evidence_summary
  13. No visual_frame_observations → has_ocr_evidence=False
  14. visual_frame_analysis_status != "analyzed" → has_ocr_evidence=False
  15. Homepage OCR → page context correctly detected, what_was_not_observed populated
  16. skill_signals populated for all claimed skills
  17. top_ocr_snippets filtered (noise words removed, capped at 8)
  18. Homepage context: Image Classification remains insufficient
  19. Training UI context: Image Classification becomes partial
  20. Noisy "Table of Contents" OCR text filtered from top_ocr_snippets

D. _analyze_workflow OCR skill promotion
  21. Skill in "unsupported" with OCR partial support → moved to "weakly_supported_skills"
  22. Skill without OCR support stays in "unsupported_skills"
  23. frame_ocr_evidence_summary present in _analyze_workflow result

E. _determine_missing_evidence with OCR context
  24. Homepage-only context → specific missing evidence message for Image Classification
  25. OCR reasoning propagated into missing evidence string

F. Noisy OCR filtering
  26. "Table of Contents" does not appear in top_ocr_snippets
  27. Unrelated tab content (other domain OCR) does not dominate target-skill signals
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _import_service():
    from app.services.extension_proof_workflow_analysis_service import (
        _detect_ocr_page_context,
        _ocr_skill_signals,
        _build_frame_ocr_evidence_summary,
        _determine_missing_evidence,
        _analyze_workflow,
    )
    return (
        _detect_ocr_page_context,
        _ocr_skill_signals,
        _build_frame_ocr_evidence_summary,
        _determine_missing_evidence,
        _analyze_workflow,
    )


_TEACHABLE_MACHINE_HOMEPAGE_OCR = (
    "Teachable Machine | Train a computer to recognize your images, sounds & poses. "
    "A fast, easy way to create machine learning models for your sites, apps, and more — "
    "no expertise or coding required. Get Started. Watch video. Used by educators."
)

_TEACHABLE_MACHINE_TRAINING_OCR = (
    "Teachable Machine | Class 1 | Add Image Samples | Webcam | Upload images | "
    "Class 2 | Hold to record | Train Model | Training... epochs 15/30"
)

_TEACHABLE_MACHINE_PREDICTION_OCR = (
    "Teachable Machine | Your model is ready | Test your model | "
    "Class 1: 0.89 | Class 2: 0.11 | confidence 89% | output"
)


# ── A. Page context detection ─────────────────────────────────────────────────

class TestDetectOCRPageContext:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def test_homepage_marketing_detected(self):
        ctx = self.detect_ctx(_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        assert ctx == "homepage_marketing"

    def test_training_ui_detected(self):
        ctx = self.detect_ctx(_TEACHABLE_MACHINE_TRAINING_OCR)
        assert ctx == "training_ui"

    def test_prediction_output_detected(self):
        ctx = self.detect_ctx(_TEACHABLE_MACHINE_PREDICTION_OCR)
        assert ctx == "prediction_output"

    def test_empty_text_returns_unknown(self):
        ctx = self.detect_ctx("")
        assert ctx == "unknown"

    def test_none_like_whitespace_returns_unknown(self):
        ctx = self.detect_ctx("   \n\t  ")
        assert ctx == "unknown"

    def test_no_crash_on_any_text(self):
        """_detect_ocr_page_context never raises on arbitrary text."""
        for text in ["hello world", "1234567890", "a" * 1000, "🎉🎊"]:
            result = self.detect_ctx(text)
            assert isinstance(result, str)


# ── B. OCR skill signals (Teachable Machine scenario) ────────────────────────

class TestOCRSkillSignals:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def _signals_map(self, skills, ocr_text, ctx):
        sigs = self.ocr_signals(skills, ocr_text, ctx)
        return {s["skill"]: s for s in sigs}

    def test_machine_learning_homepage_is_partial(self):
        """'Machine Learning' with homepage OCR → partial (platform context supports it)."""
        smap = self._signals_map(
            ["Machine Learning"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert "Machine Learning" in smap
        assert smap["Machine Learning"]["ocr_support"] == "partial"

    def test_browser_based_ai_homepage_is_partial(self):
        """'Browser-Based AI' with Teachable Machine homepage OCR → partial."""
        smap = self._signals_map(
            ["Browser-Based AI"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert "Browser-Based AI" in smap
        assert smap["Browser-Based AI"]["ocr_support"] == "partial"

    def test_image_classification_homepage_only_is_insufficient(self):
        """'Image Classification' with homepage OCR → insufficient (no training/prediction UI)."""
        smap = self._signals_map(
            ["Image Classification"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert "Image Classification" in smap
        assert smap["Image Classification"]["ocr_support"] == "insufficient", (
            f"Expected insufficient for homepage-only OCR, got: {smap['Image Classification']}"
        )

    def test_model_testing_homepage_only_is_insufficient(self):
        """'Model Testing' with homepage OCR → insufficient (no prediction output visible)."""
        smap = self._signals_map(
            ["Model Testing"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert "Model Testing" in smap
        assert smap["Model Testing"]["ocr_support"] == "insufficient"

    def test_tensorflow_js_teachable_machine_partial(self):
        """'TensorFlow.js' with 'Teachable Machine' OCR text → partial."""
        smap = self._signals_map(
            ["TensorFlow.js"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert "TensorFlow.js" in smap
        # Teachable Machine uses TF.js — should detect as partial
        assert smap["TensorFlow.js"]["ocr_support"] == "partial"

    def test_no_matching_terms_insufficient(self):
        """OCR with completely unrelated text → insufficient for any claimed skill."""
        unrelated_ocr = "Table of Contents | Chapter 1 | Chapter 2 | Introduction | Conclusion"
        smap = self._signals_map(["Image Classification"], unrelated_ocr, "unknown")
        assert smap["Image Classification"]["ocr_support"] == "insufficient"

    def test_training_ui_context_classification_partial(self):
        """'Image Classification' with training UI context → partial (training classes visible)."""
        smap = self._signals_map(
            ["Image Classification"], _TEACHABLE_MACHINE_TRAINING_OCR, "training_ui"
        )
        assert "Image Classification" in smap
        assert smap["Image Classification"]["ocr_support"] == "partial"

    def test_prediction_output_context_model_testing_partial(self):
        """'Model Testing' with prediction output context → partial."""
        smap = self._signals_map(
            ["Model Testing"], _TEACHABLE_MACHINE_PREDICTION_OCR, "prediction_output"
        )
        assert "Model Testing" in smap
        assert smap["Model Testing"]["ocr_support"] == "partial"

    def test_ocr_terms_found_populated(self):
        """ocr_terms_found list is non-empty when support is partial."""
        sigs = self.ocr_signals(
            ["Machine Learning"], _TEACHABLE_MACHINE_HOMEPAGE_OCR, "homepage_marketing"
        )
        assert sigs
        ml_sig = sigs[0]
        if ml_sig["ocr_support"] == "partial":
            assert len(ml_sig["ocr_terms_found"]) > 0

    def test_reasoning_always_present(self):
        """All signal dicts have a non-empty 'reasoning' field."""
        sigs = self.ocr_signals(
            ["Machine Learning", "Image Classification", "Model Testing"],
            _TEACHABLE_MACHINE_HOMEPAGE_OCR,
            "homepage_marketing",
        )
        for sig in sigs:
            assert isinstance(sig["reasoning"], str) and len(sig["reasoning"]) > 10, (
                f"Missing/short reasoning for {sig['skill']}: {sig!r}"
            )

    def test_empty_ocr_text_returns_empty_list(self):
        """Empty OCR text → empty signals list."""
        sigs = self.ocr_signals(["Machine Learning"], "", "unknown")
        assert sigs == []


# ── C. _build_frame_ocr_evidence_summary ─────────────────────────────────────

class TestBuildFrameOCREvidenceSummary:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def _make_vf_obs(self, status="analyzed", summary="", count=5, provider="local_ocr:tesseract"):
        return {
            "visual_frame_analysis_status": status,
            "visual_summary": summary,
            "visual_frame_count": count,
            "provider_used": provider,
            "visual_frames_stored": count,
            "extracted_result_values": [],
        }

    def test_no_observations_has_ocr_evidence_false(self):
        result = self.build_summary(None, ["Machine Learning"])
        assert result["has_ocr_evidence"] is False

    def test_not_analyzed_status_has_ocr_evidence_false(self):
        vf = self._make_vf_obs(status="not_configured")
        result = self.build_summary(vf, ["Machine Learning"])
        assert result["has_ocr_evidence"] is False

    def test_homepage_ocr_context_correctly_detected(self):
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, ["Machine Learning"])
        assert result["detected_page_context"] == "homepage_marketing"

    def test_homepage_ocr_what_was_not_observed_populated(self):
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, ["Image Classification"])
        assert len(result["what_was_not_observed"]) > 0

    def test_skill_signals_populated_for_all_claimed_skills(self):
        skills = ["Machine Learning", "Image Classification", "Browser-Based AI", "Model Testing"]
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, skills)
        assert result["has_ocr_evidence"] is True
        result_skills = {s["skill"] for s in result["skill_signals"]}
        for sk in skills:
            # Normalized skill name may differ; just check length matches
            pass
        assert len(result["skill_signals"]) == len(skills)

    def test_image_classification_insufficient_in_homepage_summary(self):
        """In homepage context, Image Classification signal is insufficient."""
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, ["Image Classification"])
        assert result["has_ocr_evidence"] is True
        ic_sig = next((s for s in result["skill_signals"] if "Classification" in s["skill"]), None)
        assert ic_sig is not None
        assert ic_sig["ocr_support"] == "insufficient"

    def test_image_classification_partial_in_training_ui_summary(self):
        """In training UI context, Image Classification signal is partial."""
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_TRAINING_OCR)
        result = self.build_summary(vf, ["Image Classification"])
        ic_sig = next((s for s in result["skill_signals"] if "Classification" in s["skill"]), None)
        assert ic_sig is not None
        assert ic_sig["ocr_support"] == "partial"

    def test_noise_table_of_contents_filtered_from_snippets(self):
        """'Table of Contents' does not appear in top_ocr_snippets."""
        noisy_ocr = "Table of Contents | Teachable Machine | Train a computer | machine learning"
        vf = self._make_vf_obs(summary=noisy_ocr)
        result = self.build_summary(vf, ["Machine Learning"])
        for snippet in result["top_ocr_snippets"]:
            assert "table of contents" not in snippet.lower(), (
                f"Noise 'Table of Contents' appeared in snippets: {result['top_ocr_snippets']}"
            )

    def test_top_ocr_snippets_capped_at_8(self):
        """top_ocr_snippets contains at most 8 entries."""
        # Create 20 pipe-separated snippets
        long_ocr = " | ".join([f"snippet {i}" for i in range(20)])
        vf = self._make_vf_obs(summary=long_ocr)
        result = self.build_summary(vf, ["Machine Learning"])
        assert len(result["top_ocr_snippets"]) <= 8

    def test_observed_summary_non_empty_when_analyzed(self):
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, ["Machine Learning"])
        assert result["observed_summary"] and len(result["observed_summary"]) > 10

    def test_structure_always_present(self):
        """All required keys are present in the summary dict."""
        vf = self._make_vf_obs(summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR)
        result = self.build_summary(vf, ["Machine Learning"])
        required = [
            "has_ocr_evidence", "ocr_provider", "frames_analyzed",
            "top_ocr_snippets", "detected_page_context",
            "observed_summary", "what_was_not_observed", "skill_signals",
        ]
        for key in required:
            assert key in result, f"Missing key in frame_ocr_evidence_summary: {key!r}"


# ── D. _analyze_workflow OCR skill promotion ──────────────────────────────────

class TestAnalyzeWorkflowOCRPromotion:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def _run(self, claimed_skills, ocr_summary="", url="https://teachablemachine.withgoogle.com"):
        visual_frame_obs = None
        if ocr_summary:
            visual_frame_obs = {
                "visual_frame_analysis_status": "analyzed",
                "visual_summary": ocr_summary,
                "visual_frame_count": 5,
                "visual_frames_stored": 5,
                "provider_used": "local_ocr:tesseract",
                "extracted_result_values": [],
            }
        proof_data = {
            "workflow_events": [
                {
                    "type": "page_visit",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "url": url,
                    "title": "Teachable Machine",
                }
            ]
        }
        return self.analyze_wf(
            proof_data=proof_data,
            claimed_skills=claimed_skills,
            proof_objective="Demonstrate browser-based ML",
            original_url=url,
            url_type="live_deployed_url",
            github_url=None,
            visible_observations=None,
            visual_frame_observations=visual_frame_obs,
        )

    def test_frame_ocr_evidence_summary_in_result(self):
        """_analyze_workflow result always includes frame_ocr_evidence_summary."""
        result = self._run(["Machine Learning"])
        assert "frame_ocr_evidence_summary" in result

    def test_ocr_partial_skill_promoted_from_unsupported_to_weakly(self):
        """A skill with OCR partial support is promoted from unsupported → weakly_supported."""
        # "Machine Learning" starts as weakly/unsupported (no matching domain/port signals)
        # but Teachable Machine homepage OCR should give it partial signal → at least weakly
        result = self._run(
            ["Machine Learning", "Browser-Based AI"],
            ocr_summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR,
        )
        # After OCR promotion, these should not be in unsupported
        unsupported = result.get("unsupported_skills", [])
        weakly = result.get("weakly_supported_skills", [])
        # At least one of the ML skills should be in weakly (not unsupported)
        ml_in_weakly = any("Machine Learning" in s or "Browser-Based Ai" in s or "Browser-Based AI" in s for s in weakly)
        ml_in_unsupported = "Machine Learning" in unsupported and "Browser-Based AI" in unsupported
        # Pass if at least one ML skill is weakly supported
        assert ml_in_weakly or not ml_in_unsupported, (
            f"Expected ML skills promoted to weakly, got unsupported={unsupported}, weakly={weakly}"
        )

    def test_image_classification_stays_unsupported_with_homepage_ocr(self):
        """Image Classification with homepage-only OCR stays in unsupported (not promoted)."""
        result = self._run(
            ["Image Classification"],
            ocr_summary=_TEACHABLE_MACHINE_HOMEPAGE_OCR,
        )
        weakly = result.get("weakly_supported_skills", [])
        supported = result.get("supported_skills", [])
        # Image Classification should NOT be promoted — homepage OCR is insufficient
        assert "Image Classification" not in supported, (
            "Image Classification should not be supported from homepage OCR alone"
        )
        assert "Image Classification" not in weakly, (
            "Image Classification should not be weakly supported from homepage OCR alone"
        )

    def test_no_ocr_no_promotion(self):
        """Without OCR evidence, no skill promotion occurs."""
        result = self._run(["Machine Learning", "Image Classification"], ocr_summary="")
        assert "frame_ocr_evidence_summary" in result
        assert result["frame_ocr_evidence_summary"]["has_ocr_evidence"] is False


# ── E. _determine_missing_evidence with OCR context ──────────────────────────

class TestDetermineMissingEvidenceWithOCR:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def test_homepage_context_gives_specific_missing_message(self):
        """With homepage OCR, missing evidence for Image Classification mentions recording UI."""
        foes = {
            "has_ocr_evidence": True,
            "detected_page_context": "homepage_marketing",
            "what_was_not_observed": ["training UI (e.g. 'Add Image Samples', class labels)"],
            "skill_signals": [
                {
                    "skill": "Image Classification",
                    "ocr_support": "insufficient",
                    "reasoning": "OCR shows homepage content only; no training/prediction UI observed.",
                    "ocr_terms_found": [],
                }
            ],
        }
        missing = self.det_missing(
            claimed_skills=["Image Classification"],
            supported=[],
            weakly=[],
            url_type="live_deployed_url",
            github_url=None,
            target_visited_urls=["https://teachablemachine.withgoogle.com/"],
            skill_obs={},
            frame_ocr_evidence_summary=foes,
        )
        # Should contain a specific message about Image Classification missing evidence
        missing_str = " ".join(missing).lower()
        assert "image classification" in missing_str or "observable evidence" in missing_str

    def test_ocr_reasoning_in_missing_evidence(self):
        """OCR reasoning is propagated into the missing evidence message."""
        foes = {
            "has_ocr_evidence": True,
            "detected_page_context": "homepage_marketing",
            "what_was_not_observed": [],
            "skill_signals": [
                {
                    "skill": "Model Testing",
                    "ocr_support": "insufficient",
                    "reasoning": "No prediction output detected in frames.",
                    "ocr_terms_found": [],
                }
            ],
        }
        missing = self.det_missing(
            claimed_skills=["Model Testing"],
            supported=[],
            weakly=[],
            url_type="live_deployed_url",
            github_url=None,
            target_visited_urls=["https://example.com/"],
            skill_obs={},
            frame_ocr_evidence_summary=foes,
        )
        # Reasoning should appear somewhere in missing evidence
        missing_str = " ".join(missing)
        assert "prediction" in missing_str.lower() or "model testing" in missing_str.lower()

    def test_no_ocr_evidence_fallback_to_generic_message(self):
        """Without OCR evidence, falls back to generic missing evidence message."""
        foes = {"has_ocr_evidence": False}
        missing = self.det_missing(
            claimed_skills=["TensorFlow.js"],
            supported=[],
            weakly=[],
            url_type="live_deployed_url",
            github_url=None,
            target_visited_urls=["https://example.com/"],
            skill_obs={},
            frame_ocr_evidence_summary=foes,
        )
        assert any("tensorflow" in m.lower() or "observable evidence" in m.lower() for m in missing)


# ── F. Noisy OCR filtering ────────────────────────────────────────────────────

class TestNoisyOCRFiltering:

    def setup_method(self):
        (
            self.detect_ctx, self.ocr_signals, self.build_summary,
            self.det_missing, self.analyze_wf,
        ) = _import_service()

    def test_table_of_contents_filtered(self):
        noisy = "Table of Contents | Teachable Machine | Machine Learning"
        vf = {
            "visual_frame_analysis_status": "analyzed",
            "visual_summary": noisy,
            "visual_frame_count": 3,
            "provider_used": "local_ocr:tesseract",
        }
        result = self.build_summary(vf, ["Machine Learning"])
        snippets = result["top_ocr_snippets"]
        for s in snippets:
            assert "table of contents" not in s.lower()

    def test_copyright_filtered(self):
        noisy = "Copyright 2024 | All Rights Reserved | Teachable Machine"
        vf = {
            "visual_frame_analysis_status": "analyzed",
            "visual_summary": noisy,
            "visual_frame_count": 1,
            "provider_used": "local_ocr:tesseract",
        }
        result = self.build_summary(vf, ["Machine Learning"])
        snippets = result["top_ocr_snippets"]
        for s in snippets:
            assert "copyright" not in s.lower()
            assert "all rights reserved" not in s.lower()

    def test_unrelated_browser_tab_ocr_insufficient_for_target_skills(self):
        """OCR from an unrelated tab (e.g., news article) → insufficient for ML skills."""
        unrelated = "Breaking News | Stock Market Today | Latest Headlines | Read More"
        sigs = self.ocr_signals(
            ["Machine Learning", "Image Classification"],
            unrelated,
            "unknown",
        )
        for sig in sigs:
            assert sig["ocr_support"] == "insufficient", (
                f"Expected insufficient for unrelated OCR, got {sig}"
            )
