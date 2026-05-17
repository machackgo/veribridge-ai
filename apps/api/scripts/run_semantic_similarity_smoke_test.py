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


def main() -> int:
    provider = LocalSentenceEmbeddingProvider()
    try:
        scored = score_examples(CALIBRATION_EXAMPLES, provider)
    except Exception as exc:
        print("Semantic similarity smoke test could not run with the local embedding model.")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Install/cache the configured Sentence Transformers model and rerun this script.")
        print("For a one-time development download, rerun with VERIBRIDGE_ALLOW_MODEL_DOWNLOAD=true.")
        return 1
    print_report(scored, summarize_scores(scored))
    return 0


def _scores_for(scored_examples: list[ScoredSmokeTestExample], expected_judgment: str) -> list[float]:
    return [item.score for item in scored_examples if item.example.expected_judgment == expected_judgment]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _format_optional_score(value: float | str | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
