"""Offline tests for GitHub false-positive reduction evaluation configuration."""

from __future__ import annotations

from scripts.run_github_false_positive_reduction_evaluation import (
    EVALUATION_SCENARIOS,
    GROUP_BORDERLINE,
    GROUP_FALSE_POSITIVE_TRAP,
    GROUP_GENERIC_INCOMPLETE,
    GROUP_STRONG_TRUE_POSITIVE,
    RECOMMENDATION_BLOCKED,
    RECOMMENDATION_INSUFFICIENT,
    RECOMMENDATION_PARTIAL_OR_REVIEW,
    RECOMMENDATION_VERIFIED,
    VALID_RECOMMENDATIONS,
    VALID_SCENARIO_GROUPS,
    GitHubFalsePositiveEvaluationResult,
    build_conclusion,
    build_evaluation_context,
    format_before_after_diagnostic,
    format_result,
    summarize_result_dicts,
    summarize_results,
)


def test_evaluation_scenario_set_is_non_empty_and_valid() -> None:
    assert len(EVALUATION_SCENARIOS) == 13
    assert {scenario.group for scenario in EVALUATION_SCENARIOS} <= VALID_SCENARIO_GROUPS
    assert {GROUP_STRONG_TRUE_POSITIVE, GROUP_FALSE_POSITIVE_TRAP, GROUP_GENERIC_INCOMPLETE, GROUP_BORDERLINE} <= {
        scenario.group for scenario in EVALUATION_SCENARIOS
    }


def test_every_scenario_has_required_fields_and_segments() -> None:
    for scenario in EVALUATION_SCENARIOS:
        assert scenario.scenario_id > 0
        assert scenario.name.strip()
        assert scenario.group in VALID_SCENARIO_GROUPS
        assert scenario.claim.strip()
        assert scenario.code_segments
        assert scenario.expected_interpretation in VALID_RECOMMENDATIONS
        assert scenario.overall_code_summary.strip()


def test_every_scenario_can_build_evaluation_context() -> None:
    for scenario in EVALUATION_SCENARIOS:
        context = build_evaluation_context(scenario)
        assert context["available"] is True
        assert context["evidence"]["evidence_description"] == scenario.claim
        assert context["segmentation"].available is True
        assert context["segmentation"].overall_summary == scenario.overall_code_summary
        assert len(context["segmentation"].segments) == len(scenario.code_segments)


def test_summary_aggregation_counts_expected_groups() -> None:
    results = [
        _result(0, RECOMMENDATION_VERIFIED),
        _result(1, RECOMMENDATION_VERIFIED),
        _result(2, RECOMMENDATION_VERIFIED),
        _result(3, RECOMMENDATION_BLOCKED),
        _result(4, RECOMMENDATION_BLOCKED),
        _result(5, RECOMMENDATION_BLOCKED),
        _result(6, RECOMMENDATION_PARTIAL_OR_REVIEW),
        _result(7, RECOMMENDATION_BLOCKED),
        _result(8, RECOMMENDATION_BLOCKED),
        _result(9, RECOMMENDATION_BLOCKED),
        _result(10, RECOMMENDATION_PARTIAL_OR_REVIEW),
        _result(11, RECOMMENDATION_PARTIAL_OR_REVIEW),
        _result(12, RECOMMENDATION_PARTIAL_OR_REVIEW),
    ]

    summary = summarize_results(results)

    assert summary.strong_true_positive_support_count == 3
    assert summary.strong_true_positive_total == 3
    assert summary.false_positive_trap_blocked_or_downgraded_count == 4
    assert summary.false_positive_trap_total == 4
    assert summary.generic_incomplete_kept_cautious_count == 3
    assert summary.generic_incomplete_total == 3
    assert summary.borderline_cautious_count == 3
    assert summary.borderline_total == 3
    assert summary.suspicious_too_permissive == []
    assert summary.suspicious_too_strict == []
    assert summary.production_logic_trustworthy is True
    assert summary.bug_or_logic_adjustment_recommended is False
    assert "No production logic changes recommended." in summary.conclusion


