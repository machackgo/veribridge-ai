"""Tests for semantic website verification results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_semantic_similarity_service import SemanticSimilarityResult
from app.services.website_semantic_evaluator_provider import DeterministicMockWebsiteSemanticEvaluator

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _now(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat()


def _seed_evidence(store: dict, user_id: str = USER_ID, website: bool = True) -> dict:
    evidence = {
        "id": str(uuid4()),
        "user_id": user_id,
        "skill_name": "FastAPI",
        "evidence_type": "Deployed website URL" if website else "Code file",
        "evidence_url": "https://student-demo.example.com" if website else "https://github.com/acme/repo/blob/main/app.py",
        "proof_visibility": "public",
        "evidence_description": "Built a deployed app that predicts accident route risk and recommends safer routes.",
        "metadata": {"title": "Route risk dashboard"},
        "created_at": _now(),
        "updated_at": _now(),
    }
    store.setdefault("skill_evidence", {})[evidence["id"]] = evidence
    return evidence


def _seed_plan(store: dict, evidence: dict, *, warnings: list[str] | None = None, requires_login: bool = False, offset: int = 0) -> dict:
    plan = {
        "id": str(uuid4()),
        "user_id": evidence["user_id"],
        "skill_evidence_id": evidence["id"],
        "website_url": evidence["evidence_url"],
        "feature_to_verify": "Accident risk rerouting dashboard",
        "plan_status": "ready",
        "normalized_test_steps": [
            "Open the live website.",
            "Enter Worcester, MA as the source.",
            "Enter Boston, MA as the destination.",
            "Click Analyze Route.",
            "Confirm a risk score and safer rerouting recommendation appears.",
        ],
        "expected_output": "Risk score and safer rerouting recommendation are visible.",
        "sample_inputs": {"source": "Worcester, MA", "destination": "Boston, MA"},
        "inferred_action_candidates": [],
        "validation_warnings": warnings or [],
        "requires_login": requires_login,
        "can_attempt_automated_execution": not requires_login,
        "planner_version": "website-plan-v1",
        "guide_snapshot": {},
        "created_at": _now(offset),
    }
    store.setdefault("website_verification_plans", {})[plan["id"]] = plan
    return plan


def _seed_static_run(store: dict, evidence: dict, plan: dict, status: str = "static_verified", offset: int = 0) -> dict:
    passed = 4 if status != "failed_static_checks" else 1
    failed = 0 if status != "failed_static_checks" else 4
    run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": evidence["user_id"],
        "execution_status": status,
        "executor_version": "website-executor-static-v1",
        "execution_summary": "Static checks found risk score and safer rerouting content." if failed == 0 else "Static checks did not find route risk output.",
        "checks_attempted": 5,
        "checks_passed": passed,
        "checks_failed": failed,
        "checks_needing_review": 0,
        "created_at": _now(offset),
        "updated_at": _now(offset),
    }
    store.setdefault("website_verification_runs", {})[run["id"]] = run
    check = {
        "id": str(uuid4()),
        "run_id": run["id"],
        "check_key": "expected_output_keywords",
        "check_label": "Expected output keyword check",
        "check_type": "expected_output_keyword_check",
        "expected_value": "risk, score, safer, rerouting",
        "observed_value": "risk, score, safer, rerouting" if failed == 0 else None,
        "check_status": "passed" if failed == 0 else "failed",
        "check_summary": "Matched keywords: risk, score, safer, rerouting." if failed == 0 else "No derived keywords were found.",
        "created_at": _now(offset),
    }
    store.setdefault("website_verification_run_checks", {})[check["id"]] = check
    return run


def _seed_browser_run(store: dict, evidence: dict, plan: dict, status: str = "browser_verified", offset: int = 0) -> dict:
    passed = 4 if status == "browser_verified" else 2 if status == "browser_partially_verified" else 1
    failed = 1 if status == "browser_failed" else 0
    review = 1 if status in {"needs_human_review", "blocked_by_login"} else 0
    run = {
        "id": str(uuid4()),
        "evidence_id": evidence["id"],
        "plan_id": plan["id"],
        "user_id": evidence["user_id"],
        "browser_execution_status": status,
        "executor_version": "website-browser-executor-v1",
        "execution_summary": "Browser flow displayed a risk score and safer rerouting recommendation.",
        "inspected_url": evidence["evidence_url"],
        "final_url": evidence["evidence_url"],
        "page_title": "Accident Risk Route Analyzer",
        "safe_text_snapshot": (
            "Risk Score: High. Safer rerouting recommendation available."
            if status != "browser_failed"
            else "Welcome to my portfolio."
        ),
        "steps_attempted": 4,
        "steps_passed": passed,
        "steps_failed": failed,
        "steps_skipped": 0,
        "steps_needing_review": review,
        "browser_metadata": {},
        "created_at": _now(offset),
        "updated_at": _now(offset),
    }
    store.setdefault("website_browser_verification_runs", {})[run["id"]] = run
    step = {
        "id": str(uuid4()),
        "run_id": run["id"],
        "step_index": 4,
        "plan_step_key": "expected_output",
        "action_type": "assert_text_present",
        "expected_result": plan["expected_output"],
        "observed_result": "risk, score, safer, rerouting" if status != "browser_failed" else None,
        "step_status": "passed" if status != "browser_failed" else "failed",
        "step_summary": "Expected output appeared on the final page." if status != "browser_failed" else "Expected output was not visible.",
        "created_at": _now(offset),
    }
    store.setdefault("website_browser_verification_steps", {})[step["id"]] = step
    return run


def _seed_ready_context(
    store: dict,
    *,
    static_status: str | None = "static_verified",
    browser_status: str | None = "browser_verified",
    warnings: list[str] | None = None,
    requires_login: bool = False,
) -> tuple[dict, dict, dict | None, dict | None]:
    evidence = _seed_evidence(store)
    plan = _seed_plan(store, evidence, warnings=warnings, requires_login=requires_login)
    static_run = _seed_static_run(store, evidence, plan, static_status) if static_status else None
    browser_run = _seed_browser_run(store, evidence, plan, browser_status) if browser_status else None
    return evidence, plan, static_run, browser_run


def _evaluate(client: TestClient, evidence_id: str, body: dict | None = None):
    return client.post(f"/api/v1/student/skill-evidence/{evidence_id}/website-semantic-verification-results", json=body or {})


def test_semantic_evaluator_returns_verified_when_browser_run_verified_and_outputs_match() -> None:
    context = {
        "plan": {"expected_output": "Risk score and safer rerouting recommendation are visible.", "normalized_test_steps": ["Open"], "validation_warnings": []},
        "browser_run": {"browser_execution_status": "browser_verified", "steps_attempted": 4, "steps_passed": 4, "safe_text_snapshot": "Risk score high. Safer rerouting recommendation available."},
        "static_run": {"execution_status": "static_verified", "checks_attempted": 5, "checks_passed": 5},
        "browser_steps": [],
        "static_checks": [],
    }

    result = DeterministicMockWebsiteSemanticEvaluator().evaluate(context)

    assert result.semantic_status == "verified"
    assert 0.85 <= result.confidence_score <= 0.98


def test_semantic_result_endpoint_returns_verified_and_persists() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store)
        response = _evaluate(client, evidence["id"])

        assert response.status_code == 200
        data = response.json()
        assert data["semantic_status"] == "verified"
        assert data["evidence_id"] == evidence["id"]
        assert data["id"] in store["website_semantic_verification_results"]
        assert data["source_snapshot"]["product_verification_reconciliation"]["display_status"] in {
            "verified",
            "supported_with_review",
            "partially_supported",
        }
    finally:
        _clear_overrides()


def test_semantic_evaluator_returns_partially_verified_for_partial_browser_evidence() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store, browser_status="browser_partially_verified")
        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "partially_verified"
        assert 0.55 <= data["confidence_score"] <= 0.84
    finally:
        _clear_overrides()


def test_semantic_evaluator_returns_partially_verified_for_partial_static_without_browser() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store, static_status="partial_verification", browser_status=None)
        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "partially_verified"
        assert 0.55 <= data["confidence_score"] <= 0.84
    finally:
        _clear_overrides()


def test_semantic_evaluator_returns_not_verified_when_browser_and_static_fail() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store, static_status="failed_static_checks", browser_status="browser_failed")
        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "not_verified"
        assert 0.70 <= data["confidence_score"] <= 0.95
    finally:
        _clear_overrides()


def test_semantic_evaluator_returns_needs_human_review_for_blocked_by_login_or_ambiguous_run() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store, browser_status="blocked_by_login", requires_login=True)
        blocked = _evaluate(client, evidence["id"]).json()
        assert blocked["semantic_status"] == "needs_human_review"

        evidence2, _, _, _ = _seed_ready_context(store, browser_status="browser_verified", warnings=["vague_verification_steps"])
        ambiguous = _evaluate(client, evidence2["id"]).json()
        assert ambiguous["semantic_status"] == "needs_human_review"
        assert 0.35 <= ambiguous["confidence_score"] <= 0.70
    finally:
        _clear_overrides()


def test_semantic_evaluator_returns_insufficient_evidence_when_no_runs_exist() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_evidence(store)
        _seed_plan(store, evidence)
        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "insufficient_evidence"
        assert 0.10 <= data["confidence_score"] <= 0.40
    finally:
        _clear_overrides()


def test_recruiter_summary_and_limitations_are_generated() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store)
        data = _evaluate(client, evidence["id"]).json()

        assert "VeriBridge verified" in data["recruiter_facing_summary"]
        assert "visible website behavior" in data["limitations"]
        assert data["recommended_next_action"] == "No further action required."
    finally:
        _clear_overrides()


def test_latest_endpoint_returns_newest_result_and_list_is_newest_first() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store)
        first = _evaluate(client, evidence["id"]).json()
        second = _evaluate(client, evidence["id"]).json()

        latest = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results/latest").json()
        listed = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results").json()

        assert latest["id"] == second["id"]
        assert listed["results"][0]["id"] == second["id"]
        assert listed["results"][1]["id"] == first["id"]
    finally:
        _clear_overrides()


def test_get_one_endpoint_works() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store)
        result = _evaluate(client, evidence["id"]).json()
        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results/{result['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == result["id"]
    finally:
        _clear_overrides()


def test_user_cannot_access_another_users_semantic_result() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _, _ = _seed_ready_context(store)
        result = _evaluate(client, evidence["id"]).json()
        other_client = _client(store, OTHER_USER_ID)

        response = other_client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-semantic-verification-results/{result['id']}")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_missing_evidence_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = _evaluate(client, "missing")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_missing_plan_returns_404_when_explicitly_requested() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_evidence(store)
        response = _evaluate(client, evidence["id"], {"plan_id": "missing"})

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "website_verification_plan_not_found"
    finally:
        _clear_overrides()


def test_missing_static_run_returns_404_when_explicitly_requested() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, plan, _, _ = _seed_ready_context(store)
        response = _evaluate(client, evidence["id"], {"plan_id": plan["id"], "static_run_id": "missing"})

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "website_verification_run_not_found"
    finally:
        _clear_overrides()


def test_missing_browser_run_returns_404_when_explicitly_requested() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, plan, _, _ = _seed_ready_context(store)
        response = _evaluate(client, evidence["id"], {"plan_id": plan["id"], "browser_run_id": "missing"})

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "website_browser_verification_run_not_found"
    finally:
        _clear_overrides()


def test_non_website_evidence_returns_clean_422() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_evidence(store, website=False)
        _seed_plan(store, evidence)
        response = _evaluate(client, evidence["id"])

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "website_semantic_verification_not_allowed"
    finally:
        _clear_overrides()


def test_custom_explicit_static_and_browser_run_ids_are_used() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = _seed_evidence(store)
        plan = _seed_plan(store, evidence)
        _seed_static_run(store, evidence, plan, "failed_static_checks", offset=1)
        _seed_browser_run(store, evidence, plan, "browser_failed", offset=1)
        explicit_static = _seed_static_run(store, evidence, plan, "static_verified", offset=0)
        explicit_browser = _seed_browser_run(store, evidence, plan, "browser_verified", offset=0)

        data = _evaluate(
            client,
            evidence["id"],
            {"plan_id": plan["id"], "static_run_id": explicit_static["id"], "browser_run_id": explicit_browser["id"]},
        ).json()

        assert data["semantic_status"] == "verified"
        assert data["static_run_id"] == explicit_static["id"]
        assert data["browser_run_id"] == explicit_browser["id"]
    finally:
        _clear_overrides()


def test_source_snapshot_includes_compact_summary_references() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, plan, static_run, browser_run = _seed_ready_context(store)
        data = _evaluate(client, evidence["id"]).json()
        snapshot = data["source_snapshot"]

        assert snapshot["plan"]["id"] == plan["id"]
        assert snapshot["static_run"]["id"] == static_run["id"]
        assert snapshot["browser_run"]["id"] == browser_run["id"]
        assert "safe_text_snapshot_excerpt" in snapshot["browser_run"]
        assert len(snapshot["browser_run"]["safe_text_snapshot_excerpt"]) < 500
    finally:
        _clear_overrides()


def test_high_semantic_similarity_is_not_enough_when_expected_output_mismatches(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    monkeypatch.setattr(
        "app.services.website_semantic_verification_service.evaluate_semantic_similarity",
        lambda context, provider=None: SemanticSimilarityResult(
            available=True,
            score=0.91,
            model_name="fake-local-embedding-model",
            method="sentence_transformers_cosine_similarity",
            claim_text="The app predicts accident risk.",
            observed_text="Historical accident counts by city are displayed.",
            interpretation="strong_semantic_match",
            supports_verification=True,
        ),
    )
    try:
        evidence, plan, _, browser_run = _seed_ready_context(store)
        plan["expected_output"] = "A risk score and accident-risk prediction should appear."
        browser_run["safe_text_snapshot"] = "Historical accident counts by city are displayed."
        browser_run["execution_summary"] = "Browser flow displayed historical accident counts by city."
        for step in store["website_browser_verification_steps"].values():
            if step["run_id"] == browser_run["id"]:
                step["observed_result"] = "Historical accident counts by city are displayed."
                step["step_summary"] = "Historical counts appeared, but no prediction output was shown."

        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "needs_human_review"
        assert data["source_snapshot"]["expected_output_match"]["blocks_full_verification"] is True
    finally:
        _clear_overrides()


def test_expected_output_match_acts_as_false_positive_guardrail_for_upload_not_verification() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, plan, _, browser_run = _seed_ready_context(store)
        plan["feature_to_verify"] = "verifies whether a student demonstrated the selected programming skill using submitted GitHub evidence"
        plan["expected_output"] = "A verification result should confirm the selected skill was found."
        browser_run["safe_text_snapshot"] = "GitHub repository uploaded successfully."
        browser_run["execution_summary"] = "Browser flow showed that the repository upload completed."
        for step in store["website_browser_verification_steps"].values():
            if step["run_id"] == browser_run["id"]:
                step["observed_result"] = "GitHub repository uploaded successfully."
                step["step_summary"] = "Upload completed, but no verification result appeared."

        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "needs_human_review"
        assert "did not clearly demonstrate" in data["recruiter_facing_summary"]
    finally:
        _clear_overrides()


def test_recruiter_summary_is_cautious_when_output_mismatch_exists() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, plan, _, browser_run = _seed_ready_context(store)
        plan["expected_output"] = "A customized resume draft should appear."
        browser_run["safe_text_snapshot"] = "Job description uploaded successfully."
        browser_run["execution_summary"] = "Browser flow uploaded a job description."
        for step in store["website_browser_verification_steps"].values():
            if step["run_id"] == browser_run["id"]:
                step["observed_result"] = "Job description uploaded successfully."
                step["step_summary"] = "Input upload completed, but no customized resume draft appeared."

        data = _evaluate(client, evidence["id"]).json()

        assert data["semantic_status"] == "needs_human_review"
        assert data["source_snapshot"]["expected_output_match"]["blocks_full_verification"] is True
        assert "reviewed manually" in data["recruiter_facing_summary"]
    finally:
        _clear_overrides()
