"""Run local semantic similarity smoke tests for website proof examples."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
EXPECTED_DISPLAY_NAMES = {
    EXPECTED_HIGH: "should_be_high",
    EXPECTED_MEDIUM: "should_be_medium",
    EXPECTED_LOW: "should_be_low",
    EXPECTED_CAUTIOUS: "tricky_borderline",
}

ALIGNED = "aligned"
REVIEW = "review_thresholds"
HELPED = "helped"
HURT = "hurt"
SIMILAR = "stayed_similar"


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
class FullCalibrationComparison:
    case_id: int
    example: SmokeTestExample
    raw_score: float
    raw_label: str
    enriched_score: float
    enriched_label: str
    score_delta: float
    enrichment_effect: str
    claim_bundle: str
    observed_bundle: str


@dataclass(frozen=True)
class GroupCalibrationSummary:
    expected_judgment: str
    average_raw_score: float | None
    average_enriched_score: float | None
    average_delta: float | None
    lowest_enriched_score: float | None = None
    highest_enriched_score: float | None = None
    suspiciously_high_cases: list[int] | None = None


@dataclass(frozen=True)
class ThresholdRecommendation:
    strong_threshold: float
    moderate_threshold: float
    weak_threshold: float
    recommendation: str
    reason: str
    false_positive_risk: str


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


def score_full_calibration_comparisons(
    examples: list[SmokeTestExample],
    provider: LocalSentenceEmbeddingProvider,
) -> list[FullCalibrationComparison]:
    comparisons: list[FullCalibrationComparison] = []
    for index, example in enumerate(examples, start=1):
        raw_score = compute_embedding_similarity(example.claim, example.observed, provider)
        context = build_enriched_calibration_context(example)
        claim_bundle = build_claim_semantic_bundle(context)
        observed_bundle = build_observed_semantic_bundle(context)
        enriched_score = compute_embedding_similarity(claim_bundle, observed_bundle, provider)
        if raw_score is None or enriched_score is None:
            raise RuntimeError("Semantic similarity service returned no score for a full calibration comparison.")
        delta = score_delta(raw_score, enriched_score)
        comparisons.append(
            FullCalibrationComparison(
                case_id=index,
                example=example,
                raw_score=raw_score,
                raw_label=semantic_similarity_label(raw_score),
                enriched_score=enriched_score,
                enriched_label=semantic_similarity_label(enriched_score),
                score_delta=delta,
                enrichment_effect=classify_enrichment_effect(delta),
                claim_bundle=claim_bundle,
                observed_bundle=observed_bundle,
            )
        )
    return comparisons


def build_enriched_calibration_context(example: SmokeTestExample) -> dict:
    browser_status = _browser_status_for_expected_judgment(example.expected_judgment)
    static_status = _static_status_for_expected_judgment(example.expected_judgment)
    return {
        "evidence": {
            "evidence_description": f"Calibration claim for website proof verification: {example.claim}",
        },
        "plan": {
            "feature_to_verify": _claim_as_feature(example.claim),
            "expected_output": _claim_as_expected_output(example.claim),
            "normalized_test_steps": _steps_for_expected_judgment(example.expected_judgment),
            "sample_inputs": _sample_inputs_for_claim(example.claim),
        },
        "static_run": {
            "execution_status": static_status,
            "execution_summary": _static_summary_for_expected_judgment(example),
        },
        "static_checks": [
            {
                "check_status": "passed" if example.expected_judgment in {EXPECTED_HIGH, EXPECTED_MEDIUM, EXPECTED_CAUTIOUS} else "failed",
                "observed_value": example.observed,
                "check_summary": _static_check_summary_for_expected_judgment(example),
            }
        ],
        "browser_run": {
            "browser_execution_status": browser_status,
            "execution_summary": _browser_summary_for_expected_judgment(example),
            "page_title": _page_title_for_claim(example.claim),
            "safe_text_snapshot": example.observed,
        },
        "browser_steps": [
            {
                "step_status": "passed" if example.expected_judgment == EXPECTED_HIGH else ("failed" if example.expected_judgment == EXPECTED_LOW else "needs_human_review"),
                "step_summary": _browser_step_summary_for_expected_judgment(example),
                "observed_result": example.observed,
            }
        ],
    }


def score_delta(raw_score: float, enriched_score: float) -> float:
    return round(enriched_score - raw_score, 4)


def classify_enrichment_effect(delta: float) -> str:
    if delta >= 0.03:
        return HELPED
    if delta <= -0.03:
        return HURT
    return SIMILAR


def summarize_full_calibration(
    comparisons: list[FullCalibrationComparison],
) -> dict[str, GroupCalibrationSummary]:
    summaries: dict[str, GroupCalibrationSummary] = {}
    for expected in [EXPECTED_HIGH, EXPECTED_MEDIUM, EXPECTED_LOW, EXPECTED_CAUTIOUS]:
        group = [item for item in comparisons if item.example.expected_judgment == expected]
        raw_scores = [item.raw_score for item in group]
        enriched_scores = [item.enriched_score for item in group]
        deltas = [item.score_delta for item in group]
        suspicious = [item.case_id for item in group if expected == EXPECTED_CAUTIOUS and item.enriched_score >= 0.68]
        summaries[expected] = GroupCalibrationSummary(
            expected_judgment=expected,
            average_raw_score=_average(raw_scores),
            average_enriched_score=_average(enriched_scores),
            average_delta=_average(deltas),
            lowest_enriched_score=min(enriched_scores) if expected == EXPECTED_HIGH and enriched_scores else None,
            highest_enriched_score=max(enriched_scores) if expected == EXPECTED_LOW and enriched_scores else None,
            suspiciously_high_cases=suspicious if expected == EXPECTED_CAUTIOUS else None,
        )
    return summaries


def build_threshold_recommendation(
    comparisons: list[FullCalibrationComparison],
    summaries: dict[str, GroupCalibrationSummary],
) -> ThresholdRecommendation:
    high_summary = summaries[EXPECTED_HIGH]
    low_summary = summaries[EXPECTED_LOW]
    cautious_summary = summaries[EXPECTED_CAUTIOUS]
    high_improved = (high_summary.average_delta or 0.0) > 0.0
    highest_low = low_summary.highest_enriched_score or 0.0
    suspicious_cases = cautious_summary.suspiciously_high_cases or []
    false_positive_risk = "low"
    if highest_low >= 0.50 or suspicious_cases:
        false_positive_risk = "elevated"
    if highest_low >= 0.68:
        false_positive_risk = "high"

    if false_positive_risk != "low":
        recommendation = "reasonable"
        reason = (
            "Current production thresholds should remain unchanged for now. Enriched bundles improved some positive examples, "
            "but low or tricky examples also reached score ranges where loosening thresholds would increase false-positive risk."
        )
    elif high_improved and high_summary.lowest_enriched_score is not None and high_summary.lowest_enriched_score < 0.68:
        recommendation = "too_strict_for_some_true_positives"
        reason = (
            "Moderate threshold may be considered for future review, but no production change is made in this phase because "
            "the calibration set is still small."
        )
    else:
        recommendation = "reasonable"
        reason = "Current production thresholds should remain unchanged for now."

    if all(item.enriched_score >= 0.82 for item in comparisons if item.example.expected_judgment == EXPECTED_LOW):
        recommendation = "too_loose"
        reason = "Low examples are scoring as strong matches, so thresholds should be reviewed before relying on similarity."

    return ThresholdRecommendation(
        strong_threshold=0.82,
        moderate_threshold=0.68,
        weak_threshold=0.50,
        recommendation=recommendation,
        reason=reason,
        false_positive_risk=false_positive_risk,
    )


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


def print_full_calibration_report(
    comparisons: list[FullCalibrationComparison],
    summaries: dict[str, GroupCalibrationSummary],
    recommendation: ThresholdRecommendation,
) -> None:
    print("\nFull Raw vs Enriched Calibration")
    print("=" * 72)
    for item in comparisons:
        print(f"\nCase {item.case_id}: {item.example.group}")
        print(f"Expected category: {EXPECTED_DISPLAY_NAMES[item.example.expected_judgment]}")
        print(f"Raw score:         {item.raw_score:.4f} ({item.raw_label})")
        print(f"Enriched score:    {item.enriched_score:.4f} ({item.enriched_label})")
        print(f"Score delta:       {item.score_delta:+.4f}")
        print(f"Enrichment effect: {item.enrichment_effect}")
        print(f"Claim:             {item.example.claim}")
        print(f"Observed:          {item.example.observed}")

    print("\nGrouped Calibration Summary")
    print("-" * 72)
    for expected in [EXPECTED_HIGH, EXPECTED_MEDIUM, EXPECTED_LOW, EXPECTED_CAUTIOUS]:
        summary = summaries[expected]
        print(f"\n{EXPECTED_DISPLAY_NAMES[expected]}")
        print(f"  Average raw score:      {_format_optional_score(summary.average_raw_score)}")
        print(f"  Average enriched score: {_format_optional_score(summary.average_enriched_score)}")
        print(f"  Average delta:          {_format_optional_score(summary.average_delta)}")
        if summary.lowest_enriched_score is not None:
            print(f"  Lowest enriched score:  {_format_optional_score(summary.lowest_enriched_score)}")
        if summary.highest_enriched_score is not None:
            print(f"  Highest enriched score: {_format_optional_score(summary.highest_enriched_score)}")
        if summary.suspiciously_high_cases is not None:
            cases = ", ".join(str(case_id) for case_id in summary.suspiciously_high_cases) or "none"
            print(f"  Suspiciously high cases: {cases}")

    high_delta = summaries[EXPECTED_HIGH].average_delta or 0.0
    low_delta = summaries[EXPECTED_LOW].average_delta or 0.0
    print("\nCalibration Interpretation")
    print("-" * 72)
    print(f"True-positive alignment: {'improved' if high_delta > 0 else 'not clearly improved'}")
    print(f"False-positive inflation: {'observed' if low_delta > 0.03 or recommendation.false_positive_risk != 'low' else 'not clearly observed'}")
    print(f"Threshold posture: {recommendation.recommendation}")
    print("\nThreshold Recommendation")
    print("-" * 72)
    print(f"strong:   keep at {recommendation.strong_threshold:.2f}")
    print(f"moderate: keep at {recommendation.moderate_threshold:.2f}")
    print(f"weak:     keep at {recommendation.weak_threshold:.2f}")
    print(f"False-positive risk: {recommendation.false_positive_risk}")
    print(f"Reason: {recommendation.reason}")


def main() -> int:
    provider = LocalSentenceEmbeddingProvider()
    try:
        scored = score_examples(CALIBRATION_EXAMPLES, provider)
        bundle_comparisons = score_bundle_comparisons(BUNDLE_COMPARISON_EXAMPLES, provider)
        full_comparisons = score_full_calibration_comparisons(CALIBRATION_EXAMPLES, provider)
    except Exception as exc:
        print("Semantic similarity smoke test could not run with the local embedding model.")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Install/cache the configured Sentence Transformers model and rerun this script.")
        print("For a one-time development download, rerun with VERIBRIDGE_ALLOW_MODEL_DOWNLOAD=true.")
        return 1
    print_report(scored, summarize_scores(scored))
    print_bundle_comparison_report(bundle_comparisons)
    full_summary = summarize_full_calibration(full_comparisons)
    print_full_calibration_report(full_comparisons, full_summary, build_threshold_recommendation(full_comparisons, full_summary))
    return 0


def _scores_for(scored_examples: list[ScoredSmokeTestExample], expected_judgment: str) -> list[float]:
    return [item.score for item in scored_examples if item.example.expected_judgment == expected_judgment]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _format_optional_score(value: float | str | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/a"


def _claim_as_feature(claim: str) -> str:
    claim = claim.strip().rstrip(".")
    lowered = claim.lower()
    for prefix in ("this website ", "this app ", "this dashboard ", "this tool ", "this platform ", "this feature "):
        if lowered.startswith(prefix):
            return claim[len(prefix) :]
    return claim


def _claim_as_expected_output(claim: str) -> str:
    return f"Visible website output should support the claim: {claim.rstrip('.')}."


def _browser_status_for_expected_judgment(expected_judgment: str) -> str:
    if expected_judgment == EXPECTED_HIGH:
        return "browser_verified"
    if expected_judgment == EXPECTED_LOW:
        return "browser_failed"
    return "browser_partially_verified"


def _static_status_for_expected_judgment(expected_judgment: str) -> str:
    if expected_judgment == EXPECTED_HIGH:
        return "static_verified"
    if expected_judgment == EXPECTED_LOW:
        return "failed_static_checks"
    return "partial_verification"


def _steps_for_expected_judgment(expected_judgment: str) -> list[str]:
    if expected_judgment == EXPECTED_LOW:
        return ["Open the submitted website.", "Look for visible output that supports the claimed feature."]
    return ["Open the submitted website.", "Run the relevant website flow.", "Confirm the visible output matches the claimed feature."]


def _sample_inputs_for_claim(claim: str) -> dict[str, str]:
    lowered = claim.lower()
    if "route" in lowered:
        return {"source": "Boston", "destination": "Cambridge"}
    if "salary" in lowered or "compensation" in lowered:
        return {"city_a": "New York", "city_b": "Austin"}
    if "visa" in lowered or "job" in lowered:
        return {"work_authorization": "F-1 OPT", "role": "Software Engineer"}
    if "github" in lowered or "project" in lowered:
        return {"repository": "student/project-proof"}
    return {}


def _browser_summary_for_expected_judgment(example: SmokeTestExample) -> str:
    if example.expected_judgment == EXPECTED_HIGH:
        return f"Browser verification completed the relevant flow and observed visible output: {example.observed}"
    if example.expected_judgment == EXPECTED_MEDIUM:
        return f"Browser verification observed related supporting output, but the flow did not fully confirm every part of the claim: {example.observed}"
    if example.expected_judgment == EXPECTED_LOW:
        return f"Browser verification attempted the claimed flow but observed unrelated visible output: {example.observed}"
    return f"Browser verification observed related but not equivalent output that should be treated cautiously: {example.observed}"


def _browser_step_summary_for_expected_judgment(example: SmokeTestExample) -> str:
    if example.expected_judgment == EXPECTED_LOW:
        return "The observed page text did not demonstrate the claimed website behavior."
    if example.expected_judgment == EXPECTED_CAUTIOUS:
        return "The observed page text was related to the topic but did not fully demonstrate the claimed behavior."
    return "The observed page text provided semantic evidence related to the claimed website behavior."


def _static_summary_for_expected_judgment(example: SmokeTestExample) -> str:
    if example.expected_judgment == EXPECTED_LOW:
        return "Static checks did not find clear evidence for the claimed website behavior."
    if example.expected_judgment == EXPECTED_CAUTIOUS:
        return "Static checks found related terms, but the observed evidence may not be equivalent to the claim."
    return "Static checks found language related to the claimed website behavior."


def _static_check_summary_for_expected_judgment(example: SmokeTestExample) -> str:
    if example.expected_judgment == EXPECTED_LOW:
        return "Observed text did not match the expected claim."
    if example.expected_judgment == EXPECTED_CAUTIOUS:
        return "Observed text was topically related but may be incomplete."
    return "Observed text matched related feature terminology."


def _page_title_for_claim(claim: str) -> str:
    lowered = claim.lower()
    if "route" in lowered:
        return "Route Analysis"
    if "salary" in lowered or "compensation" in lowered:
        return "Compensation Dashboard"
    if "visa" in lowered or "job" in lowered:
        return "Job Search"
    if "github" in lowered or "project" in lowered or "skill" in lowered:
        return "Proof Verification"
    return "Student Website"


if __name__ == "__main__":
    raise SystemExit(main())
