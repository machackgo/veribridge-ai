"""Tests for recruiter-friendly GitHub proof reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.github_recruiter_proof_report_service import (
    GitHubRecruiterProofReportNotAllowedError,
    GitHubRecruiterProofReportNotFoundError,
    GitHubRecruiterProofReportService,
)
from app.services.github_claim_code_semantic_verification_service import GitHubSemanticVerificationResultNotFoundError

USER_ID = "00000000-0000-0000-0000-000000000501"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000502"
EVIDENCE_ID = "00000000-0000-0000-0000-000000000601"
SEMANTIC_RESULT_ID = "00000000-0000-0000-0000-000000000701"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _now(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()


def _evidence_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": EVIDENCE_ID,
        "user_id": USER_ID,
        "skill_name": "Machine Learning",
        "evidence_type": "GitHub file",
        "evidence_description": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        "repository_url": "https://github.com/user/project",
        "file_path": "Tree.py",
        "verification_status": "verified",
        "verification_summary": "Public GitHub proof verified.",
        "verifier_version": "github-file-v1",
        "metadata": {"title": "Stroke prediction notebook"},
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    return row


def _seed_evidence(store: dict, **overrides: object) -> dict[str, object]:
    evidence = _evidence_row(**overrides)
    store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
    return evidence


def _segment(line_start: int, line_end: int, summary: str, segment_type: str, signals: list[str], score: float) -> dict[str, object]:
    return {
        "line_start": line_start,
        "line_end": line_end,
        "segment_type": segment_type,
        "summary": summary,
        "detected_signals": signals,
        "semantic_score": score,
        "semantic_label": "strong_semantic_match" if score >= 0.82 else "moderate_semantic_match" if score >= 0.68 else "weak_semantic_match",
        "supports_skill": True,
        "confidence_hint": "high" if score >= 0.82 else "medium",
    }


def _semantic_result_row(
    *,
    status: str,
    confidence: float,
    recruiter_summary: str,
    evidence_summary: str,
    limitations: str,
    next_action: str,
    satisfied: list[dict[str, object]],
    missing_critical: list[dict[str, object]],
    missing_supporting: list[dict[str, object]] | None = None,
    matched_segments: list[dict[str, object]] | None = None,
    strongest: tuple[int, int, str] = (20, 32, "Initializes a Decision Tree classifier."),
    created_at: str | None = None,
) -> dict[str, object]:
    if matched_segments is None:
        matched_segments = [
        _segment(20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("], 0.91),
        _segment(34, 50, "Generates predictions on the test set using predict().", "prediction_inference", ["predict(", "y_pred"], 0.89),
        _segment(52, 61, "Evaluates model performance using accuracy_score and f1_score.", "evaluation_metrics", ["accuracy_score", "f1_score"], 0.93),
        ]
    claim_capability_match = {
        "available": bool(satisfied or missing_critical or missing_supporting),
        "capability_match_status": "strong_capability_match" if status == "verified" else "partial_capability_match" if missing_critical else "capability_mismatch" if status == "not_verified" else "unavailable",
        "supports_full_verification": status == "verified",
        "blocks_full_verification": status in {"partially_verified", "not_verified", "needs_human_review", "insufficient_evidence"},
        "extracted_requirements": [
            {"requirement_key": item["requirement_key"], "requirement_label": item["requirement_label"], "requirement_type": item.get("requirement_type", item["requirement_key"]), "importance": item.get("importance", "critical")}
            for item in satisfied + missing_critical + (missing_supporting or [])
        ],
        "satisfied_requirements": satisfied,
        "missing_critical_requirements": missing_critical,
        "missing_supporting_requirements": missing_supporting or [],
        "notes": "Report fixture.",
    }
    return {
        "id": SEMANTIC_RESULT_ID,
        "evidence_id": EVIDENCE_ID,
        "user_id": USER_ID,
        "semantic_status": status,
        "confidence_score": confidence,
        "evaluator_version": "github-claim-code-semantic-v1",
        "evaluator_provider": "local_deterministic_embedding",
        "recruiter_facing_summary": recruiter_summary,
        "evidence_summary": evidence_summary,
        "limitations": limitations,
        "recommended_next_action": next_action,
        "strongest_matching_segment_start": strongest[0],
        "strongest_matching_segment_end": strongest[1],
        "strongest_matching_segment_summary": strongest[2],
        "source_snapshot": {
            "claim_preview": "I built and evaluated a Decision Tree classification model for stroke prediction.",
            "overall_code_summary_preview": "The selected code demonstrates a Decision Tree classification workflow for stroke prediction with model initialization, training, prediction, and evaluation.",
            "claim_capability_match": claim_capability_match,
            "matched_segments": matched_segments,
            "segmentation": {
                "available": True,
                "skill_name": "Machine Learning",
                "total_segments": len(matched_segments),
                "segments": matched_segments,
                "overall_summary": "The selected code demonstrates a Decision Tree classification workflow for stroke prediction with model initialization, training, prediction, and evaluation.",
                "notes": None,
            },
        },
        "created_at": created_at or _now(),
        "updated_at": created_at or _now(),
    }


def _seed_github_result(store: dict, row: dict[str, object] | None = None) -> dict[str, object]:
    result = row or _semantic_result_row(
        status="verified",
        confidence=0.91,
        recruiter_summary="VeriBridge found that the selected code supports the student's claim.",
        evidence_summary="Lines 20-32 train the classifier; lines 34-50 generate predictions; lines 52-61 evaluate performance.",
        limitations="This report reflects selected GitHub lines only.",
        next_action="No further action required.",
        satisfied=[
            {
                "requirement_key": "model_training",
                "requirement_label": "Model training",
                "requirement_type": "model_training",
                "importance": "critical",
                "matching_segment_start": 20,
                "matching_segment_end": 32,
                "matching_segment_type": "model_training",
                "matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                "matching_signals": ["DecisionTreeClassifier", "fit("],
            },
            {
                "requirement_key": "prediction_inference",
                "requirement_label": "Prediction inference",
                "requirement_type": "prediction_inference",
                "importance": "critical",
                "matching_segment_start": 34,
                "matching_segment_end": 50,
                "matching_segment_type": "prediction_inference",
                "matching_segment_summary": "Generates predictions on the test set using predict().",
                "matching_signals": ["predict(", "y_pred"],
            },
            {
                "requirement_key": "model_evaluation",
                "requirement_label": "Model evaluation",
                "requirement_type": "model_evaluation",
                "importance": "critical",
                "matching_segment_start": 52,
                "matching_segment_end": 61,
                "matching_segment_type": "evaluation_metrics",
                "matching_segment_summary": "Evaluates model performance using accuracy_score and f1_score.",
                "matching_signals": ["accuracy_score", "f1_score"],
            },
        ],
        missing_critical=[],
    )
    store.setdefault("github_semantic_verification_results", {})[result["id"]] = result
    return result


def _make_service(store: dict | None = None) -> GitHubRecruiterProofReportService:
    return GitHubRecruiterProofReportService(store or {})


def test_verified_report_generated_from_verified_semantic_result() -> None:
    store: dict = {}
    _seed_evidence(store)
    semantic = _seed_github_result(store)

    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

    assert report.report_status == "verified"
    assert report.github_semantic_result_id == semantic["id"]
    assert report.confirmed_capabilities
    assert any(item.line_start == 20 and item.line_end == 32 for item in report.supporting_line_ranges)
    assert "supports the student's claim" in report.recruiter_summary.lower()


def test_partially_verified_report_generated_from_partial_semantic_result() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="partially_verified",
            confidence=0.71,
            recruiter_summary="VeriBridge found partial support for the student's claim.",
            evidence_summary="Lines 20-32 and 34-50 support part of the workflow.",
            limitations="One capability was not clearly demonstrated.",
            next_action="Human review recommended.",
            satisfied=[
                {
                    "requirement_key": "model_training",
                    "requirement_label": "Model training",
                    "requirement_type": "model_training",
                    "importance": "critical",
                    "matching_segment_start": 20,
                    "matching_segment_end": 32,
                    "matching_segment_type": "model_training",
                    "matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                    "matching_signals": ["DecisionTreeClassifier", "fit("],
                }
            ],
            missing_critical=[
                {
                    "requirement_key": "model_evaluation",
                    "requirement_label": "Model evaluation",
                    "requirement_type": "model_evaluation",
                    "importance": "critical",
                }
            ],
        ),
    )

    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

    assert report.report_status == "partially_verified"
    assert report.missing_capabilities[0].label == "Model evaluation"
    assert "part of the student's claim" in report.recruiter_summary.lower()


def test_not_verified_report_generated_from_failed_semantic_result() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="not_verified",
            confidence=0.82,
            recruiter_summary="VeriBridge could not confirm the student's claim from the selected GitHub code evidence.",
            evidence_summary="The selected code did not demonstrate the claimed workflow.",
            limitations="The selected code was unrelated.",
            next_action="Provide stronger GitHub proof evidence.",
            satisfied=[],
            missing_critical=[
                {
                    "requirement_key": "model_training",
                    "requirement_label": "Model training",
                    "requirement_type": "model_training",
                    "importance": "critical",
                }
            ],
            matched_segments=[
                _segment(10, 18, "Reads data with pandas.", "data_preprocessing", ["read_csv"], 0.18),
            ],
        ),
    )

    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

    assert report.report_status == "not_verified"
    assert report.confirmed_capabilities == []
    assert "could not confirm" in report.recruiter_summary.lower()


def test_needs_review_report_generated_from_review_semantic_result() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="needs_human_review",
            confidence=0.55,
            recruiter_summary="The selected code contains potentially relevant signals.",
            evidence_summary="The code looked related but not conclusive.",
            limitations="Signals are mixed.",
            next_action="Human review recommended because the code signals are mixed or generic.",
            satisfied=[
                {
                    "requirement_key": "api_endpoint",
                    "requirement_label": "API endpoint",
                    "requirement_type": "api_endpoint",
                    "importance": "critical",
                    "matching_segment_start": 12,
                    "matching_segment_end": 22,
                    "matching_segment_type": "api_endpoint",
                    "matching_segment_summary": "Defines a POST route for submissions.",
                    "matching_signals": ["FastAPI", "@app.post"],
                }
            ],
            missing_critical=[
                {
                    "requirement_key": "database_write",
                    "requirement_label": "Database write",
                    "requirement_type": "database_write",
                    "importance": "critical",
                }
            ],
        ),
    )

    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

    assert report.report_status == "needs_human_review"
    assert "review is recommended" in report.headline.lower()


def test_insufficient_evidence_handled_safely() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="insufficient_evidence",
            confidence=0.18,
            recruiter_summary="Not enough structured GitHub evidence was available.",
            evidence_summary="Evidence was too sparse.",
            limitations="Sparse evidence.",
            next_action="Provide more complete GitHub proof evidence.",
            satisfied=[],
            missing_critical=[],
            matched_segments=[],
            strongest=(None, None, ""),
        ),
    )

    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

    assert report.report_status == "insufficient_evidence"
    assert report.supporting_line_ranges == []


def test_headline_matches_report_status() -> None:
    service = _make_service()
    assert service.build_report_headline({"semantic_result": type("X", (), {"semantic_status": "verified"})()}) == "Selected GitHub code supports the student’s claim."
    assert service.build_report_headline({"semantic_result": type("X", (), {"semantic_status": "partially_verified"})()}) == "Selected GitHub code supports part of the student’s claim."
    assert service.build_report_headline({"semantic_result": type("X", (), {"semantic_status": "not_verified"})()}) == "Selected GitHub code did not clearly support the student’s claim."
    assert service.build_report_headline({"semantic_result": type("X", (), {"semantic_status": "needs_human_review"})()}) == "Selected GitHub code may be relevant, but review is recommended."
    assert service.build_report_headline({"semantic_result": type("X", (), {"semantic_status": "insufficient_evidence"})()}) == "Not enough GitHub evidence was available for a reliable report."


def test_recruiter_summary_matches_report_status() -> None:
    service = _make_service()
    context = {"semantic_result": type("X", (), {"semantic_status": "verified"})(), "capability_snapshot": {"satisfied_requirements": [{"label": "Model training"}, {"label": "Model evaluation"}], "missing_critical_requirements": []}, "evidence": _evidence_row()}
    summary = service.build_recruiter_summary(context)
    assert "supports the student's claim" in summary.lower()


def test_confirmed_capabilities_populated_from_capability_metadata() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert {item.requirement_key for item in report.confirmed_capabilities} == {"model_training", "prediction_inference", "model_evaluation"}
    assert any(item.supporting_line_range == "20-32" for item in report.confirmed_capabilities)


def test_missing_capabilities_populated_when_critical_requirements_absent() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="partially_verified",
            confidence=0.71,
            recruiter_summary="Partial support.",
            evidence_summary="Partial support.",
            limitations="One capability missing.",
            next_action="Human review recommended.",
            satisfied=[
                {
                    "requirement_key": "model_training",
                    "requirement_label": "Model training",
                    "requirement_type": "model_training",
                    "importance": "critical",
                    "matching_segment_start": 20,
                    "matching_segment_end": 32,
                    "matching_segment_type": "model_training",
                    "matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                    "matching_signals": ["DecisionTreeClassifier", "fit("],
                }
            ],
            missing_critical=[
                {
                    "requirement_key": "model_evaluation",
                    "requirement_label": "Model evaluation",
                    "requirement_type": "model_evaluation",
                    "importance": "critical",
                }
            ],
        ),
    )
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert report.missing_capabilities[0].requirement_key == "model_evaluation"


def test_supporting_line_ranges_preserve_exact_line_numbers() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert any(item.line_start == 20 and item.line_end == 32 for item in report.supporting_line_ranges)


def test_duplicate_line_ranges_are_deduplicated() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(
        store,
        _semantic_result_row(
            status="verified",
            confidence=0.91,
            recruiter_summary="Verified.",
            evidence_summary="Verified.",
            limitations="None.",
            next_action="No further action required.",
            satisfied=[
                {
                    "requirement_key": "model_training",
                    "requirement_label": "Model training",
                    "requirement_type": "model_training",
                    "importance": "critical",
                    "matching_segment_start": 20,
                    "matching_segment_end": 32,
                    "matching_segment_type": "model_training",
                    "matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                    "matching_signals": ["DecisionTreeClassifier", "fit("],
                }
            ],
            missing_critical=[],
            matched_segments=[
                _segment(20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("], 0.91),
                _segment(20, 32, "Initializes a Decision Tree classifier and trains it using fit().", "model_training", ["DecisionTreeClassifier", "fit("], 0.91),
            ],
        ),
    )
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert len(report.supporting_line_ranges) == 1


def test_report_snapshot_stores_compact_source_metadata() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert report.report_snapshot["semantic_result_id"] == SEMANTIC_RESULT_ID
    assert report.report_snapshot["capability_match_status"] == "strong_capability_match"
    assert report.report_snapshot["source_matched_segments"]


def test_report_persists_to_db() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    assert report.id in store["github_recruiter_proof_reports"]


def test_latest_list_and_get_endpoints_work() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _evidence_row()
        store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
        semantic_one = _seed_github_result(store)
        first_report = GitHubRecruiterProofReportService(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
        store["github_recruiter_proof_reports"][first_report.id]["created_at"] = _now(-10)
        semantic_two = _seed_github_result(
            store,
            _semantic_result_row(
                status="partially_verified",
                confidence=0.72,
                recruiter_summary="Partial.",
                evidence_summary="Partial.",
                limitations="Partial.",
                next_action="Human review recommended.",
                satisfied=[
                    {
                        "requirement_key": "model_training",
                        "requirement_label": "Model training",
                        "requirement_type": "model_training",
                        "importance": "critical",
                        "matching_segment_start": 20,
                        "matching_segment_end": 32,
                        "matching_segment_type": "model_training",
                        "matching_segment_summary": "Initializes a Decision Tree classifier and trains it using fit().",
                        "matching_signals": ["DecisionTreeClassifier", "fit("],
                    }
                ],
                missing_critical=[
                    {
                        "requirement_key": "model_evaluation",
                        "requirement_label": "Model evaluation",
                        "requirement_type": "model_evaluation",
                        "importance": "critical",
                    }
                ],
                created_at=_now(10),
            ),
        )
        second_report = GitHubRecruiterProofReportService(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)

        latest = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-recruiter-proof-reports/latest")
        listing = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-recruiter-proof-reports")
        one = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-recruiter-proof-reports/{second_report.id}")

        assert latest.status_code == 200
        assert latest.json()["id"] == second_report.id
        assert listing.status_code == 200
        assert listing.json()["results"][0]["id"] == second_report.id
        assert one.status_code == 200
        assert one.json()["id"] == second_report.id
    finally:
        _clear_overrides()


def test_other_user_cannot_access_report() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    report = _make_service(store).generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
    client = _client(store, OTHER_USER_ID)
    try:
        store.setdefault("github_recruiter_proof_reports", {})[report.id] = {
            "id": report.id,
            "evidence_id": report.evidence_id,
            "github_semantic_result_id": report.github_semantic_result_id,
            "user_id": report.user_id,
            "report_status": report.report_status,
            "confidence_score": report.confidence_score,
            "report_version": report.report_version,
            "student_claim": report.student_claim,
            "headline": report.headline,
            "recruiter_summary": report.recruiter_summary,
            "evidence_summary": report.evidence_summary,
            "limitations": report.limitations,
            "recommended_next_action": report.recommended_next_action,
            "confirmed_capabilities": [item.model_dump() for item in report.confirmed_capabilities],
            "missing_capabilities": [item.model_dump() for item in report.missing_capabilities],
            "supporting_line_ranges": [item.model_dump() for item in report.supporting_line_ranges],
            "report_snapshot": report.report_snapshot,
            "created_at": report.created_at,
            "updated_at": report.updated_at,
        }
        response = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/github-recruiter-proof-reports/{report.id}")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_non_github_evidence_returns_422() -> None:
    store: dict = {}
    evidence = _evidence_row(repository_url="https://example.com/project", file_path=None, evidence_type="Deployed website URL")
    store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
    _seed_github_result(store)
    service = _make_service(store)

    try:
        service.generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
        raise AssertionError("Expected GitHubRecruiterProofReportNotAllowedError")
    except GitHubRecruiterProofReportNotAllowedError:
        pass


def test_missing_semantic_result_returns_clean_422() -> None:
    store: dict = {}
    _seed_evidence(store)
    service = _make_service(store)

    try:
        service.generate_latest_github_recruiter_proof_report(USER_ID, EVIDENCE_ID)
        raise AssertionError("Expected GitHubRecruiterProofReportNotAllowedError")
    except GitHubRecruiterProofReportNotAllowedError:
        pass


def test_missing_explicit_semantic_result_returns_404() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_result(store)
    service = _make_service(store)

    try:
        service.generate_github_recruiter_proof_report(USER_ID, EVIDENCE_ID, semantic_result_id=str(uuid4()))
        raise AssertionError("Expected GitHubSemanticVerificationResultNotFoundError")
    except GitHubSemanticVerificationResultNotFoundError:
        pass
