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
    FullCalibrationComparison,
    GroupCalibrationSummary,
    ScoredSmokeTestExample,
    ThresholdRecommendation,
    build_enriched_calibration_context,
    build_threshold_recommendation,
    classify_enrichment_effect,
    evaluate_alignment,
    score_delta,
    score_bundle_comparisons,
    score_full_calibration_comparisons,
    semantic_similarity_label,
    summarize_full_calibration,
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


def test_every_curated_example_can_build_raw_and_enriched_inputs() -> None:
    for example in CALIBRATION_EXAMPLES:
        context = build_enriched_calibration_context(example)

        assert example.claim.strip()
        assert example.observed.strip()
        assert context["plan"]["feature_to_verify"].strip()
        assert context["plan"]["expected_output"].strip()
        assert context["browser_run"]["safe_text_snapshot"] == example.observed
        assert context["browser_run"]["browser_execution_status"] in {
            "browser_verified",
            "browser_partially_verified",
            "browser_failed",
        }


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


def test_score_delta_and_enrichment_effect_helpers() -> None:
    assert score_delta(0.40, 0.55) == 0.15
    assert score_delta(0.55, 0.40) == -0.15
    assert classify_enrichment_effect(0.04) == "helped"
    assert classify_enrichment_effect(-0.04) == "hurt"
    assert classify_enrichment_effect(0.01) == "stayed_similar"


def test_full_calibration_scoring_returns_valid_comparison_structure() -> None:
    class Provider:
        model_name = "fake-provider"

        def encode(self, texts: list[str]) -> list[list[float]]:
            assert len(texts) == 2
            if "unrelated visible output" in texts[1]:
                return [[1.0, 0.0], [0.0, 1.0]]
            return [[1.0, 0.0], [0.9, 0.1]]

    comparisons = score_full_calibration_comparisons(CALIBRATION_EXAMPLES[:2], Provider())

    assert len(comparisons) == 2
    assert isinstance(comparisons[0], FullCalibrationComparison)
    assert comparisons[0].case_id == 1
    assert comparisons[0].raw_label == "strong_semantic_match"
    assert comparisons[0].enriched_label == "strong_semantic_match"
    assert comparisons[0].claim_bundle.strip()
    assert comparisons[0].observed_bundle.strip()


def test_grouped_full_calibration_summary_aggregates_scores() -> None:
    comparisons = [
        FullCalibrationComparison(1, CALIBRATION_EXAMPLES[0], 0.40, "low_semantic_match", 0.60, "weak_semantic_match", 0.20, "helped", "claim", "observed"),
        FullCalibrationComparison(2, CALIBRATION_EXAMPLES[1], 0.50, "weak_semantic_match", 0.70, "moderate_semantic_match", 0.20, "helped", "claim", "observed"),
        FullCalibrationComparison(5, CALIBRATION_EXAMPLES[4], 0.30, "low_semantic_match", 0.45, "low_semantic_match", 0.15, "helped", "claim", "observed"),
        FullCalibrationComparison(8, CALIBRATION_EXAMPLES[7], 0.10, "low_semantic_match", 0.20, "low_semantic_match", 0.10, "helped", "claim", "observed"),
        FullCalibrationComparison(12, CALIBRATION_EXAMPLES[11], 0.70, "moderate_semantic_match", 0.72, "moderate_semantic_match", 0.02, "stayed_similar", "claim", "observed"),
    ]

    summary = summarize_full_calibration(comparisons)

    assert isinstance(summary[EXPECTED_HIGH], GroupCalibrationSummary)
    assert summary[EXPECTED_HIGH].average_raw_score == 0.45
    assert summary[EXPECTED_HIGH].average_enriched_score == 0.65
    assert summary[EXPECTED_HIGH].average_delta == 0.20
    assert summary[EXPECTED_HIGH].lowest_enriched_score == 0.60
    assert summary[EXPECTED_LOW].highest_enriched_score == 0.20
    assert summary[EXPECTED_CAUTIOUS].suspiciously_high_cases == [12]


def test_threshold_recommendation_helper_returns_valid_structure() -> None:
    comparisons = [
        FullCalibrationComparison(1, CALIBRATION_EXAMPLES[0], 0.40, "low_semantic_match", 0.60, "weak_semantic_match", 0.20, "helped", "claim", "observed"),
        FullCalibrationComparison(8, CALIBRATION_EXAMPLES[7], 0.10, "low_semantic_match", 0.55, "weak_semantic_match", 0.45, "helped", "claim", "observed"),
        FullCalibrationComparison(12, CALIBRATION_EXAMPLES[11], 0.70, "moderate_semantic_match", 0.72, "moderate_semantic_match", 0.02, "stayed_similar", "claim", "observed"),
    ]
    summary = summarize_full_calibration(comparisons)

    recommendation = build_threshold_recommendation(comparisons, summary)

    assert isinstance(recommendation, ThresholdRecommendation)
    assert recommendation.strong_threshold == 0.82
    assert recommendation.moderate_threshold == 0.68
    assert recommendation.weak_threshold == 0.50
    assert recommendation.recommendation in {"too_strict_for_some_true_positives", "reasonable", "too_loose"}
    assert recommendation.false_positive_risk in {"low", "elevated", "high"}
    assert recommendation.reason


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
