"""Evaluate GitHub capability-matching guardrails against false positives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.github_claim_capability_match_service import GitHubClaimCapabilityMatchResult  # noqa: E402
from app.services.github_claim_code_semantic_verification_service import (  # noqa: E402
    GitHubClaimCodeSemanticEvaluationResult,
    GitHubClaimCodeSegmentMatch,
    GitHubSemanticVerificationService,
)
from app.services.github_code_evidence_segmentation_service import (  # noqa: E402
    GitHubCodeEvidenceSegment,
    GitHubCodeEvidenceSegmentationResult,
)
from app.services.website_semantic_similarity_service import LocalSentenceEmbeddingProvider  # noqa: E402

GROUP_STRONG_TRUE_POSITIVE = "strong_true_positive"
GROUP_FALSE_POSITIVE_TRAP = "false_positive_trap"
GROUP_GENERIC_INCOMPLETE = "generic_incomplete"
GROUP_BORDERLINE = "borderline"
VALID_SCENARIO_GROUPS = {
    GROUP_STRONG_TRUE_POSITIVE,
    GROUP_FALSE_POSITIVE_TRAP,
    GROUP_GENERIC_INCOMPLETE,
    GROUP_BORDERLINE,
}

RECOMMENDATION_VERIFIED = "verified_allowed"
RECOMMENDATION_PARTIAL_OR_REVIEW = "partial_or_review"
RECOMMENDATION_BLOCKED = "blocked_not_verified"
RECOMMENDATION_INSUFFICIENT = "insufficient_evidence"
VALID_RECOMMENDATIONS = {
    RECOMMENDATION_VERIFIED,
    RECOMMENDATION_PARTIAL_OR_REVIEW,
    RECOMMENDATION_BLOCKED,
    RECOMMENDATION_INSUFFICIENT,
}

SEMANTIC_SUPPORTS = "supports_verification"
SEMANTIC_MAYBE_SUPPORTIVE = "maybe_supportive"
SEMANTIC_RELATED = "related"
SEMANTIC_NOT_SUPPORTIVE = "not_supportive"


def _segment(
    index: int,
    line_start: int,
    line_end: int,
    summary: str,
    segment_type: str,
    detected_signals: list[str],
    supports_skill: bool = True,
    confidence_hint: str = "high",
) -> GitHubCodeEvidenceSegment:
    return GitHubCodeEvidenceSegment(
        segment_index=index,
        line_start=line_start,
        line_end=line_end,
        code_excerpt=summary,
        segment_type=segment_type,
        detected_signals=detected_signals,
        summary=summary,
        supports_skill=supports_skill,
        confidence_hint=confidence_hint,
    )


@dataclass(frozen=True)
class GitHubFalsePositiveEvaluationScenario:
    scenario_id: int
    name: str
    group: str
    skill_name: str
    claim: str
    code_segments: list[GitHubCodeEvidenceSegment]
    overall_code_summary: str
    expected_interpretation: str


@dataclass(frozen=True)
class GitHubFalsePositiveEvaluationResult:
    scenario: GitHubFalsePositiveEvaluationScenario
    semantic_status: str
    confidence_score: float
    semantic_similarity_score: float | None
    semantic_similarity_label: str
    semantic_similarity_alone: str
    capability_match_status: str
    blocks_full_verification: bool
    extracted_requirements: list[dict[str, Any]]
    satisfied_requirements: list[dict[str, Any]]
    missing_critical_requirements: list[dict[str, Any]]
    final_interpretation: str
    reason: str
    matched_segments: list[GitHubClaimCodeSegmentMatch]
    expected_interpretation: str
    evaluation_notes: str | None = None


@dataclass(frozen=True)
class GitHubFalsePositiveEvaluationSummary:
    strong_true_positive_support_count: int
    strong_true_positive_total: int
    false_positive_trap_blocked_or_downgraded_count: int
    false_positive_trap_total: int
    generic_incomplete_kept_cautious_count: int
    generic_incomplete_total: int
    borderline_cautious_count: int
    borderline_total: int
    suspicious_too_permissive: list[int]
    suspicious_too_strict: list[int]
    production_logic_trustworthy: bool
    bug_or_logic_adjustment_recommended: bool
    conclusion: str


EVALUATION_SCENARIOS: list[GitHubFalsePositiveEvaluationScenario] = [
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=1,
        name="Complete ML workflow",
        group=GROUP_STRONG_TRUE_POSITIVE,
        skill_name="Machine Learning",
        claim="I built and evaluated a Decision Tree classification model for stroke prediction.",
        code_segments=[
            _segment(1, 20, 28, "Initializes a DecisionTreeClassifier for stroke prediction.", "model_training", ["DecisionTreeClassifier", "classifier ="]),
            _segment(2, 30, 36, "Trains the Decision Tree classifier on the training set with fit().", "model_training", ["fit(", "X_train", "y_train"]),
            _segment(3, 38, 44, "Generates stroke predictions on the test set using predict().", "prediction_inference", ["predict(", "y_pred"]),
            _segment(4, 46, 58, "Evaluates stroke prediction performance with accuracy_score and f1_score.", "evaluation_metrics", ["accuracy_score", "f1_score"]),
        ],
        overall_code_summary="The selected code demonstrates a Decision Tree classification workflow for stroke prediction with model initialization, training, prediction, and evaluation.",
        expected_interpretation=RECOMMENDATION_VERIFIED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=2,
        name="API plus database write",
        group=GROUP_STRONG_TRUE_POSITIVE,
        skill_name="Backend Development",
        claim="I built a FastAPI endpoint that stores submitted student evidence in a database.",
        code_segments=[
            _segment(1, 12, 22, "Defines a POST FastAPI endpoint for submitted student evidence.", "api_endpoint", ["FastAPI", "@app.post"]),
            _segment(2, 24, 35, "Inserts the submitted student evidence into the database.", "database_logic", ["insert(", "supabase"]),
            _segment(3, 37, 42, "Returns a saved evidence response after the database write.", "database_logic", ["save", "response"]),
        ],
        overall_code_summary="The selected code defines a FastAPI POST endpoint that stores submitted student evidence in a database and returns the saved response.",
        expected_interpretation=RECOMMENDATION_VERIFIED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=3,
        name="Authentication and protected routes",
        group=GROUP_STRONG_TRUE_POSITIVE,
        skill_name="Backend Development",
        claim="I implemented JWT authentication and protected API routes.",
        code_segments=[
            _segment(1, 10, 18, "Parses the Authorization header for the JWT bearer token.", "authentication_logic", ["Authorization", "token"]),
            _segment(2, 20, 33, "Validates the JWT token before protected access.", "authentication_logic", ["jwt", "token", "session"]),
            _segment(3, 35, 43, "Uses an authenticated user dependency in a protected API route.", "api_endpoint", ["protected", "auth", "@app.get"]),
        ],
        overall_code_summary="The selected code demonstrates JWT authentication and protected API route handling with an authenticated user dependency.",
        expected_interpretation=RECOMMENDATION_VERIFIED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=4,
        name="ML-related but no training or evaluation",
        group=GROUP_FALSE_POSITIVE_TRAP,
        skill_name="Machine Learning",
        claim="I built and evaluated a machine learning classification model.",
        code_segments=[
            _segment(1, 10, 18, "Loads CSV data with pandas.", "data_preprocessing", ["read_csv"]),
            _segment(2, 20, 26, "Cleans missing values.", "data_preprocessing", ["dropna", "fillna"]),
            _segment(3, 28, 35, "Splits the data into train and test sets.", "data_preprocessing", ["train_test_split"]),
        ],
        overall_code_summary="The selected code prepares data but does not show model training, prediction, or evaluation.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=5,
        name="Prediction claim with preprocessing only",
        group=GROUP_FALSE_POSITIVE_TRAP,
        skill_name="Machine Learning",
        claim="I created a model that predicts loan default risk.",
        code_segments=[
            _segment(1, 5, 14, "Encodes categorical columns.", "data_preprocessing", ["LabelEncoder", "OneHotEncoder"]),
            _segment(2, 16, 24, "Scales numerical features.", "data_preprocessing", ["StandardScaler"]),
            _segment(3, 26, 30, "Prepares X and y arrays.", "data_preprocessing", ["X", "y"]),
        ],
        overall_code_summary="The selected code only shows preprocessing steps and does not show training or prediction.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=6,
        name="API schema without route logic",
        group=GROUP_FALSE_POSITIVE_TRAP,
        skill_name="Backend Development",
        claim="I built an API that evaluates resumes and returns a verification result.",
        code_segments=[
            _segment(1, 8, 16, "Defines a Pydantic request model.", "generic_logic", ["BaseModel", "schema"]),
            _segment(2, 18, 24, "Defines a response schema.", "generic_logic", ["BaseModel", "response"]),
        ],
        overall_code_summary="The selected code defines request and response schemas but no API route or business logic.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=7,
        name="Authentication claim with generic route only",
        group=GROUP_FALSE_POSITIVE_TRAP,
        skill_name="Backend Development",
        claim="I implemented secure authentication for protected recruiter endpoints.",
        code_segments=[
            _segment(1, 12, 20, "Defines a recruiter API route.", "api_endpoint", ["FastAPI", "@app.get"]),
            _segment(2, 22, 30, "Returns a recruiter candidate list.", "api_endpoint", ["route", "response"]),
        ],
        overall_code_summary="The selected code defines a route but does not show authentication checks or protected access logic.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=8,
        name="ML imports only",
        group=GROUP_GENERIC_INCOMPLETE,
        skill_name="Machine Learning",
        claim="I built a Random Forest model for disease prediction.",
        code_segments=[
            _segment(1, 1, 6, "Imports pandas and RandomForestClassifier.", "generic_logic", ["pandas", "RandomForestClassifier"]),
        ],
        overall_code_summary="The selected code only shows imports and does not show model training, prediction, or evaluation.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=9,
        name="Database claim with variable names only",
        group=GROUP_GENERIC_INCOMPLETE,
        skill_name="Backend Development",
        claim="I stored verified proof records in Supabase.",
        code_segments=[
            _segment(1, 4, 10, "Defines a supabase_client variable.", "generic_logic", ["supabase_client"]),
        ],
        overall_code_summary="The selected code mentions a Supabase client but does not show an insert, update, or write operation.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=10,
        name="Visualization claim with generic UI code",
        group=GROUP_GENERIC_INCOMPLETE,
        skill_name="Frontend Development",
        claim="I created a dashboard that visualizes job opportunity heatmaps.",
        code_segments=[
            _segment(1, 10, 18, "Defines a React component layout.", "ui_component", ["React", "useState", "className="]),
            _segment(2, 20, 28, "Renders generic containers and buttons.", "ui_component", ["<div", "<button"]),
        ],
        overall_code_summary="The selected code defines UI layout but no chart, plot, heatmap, or other visualization rendering.",
        expected_interpretation=RECOMMENDATION_BLOCKED,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=11,
        name="Training shown, evaluation missing",
        group=GROUP_BORDERLINE,
        skill_name="Machine Learning",
        claim="I trained and evaluated a Logistic Regression model.",
        code_segments=[
            _segment(1, 22, 30, "Initializes LogisticRegression.", "model_training", ["LogisticRegression"]),
            _segment(2, 32, 38, "Calls fit() on the training data.", "model_training", ["fit(", "X_train"]),
        ],
        overall_code_summary="The selected code shows model training but not evaluation metrics.",
        expected_interpretation=RECOMMENDATION_PARTIAL_OR_REVIEW,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=12,
        name="API route with ambiguous database helper",
        group=GROUP_BORDERLINE,
        skill_name="Backend Development",
        claim="I built a submission endpoint that stores data in the database.",
        code_segments=[
            _segment(1, 10, 22, "Defines a POST route for submissions.", "api_endpoint", ["FastAPI", "@app.post"]),
            _segment(2, 24, 30, "Calls helper save_submission(...).", "generic_logic", ["save_submission"]),
        ],
        overall_code_summary="The selected code shows an endpoint and an ambiguous helper call, but the database write is not visible.",
        expected_interpretation=RECOMMENDATION_PARTIAL_OR_REVIEW,
    ),
    GitHubFalsePositiveEvaluationScenario(
        scenario_id=13,
        name="Prediction shown but model origin unclear",
        group=GROUP_BORDERLINE,
        skill_name="Machine Learning",
        claim="I built a model that predicts applicant job fit.",
        code_segments=[
            _segment(1, 41, 48, "Calls model.predict(features).", "prediction_inference", ["predict(", "y_pred"]),
        ],
        overall_code_summary="The selected code shows prediction inference but not model initialization or training.",
        expected_interpretation=RECOMMENDATION_PARTIAL_OR_REVIEW,
    ),
]


def build_evaluation_context(scenario: GitHubFalsePositiveEvaluationScenario) -> dict[str, Any]:
    segmentation = GitHubCodeEvidenceSegmentationResult(
        available=True,
        skill_name=scenario.skill_name,
        total_segments=len(scenario.code_segments),
        segments=scenario.code_segments,
        overall_summary=scenario.overall_code_summary,
        notes=None,
    )
    evidence = {
        "skill_name": scenario.skill_name,
        "evidence_description": scenario.claim,
        "evidence_type": "GitHub file",
        "metadata": {"title": scenario.name},
    }
    return {
        "available": True,
        "evidence": evidence,
        "claim_text": scenario.claim,
        "segmentation": segmentation,
    }


def evaluate_scenario(
    scenario: GitHubFalsePositiveEvaluationScenario,
    service: GitHubSemanticVerificationService,
) -> GitHubFalsePositiveEvaluationResult:
    context = build_evaluation_context(scenario)
    evaluation = service.evaluate_semantically(context)
    capability_match = service.evaluate_claim_capability_match(context)
    overall_match = service.evaluate_claim_against_overall_code_summary(context)
    segment_matches = evaluation.matched_segments

    recommended = recommend_final_interpretation(evaluation, capability_match, overall_match, segment_matches)
    reason = build_reason(evaluation, capability_match, overall_match, segment_matches, recommended)
    return GitHubFalsePositiveEvaluationResult(
        scenario=scenario,
        semantic_status=evaluation.semantic_status,
        confidence_score=evaluation.confidence_score,
        semantic_similarity_score=overall_match.get("score"),
        semantic_similarity_label=overall_match.get("label") or "unavailable",
        semantic_similarity_alone=interpret_semantic_similarity_alone(overall_match, segment_matches),
        capability_match_status=capability_match.capability_match_status,
        blocks_full_verification=capability_match.blocks_full_verification,
        extracted_requirements=[_requirement_to_dict(item) for item in capability_match.extracted_requirements],
        satisfied_requirements=capability_match.satisfied_requirements,
        missing_critical_requirements=capability_match.missing_critical_requirements,
        final_interpretation=recommended,
        reason=reason,
        matched_segments=segment_matches,
        expected_interpretation=scenario.expected_interpretation,
        evaluation_notes=evaluation.internal_reasoning_summary,
    )


def evaluate_scenarios(
    scenarios: list[GitHubFalsePositiveEvaluationScenario],
    service: GitHubSemanticVerificationService,
) -> list[GitHubFalsePositiveEvaluationResult]:
    return [evaluate_scenario(scenario, service) for scenario in scenarios]


def interpret_semantic_similarity_alone(
    overall_match: dict[str, Any],
    segment_matches: list[GitHubClaimCodeSegmentMatch],
) -> str:
    scores = [float(overall_match.get("score") or 0.0)]
    scores.extend(float(match.semantic_score or 0.0) for match in segment_matches)
    strongest = max(scores) if scores else 0.0
    supportive = sum(1 for match in segment_matches if match.semantic_score is not None and match.semantic_score >= 0.68)
    if strongest >= 0.82 and supportive >= 2:
        return SEMANTIC_SUPPORTS
    if strongest >= 0.68 or supportive >= 1:
        return SEMANTIC_MAYBE_SUPPORTIVE
    if strongest >= 0.50:
        return SEMANTIC_RELATED
    return SEMANTIC_NOT_SUPPORTIVE


def recommend_final_interpretation(
    evaluation: GitHubClaimCodeSemanticEvaluationResult,
    capability_match: GitHubClaimCapabilityMatchResult,
    overall_match: dict[str, Any],
    segment_matches: list[GitHubClaimCodeSegmentMatch],
) -> str:
    if evaluation.semantic_status == "insufficient_evidence" or not capability_match.available:
        return RECOMMENDATION_INSUFFICIENT
    overall_score = float(overall_match.get("score") or 0.0)
    strongest_score = max((float(match.semantic_score or 0.0) for match in segment_matches), default=0.0)
    supportive_count = sum(1 for match in segment_matches if match.semantic_score is not None and match.semantic_score >= 0.55)

    if capability_match.blocks_full_verification:
        if evaluation.semantic_status in {"partially_verified", "needs_human_review"} and overall_score >= 0.50:
            return RECOMMENDATION_PARTIAL_OR_REVIEW
        return RECOMMENDATION_BLOCKED

    if capability_match.supports_full_verification:
        return RECOMMENDATION_VERIFIED

    if overall_score >= 0.70 and strongest_score >= 0.55 and supportive_count >= 1:
        return RECOMMENDATION_VERIFIED
    if evaluation.semantic_status == "verified" and overall_score >= 0.68:
        return RECOMMENDATION_VERIFIED
    if evaluation.semantic_status in {"partially_verified", "needs_human_review"} and overall_score >= 0.60:
        return RECOMMENDATION_PARTIAL_OR_REVIEW
    return RECOMMENDATION_BLOCKED


def build_reason(
    evaluation: GitHubClaimCodeSemanticEvaluationResult,
    capability_match: GitHubClaimCapabilityMatchResult,
    overall_match: dict[str, Any],
    segment_matches: list[GitHubClaimCodeSegmentMatch],
    recommended: str,
) -> str:
    strongest = _strongest_match(segment_matches)
    if recommended == RECOMMENDATION_VERIFIED:
        if strongest:
            return (
                f"Strong semantic support and complete capability coverage were found, with the strongest match at "
                f"lines {strongest.line_start}-{strongest.line_end}."
            )
        return "Strong semantic support and complete capability coverage were found."
    if capability_match.blocks_full_verification:
        missing = ", ".join(item.get("requirement_label") or item.get("requirement_key") for item in capability_match.missing_critical_requirements[:3])
        if missing:
            return f"Critical capabilities were missing: {missing}."
        return "The code looked related, but the required capabilities were not sufficiently demonstrated."
    if evaluation.semantic_status in {"partially_verified", "needs_human_review"}:
        return "The code is related, but the selected lines do not fully prove every claimed capability."
    score = overall_match.get("score")
    if score is not None:
        return f"Semantic similarity was {float(score):.2f}, but the code evidence was not strong enough for full verification."
    return "The available evidence was too weak for a reliable judgment."


def summarize_results(results: list[GitHubFalsePositiveEvaluationResult]) -> GitHubFalsePositiveEvaluationSummary:
    true_positive_results = _results_for_group(results, GROUP_STRONG_TRUE_POSITIVE)
    trap_results = _results_for_group(results, GROUP_FALSE_POSITIVE_TRAP)
    generic_results = _results_for_group(results, GROUP_GENERIC_INCOMPLETE)
    borderline_results = _results_for_group(results, GROUP_BORDERLINE)

    true_positive_support = sum(1 for result in true_positive_results if result.final_interpretation == RECOMMENDATION_VERIFIED)
    trap_blocked_or_downgraded = sum(1 for result in trap_results if result.final_interpretation != RECOMMENDATION_VERIFIED)
    generic_cautious = sum(1 for result in generic_results if result.final_interpretation != RECOMMENDATION_VERIFIED)
    borderline_cautious = sum(1 for result in borderline_results if result.final_interpretation != RECOMMENDATION_VERIFIED)

    suspicious_too_permissive = [
        result.scenario.scenario_id
        for result in [*trap_results, *generic_results]
        if result.final_interpretation == RECOMMENDATION_VERIFIED
    ]
    suspicious_too_strict = [
        result.scenario.scenario_id
        for result in true_positive_results
        if result.final_interpretation != RECOMMENDATION_VERIFIED
    ]
    production_logic_trustworthy = not suspicious_too_permissive and not suspicious_too_strict
    bug_or_logic_adjustment_recommended = bool(suspicious_too_permissive or suspicious_too_strict)
    conclusion = build_conclusion(
        true_positive_support,
        len(true_positive_results),
        trap_blocked_or_downgraded,
        len(trap_results),
        generic_cautious,
        len(generic_results),
        borderline_cautious,
        len(borderline_results),
        suspicious_too_permissive,
        suspicious_too_strict,
        production_logic_trustworthy,
        bug_or_logic_adjustment_recommended,
    )
    return GitHubFalsePositiveEvaluationSummary(
        strong_true_positive_support_count=true_positive_support,
        strong_true_positive_total=len(true_positive_results),
        false_positive_trap_blocked_or_downgraded_count=trap_blocked_or_downgraded,
        false_positive_trap_total=len(trap_results),
        generic_incomplete_kept_cautious_count=generic_cautious,
        generic_incomplete_total=len(generic_results),
        borderline_cautious_count=borderline_cautious,
        borderline_total=len(borderline_results),
        suspicious_too_permissive=suspicious_too_permissive,
        suspicious_too_strict=suspicious_too_strict,
        production_logic_trustworthy=production_logic_trustworthy,
        bug_or_logic_adjustment_recommended=bug_or_logic_adjustment_recommended,
        conclusion=conclusion,
    )


def build_conclusion(
    true_positive_support: int,
    true_positive_total: int,
    trap_blocked_or_downgraded: int,
    trap_total: int,
    generic_cautious: int,
    generic_total: int,
    borderline_cautious: int,
    borderline_total: int,
    suspicious_too_permissive: list[int],
    suspicious_too_strict: list[int],
    production_logic_trustworthy: bool,
    bug_or_logic_adjustment_recommended: bool,
) -> str:
    if not suspicious_too_permissive and not suspicious_too_strict:
        recommendation = "No production logic changes recommended."
    elif suspicious_too_permissive:
        recommendation = "Review guardrail strictness before loosening any verification logic."
    else:
        recommendation = "Review whether some true-positive cases need richer code evidence."
    trust_note = "Production logic appears trustworthy." if production_logic_trustworthy else "Production logic needs review."
    bug_note = " A bug or logic adjustment is recommended." if bug_or_logic_adjustment_recommended else ""
    return (
        f"Expected-output-capability matching preserved {true_positive_support}/{true_positive_total} strong true-positive cases, "
        f"blocked or downgraded {trap_blocked_or_downgraded}/{trap_total} false-positive traps, kept "
        f"{generic_cautious}/{generic_total} generic/incomplete cases cautious, and kept "
        f"{borderline_cautious}/{borderline_total} borderline cases cautious. {trust_note} {recommendation}{bug_note}"
    )


def print_report(results: list[GitHubFalsePositiveEvaluationResult], summary: GitHubFalsePositiveEvaluationSummary) -> None:
    print("VeriBridge GitHub Capability-Matching False-Positive Evaluation")
    print("=" * 80)
    for result in results:
        diagnostic = format_before_after_diagnostic(result)
        print(f"\nScenario {result.scenario.scenario_id}: {result.scenario.name}")
        print(f"Group:                  {result.scenario.group}")
        print(f"Claim:                  {result.scenario.claim}")
        print(f"Code evidence segments:")
        for segment in result.scenario.code_segments:
            signals = ", ".join(segment.detected_signals) if segment.detected_signals else "none"
            print(f"  - Lines {segment.line_start}-{segment.line_end}: {segment.summary}")
            print(f"    Type: {segment.segment_type}; signals: {signals}")
        print(f"Extracted requirements:  {_format_requirement_list(result.extracted_requirements)}")
        print(f"Satisfied requirements:  {_format_requirement_matches(result.satisfied_requirements)}")
        print(f"Missing critical reqs:   {_format_requirement_list(result.missing_critical_requirements)}")
        print(f"Capability status:       {result.capability_match_status}")
        print(f"Blocks full verification:{_format_bool(result.blocks_full_verification)}")
        print(f"Semantic score:          {_format_optional_score(result.semantic_similarity_score)}")
        print(f"Semantic label:          {result.semantic_similarity_label}")
        print(f"Without guardrail:        {diagnostic['semantic_similarity_alone']}")
        print(f"Final interpretation:    {result.final_interpretation}")
        print(f"Expected interpretation: {result.expected_interpretation}")
        print(f"Reason:                  {result.reason}")
        if result.evaluation_notes:
            print(f"Evaluation notes:        {result.evaluation_notes}")

    print("\nEvaluation Summary")
    print("-" * 80)
    print(
        "Strong true positives preserved:              "
        f"{summary.strong_true_positive_support_count}/{summary.strong_true_positive_total}"
    )
    print(
        "False-positive traps blocked/downgraded:      "
        f"{summary.false_positive_trap_blocked_or_downgraded_count}/{summary.false_positive_trap_total}"
    )
    print(
        "Generic/incomplete cases kept cautious:       "
        f"{summary.generic_incomplete_kept_cautious_count}/{summary.generic_incomplete_total}"
    )
    print(
        "Borderline cases kept cautious:               "
        f"{summary.borderline_cautious_count}/{summary.borderline_total}"
    )
    print(f"Suspicious too permissive cases:              {_format_int_list(summary.suspicious_too_permissive)}")
    print(f"Suspicious too strict cases:                  {_format_int_list(summary.suspicious_too_strict)}")
    print(f"Production logic trustworthy:                 {_format_bool(summary.production_logic_trustworthy)}")
    print(f"Bug or logic adjustment recommended:          {_format_bool(summary.bug_or_logic_adjustment_recommended)}")
    print("\nConclusion")
    print("-" * 80)
    print(summary.conclusion)


def format_before_after_diagnostic(result: GitHubFalsePositiveEvaluationResult) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario.scenario_id,
        "scenario_group": result.scenario.group,
        "semantic_similarity_alone": result.semantic_similarity_alone,
        "capability_guardrail": "blocks_full_verification" if result.blocks_full_verification else "does_not_block",
        "final_interpretation": result.final_interpretation,
        "expected_interpretation": result.expected_interpretation,
    }


def format_result(result: GitHubFalsePositiveEvaluationResult) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario.scenario_id,
        "name": result.scenario.name,
        "group": result.scenario.group,
        "semantic_status": result.semantic_status,
        "confidence_score": result.confidence_score,
        "semantic_similarity_score": result.semantic_similarity_score,
        "semantic_similarity_label": result.semantic_similarity_label,
        "semantic_similarity_alone": result.semantic_similarity_alone,
        "capability_match_status": result.capability_match_status,
        "blocks_full_verification": result.blocks_full_verification,
        "final_interpretation": result.final_interpretation,
        "expected_interpretation": result.expected_interpretation,
        "reason": result.reason,
        "matched_segments": [
            {
                "line_start": match.line_start,
                "line_end": match.line_end,
                "segment_type": match.segment_type,
                "summary": match.summary,
                "semantic_score": getattr(match, "semantic_score", None),
                "semantic_label": getattr(match, "semantic_label", None),
            }
            for match in result.matched_segments
        ],
    }


def summarize_result_dicts(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = {
        "strong_true_positive": [item for item in results if item["group"] == GROUP_STRONG_TRUE_POSITIVE],
        "false_positive_trap": [item for item in results if item["group"] == GROUP_FALSE_POSITIVE_TRAP],
        "generic_incomplete": [item for item in results if item["group"] == GROUP_GENERIC_INCOMPLETE],
        "borderline": [item for item in results if item["group"] == GROUP_BORDERLINE],
    }
    summary = {
        "strong_true_positive_preserved": sum(1 for item in grouped["strong_true_positive"] if item["final_interpretation"] == RECOMMENDATION_VERIFIED),
        "strong_true_positive_total": len(grouped["strong_true_positive"]),
        "false_positive_traps_blocked_or_downgraded": sum(1 for item in grouped["false_positive_trap"] if item["final_interpretation"] != RECOMMENDATION_VERIFIED),
        "false_positive_trap_total": len(grouped["false_positive_trap"]),
        "generic_incomplete_kept_cautious": sum(1 for item in grouped["generic_incomplete"] if item["final_interpretation"] != RECOMMENDATION_VERIFIED),
        "generic_incomplete_total": len(grouped["generic_incomplete"]),
        "borderline_kept_cautious": sum(1 for item in grouped["borderline"] if item["final_interpretation"] != RECOMMENDATION_VERIFIED),
        "borderline_total": len(grouped["borderline"]),
        "suspicious_too_permissive": [
            item["scenario_id"]
            for item in grouped["false_positive_trap"] + grouped["generic_incomplete"]
            if item["final_interpretation"] == RECOMMENDATION_VERIFIED
        ],
        "suspicious_too_strict": [
            item["scenario_id"]
            for item in grouped["strong_true_positive"]
            if item["final_interpretation"] != RECOMMENDATION_VERIFIED
        ],
    }
    summary["production_logic_trustworthy"] = not summary["suspicious_too_permissive"] and not summary["suspicious_too_strict"]
    summary["bug_or_logic_adjustment_recommended"] = bool(summary["suspicious_too_permissive"] or summary["suspicious_too_strict"])
    return summary


def _results_for_group(
    results: list[GitHubFalsePositiveEvaluationResult],
    group: str,
) -> list[GitHubFalsePositiveEvaluationResult]:
    return [result for result in results if result.scenario.group == group]


def _requirement_to_dict(requirement: Any) -> dict[str, Any]:
    return {
        "requirement_key": requirement.requirement_key,
        "requirement_label": requirement.requirement_label,
        "requirement_type": requirement.requirement_type,
        "importance": requirement.importance,
        "source_phrase": requirement.source_phrase,
    }


def _strongest_match(matches: list[GitHubClaimCodeSegmentMatch]) -> GitHubClaimCodeSegmentMatch | None:
    if not matches:
        return None
    return max(matches, key=lambda match: (match.semantic_score or 0.0, match.supports_skill, -match.line_start))


def _format_requirement_list(requirements: list[dict[str, Any]]) -> str:
    if not requirements:
        return "none"
    parts = []
    for item in requirements:
        label = item.get("requirement_label") or item.get("requirement_key") or "unknown"
        importance = item.get("importance") or "unknown"
        parts.append(f"{label} ({importance})")
    return ", ".join(parts)


def _format_requirement_matches(requirements: list[dict[str, Any]]) -> str:
    if not requirements:
        return "none"
    parts = []
    for item in requirements:
        label = item.get("requirement_label") or item.get("requirement_key") or "unknown"
        start = item.get("matching_segment_start")
        end = item.get("matching_segment_end")
        parts.append(f"{label} -> lines {start}-{end}")
    return ", ".join(parts)


def _format_optional_score(value: float | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/a"


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_int_list(values: list[int]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def main() -> int:
    service = GitHubSemanticVerificationService({}, embedding_provider=LocalSentenceEmbeddingProvider())
    try:
        results = evaluate_scenarios(EVALUATION_SCENARIOS, service)
    except Exception as exc:
        print("GitHub capability-matching false-positive evaluation could not run.")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("If the local embedding model is unavailable, cache it or rerun in a dev environment with access.")
        print("The script will still fall back to deterministic similarity logic if the model loader raises at runtime.")
        return 1
    summary = summarize_results(results)
    print_report(results, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
