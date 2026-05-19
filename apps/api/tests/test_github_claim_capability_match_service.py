"""Tests for GitHub claim capability matching."""

from __future__ import annotations

from app.services.github_claim_capability_match_service import (
    GitHubClaimCapabilityMatchService,
    evaluate_github_claim_capability_match,
    github_claim_capability_match_to_snapshot,
)
from app.services.github_code_evidence_segmentation_service import (
    GitHubCodeEvidenceSegment,
    GitHubCodeEvidenceSegmentationResult,
)


def _segment(
    index: int,
    line_start: int,
    line_end: int,
    summary: str,
    segment_type: str,
    detected_signals: list[str],
    supports_skill: bool = True,
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
        confidence_hint="high",
    )


def _segmentation(segments: list[GitHubCodeEvidenceSegment]) -> GitHubCodeEvidenceSegmentationResult:
    return GitHubCodeEvidenceSegmentationResult(
        available=True,
        skill_name="Machine Learning",
        total_segments=len(segments),
        segments=segments,
        overall_summary="Selected code demonstrates the described workflow.",
        notes=None,
    )


def _context(description: str, segments: list[GitHubCodeEvidenceSegment], skill_name: str = "Machine Learning") -> dict:
    return {
        "available": True,
        "claim_text": description,
        "evidence": {"skill_name": skill_name, "evidence_description": description},
        "segmentation": _segmentation(segments),
    }


def test_extracts_model_training_requirement_from_training_claim() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built and trained a Decision Tree classification model.",
            [_segment(1, 20, 32, "Initializes and trains a Decision Tree classifier.", "model_training", ["DecisionTreeClassifier", "fit("])],
        )
    )
    requirement_keys = [item.requirement_key for item in result.extracted_requirements]
    assert "model_training" in requirement_keys
    assert result.capability_match_status == "strong_capability_match"


def test_extracts_model_training_requirement_from_built_classification_model_claim() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built and evaluated a Decision Tree classification model for stroke prediction.",
            [_segment(1, 20, 32, "Initializes and trains a Decision Tree classifier.", "model_training", ["DecisionTreeClassifier", "fit("])],
        )
    )
    requirement_keys = [item.requirement_key for item in result.extracted_requirements]
    assert "model_training" in requirement_keys


def test_extracts_model_evaluation_requirement_from_evaluation_claim() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I evaluated the model using accuracy and confusion matrix metrics.",
            [_segment(1, 40, 48, "Reports accuracy_score and confusion_matrix.", "evaluation_metrics", ["accuracy_score", "confusion_matrix"])],
        )
    )
    requirement_keys = [item.requirement_key for item in result.extracted_requirements]
    assert "model_evaluation" in requirement_keys
    assert result.capability_match_status == "strong_capability_match"


def test_extracts_prediction_requirement_from_prediction_claim() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I generated predictions on the test set.",
            [_segment(1, 50, 58, "Generates predictions with predict().", "prediction_inference", ["predict("])],
        )
    )
    requirement_keys = [item.requirement_key for item in result.extracted_requirements]
    assert "prediction_inference" in requirement_keys


def test_extracts_api_and_database_requirements_from_backend_claim() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built a REST API that stores user submissions in a database.",
            [
                _segment(1, 10, 18, "Defines a FastAPI route.", "api_endpoint", ["FastAPI", "@app.post"]),
                _segment(2, 20, 30, "Inserts records into the database.", "database_logic", ["insert(", "supabase"]),
            ],
            skill_name="Backend Development",
        )
    )
    requirement_keys = {item.requirement_key for item in result.extracted_requirements}
    assert {"api_endpoint", "database_write"} <= requirement_keys
    assert result.supports_full_verification is True


def test_matches_requirements_to_correct_segments_and_preserves_line_ranges() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I trained and evaluated a Random Forest model.",
            [
                _segment(1, 20, 32, "Initializes a RandomForestClassifier and trains it.", "model_training", ["RandomForestClassifier", "fit("]),
                _segment(2, 34, 42, "Reports f1_score and confusion_matrix.", "evaluation_metrics", ["f1_score", "confusion_matrix"]),
            ],
        )
    )
    satisfied = {item["requirement_key"]: item for item in result.satisfied_requirements}
    assert satisfied["model_training"]["matching_segment_start"] == 20
    assert satisfied["model_training"]["matching_segment_end"] == 32
    assert satisfied["model_evaluation"]["matching_segment_start"] == 34
    assert satisfied["model_evaluation"]["matching_segment_end"] == 42


