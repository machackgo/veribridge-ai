"""Tests for GitHub claim-to-code semantic verification."""

from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.schemas.github_semantic_verification_result import GitHubSemanticVerificationResultResponse
from app.services.github_claim_code_semantic_verification_service import GitHubSemanticVerificationService
from app.services.github_code_evidence_segmentation_service import (
    GitHubCodeEvidenceSegment,
    GitHubCodeEvidenceSegmentationResult,
)
from app.services.github_evidence_service import GitHubFileFetchResult, verify_github_file_evidence

USER_ID = "00000000-0000-0000-0000-000000000101"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000102"
EVIDENCE_ID = "00000000-0000-0000-0000-000000000201"
RESULT_ID = "00000000-0000-0000-0000-000000000301"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _evidence_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": EVIDENCE_ID,
        "user_id": USER_ID,
        "skill_name": "Machine Learning",
        "evidence_type": "GitHub file",
        "evidence_description": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        "repository_url": "https://github.com/user/project",
        "file_path": "Tree.py",
        "metadata": {},
    }
    row.update(overrides)
    return row


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


def _segmentation_result(segments: list[GitHubCodeEvidenceSegment], overall_summary: str, skill_name: str = "Machine Learning") -> GitHubCodeEvidenceSegmentationResult:
    return GitHubCodeEvidenceSegmentationResult(
        available=True,
        skill_name=skill_name,
        total_segments=len(segments),
        segments=segments,
        overall_summary=overall_summary,
        notes=None,
    )


def _make_service(store: dict | None = None) -> GitHubSemanticVerificationService:
    return GitHubSemanticVerificationService(store or {})


def _score_by_keywords(score_map: dict[str, float], default: float = 0.2):
    def _score(_: str, text_b: str) -> float:
        normalized = text_b.lower()
        for needle, score in score_map.items():
            if needle.lower() in normalized:
                return score
        return default

    return _score


def test_claim_text_building_uses_student_description_and_skill() -> None:
    service = _make_service()
    claim = service.build_github_claim_text(
        {
            "evidence": {
                "skill_name": "Machine Learning",
                "evidence_description": "I built and evaluated a Decision Tree classification model for stroke prediction.",
                "metadata": {"title": "Stroke prediction notebook"},
            }
        }
    )
    assert "Decision Tree classification model" in claim
    assert "Stroke prediction notebook" in claim
    assert "Skill: Machine Learning" in claim


