"""Tests for expected-output matching in website semantic verification."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_expected_output_match_service import (
    build_expected_output_text,
    build_observed_output_text,
    detect_exact_output_signal_hits,
    detect_missing_required_signals,
    evaluate_expected_output_match,
    extract_required_output_signals,
)

USER_ID = "00000000-0000-0000-0000-000000000001"


class _FakeEmbeddingProvider:
    model_name = "fake-expected-output-model"

    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors

    def encode(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 2
        return self._vectors


class _UnavailableEmbeddingProvider:
    model_name = "unavailable-expected-output-model"

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("model unavailable")


def _context(expected: str, observed: str, *, browser_status: str = "browser_verified") -> dict:
    return {
        "plan": {
            "feature_to_verify": "predicts accident risk for a route after users enter source and destination locations",
            "expected_output": expected,
            "normalized_test_steps": ["Open website", "Analyze route", "Confirm expected output"],
        },
        "browser_run": {
            "browser_execution_status": browser_status,
            "execution_summary": "Browser execution completed the route analysis flow.",
            "page_title": "Route Analyzer",
            "safe_text_snapshot": observed,
            "steps_attempted": 4,
            "steps_passed": 4 if browser_status == "browser_verified" else 2,
        },
        "browser_steps": [
            {
                "step_status": "passed" if browser_status == "browser_verified" else "needs_human_review",
                "observed_result": observed,
                "step_summary": "Observed final website output after the action.",
            }
        ],
        "static_run": {
            "execution_status": "static_verified",
            "execution_summary": "Static inspection found route risk language.",
        },
        "static_checks": [
            {
                "check_status": "passed",
                "observed_value": observed,
                "check_summary": "Observed expected route terminology.",
            }
        ],
    }


def _client(store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seed_semantic_context(store: dict, *, expected: str, observed: str, browser_status: str = "browser_verified") -> dict:
    evidence = {
        "id": str(uuid4()),
        "user_id": USER_ID,
        "skill_name": "FastAPI",
        "evidence_type": "Deployed website URL",
        "evidence_url": "https://student-demo.example.com",
        "proof_visibility": "public",
        "evidence_description": "Built a website that predicts accident route risk and recommends safer routes.",
        "metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    plan = {
        "id": str(uuid4()),
        "user_id": USER_ID,
        "skill_evidence_id": evidence["id"],
        "website_url": evidence["evidence_url"],
        "feature_to_verify": "predicts accident risk for a route after users enter source and destination locations",
        "plan_status": "ready",
        "normalized_test_steps": ["Open website", "Enter route", "Click Analyze Route", "Confirm expected output"],
        "expected_output": expected,
        "sample_inputs": {"source": "Worcester", "destination": "Boston"},
        "inferred_action_candidates": [],
        "validation_warnings": [],
        "requires_login": False,
        "can_attempt_automated_execution": True,
        "planner_version": "website-plan-v1",
        "guide_snapshot": {},
        "created_at": _now(),
    }
    static_run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": USER_ID,
        "execution_status": "static_verified",
        "executor_version": "website-executor-static-v1",
        "execution_summary": f"Static checks found: {observed}",
        "checks_attempted": 4,
        "checks_passed": 4,
        "checks_failed": 0,
        "checks_needing_review": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    browser_run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": USER_ID,
        "browser_execution_status": browser_status,
        "executor_version": "website-browser-executor-v1",
        "execution_summary": "Browser flow reached the final output area.",
        "inspected_url": evidence["evidence_url"],
        "final_url": evidence["evidence_url"],
        "page_title": "Route Analyzer",
        "safe_text_snapshot": observed,
        "steps_attempted": 4,
        "steps_passed": 4 if browser_status == "browser_verified" else 2,
        "steps_failed": 0,
        "steps_skipped": 0,
        "steps_needing_review": 0,
        "browser_metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    step = {
        "id": str(uuid4()),
        "run_id": browser_run["id"],
        "step_index": 4,
        "plan_step_key": "expected_output",
        "action_type": "assert_text_present",
        "expected_result": expected,
        "observed_result": observed,
        "step_status": "passed",
        "step_summary": "The final page produced output after analysis.",
        "created_at": _now(),
    }
    store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
    store.setdefault("website_verification_plans", {})[plan["id"]] = plan
    store.setdefault("website_verification_runs", {})[static_run["id"]] = static_run
    store.setdefault("website_browser_verification_runs", {})[browser_run["id"]] = browser_run
    store.setdefault("website_browser_verification_steps", {})[step["id"]] = step
    return evidence


def test_expected_output_text_builder_uses_expected_output() -> None:
    text = build_expected_output_text(_context("A risk score and safer route recommendation should appear.", "Risk Score: High."))

    assert "risk score" in text.lower()
    assert "safer route recommendation" in text.lower()


def test_observed_output_text_builder_uses_browser_results_before_static() -> None:
    text = build_observed_output_text(_context("A risk score should appear.", "Risk Score: High. Safer route available."))

    assert "Risk Score: High" in text
    assert "Browser execution completed" in text


def test_strong_expected_output_match_when_expected_and_observed_align() -> None:
    result = evaluate_expected_output_match(
        _context("A route risk score and safer route recommendation should appear.", "Risk Score: High. Safer route available."),
        _FakeEmbeddingProvider([[1.0, 0.0], [0.95, 0.05]]),
    )

    assert result.label == "strong_expected_output_match"
    assert result.supports_verification is True
    assert result.blocks_full_verification is False
    assert "risk score" in result.exact_signal_hits


def test_low_expected_output_match_for_generic_output() -> None:
    result = evaluate_expected_output_match(
        _context("A risk score and accident-risk prediction should appear.", "Route analysis completed."),
        _FakeEmbeddingProvider([[1.0, 0.0], [0.1, 0.9]]),
    )

    assert result.label in {"low_expected_output_match", "weak_expected_output_match"}
    assert result.supports_verification is False
    assert result.blocks_full_verification is True


def test_risk_prediction_vs_historical_counts_is_not_strong_match() -> None:
    result = evaluate_expected_output_match(
        _context("A risk score and accident-risk prediction should appear.", "Historical accident counts by city are displayed."),
        _FakeEmbeddingProvider([[1.0, 0.0], [0.6, 0.4]]),
    )

    assert result.label != "strong_expected_output_match"
    assert result.blocks_full_verification is True


def test_verification_result_vs_upload_successful_is_not_strong_match() -> None:
    result = evaluate_expected_output_match(
        _context("A verification result should confirm the selected skill was found.", "GitHub repository uploaded successfully."),
        _FakeEmbeddingProvider([[1.0, 0.0], [0.55, 0.45]]),
    )

    assert result.supports_verification is False
    assert result.blocks_full_verification is True
    assert "verification result" in result.missing_required_signals


def test_customized_resume_draft_vs_job_description_uploaded_is_not_strong_match() -> None:
    result = evaluate_expected_output_match(
        _context("A customized resume draft should appear.", "Job description uploaded successfully."),
        _FakeEmbeddingProvider([[1.0, 0.0], [0.55, 0.45]]),
    )

    assert result.supports_verification is False
    assert result.blocks_full_verification is True


def test_signal_extraction_identifies_key_output_phrases() -> None:
    signals = extract_required_output_signals("A prediction probability and predicted disease label should be shown.")

    assert "prediction probability" in signals
    assert "disease label" in signals
    assert "predicted label" in signals


def test_missing_required_signals_are_detected() -> None:
    signals = ["risk score", "safer route", "recommendation"]
    hits = detect_exact_output_signal_hits(signals, "Risk Score: High.")
    misses = detect_missing_required_signals(signals, "Risk Score: High.")

    assert hits == ["risk score"]
    assert "safer route" in misses
    assert "recommendation" in misses


def test_provider_unavailable_uses_exact_signal_fallback() -> None:
    result = evaluate_expected_output_match(
        _context("A risk score and safer route recommendation should appear.", "Risk Score: High. Safer route available."),
        _UnavailableEmbeddingProvider(),
    )

    assert result.available is False
    assert result.supports_verification is True
    assert result.blocks_full_verification is False
    assert "RuntimeError" in (result.notes or "")


def test_expected_output_match_metadata_is_stored_in_semantic_source_snapshot() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_semantic_context(
            store,
            expected="A risk score and safer route recommendation should appear.",
            observed="Risk Score: High. Safer route available.",
        )
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={})

        assert response.status_code == 200
        snapshot = response.json()["source_snapshot"]["expected_output_match"]
        assert snapshot["label"] in {"strong_expected_output_match", "moderate_expected_output_match"}
        assert "risk score" in snapshot["exact_signal_hits"]
        assert snapshot["blocks_full_verification"] is False
    finally:
        _clear_overrides()


def test_verified_semantic_outcome_is_blocked_when_expected_output_match_is_weak() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_semantic_context(
            store,
            expected="A risk score and accident-risk prediction should appear.",
            observed="Route analysis completed.",
        )
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={}).json()

        assert data["semantic_status"] == "needs_human_review"
        assert data["source_snapshot"]["expected_output_match"]["blocks_full_verification"] is True
    finally:
        _clear_overrides()


def test_strong_browser_support_and_strong_expected_output_match_can_verify() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_semantic_context(
            store,
            expected="A risk score and safer route recommendation should appear.",
            observed="Risk Score: High. Safer route available.",
        )
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={}).json()

        assert data["semantic_status"] == "verified"
        assert data["source_snapshot"]["expected_output_match"]["supports_verification"] is True
    finally:
        _clear_overrides()


def test_generic_success_messages_do_not_create_false_verified_results() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_semantic_context(
            store,
            expected="A recommended salary range and target market comparison should appear.",
            observed="Salary dashboard loaded.",
        )
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results", json={}).json()

        assert data["semantic_status"] == "needs_human_review"
        assert data["source_snapshot"]["expected_output_match"]["blocks_full_verification"] is True
    finally:
        _clear_overrides()