def test_before_vs_after_diagnostic_formatter_returns_structured_output() -> None:
    result = _result(3, RECOMMENDATION_BLOCKED)
    diagnostic = format_before_after_diagnostic(result)

    assert diagnostic["scenario_id"] == EVALUATION_SCENARIOS[3].scenario_id
    assert diagnostic["scenario_group"] == EVALUATION_SCENARIOS[3].group
    assert diagnostic["semantic_similarity_alone"] == result.semantic_similarity_alone
    assert diagnostic["capability_guardrail"] == "blocks_full_verification"
    assert diagnostic["final_interpretation"] == RECOMMENDATION_BLOCKED


def test_result_formatter_returns_structured_output() -> None:
    result = _result(0, RECOMMENDATION_VERIFIED)
    formatted = format_result(result)

    assert formatted["scenario_id"] == result.scenario.scenario_id
    assert formatted["group"] == result.scenario.group
    assert formatted["final_interpretation"] == RECOMMENDATION_VERIFIED
    assert formatted["matched_segments"]
    assert formatted["matched_segments"][0]["line_start"] == result.matched_segments[0].line_start


def test_recommendation_labels_are_valid() -> None:
    assert VALID_RECOMMENDATIONS == {
        RECOMMENDATION_VERIFIED,
        RECOMMENDATION_PARTIAL_OR_REVIEW,
        RECOMMENDATION_BLOCKED,
        RECOMMENDATION_INSUFFICIENT,
    }


def test_borderline_scenarios_are_represented() -> None:
    borderline_ids = [scenario.scenario_id for scenario in EVALUATION_SCENARIOS if scenario.group == GROUP_BORDERLINE]
    assert borderline_ids == [11, 12, 13]


def test_summarize_result_dicts_works_offline() -> None:
    dict_results = [format_result(_result(index, RECOMMENDATION_VERIFIED if index < 3 else RECOMMENDATION_BLOCKED)) for index in range(len(EVALUATION_SCENARIOS))]
    summary = summarize_result_dicts(dict_results)
    assert summary["strong_true_positive_preserved"] == 3
    assert summary["false_positive_traps_blocked_or_downgraded"] == 4
    assert summary["generic_incomplete_kept_cautious"] == 3
    assert summary["borderline_kept_cautious"] == 3


def test_build_conclusion_includes_counts_and_recommendation_note() -> None:
    conclusion = build_conclusion(
        3,
        3,
        4,
        4,
        3,
        3,
        3,
        3,
        [],
        [],
        True,
        False,
    )

    assert "3/3 strong true-positive cases" in conclusion
    assert "4/4 false-positive traps" in conclusion
    assert "Production logic appears trustworthy." in conclusion
    assert "No production logic changes recommended." in conclusion


def _result(scenario_index: int, final_interpretation: str) -> GitHubFalsePositiveEvaluationResult:
    scenario = EVALUATION_SCENARIOS[scenario_index]
    return GitHubFalsePositiveEvaluationResult(
        scenario=scenario,
        semantic_status="verified" if final_interpretation == RECOMMENDATION_VERIFIED else "not_verified",
        confidence_score=0.92 if final_interpretation == RECOMMENDATION_VERIFIED else 0.61,
        semantic_similarity_score=0.88,
        semantic_similarity_label="strong_semantic_match",
        semantic_similarity_alone="supports_verification" if final_interpretation == RECOMMENDATION_VERIFIED else "related",
        capability_match_status="strong_capability_match" if final_interpretation == RECOMMENDATION_VERIFIED else "capability_mismatch",
        blocks_full_verification=final_interpretation != RECOMMENDATION_VERIFIED,
        extracted_requirements=[],
        satisfied_requirements=[],
        missing_critical_requirements=[],
        final_interpretation=final_interpretation,
        reason="Offline test fixture.",
        matched_segments=[scenario.code_segments[0]],
        expected_interpretation=scenario.expected_interpretation,
    )