def test_segment_matching_inputs_include_line_ranges_and_signals() -> None:
    service = _make_service()
    context = {
        "segmentation": _segmentation_result(
            [
                _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("]),
            ],
            "The selected code demonstrates model setup and training.",
        )
    }
    formatted = service.build_code_segment_match_inputs(context)
    assert formatted == [
        "Lines 20-32: Initializes a Decision Tree classifier and trains it using fit(). Segment type: model_training. Detected signals: DecisionTreeClassifier, fit(."
    ]


def test_verified_result_for_ml_workflow_supports_claim() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_initialization", ["DecisionTreeClassifier", "fit("]),
        _segment(2, 34, 50, "Generates predictions on the test set with predict().", "prediction_inference", ["predict("]),
        _segment(3, 52, 61, "Evaluates model performance using accuracy_score and confusion_matrix.", "evaluation_metrics", ["accuracy_score", "confusion_matrix"]),
    ]
    segmentation = _segmentation_result(segments, "The selected code demonstrates model initialization, training, prediction, and evaluation.")
    context = {
        "available": True,
        "evidence": _evidence_row(),
        "claim_text": service.build_github_claim_text({"evidence": _evidence_row()}),
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords(
        {
            "overall code summary": 0.93,
            "initializes a decision tree": 0.92,
            "generates predictions": 0.90,
            "evaluates model performance": 0.91,
        },
        default=0.18,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status == "verified"
    assert evaluation.confidence_score >= 0.85
    assert evaluation.strongest_matching_segment_start == 20
    assert evaluation.strongest_matching_segment_end == 32
    assert evaluation.matched_segments[0].semantic_score is not None
    assert "decision tree classifier" in evaluation.recruiter_facing_summary.lower()
    assert evaluation.internal_reasoning_summary


def test_partially_verified_when_only_some_claim_details_are_supported() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("]),
        _segment(2, 34, 50, "Generates predictions on the test set with predict().", "prediction_inference", ["predict("]),
    ]
    segmentation = _segmentation_result(segments, "The selected code demonstrates model training and prediction.")
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I built and evaluated a Decision Tree classification model for stroke prediction with metrics and comparison."
        ),
        "claim_text": "I built and evaluated a Decision Tree classification model for stroke prediction with metrics and comparison.",
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords(
        {
            "overall code summary": 0.74,
            "initializes a decision tree": 0.76,
            "generates predictions": 0.72,
        },
        default=0.28,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status in {"partially_verified", "needs_human_review"}
    assert 0.50 <= evaluation.confidence_score <= 0.84


def test_github_semantic_snapshot_includes_reconciled_display_status() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("]),
    ]
    segmentation = _segmentation_result(segments, "The selected code demonstrates model training.")
    context = {
        "available": True,
        "evidence": _evidence_row(),
        "claim_text": service.build_github_claim_text({"evidence": _evidence_row()}),
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords({"overall code summary": 0.93, "initializes a decision tree": 0.92}, default=0.18)

    evaluation = service.evaluate_semantically(context)
    snapshot = service._source_snapshot(context, evaluation)

    assert snapshot["product_verification_reconciliation"]["display_status"] in {
        "verified",
        "supported_with_review",
        "partially_supported",
        "not_verified",
    }


def test_not_verified_for_unrelated_ui_or_database_code() -> None:
    service = _make_service()
    segments = [
        _segment(
            1,
            20,
            26,
            "Defines a React sidebar component for dashboard navigation.",
            "ui_component",
            ["React", "useState", "className="],
            supports_skill=False,
        ),
        _segment(
            2,
            28,
            36,
            "Writes user settings to the database table.",
            "database_logic",
            ["supabase", "insert(", "commit("],
            supports_skill=False,
        ),
    ]
    segmentation = _segmentation_result(segments, "The selected code defines UI and database support logic.")
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I built and evaluated a Decision Tree classification model for stroke prediction.",
        ),
        "claim_text": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords(
        {
            "overall code summary": 0.18,
            "react sidebar": 0.14,
            "database": 0.58,
        },
        default=0.10,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status == "not_verified"
    assert evaluation.confidence_score >= 0.70


def test_needs_human_review_for_generic_signals() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 26, "Adds generic helper logic for the application.", "generic_logic", ["helper", "logic"], supports_skill=False, confidence_hint="low"),
        _segment(2, 28, 36, "Processes an input and returns a result.", "generic_logic", ["input", "result"], supports_skill=False, confidence_hint="low"),
    ]
    segmentation = _segmentation_result(segments, "The selected code contains generic application logic.")
    context = {
        "available": True,
        "evidence": _evidence_row(evidence_description="I built a machine learning model for stroke prediction."),
        "claim_text": "I built a machine learning model for stroke prediction.",
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords({"generic application": 0.58, "overall code summary": 0.60}, default=0.56)

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status in {"needs_human_review", "not_verified"}
    assert 0.70 <= evaluation.confidence_score <= 0.95


def test_insufficient_evidence_when_claim_or_segmentation_is_missing() -> None:
    service = _make_service()
    evaluation = service.evaluate_semantically({"available": False, "claim_text": "", "segmentation": None})
    assert evaluation.semantic_status == "insufficient_evidence"
    assert evaluation.confidence_score == 0.18


def test_provider_unavailable_falls_back_without_crashing(monkeypatch) -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("]),
    ]
    context = {
        "available": True,
        "evidence": _evidence_row(),
        "claim_text": "I built a Decision Tree classifier.",
        "segmentation": _segmentation_result(segments, "The selected code demonstrates model training."),
    }

    def _raise(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "app.services.github_claim_code_semantic_verification_service.compute_embedding_similarity",
        _raise,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status in {"partially_verified", "needs_human_review", "not_verified"}
    assert service._similarity_fallback_used is True


def test_high_semantic_similarity_alone_cannot_verify_when_critical_capability_missing() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 26, "Reads data with pandas.", "data_preprocessing", ["read_csv", "StandardScaler"]),
        _segment(2, 28, 36, "Splits data into training and test sets.", "data_preprocessing", ["train_test_split"]),
    ]
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I built and evaluated a Decision Tree classification model."
        ),
        "claim_text": "I built and evaluated a Decision Tree classification model.",
        "segmentation": _segmentation_result(segments, "The selected code prepares data for modeling."),
    }
    service._score_text_pair = _score_by_keywords(
        {
            "selected code prepares data for modeling": 0.92,
            "reads data with pandas": 0.90,
            "splits data into training and test sets": 0.89,
        },
        default=0.88,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status != "verified"
    assert evaluation.semantic_status in {"partially_verified", "needs_human_review", "not_verified"}


def test_complete_capabilities_remain_verified() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a RandomForestClassifier and trains it.", "model_training", ["RandomForestClassifier", "fit("]),
        _segment(2, 34, 42, "Reports f1_score and classification_report.", "evaluation_metrics", ["f1_score", "classification_report"]),
    ]
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I trained and evaluated a Random Forest model with F1 score."
        ),
        "claim_text": "I trained and evaluated a Random Forest model with F1 score.",
        "segmentation": _segmentation_result(segments, "The selected code demonstrates model training and evaluation."),
    }
    service._score_text_pair = _score_by_keywords(
        {
            "selected code demonstrates model training and evaluation": 0.95,
            "initializes a randomforestclassifier": 0.95,
            "reports f1_score": 0.94,
        },
        default=0.90,
    )

    evaluation = service.evaluate_semantically(context)

    assert evaluation.semantic_status == "verified"
    assert "model training" in evaluation.recruiter_facing_summary.lower()


