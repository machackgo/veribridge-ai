"""Evaluate expected-output guardrails against false-positive website proof cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.website_expected_output_match_service import (  # noqa: E402
    ExpectedOutputMatchResult,
    evaluate_expected_output_match,
)
from app.services.website_semantic_similarity_service import (  # noqa: E402
    LocalSentenceEmbeddingProvider,
    SentenceEmbeddingProvider,
    SemanticSimilarityResult,
    evaluate_semantic_similarity,
    semantic_similarity_label,
)

GROUP_STRONG_TRUE_POSITIVE = "strong_true_positive"
GROUP_FALSE_POSITIVE_TRAP = "false_positive_trap"
GROUP_GENERIC_OUTPUT = "generic_output"
GROUP_BORDERLINE = "borderline"
VALID_SCENARIO_GROUPS = {
    GROUP_STRONG_TRUE_POSITIVE,
    GROUP_FALSE_POSITIVE_TRAP,
    GROUP_GENERIC_OUTPUT,
    GROUP_BORDERLINE,
}

INTERPRETATION_SUPPORTS = "supports_verification"
INTERPRETATION_PARTIAL = "partial_support"
INTERPRETATION_BLOCKS = "blocks_full_verification"
INTERPRETATION_NEEDS_REVIEW = "needs_review"
VALID_INTERPRETATIONS = {
    INTERPRETATION_SUPPORTS,
    INTERPRETATION_PARTIAL,
    INTERPRETATION_BLOCKS,
    INTERPRETATION_NEEDS_REVIEW,
}

SEMANTIC_RELATED = "related"
SEMANTIC_MAYBE_SUPPORTIVE = "maybe_supportive"
SEMANTIC_NOT_SUPPORTIVE = "not_supportive"


@dataclass(frozen=True)
class FalsePositiveEvaluationScenario:
    scenario_id: int
    name: str
    group: str
    claim: str
    expected_output: str
    observed_output: str


@dataclass(frozen=True)
class FalsePositiveEvaluationResult:
    scenario: FalsePositiveEvaluationScenario
    semantic_similarity_score: float | None
    semantic_similarity_label: str
    semantic_similarity_alone: str
    expected_output_match_score: float | None
    expected_output_match_label: str
    exact_signal_hits: list[str]
    missing_required_signals: list[str]
    blocks_full_verification: bool
    final_interpretation: str
    expected_output_notes: str | None = None


@dataclass(frozen=True)
class FalsePositiveEvaluationSummary:
    strong_true_positive_support_count: int
    strong_true_positive_total: int
    false_positive_trap_blocked_or_downgraded_count: int
    false_positive_trap_total: int
    generic_output_blocked_count: int
    generic_output_total: int
    borderline_cautious_count: int
    borderline_total: int
    suspicious_too_permissive: list[int]
    suspicious_too_strict: list[int]
    conclusion: str


EVALUATION_SCENARIOS: list[FalsePositiveEvaluationScenario] = [
    FalsePositiveEvaluationScenario(
        scenario_id=1,
        name="Route risk score and safer route",
        group=GROUP_STRONG_TRUE_POSITIVE,
        claim="This website predicts accident risk for a route and recommends a safer alternative.",
        expected_output="A route risk score and a safer route recommendation should appear.",
        observed_output="Risk Score: High. Safer route available.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=2,
        name="Customized resume draft",
        group=GROUP_STRONG_TRUE_POSITIVE,
        claim="This app generates a customized resume draft from a job description.",
        expected_output="A tailored resume draft should appear after analysis.",
        observed_output="Customized Resume Draft ready for review.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=3,
        name="Python usage verification result",
        group=GROUP_STRONG_TRUE_POSITIVE,
        claim="This tool verifies that Python usage was found in a submitted GitHub project.",
        expected_output="A verification result should confirm Python usage was found.",
        observed_output="Verification result: Python usage found in app/main.py.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=4,
        name="Prediction versus historical counts",
        group=GROUP_FALSE_POSITIVE_TRAP,
        claim="This app predicts accident risk for a route.",
        expected_output="A risk prediction score should appear.",
        observed_output="Historical accident counts by city are displayed.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=5,
        name="Verification versus upload",
        group=GROUP_FALSE_POSITIVE_TRAP,
        claim="This tool verifies GitHub skill evidence.",
        expected_output="A verification result should confirm the selected skill was found.",
        observed_output="GitHub repository uploaded successfully.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=6,
        name="Resume generation versus upload",
        group=GROUP_FALSE_POSITIVE_TRAP,
        claim="This website generates a customized resume draft.",
        expected_output="A tailored resume draft should appear.",
        observed_output="Job description uploaded successfully.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=7,
        name="Visa job recommendation versus preference save",
        group=GROUP_FALSE_POSITIVE_TRAP,
        claim="This platform recommends visa-compatible job opportunities.",
        expected_output="A filtered list of visa-compatible roles should appear.",
        observed_output="Visa preferences saved successfully.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=8,
        name="Route safety generic completion",
        group=GROUP_GENERIC_OUTPUT,
        claim="This website analyzes route safety.",
        expected_output="A route safety score should appear.",
        observed_output="Analysis completed successfully.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=9,
        name="Skill evidence generic done",
        group=GROUP_GENERIC_OUTPUT,
        claim="This tool checks whether evidence supports the selected skill.",
        expected_output="A verification decision should appear.",
        observed_output="Done.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=10,
        name="Salary report generic processed",
        group=GROUP_GENERIC_OUTPUT,
        claim="This system creates a salary comparison report.",
        expected_output="A comparison report should appear.",
        observed_output="Request processed.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=11,
        name="Safer route borderline",
        group=GROUP_BORDERLINE,
        claim="This website recommends safer routes.",
        expected_output="A safer route recommendation should appear.",
        observed_output="Alternative route available.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=12,
        name="Risk score borderline",
        group=GROUP_BORDERLINE,
        claim="This app predicts accident risk.",
        expected_output="A risk score should appear.",
        observed_output="Route score generated.",
    ),
    FalsePositiveEvaluationScenario(
        scenario_id=13,
        name="Resume quality borderline",
        group=GROUP_BORDERLINE,
        claim="This system verifies resume quality.",
        expected_output="A resume quality score should appear.",
        observed_output="Resume analysis complete.",
    ),
]


def build_evaluation_context(scenario: FalsePositiveEvaluationScenario) -> dict[str, Any]:
    return {
        "evidence": {
            "evidence_description": scenario.claim,
        },
        "plan": {
            "feature_to_verify": _claim_as_feature(scenario.claim),
            "expected_output": scenario.expected_output,
            "normalized_test_steps": [
                "Open the submitted website.",
                "Run the relevant public website flow.",
                "Compare the visible final output to the student's expected result.",
            ],
            "sample_inputs": _sample_inputs_for_claim(scenario.claim),
        },
        "static_run": {
            "execution_status": "partial_verification",
            "execution_summary": f"Static inspection found visible text related to the scenario: {scenario.observed_output}",
        },
        "static_checks": [
            {
                "check_status": "passed",
                "observed_value": scenario.observed_output,
                "check_summary": "Static inspection captured the observed output text.",
            }
        ],
        "browser_run": {
            "browser_execution_status": "browser_verified",
            "execution_summary": f"Browser execution completed the flow and observed: {scenario.observed_output}",
            "page_title": scenario.name,
            "safe_text_snapshot": scenario.observed_output,
        },
        "browser_steps": [
            {
                "step_status": "passed",
                "step_summary": "Observed final website output after the verification action.",
                "observed_result": scenario.observed_output,
            }
        ],
    }


def evaluate_scenario(
    scenario: FalsePositiveEvaluationScenario,
    provider: SentenceEmbeddingProvider,
) -> FalsePositiveEvaluationResult:
    context = build_evaluation_context(scenario)
    semantic_result = evaluate_semantic_similarity(context, provider)
    expected_output_result = evaluate_expected_output_match(context, provider)
    final_interpretation = recommend_final_interpretation(semantic_result, expected_output_result)
    return FalsePositiveEvaluationResult(
        scenario=scenario,
        semantic_similarity_score=semantic_result.score,
        semantic_similarity_label=semantic_result.interpretation,
        semantic_similarity_alone=interpret_semantic_similarity_alone(semantic_result.score),
        expected_output_match_score=expected_output_result.score,
        expected_output_match_label=expected_output_result.label,
        exact_signal_hits=expected_output_result.exact_signal_hits,
        missing_required_signals=expected_output_result.missing_required_signals,
        blocks_full_verification=expected_output_result.blocks_full_verification,
        final_interpretation=final_interpretation,
        expected_output_notes=expected_output_result.notes,
    )


def evaluate_scenarios(
    scenarios: list[FalsePositiveEvaluationScenario],
    provider: SentenceEmbeddingProvider,
) -> list[FalsePositiveEvaluationResult]:
    return [evaluate_scenario(scenario, provider) for scenario in scenarios]


def interpret_semantic_similarity_alone(score: float | None) -> str:
    if score is None:
        return SEMANTIC_NOT_SUPPORTIVE
    label = semantic_similarity_label(score)
    if label in {"strong_semantic_match", "moderate_semantic_match"}:
        return SEMANTIC_MAYBE_SUPPORTIVE
    if label == "weak_semantic_match":
        return SEMANTIC_RELATED
    return SEMANTIC_NOT_SUPPORTIVE


def recommend_final_interpretation(
    semantic_result: SemanticSimilarityResult,
    expected_output_result: ExpectedOutputMatchResult,
) -> str:
    semantic_score = semantic_result.score or 0.0
    if expected_output_result.supports_verification and not expected_output_result.blocks_full_verification:
        return INTERPRETATION_SUPPORTS
    if not expected_output_result.blocks_full_verification:
        return INTERPRETATION_PARTIAL
    if expected_output_result.label == "weak_expected_output_match":
        if semantic_score >= 0.68 and expected_output_result.exact_signal_hits:
            return INTERPRETATION_PARTIAL
        if semantic_score >= 0.68:
            return INTERPRETATION_NEEDS_REVIEW
    if expected_output_result.label == "unavailable":
        return INTERPRETATION_NEEDS_REVIEW
    return INTERPRETATION_BLOCKS


def format_before_after_diagnostic(result: FalsePositiveEvaluationResult) -> dict[str, Any]:
    if result.final_interpretation == INTERPRETATION_SUPPORTS:
        guardrail_adjustment = INTERPRETATION_SUPPORTS
    elif result.final_interpretation == INTERPRETATION_PARTIAL:
        guardrail_adjustment = INTERPRETATION_PARTIAL
    elif result.blocks_full_verification:
        guardrail_adjustment = INTERPRETATION_BLOCKS
    else:
        guardrail_adjustment = INTERPRETATION_NEEDS_REVIEW
    return {
        "scenario_id": result.scenario.scenario_id,
        "semantic_similarity_alone": result.semantic_similarity_alone,
        "semantic_similarity_label": result.semantic_similarity_label,
        "expected_output_guardrail": guardrail_adjustment,
        "expected_output_match_label": result.expected_output_match_label,
        "final_interpretation": result.final_interpretation,
    }


def summarize_results(results: list[FalsePositiveEvaluationResult]) -> FalsePositiveEvaluationSummary:
    true_positive_results = _results_for_group(results, GROUP_STRONG_TRUE_POSITIVE)
    trap_results = _results_for_group(results, GROUP_FALSE_POSITIVE_TRAP)
    generic_results = _results_for_group(results, GROUP_GENERIC_OUTPUT)
    borderline_results = _results_for_group(results, GROUP_BORDERLINE)

    true_positive_support = sum(1 for result in true_positive_results if result.final_interpretation == INTERPRETATION_SUPPORTS)
    trap_blocked_or_downgraded = sum(1 for result in trap_results if result.final_interpretation != INTERPRETATION_SUPPORTS)
    generic_blocked = sum(1 for result in generic_results if result.final_interpretation in {INTERPRETATION_BLOCKS, INTERPRETATION_NEEDS_REVIEW})
    borderline_cautious = sum(
        1
        for result in borderline_results
        if result.final_interpretation in {INTERPRETATION_PARTIAL, INTERPRETATION_BLOCKS, INTERPRETATION_NEEDS_REVIEW}
    )

    suspicious_too_permissive = [
        result.scenario.scenario_id
        for result in [*trap_results, *generic_results]
        if result.final_interpretation == INTERPRETATION_SUPPORTS
    ]
    suspicious_too_strict = [
        result.scenario.scenario_id
        for result in true_positive_results
        if result.final_interpretation != INTERPRETATION_SUPPORTS
    ]
    conclusion = build_conclusion(
        true_positive_support,
        len(true_positive_results),
        trap_blocked_or_downgraded,
        len(trap_results),
        generic_blocked,
        len(generic_results),
        borderline_cautious,
        len(borderline_results),
        suspicious_too_permissive,
        suspicious_too_strict,
    )
    return FalsePositiveEvaluationSummary(
        strong_true_positive_support_count=true_positive_support,
        strong_true_positive_total=len(true_positive_results),
        false_positive_trap_blocked_or_downgraded_count=trap_blocked_or_downgraded,
        false_positive_trap_total=len(trap_results),
        generic_output_blocked_count=generic_blocked,
        generic_output_total=len(generic_results),
        borderline_cautious_count=borderline_cautious,
        borderline_total=len(borderline_results),
        suspicious_too_permissive=suspicious_too_permissive,
        suspicious_too_strict=suspicious_too_strict,
        conclusion=conclusion,
    )


def build_conclusion(
    true_positive_support: int,
    true_positive_total: int,
    trap_blocked_or_downgraded: int,
    trap_total: int,
    generic_blocked: int,
    generic_total: int,
    borderline_cautious: int,
    borderline_total: int,
    suspicious_too_permissive: list[int],
    suspicious_too_strict: list[int],
) -> str:
    if not suspicious_too_permissive and not suspicious_too_strict:
        recommendation = "No production logic changes recommended."
    elif suspicious_too_permissive:
        recommendation = "Review guardrail strictness before loosening any verification thresholds."
    else:
        recommendation = "Review whether some true-positive cases need richer observed output signals."
    return (
        f"Expected-output matching preserved {true_positive_support}/{true_positive_total} strong true-positive cases, "
        f"blocked or downgraded {trap_blocked_or_downgraded}/{trap_total} false-positive traps, "
        f"blocked {generic_blocked}/{generic_total} generic-output cases, and kept "
        f"{borderline_cautious}/{borderline_total} borderline cases cautious. {recommendation}"
    )


def print_report(results: list[FalsePositiveEvaluationResult], summary: FalsePositiveEvaluationSummary) -> None:
    print("VeriBridge Expected-Output False-Positive Evaluation")
    print("=" * 72)
    for result in results:
        diagnostic = format_before_after_diagnostic(result)
        print(f"\nScenario {result.scenario.scenario_id}: {result.scenario.name}")
        print(f"Group:                  {result.scenario.group}")
        print(f"Claim:                  {result.scenario.claim}")
        print(f"Expected output:        {result.scenario.expected_output}")
        print(f"Observed output:         {result.scenario.observed_output}")
        print(f"Semantic score:         {_format_optional_score(result.semantic_similarity_score)}")
        print(f"Semantic label:         {result.semantic_similarity_label}")
        print(f"Semantic alone:         {diagnostic['semantic_similarity_alone']}")
        print(f"Expected-output score:  {_format_optional_score(result.expected_output_match_score)}")
        print(f"Expected-output label:  {result.expected_output_match_label}")
        print(f"Signal hits:            {_format_list(result.exact_signal_hits)}")
        print(f"Missing signals:        {_format_list(result.missing_required_signals)}")
        print(f"Blocks full verified:   {result.blocks_full_verification}")
        print(f"Guardrail adjustment:   {diagnostic['expected_output_guardrail']}")
        print(f"Final interpretation:   {result.final_interpretation}")
        if result.expected_output_notes:
            print(f"Notes:                  {result.expected_output_notes}")

    print("\nEvaluation Summary")
    print("-" * 72)
    print(
        "Strong true positives supporting verification: "
        f"{summary.strong_true_positive_support_count}/{summary.strong_true_positive_total}"
    )
    print(
        "False-positive traps blocked/downgraded:       "
        f"{summary.false_positive_trap_blocked_or_downgraded_count}/{summary.false_positive_trap_total}"
    )
    print(
        "Generic-output cases blocked:                  "
        f"{summary.generic_output_blocked_count}/{summary.generic_output_total}"
    )
    print(
        "Borderline cases kept cautious:                "
        f"{summary.borderline_cautious_count}/{summary.borderline_total}"
    )
    print(f"Suspicious too permissive cases:               {_format_int_list(summary.suspicious_too_permissive)}")
    print(f"Suspicious too strict cases:                   {_format_int_list(summary.suspicious_too_strict)}")
    print("\nConclusion")
    print("-" * 72)
    print(summary.conclusion)


def main() -> int:
    provider = LocalSentenceEmbeddingProvider()
    try:
        results = evaluate_scenarios(EVALUATION_SCENARIOS, provider)
    except Exception as exc:
        print("Expected-output false-positive evaluation could not run with the local embedding model.")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Install/cache the configured Sentence Transformers model and rerun this script.")
        print("For a one-time development download, rerun with VERIBRIDGE_ALLOW_MODEL_DOWNLOAD=true.")
        return 1
    print_report(results, summarize_results(results))
    return 0


def _results_for_group(
    results: list[FalsePositiveEvaluationResult],
    group: str,
) -> list[FalsePositiveEvaluationResult]:
    return [result for result in results if result.scenario.group == group]


def _claim_as_feature(claim: str) -> str:
    claim = claim.strip().rstrip(".")
    lowered = claim.lower()
    for prefix in ("this website ", "this app ", "this tool ", "this platform ", "this system "):
        if lowered.startswith(prefix):
            return claim[len(prefix) :]
    return claim


def _sample_inputs_for_claim(claim: str) -> dict[str, str]:
    lowered = claim.lower()
    if "route" in lowered:
        return {"source": "Boston", "destination": "Cambridge"}
    if "resume" in lowered or "job description" in lowered:
        return {"job_description": "Software engineer role", "resume": "Student resume"}
    if "github" in lowered or "python" in lowered:
        return {"repository": "student/project-proof"}
    if "visa" in lowered or "job" in lowered:
        return {"work_authorization": "F-1 OPT", "role": "Software Engineer"}
    if "salary" in lowered:
        return {"city_a": "Boston", "city_b": "Austin"}
    return {}


def _format_optional_score(value: float | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/a"


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_int_list(values: list[int]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


if __name__ == "__main__":
    raise SystemExit(main())
