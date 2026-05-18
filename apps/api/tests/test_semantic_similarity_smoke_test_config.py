"""Offline tests for semantic similarity smoke-test configuration."""

from __future__ import annotations

from scripts.run_semantic_similarity_smoke_test import (
    ALIGNED,
    BUNDLE_COMPARISON_EXAMPLES,
    CALIBRATION_EXAMPLES,
    EXPECTED_CAUTIOUS,
    EXPECTED_HIGH,
    EXPECTED_JUDGMENTS,
    EXPECTED_LOW,
    EXPECTED_MEDIUM,
    REVIEW,
    ScoredSmokeTestExample,
    evaluate_alignment,
    score_bundle_comparisons,
    semantic_similarity_label,
    summarize_scores,
)


def test_smoke_test_examples_are_valid_and_non_empty() -> None:
    assert len(CALIBRATION_EXAMPLES) == 14
    assert {example.expected_judgment for example in CALIBRATION_EXAMPLES} <= EXPECTED_JUDGMENTS
    assert {EXPECTED_HIGH, EXPECTED_MEDIUM, EXPECTED_LOW, EXPECTED_CAUTIOUS} <= {
        example.expected_judgment for example in CALIBRATION_EXAMPLES
    }
    for example in CALIBRATION_EXAMPLES:
        assert example.claim.strip()
        assert example.observed.strip()
        assert example.group.strip()


def test_bundle_comparison_examples_are_valid() -> None:
    assert BUNDLE_COMPARISON_EXAMPLES
    for example in BUNDLE_COMPARISON_EXAMPLES:
        assert example.name.strip()
        assert example.raw_claim.strip()
        assert example.raw_observed.strip()
        assert example.context["plan"]["feature_to_verify"].strip()
        assert example.context["browser_run"]["safe_text_snapshot"].strip()


def test_alignment_helper_flags_expected_cases() -> None:
    assert evaluate_alignment(EXPECTED_HIGH, 0.83) == ALIGNED
    assert evaluate_alignment(EXPECTED_HIGH, 0.49) == REVIEW
    assert evaluate_alignment(EXPECTED_MEDIUM, 0.70) == ALIGNED
    assert evaluate_alignment(EXPECTED_LOW, 0.90) == REVIEW
    assert evaluate_alignment(EXPECTED_CAUTIOUS, 0.55) == ALIGNED
    assert semantic_similarity_label(0.82) == "strong_semantic_match"


def test_summary_utility_calculates_group_scores_and_overlap_note() -> None:
    scored = [
        ScoredSmokeTestExample(CALIBRATION_EXAMPLES[0], 0.86, "strong_semantic_match", ALIGNED),
        ScoredSmokeTestExample(CALIBRATION_EXAMPLES[1], 0.82, "strong_semantic_match", ALIGNED),
        ScoredSmokeTestExample(CALIBRATION_EXAMPLES[4], 0.70, "moderate_semantic_match", ALIGNED),
        ScoredSmokeTestExample(CALIBRATION_EXAMPLES[7], 0.42, "low_semantic_match", ALIGNED),
        ScoredSmokeTestExample(CALIBRATION_EXAMPLES[8], 0.30, "low_semantic_match", ALIGNED),
    ]

    summary = summarize_scores(scored)

    assert summary["average_high"] == 0.84
    assert summary["average_medium"] == 0.70
    assert summary["average_low"] == 0.36
    assert summary["lowest_high"] == 0.82
    assert summary["highest_low"] == 0.42
    assert summary["suggested_note"] == "Thresholds appear reasonable."


def test_bundle_comparison_scoring_uses_context_bundles() -> None:
    class Provider:
        model_name = "fake-provider"

        def encode(self, texts: list[str]) -> list[list[float]]:
            assert len(texts) == 2
            return [[1.0, 0.0], [0.9, 0.1]]

    scored = score_bundle_comparisons(BUNDLE_COMPARISON_EXAMPLES, Provider())

    assert scored[0].raw_score >= 0.82
    assert scored[0].enriched_score >= 0.82
    assert "The student claims" in scored[0].claim_bundle
    assert "VeriBridge successfully completed" in scored[0].observed_bundle