def test_detects_missing_critical_requirements() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built and evaluated a Decision Tree classification model.",
            [_segment(1, 10, 18, "Preprocesses data with StandardScaler.", "data_preprocessing", ["StandardScaler"])],
        )
    )
    assert result.capability_match_status == "capability_mismatch"
    assert result.blocks_full_verification is True
    assert result.missing_critical_requirements


def test_vague_wording_returns_cautious_or_unavailable_match() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "Nice project.",
            [_segment(1, 10, 18, "Some generic logic.", "generic_logic", ["helper"])],
        )
    )
    assert result.available is False
    assert result.capability_match_status == "unavailable"


def test_false_positive_training_and_evaluation_trap_does_not_support_full_verification() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built and evaluated a Decision Tree classification model.",
            [
                _segment(1, 20, 26, "Reads data with pandas.", "data_preprocessing", ["read_csv"]),
                _segment(2, 28, 34, "Splits the dataset into train and test sets.", "data_preprocessing", ["train_test_split"]),
            ],
        )
    )
    assert result.capability_match_status in {"capability_mismatch", "partial_capability_match"}
    assert result.supports_full_verification is False


def test_strong_complete_ml_workflow_supports_full_verification() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I trained and evaluated a Random Forest model with F1 score.",
            [
                _segment(1, 20, 32, "Initializes and trains RandomForestClassifier.", "model_training", ["RandomForestClassifier", "fit("]),
                _segment(2, 34, 42, "Reports f1_score and classification_report.", "evaluation_metrics", ["f1_score", "classification_report"]),
            ],
        )
    )
    assert result.capability_match_status == "strong_capability_match"
    assert result.supports_full_verification is True
    assert result.blocks_full_verification is False


def test_api_and_database_case_supports_full_verification() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I built a REST API that stores user submissions in a database.",
            [
                _segment(1, 12, 20, "Defines a FastAPI route.", "api_endpoint", ["FastAPI", "@app.post"]),
                _segment(2, 22, 34, "Inserts records into the database.", "database_logic", ["insert(", "supabase"]),
            ],
            skill_name="Backend Development",
        )
    )
    assert result.capability_match_status == "strong_capability_match"
    assert result.supports_full_verification is True


def test_supabase_client_variable_alone_does_not_satisfy_database_write() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I stored verified proof records in Supabase.",
            [_segment(1, 4, 10, "Defines a supabase_client variable.", "generic_logic", ["supabase_client"], supports_skill=False)],
            skill_name="Backend Development",
        )
    )
    assert result.capability_match_status in {"capability_mismatch", "partial_capability_match", "unavailable"}
    assert result.supports_full_verification is False


def test_auth_claim_without_auth_code_blocks_full_verification() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I implemented authentication and protected API routes.",
            [
                _segment(1, 10, 20, "Defines a FastAPI route.", "api_endpoint", ["FastAPI", "@app.get"]),
            ],
            skill_name="Backend Development",
        )
    )
    assert result.capability_match_status in {"partial_capability_match", "capability_mismatch"}
    assert result.blocks_full_verification is True


def test_snapshot_conversion_is_compact() -> None:
    result = evaluate_github_claim_capability_match(
        _context(
            "I trained and evaluated a Random Forest model with F1 score.",
            [
                _segment(1, 20, 32, "Initializes and trains RandomForestClassifier.", "model_training", ["RandomForestClassifier", "fit("]),
                _segment(2, 34, 42, "Reports f1_score and classification_report.", "evaluation_metrics", ["f1_score", "classification_report"]),
            ],
        )
    )
    snapshot = github_claim_capability_match_to_snapshot(result)
    assert snapshot["available"] is True
    assert snapshot["capability_match_status"] == "strong_capability_match"
    assert snapshot["satisfied_requirements"]
