"""Tests for line-level GitHub code evidence segmentation."""

from __future__ import annotations

from app.services.github_code_evidence_segmentation_service import (
    github_code_evidence_segmentation_to_snapshot,
    segment_github_code_evidence,
)


def test_ml_code_segments_detect_model_training_prediction_and_evaluation() -> None:
    code = "\n".join(
        [
            "from sklearn.tree import DecisionTreeClassifier",
            "model = DecisionTreeClassifier(max_depth=3)",
            "",
            "from sklearn.model_selection import train_test_split",
            "model.fit(X_train, y_train)",
            "",
            "predictions = model.predict(X_test)",
            "probabilities = model.predict_proba(X_test)",
            "",
            "print(accuracy_score(y_test, predictions))",
            "print(confusion_matrix(y_test, predictions))",
        ]
    )

    result = segment_github_code_evidence(code, 20, "Machine Learning", "Built and evaluated a Decision Tree classifier.")

    assert result.available is True
    assert result.total_segments == 4
    assert [segment.segment_type for segment in result.segments] == [
        "model_initialization",
        "model_training",
        "prediction_inference",
        "evaluation_metrics",
    ]
    assert result.segments[0].line_start == 20
    assert result.segments[0].line_end == 21
    assert result.segments[1].line_start == 23
    assert result.segments[1].line_end == 24
    assert result.segments[2].line_start == 26
    assert result.segments[2].line_end == 27
    assert result.segments[3].line_start == 29
    assert result.segments[3].line_end == 30
    assert result.segments[0].supports_skill is True
    assert result.segments[1].supports_skill is True
    assert result.segments[2].supports_skill is True
    assert result.segments[3].supports_skill is True


def test_line_numbers_are_preserved_with_absolute_starting_line() -> None:
    code = "\n".join(
        [
            "import pandas as pd",
            "df = pd.read_csv('data.csv')",
            "",
            "df = df.dropna()",
            "scaler = StandardScaler()",
        ]
    )

    result = segment_github_code_evidence(code, 20, "Machine Learning", "Prepared data for a model.")

    assert result.segments[0].line_start == 20
    assert result.segments[0].line_end == 21
    assert result.segments[1].line_start == 23
    assert result.segments[1].line_end == 24


def test_selected_line_range_uses_absolute_numbering_system() -> None:
    code = "\n".join(
        [
            "from fastapi import FastAPI",
            "app = FastAPI()",
            "",
            "@app.get('/health')",
            "def health():",
            "    return {'ok': True}",
        ]
    )

    result = segment_github_code_evidence(code, 20, "FastAPI", "Built a backend health check endpoint.")

    assert all(segment.line_start >= 20 for segment in result.segments)
    assert all(segment.line_end >= segment.line_start for segment in result.segments)
    assert result.segments[0].line_start == 20


def test_overall_summary_mentions_ml_workflow_when_key_segments_are_present() -> None:
    code = "\n".join(
        [
            "from sklearn.tree import DecisionTreeClassifier",
            "model = DecisionTreeClassifier()",
            "",
            "model.fit(X_train, y_train)",
            "",
            "predictions = model.predict(X_test)",
            "",
            "print(accuracy_score(y_test, predictions))",
        ]
    )

    result = segment_github_code_evidence(code, 20, "Machine Learning", "Built a classifier workflow.")

    assert "machine learning workflow" in result.overall_summary.lower()
    assert "model setup" in result.overall_summary.lower()
    assert "training" in result.overall_summary.lower()
    assert "prediction" in result.overall_summary.lower()
    assert "evaluation" in result.overall_summary.lower()


def test_api_endpoint_code_produces_api_endpoint_segment() -> None:
    code = "\n".join(
        [
            "from fastapi import APIRouter",
            "router = APIRouter()",
            "",
            "@router.get('/health')",
            "def health_check():",
            "    return {'ok': True}",
        ]
    )

    result = segment_github_code_evidence(code, 1, "FastAPI", "Defined a health endpoint.")

    assert any(segment.segment_type == "api_endpoint" for segment in result.segments)
    api_segment = next(segment for segment in result.segments if segment.segment_type == "api_endpoint")
    assert "api route" in api_segment.summary.lower()
    assert api_segment.supports_skill is True


def test_data_preprocessing_code_produces_data_preprocessing_segment() -> None:
    code = "\n".join(
        [
            "df = pd.read_csv('data.csv')",
            "df = df.dropna()",
            "",
            "scaler = StandardScaler()",
            "X_scaled = scaler.fit_transform(X)",
        ]
    )

    result = segment_github_code_evidence(code, 15, "Machine Learning", "Prepared data before training.")

    assert any(segment.segment_type == "data_preprocessing" for segment in result.segments)
    preprocessing_segment = next(segment for segment in result.segments if segment.segment_type == "data_preprocessing")
    assert "prepares the input data" in preprocessing_segment.summary.lower()
    assert preprocessing_segment.supports_skill is True


def test_generic_code_with_weak_signals_does_not_overclaim() -> None:
    code = "\n".join(
        [
            "def helper(value):",
            "    result = value + 1",
            "    return result",
        ]
    )

    result = segment_github_code_evidence(code, 40, "Machine Learning", "Utility helper function.")

    assert result.available is True
    assert result.total_segments == 1
    assert result.segments[0].segment_type in {"generic_logic", "unknown"}
    assert result.segments[0].supports_skill is False
    assert result.segments[0].confidence_hint == "low"


def test_very_short_selected_range_returns_one_segment() -> None:
    result = segment_github_code_evidence("model.fit(X_train, y_train)", 42, "Machine Learning", "Training step.")

    assert result.total_segments == 1
    assert result.segments[0].line_start == 42
    assert result.segments[0].line_end == 42
    assert result.segments[0].segment_type == "model_training"


def test_empty_or_missing_code_returns_unavailable_result_safely() -> None:
    result = segment_github_code_evidence("", 10, "Machine Learning", "Empty range.")

    assert result.available is False
    assert result.total_segments == 0
    assert result.segments == []
    assert "No GitHub code" in result.overall_summary


def test_snapshot_serialization_returns_compact_metadata() -> None:
    result = segment_github_code_evidence(
        "\n".join(["model = DecisionTreeClassifier()", "model.fit(X_train, y_train)"]),
        20,
        "Machine Learning",
        "Built a classifier.",
    )

    snapshot = github_code_evidence_segmentation_to_snapshot(result)

    assert snapshot["available"] is True
    assert snapshot["overall_summary"]
    assert snapshot["segments"][0]["line_start"] == 20
    assert snapshot["segments"][0]["segment_type"] in {"model_initialization", "model_training"}