def test_source_snapshot_stores_capability_match_metadata() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 26, "Reads data with pandas.", "data_preprocessing", ["read_csv"]),
        _segment(2, 28, 36, "Splits data into training and test sets.", "data_preprocessing", ["train_test_split"]),
    ]
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I built and evaluated a Decision Tree classification model."
        ),
        "claim_text": "I built and evaluated a Decision Tree classification model.",
        "segmentation": _segmentation_result(segments, "The selected code prepares data for modeling."),
    }
    service._score_text_pair = _score_by_keywords({"selected code prepares data for modeling": 0.92}, default=0.90)

    evaluation = service.evaluate_semantically(context)
    snapshot = service._source_snapshot(context, evaluation)

    assert "claim_capability_match" in snapshot
    assert snapshot["claim_capability_match"]["available"] is True
    assert snapshot["claim_capability_match"]["blocks_full_verification"] is True


def test_recruiter_summary_explains_missing_capability() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 26, "Reads data with pandas.", "data_preprocessing", ["read_csv"]),
        _segment(2, 28, 36, "Splits data into training and test sets.", "data_preprocessing", ["train_test_split"]),
    ]
    context = {
        "available": True,
        "evidence": _evidence_row(
            evidence_description="I built and evaluated a Decision Tree classification model."
        ),
        "claim_text": "I built and evaluated a Decision Tree classification model.",
        "segmentation": _segmentation_result(segments, "The selected code prepares data for modeling."),
    }
    service._score_text_pair = _score_by_keywords({"selected code prepares data for modeling": 0.92}, default=0.90)

    evaluation = service.evaluate_semantically(context)

    assert "required capabilities" in evaluation.recruiter_facing_summary.lower()


