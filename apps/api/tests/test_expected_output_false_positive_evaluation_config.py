"""Offline tests for expected-output false-positive evaluation configuration."""

from __future__ import annotations

from scripts.run_expected_output_false_positive_evaluation import (
    EVALUATION_SCENARIOS,
    GROUP_BORDERLINE,
    GROUP_FALSE_POSITIVE_TRAP,
    GROUP_GENERIC_OUTPUT,
    GROUP_STRONG_TRUE_POSITIVE,
    INTERPRETATION_BLOCKS,
    INTERPRETATION_NEEDS_REVIEW,
    INTERPRETATION_PARTIAL,
    INTERPRETATION_SUPPORTS,
    VALID_INTERPRETATIONS,
    VALID_SCENARIO_GROUPS,
    FalsePositiveEvaluationResult,
    build_conclusion,
    build_evaluation_context,
    format_before_after_diagnostic,
    summarize_results,
)


def test_evaluation_scenario_set_is_valid_and_non_empty() -> None:
    assert len(EVALUATION_SCENARIOS) == 13
    assert {scenario.group for scenario in EVALUATION_SCENARIOS} <= VALID_SCENARIO_GROUPS
    assert {GROUP_STRONG_TRUE_POSITIVE, GROUP_FALSE_POSITIVE_TRAP, GROUP_GENERIC_OUTPUT, GROUP_BORDERLINE} <= {
        scenario.group for scenario in EVALUATION_SCENARIOS
    }


def test_every_scenario_has_required_text_fields() -> None:
    for scenario in EVALUATION_SCENARIOS:
        assert scenario.scenario_id > 0
        assert scenario.name.strip()
        assert scenario.claim.strip()
        assert scenario.expected_output.strip()
        assert scenario.observed_output.strip()


def test_every_scenario_can_build_evaluation_context() -> None:
    for scenario in EVALUATION_SCENARIOS:
        context = build_evaluation_context(scenario)

        assert context["evidence"]["evidence_description"] == scenario.claim
        assert context["plan"]["expected_output"] == scenario.expected_output
        assert context["browser_run"]["safe_text_snapshot"] == scenario.observed_output
        assert context["browser_steps"][0]["observed_result"] == scenario.observed_output


def test_summary_aggregation_counts_expected_groups() -> None:
    results = [
        _result(0, INTERPRETATION_SUPPORTS),
        _result(1, INTERPRETATION_SUPPORTS),
        _result(2, INTERPRETATION_SUPPORTS),
        _result(3, INTERPRETATION_BLOCKS),
        _result(4, INTERPRETATION_PARTIAL),
        _result(5, INTERPRETATION_NEEDS_REVIEW),
        _result(6, INTERPRETATION_BLOCKS),
        _result(7, INTERPRETATION_BLOCKS),
        _result(8, INTERPRETATION_NEEDS_REVIEW),
        _result(9, INTERPRETATION_BLOCKS),
        _result(10, INTERPRETATION_PARTIAL),
        _result(11, INTERPRETATION_NEEDS_REVIEW),
        _result(12, INTERPRETATION_BLOCKS),
    ]

    summary = summarize_results(results)

    assert summary.strong_true_positive_support_count == 3
    assert summary.strong_true_positive_total == 3
    assert summary.false_positive_trap_blocked_or_downgraded_count == 4
    assert summary.false_positive_trap_total == 4
    assert summary.generic_output_blocked_count == 3
    assert summary.generic_output_total == 3
    assert summary.borderline_cautious_count == 3
    assert summary.borderline_total == 3
    assert summary.suspicious_too_permissive == []
    assert summary.suspicious_too_strict == []
    assert "No production logic changes recommended" in summary.conclusion


def test_before_vs_after_diagnostic_formatter_returns_structured_output() -> None:
    result = _result(3, INTERPRETATION_BLOCKS)

    diagnostic = format_before_after_diagnostic(result)

    assert diagnostic["scenario_id"] == EVALUATION_SCENARIOS[3].scenario_id
    assert diagnostic["semantic_similarity_alone"] == result.semantic_similarity_alone
    assert diagnostic["semantic_similarity_label"] == result.semantic_similarity_label
    assert diagnostic["expected_output_guardrail"] == INTERPRETATION_BLOCKS
    assert diagnostic["expected_output_match_label"] == result.expected_output_match_label
    assert diagnostic["final_interpretation"] == INTERPRETATION_BLOCKS


def test_interpretation_labels_are_valid() -> None:
    assert {INTERPRETATION_SUPPORTS, INTERPRETATION_PARTIAL, INTERPRETATION_BLOCKS, INTERPRETATION_NEEDS_REVIEW} == VALID_INTERPRETATIONS
    for label in VALID_INTERPRETATIONS:
        assert label.strip()


def test_build_conclusion_includes_computed_counts_and_review_note() -> None:
    conclusion = build_conclusion(
        true_positive_support=2,
        true_positive_total=3,
        trap_blocked_or_downgraded=4,
        trap_total=4,
        generic_blocked=3,
        generic_total=3,
        borderline_cautious=3,
        borderline_total=3,
        suspicious_too_permissive=[],
        suspicious_too_strict=[1],
    )

    assert "2/3 strong true-positive cases" in conclusion
    assert "4/4 false-positive traps" in conclusion
    assert "3/3 generic-output cases" in conclusion
    assert "Review whether some true-positive cases" in conclusion


def _result(scenario_index: int, final_interpretation: str) -> FalsePositiveEvaluationResult:
    return FalsePositiveEvaluationResult(
        scenario=EVALUATION_SCENARIOS[scenario_index],
        semantic_similarity_score=0.72,
        semantic_similarity_label="moderate_semantic_match",
        semantic_similarity_alone="maybe_supportive",
        expected_output_match_score=0.42,
        expected_output_match_label="weak_expected_output_match",
        exact_signal_hits=[],
        missing_required_signals=["verification result"],
        blocks_full_verification=final_interpretation != INTERPRETATION_SUPPORTS,
        final_interpretation=final_interpretation,
    )
