"""Offline tests for semantic similarity smoke-test configuration."""

from __future__ import annotations

from scripts.run_semantic_similarity_smoke_test import (
    ALIGNED,
    CALIBRATION_EXAMPLES,
    EXPECTED_CAUTIOUS,
    EXPECTED_HIGH,
    EXPECTED_JUDGMENTS,
    EXPECTED_LOW,
    EXPECTED_MEDIUM,
    REVIEW,
    ScoredSmokeTestExample,
    evaluate_alignment,
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
