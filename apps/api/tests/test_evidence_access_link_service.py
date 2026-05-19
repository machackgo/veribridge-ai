"""Tests for direct evidence access link generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.evidence_access_link_service import (
    EvidenceAccessLinkNotAllowedError,
    EvidenceAccessLinkService,
)

USER_ID = "00000000-0000-0000-0000-000000000801"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000802"
EVIDENCE_ID = "00000000-0000-0000-0000-000000000901"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _now(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()


def _seed_evidence(store: dict, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": EVIDENCE_ID,
        "user_id": USER_ID,
        "skill_name": "Machine Learning",
        "evidence_type": "GitHub file",
        "repository_url": "https://github.com/user/project",
        "file_path": "app/model.py",
        "line_start": 20,
        "line_end": 32,
        "evidence_description": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        "metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    store.setdefault("skill_evidence", {})[row["id"]] = row
    return row


def _seed_github_report(store: dict, *, ranges: list[dict[str, object]] | None = None, created_at: str | None = None) -> dict[str, object]:
    report = {
        "id": str(uuid4()),
        "evidence_id": EVIDENCE_ID,
        "github_semantic_result_id": str(uuid4()),
        "user_id": USER_ID,
        "report_status": "verified",
        "confidence_score": 0.93,
        "report_version": "github-recruiter-proof-report-v1",
        "student_claim": "I built and evaluated a Decision Tree classification model for stroke prediction.",
        "headline": "Selected GitHub code supports the student’s claim.",
        "recruiter_summary": "VeriBridge found that the selected code supports the student's claim.",
        "evidence_summary": "Lines 20-32 train the model.",
        "limitations": "This report reflects selected GitHub lines only.",
        "recommended_next_action": "No further action required.",
        "confirmed_capabilities": [
            {"requirement_key": "model_training", "label": "Model training", "supporting_line_range": "20-32"},
        ],
        "missing_capabilities": [],
        "supporting_line_ranges": ranges
        or [
            {
                "line_start": 20,
                "line_end": 32,
                "segment_type": "model_training",
                "summary": "Initializes a DecisionTreeClassifier and trains it with fit().",
                "detected_signals": ["DecisionTreeClassifier", "fit("],
                "supports_claim": True,
                "semantic_score": 0.92,
            }
        ],
        "report_snapshot": {"semantic_status": "verified"},
        "created_at": created_at or _now(),
        "updated_at": created_at or _now(),
    }
    store.setdefault("github_recruiter_proof_reports", {})[report["id"]] = report
    return report


def _seed_website_semantic_result(store: dict, *, created_at: str | None = None) -> dict[str, object]:
    row = {
        "id": str(uuid4()),
        "evidence_id": EVIDENCE_ID,
        "plan_id": str(uuid4()),
        "user_id": USER_ID,
        "semantic_status": "verified",
        "confidence_score": 0.91,
        "evaluator_version": "website-semantic-evaluator-mock-v1",
        "evaluator_provider": "deterministic_mock",
        "recruiter_facing_summary": "VeriBridge verified the deployed website.",
        "evidence_summary": "The live website displayed the expected output.",
        "limitations": "Visible behavior only.",
        "recommended_next_action": "No further action required.",
        "source_snapshot": {},
        "created_at": created_at or _now(),
        "updated_at": created_at or _now(),
    }
    store.setdefault("website_semantic_verification_results", {})[row["id"]] = row
    return row


def test_github_exact_line_url_is_generated_correctly() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(store)

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert results[0].access_type == "github_exact_lines"
    assert results[0].url.endswith("#L20-L32")
    assert results[0].source_report_type == "github_recruiter_proof_report"


def test_single_line_url_is_generated_correctly() -> None:
    store: dict = {}
    _seed_evidence(store, line_start=20, line_end=20)
    _seed_github_report(store, ranges=[{"line_start": 20, "line_end": 20, "segment_type": "model_training", "summary": "Single-line model setup.", "detected_signals": ["fit("], "supports_claim": True, "semantic_score": 0.9}])

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert results[0].url.endswith("#L20")


def test_github_links_preserve_file_path_and_line_range() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(store)

    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]

    assert result.file_path == "app/model.py"
    assert result.line_start == 20
    assert result.line_end == 32


def test_multiple_supporting_line_ranges_create_multiple_access_links() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(
        store,
        ranges=[
            {
                "line_start": 20,
                "line_end": 32,
                "segment_type": "model_training",
                "summary": "Training block.",
                "detected_signals": ["fit("],
                "supports_claim": True,
                "semantic_score": 0.92,
            },
            {
                "line_start": 34,
                "line_end": 50,
                "segment_type": "prediction_inference",
                "summary": "Prediction block.",
                "detected_signals": ["predict("],
                "supports_claim": True,
                "semantic_score": 0.89,
            },
        ],
    )

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert len(results) == 2
    assert results[0].url.endswith("#L20-L32")
    assert results[1].url.endswith("#L34-L50")


def test_missing_github_repo_or_file_data_returns_insufficient_data() -> None:
    store: dict = {}
    _seed_evidence(store, repository_url="https://github.com/user/project", file_path=None, line_start=None, line_end=None)

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert results[0].availability_status == "insufficient_data"
    assert results[0].url == ""


def test_no_github_recruiter_report_yet_returns_safe_insufficient_data() -> None:
    store: dict = {}
    _seed_evidence(store, line_start=None, line_end=None)

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert results[0].availability_status == "insufficient_data"
    assert results[0].source_report_type == "direct_skill_evidence"


def test_website_evidence_generates_live_website_link() -> None:
    store: dict = {}
    _seed_evidence(
        store,
        evidence_type="Deployed website URL",
        evidence_url="https://student-app.example.com",
        repository_url=None,
        file_path=None,
        line_start=None,
        line_end=None,
    )
    _seed_website_semantic_result(store)

    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]

    assert result.access_type == "live_website"
    assert result.url == "https://student-app.example.com"
    assert result.source_report_type == "website_semantic_verification_result"


def test_private_or_local_website_urls_are_marked_invalid_source() -> None:
    store: dict = {}
    _seed_evidence(
        store,
        evidence_type="Deployed website URL",
        evidence_url="http://localhost:3000",
        repository_url=None,
        file_path=None,
        line_start=None,
        line_end=None,
    )

    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]

    assert result.availability_status == "invalid_source"
    assert result.url == ""


def test_access_links_persist_to_db() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(store)

    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]

    assert result.id in store["evidence_access_links"]


def test_latest_list_and_get_endpoints_work() -> None:
    store: dict = {}
    client = _client(store)
    try:
        _seed_evidence(store)
        _seed_github_report(store)
        generated = client.post(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/evidence-access-links")
        assert generated.status_code == 200
        link_id = generated.json()["results"][0]["id"]

        latest = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/evidence-access-links/latest")
        listing = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/evidence-access-links")
        one = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/evidence-access-links/{link_id}")

        assert latest.status_code == 200
        assert listing.status_code == 200
        assert one.status_code == 200
        assert one.json()["id"] == link_id
    finally:
        _clear_overrides()


def test_other_user_cannot_access_another_users_links() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(store)
    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]
    client = _client(store, OTHER_USER_ID)
    try:
        response = client.get(f"/api/v1/student/skill-evidence/{EVIDENCE_ID}/evidence-access-links/{result.id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_unsupported_evidence_type_returns_clean_422() -> None:
    store: dict = {}
    store.setdefault("skill_evidence", {})[EVIDENCE_ID] = {
        "id": EVIDENCE_ID,
        "user_id": USER_ID,
        "skill_name": "Writing",
        "evidence_type": "Coursework PDF",
        "evidence_description": "Essay submission.",
        "metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }

    try:
        EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)
        raise AssertionError("Expected EvidenceAccessLinkNotAllowedError")
    except EvidenceAccessLinkNotAllowedError:
        pass
    finally:
        _clear_overrides()


def test_github_links_are_still_generated_when_only_one_supporting_range_exists() -> None:
    store: dict = {}
    _seed_evidence(store)
    _seed_github_report(
        store,
        ranges=[
            {
                "line_start": 20,
                "line_end": 32,
                "segment_type": "model_training",
                "summary": "Training block.",
                "detected_signals": ["fit("],
                "supports_claim": True,
                "semantic_score": 0.92,
            }
        ],
    )

    results = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)

    assert len(results) == 1
    assert results[0].url.endswith("#L20-L32")


def test_generation_without_report_but_with_direct_evidence_line_range_uses_direct_skill_evidence() -> None:
    store: dict = {}
    _seed_evidence(store, line_start=20, line_end=32)

    result = EvidenceAccessLinkService(store).generate_evidence_access_links(USER_ID, EVIDENCE_ID)[0]

    assert result.source_report_type == "direct_skill_evidence"
    assert result.availability_status == "available"
