"""Run local semantic similarity smoke tests for website proof examples."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.website_expected_output_match_service import evaluate_expected_output_match  # noqa: E402
from app.services.website_semantic_similarity_service import (  # noqa: E402
    LocalSentenceEmbeddingProvider,
    build_claim_semantic_bundle,
    build_observed_semantic_bundle,
    compute_embedding_similarity,
    semantic_similarity_label,
)

EXPECTED_HIGH = "should_be_high"
EXPECTED_MEDIUM = "should_be_medium"
EXPECTED_LOW = "should_be_low"
EXPECTED_CAUTIOUS = "should_be_cautious"
EXPECTED_JUDGMENTS = {EXPECTED_HIGH, EXPECTED_MEDIUM, EXPECTED_LOW, EXPECTED_CAUTIOUS}

ALIGNED = "aligned"
REVIEW = "review_thresholds"


@dataclass(frozen=True)
class SmokeTestExample:
    claim: str
    observed: str
    expected_judgment: str
    group: str


@dataclass(frozen=True)
class ScoredSmokeTestExample:
    example: SmokeTestExample
    score: float
    label: str
    alignment: str


@dataclass(frozen=True)
class BundleComparisonExample:
    name: str
    raw_claim: str
    raw_observed: str
    context: dict


@dataclass(frozen=True)
class ScoredBundleComparison:
    example: BundleComparisonExample
    raw_score: float
    raw_label: str
    enriched_score: float
    enriched_label: str
    claim_bundle: str
    observed_bundle: str


@dataclass(frozen=True)
class ExpectedOutputFalsePositiveCase:
    name: str
    expected_output: str
    observed_output: str
    expected_decision: str


CALIBRATION_EXAMPLES: list[SmokeTestExample] = [
    SmokeTestExample(
        claim="This website recommends a safer route.",
        observed="Alternative low-risk path available.",
        expected_judgment=EXPECTED_HIGH,
        group="strong_expected_matches",
    ),
    SmokeTestExample(
        claim="This app predicts accident risk for a route.",
        observed="Route risk score: High.",
        expected_judgment=EXPECTED_HIGH,
        group="strong_expected_matches",
    ),
    SmokeTestExample(
        claim="This dashboard shows a salary comparison by city.",
        observed="Average compensation across selected locations.",
        expected_judgment=EXPECTED_HIGH,
        group="strong_expected_matches",
    ),
    SmokeTestExample(
        claim="This tool verifies a student's GitHub project evidence.",
        observed="Proof file validated from the submitted repository.",
        expected_judgment=EXPECTED_HIGH,
        group="strong_expected_matches",
    ),
    SmokeTestExample(
        claim="This app helps students find visa-compatible job opportunities.",
        observed="Work authorization filters are available for job search.",
        expected_judgment=EXPECTED_MEDIUM,
        group="moderate_expected_matches",
    ),
    SmokeTestExample(
        claim="This platform identifies better locations for a target role.",
        observed="Opportunity score is higher in California than Massachusetts.",
        expected_judgment=EXPECTED_MEDIUM,
        group="moderate_expected_matches",
    ),
    SmokeTestExample(
        claim="This feature explains recruiter-facing proof of skills.",
        observed="Recruiters can review attached evidence.",
        expected_judgment=EXPECTED_MEDIUM,
        group="moderate_expected_matches",
    ),
    SmokeTestExample(
        claim="This website recommends a safer route.",
        observed="Welcome to the student dashboard.",
        expected_judgment=EXPECTED_LOW,
        group="low_expected_matches",
    ),
    SmokeTestExample(
        claim="This tool analyzes compensation across cities.",
        observed="Upload your profile photo.",
        expected_judgment=EXPECTED_LOW,
        group="low_expected_matches",
    ),
    SmokeTestExample(
        claim="This app verifies AI project evidence.",
        observed="Terms of service and privacy policy.",
        expected_judgment=EXPECTED_LOW,
        group="low_expected_matches",
    ),
    SmokeTestExample(
        claim="This platform supports visa-aware job search.",
        observed="Contact support for billing issues.",
        expected_judgment=EXPECTED_LOW,
        group="low_expected_matches",
    ),
    SmokeTestExample(
        claim="This app predicts accident risk.",
        observed="This app displays historical accident counts.",
        expected_judgment=EXPECTED_CAUTIOUS,
        group="tricky_close_but_not_equivalent",
    ),
    SmokeTestExample(
        claim="This tool verifies whether a skill was demonstrated.",
        observed="This tool allows students to upload a skill description.",
        expected_judgment=EXPECTED_CAUTIOUS,
        group="tricky_close_but_not_equivalent",
    ),
    SmokeTestExample(
        claim="This website recommends safer routes.",
        observed="This website displays a map.",
        expected_judgment=EXPECTED_CAUTIOUS,
        group="tricky_close_but_not_equivalent",
    ),
]


BUNDLE_COMPARISON_EXAMPLES: list[BundleComparisonExample] = [
    BundleComparisonExample(
        name="Safer route recommendation",
        raw_claim="This website recommends a safer route.",
        raw_observed="Alternative low-risk path available.",
        context={
            "evidence": {
                "evidence_description": "This website analyzes accident risk for a route and recommends a safer route after the user enters trip locations.",
            },
            "plan": {
                "feature_to_verify": "analyzes route accident risk after a user enters source and destination locations, then recommends a safer alternative route",
                "expected_output": "A route risk score and safer route recommendation appear on the results section.",
                "normalized_test_steps": [
                    "Enter a source location.",
                    "Enter a destination location.",
                    "Click the route analysis action.",
                    "Confirm that route risk and safer-route output appears.",
                ],
                "sample_inputs": {"source": "Boston", "destination": "Cambridge"},
            },
            "static_run": {
                "execution_status": "partial_verification",
                "execution_summary": "Static checks found route risk and safer route language.",
            },
            "static_checks": [
                {
                    "check_status": "passed",
                    "observed_value": "route risk score safer route",
                    "check_summary": "Matched visible route risk and rerouting terminology.",
                }
            ],
            "browser_run": {
                "browser_execution_status": "browser_verified",
                "execution_summary": "Browser execution entered source and destination inputs, triggered route analysis, and reached the result page.",
                "page_title": "Route Risk Analyzer",
                "safe_text_snapshot": "Risk Score: High. Safer route available. Alternative low-risk path available.",
            },
            "browser_steps": [
                {
                    "step_status": "passed",
                    "step_summary": "Entered source and destination route inputs.",
                    "observed_result": "Route form accepted both locations.",
                },
                {
                    "step_status": "passed",
                    "step_summary": "Clicked Analyze Route and observed route risk results.",
                    "observed_result": "Risk Score: High and Safer route available.",
                },
            ],
        },
    )
]


EXPECTED_OUTPUT_FALSE_POSITIVE_CASES: list[ExpectedOutputFalsePositiveCase] = [
    ExpectedOutputFalsePositiveCase(
        name="Good route-risk output",
        expected_output="A risk score and safer route recommendation should appear.",
        observed_output="Risk Score: High. Safer route available.",
        expected_decision="supports verification",
    ),
    ExpectedOutputFalsePositiveCase(
        name="Prediction vs historical counts",
        expected_output="A risk score and accident-risk prediction should appear.",
        observed_output="Historical accident counts by city are displayed.",
        expected_decision="blocks full verification",
    ),
    ExpectedOutputFalsePositiveCase(
        name="Verification vs upload",
        expected_output="A verification result should confirm the selected skill was found.",
        observed_output="GitHub repository uploaded successfully.",
        expected_decision="blocks full verification",
    ),
]


def evaluate_alignment(expected_judgment: str, score: float) -> str:
    label = semantic_similarity_label(score)
    if expected_judgment == EXPECTED_HIGH:
        return ALIGNED if label in {"strong_semantic_match", "moderate_semantic_match"} else REVIEW
    if expected_judgment == EXPECTED_MEDIUM:
        return ALIGNED if label in {"moderate_semantic_match", "weak_semantic_match"} else REVIEW
    if expected_judgment == EXPECTED_LOW:
        return ALIGNED if label in {"low_semantic_match", "weak_semantic_match"} else REVIEW
    if expected_judgment == EXPECTED_CAUTIOUS:
        return ALIGNED if label in {"low_semantic_match", "weak_semantic_match", "moderate_semantic_match"} else REVIEW
    return REVIEW


def score_examples(
    examples: list[SmokeTestExample],
    provider: LocalSentenceEmbeddingProvider,
) -> list[ScoredSmokeTestExample]:
    scored: list[ScoredSmokeTestExample] = []
    for example in examples:
        score = compute_embedding_similarity(example.claim, example.observed, provider)
        if score is None:
            raise RuntimeError("Semantic similarity service returned no score for a smoke-test example.")
        label = semantic_similarity_label(score)
        scored.append(
            ScoredSmokeTestExample(
                example=example,
                score=score,
                label=label,
                alignment=evaluate_alignment(example.expected_judgment, score),
            )
        )
    return scored


def score_bundle_comparisons(
    examples: list[BundleComparisonExample],
    provider: LocalSentenceEmbeddingProvider,
) -> list[ScoredBundleComparison]:
    scored: list[ScoredBundleComparison] = []
    for example in examples:
        raw_score = compute_embedding_similarity(example.raw_claim, example.raw_observed, provider)
        claim_bundle = build_claim_semantic_bundle(example.context)
        observed_bundle = build_observed_semantic_bundle(example.context)
        enriched_score = compute_embedding_similarity(claim_bundle, observed_bundle, provider)
        if raw_score is None or enriched_score is None:
            raise RuntimeError("Semantic similarity service returned no score for a bundle comparison example.")
        scored.append(
            ScoredBundleComparison(
                example=example,
                raw_score=raw_score,
                raw_label=semantic_similarity_label(raw_score),
                enriched_score=enriched_score,
                enriched_label=semantic_similarity_label(enriched_score),
                claim_bundle=claim_bundle,
                observed_bundle=observed_bundle,
            )
        )
    return scored


def summarize_scores(scored_examples: list[ScoredSmokeTestExample]) -> dict[str, float | str | None]:
    high_scores = _scores_for(scored_examples, EXPECTED_HIGH)
    medium_scores = _scores_for(scored_examples, EXPECTED_MEDIUM)
    low_scores = _scores_for(scored_examples, EXPECTED_LOW)
    highest_low = max(low_scores) if low_scores else None
    lowest_high = min(high_scores) if high_scores else None
    overlap = highest_low is not None and lowest_high is not None and highest_low >= lowest_high
    review_count = sum(1 for item in scored_examples if item.alignment == REVIEW)
    if overlap:
        suggested_note = "Review thresholds: some high/low examples overlap."
    elif review_count:
        suggested_note = "Review thresholds: some examples missed their expected score band."
    else:
        suggested_note = "Thresholds appear reasonable."
    return {
        "average_high": _average(high_scores),
        "average_medium": _average(medium_scores),
        "average_low": _average(low_scores),
        "lowest_high": lowest_high,
        "highest_low": highest_low,
        "review_count": float(review_count),
        "suggested_note": suggested_note,
    }


def print_report(scored_examples: list[ScoredSmokeTestExample], summary: dict[str, float | str | None]) -> None:
    print("VeriBridge Semantic Similarity Smoke Test")
    print("=" * 48)
    for index, item in enumerate(scored_examples, start=1):
        print(f"\n{index}. {item.example.group}")
        print(f"Claim:    {item.example.claim}")
        print(f"Observed: {item.example.observed}")
        print(f"Score:    {item.score:.4f}")
        print(f"Label:    {item.label}")
        print(f"Expected: {item.example.expected_judgment}")
        print(f"Review:   {item.alignment}")
    print("\nSummary")
    print("-" * 48)
    print(f"Average expected high score:   {_format_optional_score(summary['average_high'])}")
    print(f"Average expected medium score: {_format_optional_score(summary['average_medium'])}")
    print(f"Average expected low score:    {_format_optional_score(summary['average_low'])}")
    print(f"Lowest high-example score:     {_format_optional_score(summary['lowest_high'])}")
    print(f"Highest low-example score:     {_format_optional_score(summary['highest_low'])}")
    print(f"Potential review count:        {int(summary['review_count'] or 0)}")
    print(f"Suggested note:                {summary['suggested_note']}")


def print_bundle_comparison_report(scored_comparisons: list[ScoredBundleComparison]) -> None:
    print("\nRaw vs Enriched Semantic Bundle Comparison")
    print("=" * 48)
    for item in scored_comparisons:
        print(f"\nCase: {item.example.name}")
        print("Raw short text score:")
        print(f"  {item.raw_score:.4f} ({item.raw_label})")
        print("Enriched bundle score:")
        print(f"  {item.enriched_score:.4f} ({item.enriched_label})")
        print("Claim bundle preview:")
        print(f"  {item.claim_bundle[:220]}")
        print("Observed bundle preview:")
        print(f"  {item.observed_bundle[:220]}")


def print_expected_output_false_positive_report(
    cases: list[ExpectedOutputFalsePositiveCase],
    provider: LocalSentenceEmbeddingProvider,
) -> None:
    print("\nExpected Output Match False-Positive Cases")
    print("=" * 48)
    for case in cases:
        result = evaluate_expected_output_match(
            {
                "plan": {
                    "feature_to_verify": case.expected_output,
                    "expected_output": case.expected_output,
                    "normalized_test_steps": ["Run the website flow.", "Confirm expected output."],
                },
                "browser_run": {
                    "browser_execution_status": "browser_verified",
                    "execution_summary": "Browser flow produced visible output.",
                    "safe_text_snapshot": case.observed_output,
                },
                "browser_steps": [
                    {
                        "step_status": "passed",
                        "observed_result": case.observed_output,
                        "step_summary": "Observed final website output.",
                    }
                ],
                "static_run": None,
                "static_checks": [],
            },
            provider,
        )
        print(f"\nCase: {case.name}")
        print(f"Expected output: {case.expected_output}")
        print(f"Observed output:  {case.observed_output}")
        print(f"Score:           {_format_optional_score(result.score)}")
        print(f"Label:           {result.label}")
        print(f"Signal hits:     {', '.join(result.exact_signal_hits) or 'none'}")
        print(f"Signal misses:   {', '.join(result.missing_required_signals) or 'none'}")
        print(f"Expected:        {case.expected_decision}")
        print(f"Blocks verified: {result.blocks_full_verification}")


def main() -> int:
    provider = LocalSentenceEmbeddingProvider()
    try:
        scored = score_examples(CALIBRATION_EXAMPLES, provider)
        bundle_comparisons = score_bundle_comparisons(BUNDLE_COMPARISON_EXAMPLES, provider)
    except Exception as exc:
        print("Semantic similarity smoke test could not run with the local embedding model.")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Install/cache the configured Sentence Transformers model and rerun this script.")
        print("For a one-time development download, rerun with VERIBRIDGE_ALLOW_MODEL_DOWNLOAD=true.")
        return 1
    print_report(scored, summarize_scores(scored))
    print_bundle_comparison_report(bundle_comparisons)
    print_expected_output_false_positive_report(EXPECTED_OUTPUT_FALSE_POSITIVE_CASES, provider)
    return 0


def _scores_for(scored_examples: list[ScoredSmokeTestExample], expected_judgment: str) -> list[float]:
    return [item.score for item in scored_examples if item.example.expected_judgment == expected_judgment]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _format_optional_score(value: float | str | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