def test_strongest_matching_segment_metadata_is_preserved_in_source_snapshot() -> None:
    service = _make_service()
    segments = [
        _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_initialization", ["DecisionTreeClassifier", "fit("]),
        _segment(2, 34, 50, "Generates predictions on the test set with predict().", "prediction_inference", ["predict("]),
    ]
    segmentation = _segmentation_result(segments, "The selected code demonstrates model initialization and prediction.")
    context = {
        "available": True,
        "evidence": _evidence_row(),
        "claim_text": "I built a Decision Tree classifier and generated predictions.",
        "segmentation": segmentation,
    }
    service._score_text_pair = _score_by_keywords(
        {"initializes a decision tree": 0.91, "generates predictions": 0.88, "overall code summary": 0.86},
        default=0.20,
    )

    evaluation = service.evaluate_semantically(context)
    snapshot = service._source_snapshot(context, evaluation)

    assert snapshot["matched_segments"]
    assert snapshot["matched_segments"][0]["line_start"] == 20
    assert snapshot["matched_segments"][0]["line_end"] == 32
    assert snapshot["matched_segments"][0]["semantic_score"] == 0.91


def test_result_persists_to_dict_store(monkeypatch) -> None:
    store: dict = {"skill_evidence": {EVIDENCE_ID: _evidence_row()}, "github_semantic_verification_results": {}}
    service = _make_service(store)
    context = {
        "available": True,
        "evidence": _evidence_row(),
        "claim_text": "I built and evaluated a Decision Tree classifier.",
        "segmentation": _segmentation_result(
            [
                _segment(1, 20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("]),
                _segment(2, 34, 50, "Generates predictions on the test set with predict().", "prediction_inference", ["predict("]),
            ],
            "The selected code demonstrates model training and prediction.",
        ),
    }
    service._score_text_pair = _score_by_keywords({"overall code summary": 0.87, "decision tree": 0.90}, default=0.22)
    monkeypatch.setattr(service, "load_github_semantic_evaluation_context", lambda user_id, evidence_id: deepcopy(context))

    result = service.evaluate_github_semantic_verification(USER_ID, EVIDENCE_ID)

    assert result.semantic_status in {"verified", "partially_verified"}
    assert store["github_semantic_verification_results"]
    persisted_row = next(iter(store["github_semantic_verification_results"].values()))
    assert persisted_row["evidence_id"] == EVIDENCE_ID
    assert persisted_row["source_snapshot"]["matched_segments"]


def test_latest_list_and_get_endpoints_work() -> None:
    store: dict = {
        "skill_evidence": {
            EVIDENCE_ID: _evidence_row(),
        },
        "github_semantic_verification_results": {
            RESULT_ID: {
                "id": RESULT_ID,
                "evidence_id": EVIDENCE_ID,
                "user_id": USER_ID,
                "semantic_status": "verified",
                "confidence_score": 0.94,
                "evaluator_version": "github-claim-code-semantic-v1",
                "evaluator_provider": "local_deterministic_embedding",
                "recruiter_facing_summary": "Verified.",
                "evidence_summary": "Summary.",
                "limitations": "Limits.",
                "recommended_next_action": "No further action required.",
                "strongest_matching_segment_start": 20,
                "strongest_matching_segment_end": 32,
                "strongest_matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                "source_snapshot": {"matched_segments": [{"line_start": 20, "line_end": 32, "summary": "Initializes a Decision Tree classifier and trains it using fit()."}]},
                "created_at": "2026-05-19T10:00:00+00:00",
                "updated_at": "2026-05-19T10:00:00+00:00",
            },
            "00000000-0000-0000-0000-000000000302": {
                "id": "00000000-0000-0000-0000-000000000302",
                "evidence_id": EVIDENCE_ID,
                "user_id": USER_ID,
                "semantic_status": "partially_verified",
                "confidence_score": 0.74,
                "evaluator_version": "github-claim-code-semantic-v1",
                "evaluator_provider": "local_deterministic_embedding",
                "recruiter_facing_summary": "Partial.",
                "evidence_summary": "Summary.",
                "limitations": "Limits.",
                "recommended_next_action": "Review.",
                "strongest_matching_segment_start": 34,
                "strongest_matching_segment_end": 50,
                "strongest_matching_segment_summary": "Generates predictions on the test set with predict().",
                "source_snapshot": {"matched_segments": []},
                "created_at": "2026-05-19T11:00:00+00:00",
                "updated_at": "2026-05-19T11:00:00+00:00",
            },
        },
    }
    client = _client(store)
    try:
        latest = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results/latest")
        assert latest.status_code == 200
        assert latest.json()["id"] == "00000000-0000-0000-0000-000000000302"

        listed = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["results"]] == [
            "00000000-0000-0000-0000-000000000302",
            RESULT_ID,
        ]

        one = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results/{RESULT_ID}")
        assert one.status_code == 200
        assert one.json()["semantic_status"] == "verified"
    finally:
        _clear_overrides()


def test_other_user_cannot_access_result() -> None:
    store: dict = {
        "skill_evidence": {EVIDENCE_ID: _evidence_row()},
        "github_semantic_verification_results": {
            RESULT_ID: {
                "id": RESULT_ID,
                "evidence_id": EVIDENCE_ID,
                "user_id": USER_ID,
                "semantic_status": "verified",
                "confidence_score": 0.94,
                "evaluator_version": "github-claim-code-semantic-v1",
                "evaluator_provider": "local_deterministic_embedding",
                "source_snapshot": {"matched_segments": []},
                "created_at": "2026-05-19T10:00:00+00:00",
                "updated_at": "2026-05-19T10:00:00+00:00",
            }
        },
    }
    client = _client(store, OTHER_USER_ID)
    try:
        response = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results/{RESULT_ID}")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_non_github_evidence_returns_422() -> None:
    store: dict = {
        "skill_evidence": {
            EVIDENCE_ID: {
                "id": EVIDENCE_ID,
                "user_id": USER_ID,
                "skill_name": "Machine Learning",
                "evidence_type": "Deployed website URL",
                "evidence_url": "https://student.example.com",
                "evidence_description": "Website proof only.",
                "metadata": {},
            }
        },
        "github_semantic_verification_results": {},
    }
    client = _client(store)
    try:
        response = client.post(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "github_semantic_verification_not_allowed"
    finally:
        _clear_overrides()


def test_post_endpoint_returns_semantic_result(monkeypatch) -> None:
    store: dict = {
        "skill_evidence": {EVIDENCE_ID: _evidence_row()},
        "github_semantic_verification_results": {},
    }
    client = _client(store)
    try:
        response_payload = GitHubSemanticVerificationResultResponse(
            id=RESULT_ID,
            evidence_id=EVIDENCE_ID,
            user_id=USER_ID,
            semantic_status="verified",
            confidence_score=0.95,
            evaluator_version="github-claim-code-semantic-v1",
            evaluator_provider="local_deterministic_embedding",
            recruiter_facing_summary="Verified.",
            evidence_summary="Summary.",
            limitations="Limits.",
            recommended_next_action="No further action required.",
            strongest_matching_segment_start=20,
            strongest_matching_segment_end=32,
            strongest_matching_segment_summary="Initializes a Decision Tree classifier and trains it using fit().",
            matched_segments=[],
            source_snapshot={"matched_segments": []},
            created_at="2026-05-19T10:00:00+00:00",
            updated_at="2026-05-19T10:00:00+00:00",
        )
        monkeypatch.setattr(
            GitHubSemanticVerificationService,
            "evaluate_github_semantic_verification",
            lambda self, user_id, evidence_id: response_payload,
        )

        response = client.post(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-semantic-verification-results")
        assert response.status_code == 200
        assert response.json()["id"] == RESULT_ID
    finally:
        _clear_overrides()


def test_existing_rule_based_github_verification_still_works(monkeypatch) -> None:
    def fake_fetch(repository_url: str, file_path: str, branch_candidates=None) -> GitHubFileFetchResult:
        return GitHubFileFetchResult(
            ok=True,
            content=(
                "from sklearn.tree import DecisionTreeClassifier\n"
                "model = DecisionTreeClassifier()\n"
                "model.fit(X_train, y_train)\n"
            ),
            branch="main",
        )

    monkeypatch.setattr("app.services.github_evidence_service.fetch_public_github_file", fake_fetch)
    result = verify_github_file_evidence(
        {
            "skill_name": "Machine Learning",
            "repository_url": "https://github.com/user/project",
            "file_path": "Tree.py",
            "line_start": 1,
            "line_end": 3,
            "evidence_description": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        }
    )
    assert result is not None
    assert result["status"] == "verified"
