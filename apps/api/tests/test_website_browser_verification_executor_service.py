"""Tests for safe browser website verification runs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_browser_verification_executor_service import (
    _BrowserPageState,
    _BrowserRunResult,
    _ExecutedStep,
)

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _website_payload() -> dict:
    return {
        "skill_name": "FastAPI",
        "evidence_type": "Deployed website URL",
        "evidence_url": "https://student-demo.example.com",
        "proof_visibility": "public",
        "evidence_description": "Built a deployed website for route risk scoring.",
        "metadata": {"title": "Route risk dashboard"},
    }


def _browser_guide_payload() -> dict:
    return {
        "project_overview": "Public dashboard for accident risk rerouting.",
        "feature_to_verify": (
            "After a visitor enters a source and destination, the website analyzes accident risk for that route "
            "and displays a safer rerouting recommendation with a visible risk score."
        ),
        "verification_steps": [
            "Open the live website.",
            "Enter source as Worcester, MA.",
            "Enter destination as Boston, MA.",
            "Click Analyze Route.",
            "Confirm a risk score card appears.",
        ],
        "sample_inputs": {"source": "Worcester, MA", "destination": "Boston, MA"},
        "expected_output": "Risk score card and safer rerouting recommendation are visible on the route results page.",
        "login_required": False,
    }


def _login_guide_payload() -> dict:
    return {
        **_browser_guide_payload(),
        "verification_steps": ["Open the live website.", "Sign in with the test account.", "Confirm dashboard loads."],
        "login_required": True,
        "access_notes": "Requires account login.",
    }


def _vague_guide_payload() -> dict:
    return {
        **_browser_guide_payload(),
        "verification_steps": ["Test the app."],
        "sample_inputs": None,
        "expected_output": "The website displays a meaningful project result to the visitor.",
    }


def _unsafe_click_guide_payload() -> dict:
    return {
        **_browser_guide_payload(),
        "verification_steps": ["Open the live website.", "Click Pay Now.", "Confirm receipt preview appears."],
        "sample_inputs": None,
        "expected_output": "Receipt preview confirmation appears after the checkout button is clicked.",
    }


def _create_evidence_guide_plan(client: TestClient, guide: dict | None = None) -> tuple[dict, dict, dict]:
    evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
    guide_response = client.post(
        f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
        json=guide or _browser_guide_payload(),
    ).json()
    plan = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-plan").json()
    return evidence, guide_response, plan


def _fake_browser(monkeypatch, page_text: str, fail_expected: bool = False) -> list:
    captured_steps: list = []

    def fake_run(self, website_url: str, steps: list) -> _BrowserRunResult:
        captured_steps.extend(steps)
        executed = []
        for step in steps:
            if step.action_type == "unsupported":
                status = "unsupported"
                summary = "Unsupported step was not executed."
                observed = None
            elif step.action_type == "assert_text_present" and fail_expected:
                status = "failed"
                summary = "Expected browser text keywords were not visible."
                observed = None
            else:
                status = "passed"
                summary = f"{step.action_type} completed."
                observed = step.action_target or step.action_value or website_url
            executed.append(
                _ExecutedStep(
                    step_index=step.step_index,
                    plan_step_key=step.plan_step_key,
                    action_type=step.action_type,
                    action_target=step.action_target,
                    action_value=step.action_value,
                    expected_result=step.expected_result,
                    observed_result=observed,
                    step_status=status,
                    step_summary=summary,
                )
            )
        return _BrowserRunResult(
            steps=executed,
            page_state=_BrowserPageState(
                inspected_url=website_url,
                final_url=website_url,
                page_title="Accident Risk Route Analyzer",
                safe_text_snapshot=page_text,
                browser_metadata={"adapter": "fake", "browser_closed_cleanly": True},
            ),
        )

    monkeypatch.setattr("app.services.website_browser_verification_executor_service.WebsiteBrowserAutomationAdapter.run", fake_run)
    return captured_steps


def test_browser_executor_creates_run_from_latest_eligible_plan(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, plan = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["evidence_id"] == evidence["id"]
        assert data["plan_id"] == plan["id"]
        assert data["user_id"] == USER_ID
        assert data["executor_version"] == "website-browser-executor-v1"
        assert data["browser_execution_status"] == "browser_verified"
        assert data["steps_attempted"] >= 3
        assert data["steps_passed"] == len(data["steps"])
    finally:
        _clear_overrides()


def test_browser_run_stores_ids_and_page_state(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, plan = _create_evidence_guide_plan(client)
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()

        assert data["evidence_id"] == evidence["id"]
        assert data["plan_id"] == plan["id"]
        assert data["user_id"] == USER_ID
        assert data["final_url"] == "https://student-demo.example.com"
        assert "Risk score" in data["safe_text_snapshot"]
        assert data["browser_metadata"]["browser_closed_cleanly"] is True
    finally:
        _clear_overrides()


def test_login_required_plan_returns_blocked_by_login() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _login_guide_payload())
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "blocked_by_login"
        assert data["steps"][0]["step_status"] == "blocked_by_login"
    finally:
        _clear_overrides()


def test_non_browser_executable_plan_returns_needs_human_review() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _vague_guide_payload())
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "needs_human_review"
        assert data["steps"][0]["step_status"] == "needs_review"
    finally:
        _clear_overrides()


def test_safe_navigation_click_and_expected_text_returns_browser_verified(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    captured_steps = _fake_browser(monkeypatch, "Route risk score card and safer rerouting recommendation.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "browser_verified"
        assert any(step.action_type == "click" and step.action_target == "Analyze Route" for step in captured_steps)
        assert any(step.action_type == "fill" and step.action_value == "Worcester, MA" for step in captured_steps)
    finally:
        _clear_overrides()


def test_executable_flow_without_expected_text_returns_browser_failed(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Welcome to my portfolio.", fail_expected=True)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "browser_failed"
        assert data["steps_failed"] >= 1
    finally:
        _clear_overrides()


def test_invalid_localhost_url_is_safely_rejected() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post(
            "/api/v1/student/skill-evidence",
            json={**_website_payload(), "evidence_url": "http://localhost:3000"},
        ).json()
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "website_browser_verification_run_not_allowed"
    finally:
        _clear_overrides()


def test_unsafe_click_target_is_not_executed(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    captured_steps = _fake_browser(monkeypatch, "Payment completed confirmation appears.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _unsafe_click_guide_payload())
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        assert not any(step.action_type == "click" and "Pay" in (step.action_target or "") for step in captured_steps)
        assert any(step.action_type == "unsupported" and "Pay Now" in (step.action_target or "") for step in captured_steps)
        assert any(step["step_status"] == "unsupported" for step in response.json()["steps"])
    finally:
        _clear_overrides()


def test_browser_timeout_returns_execution_timeout(monkeypatch) -> None:
    from app.services.website_browser_verification_executor_service import WebsiteBrowserExecutionTimeoutError

    def fake_run(self, website_url: str, steps: list) -> _BrowserRunResult:
        raise WebsiteBrowserExecutionTimeoutError("browser_execution_timeout")

    monkeypatch.setattr("app.services.website_browser_verification_executor_service.WebsiteBrowserAutomationAdapter.run", fake_run)
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "execution_timeout"
        assert data["steps"][0]["step_status"] == "timeout"
    finally:
        _clear_overrides()


def test_step_records_store_passed_failed_and_skipped_states(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Portfolio page.", fail_expected=True)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _unsafe_click_guide_payload())
        data = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()

        statuses = {step["step_status"] for step in data["steps"]}
        assert "passed" in statuses
        assert "failed" in statuses
        assert "unsupported" in statuses
    finally:
        _clear_overrides()


def test_latest_browser_run_endpoint_returns_newest_run(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        first = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()
        second = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs/latest")

        assert response.status_code == 200
        latest = response.json()
        assert latest["id"] == second["id"]
        assert latest["id"] != first["id"]
    finally:
        _clear_overrides()


def test_list_browser_runs_endpoint_returns_newest_first(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        first = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()
        second = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        runs = response.json()["runs"]
        assert [run["id"] for run in runs] == [second["id"], first["id"]]
    finally:
        _clear_overrides()


def test_get_one_browser_run_endpoint(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        run = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs/{run['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == run["id"]
        assert response.json()["steps"]
    finally:
        _clear_overrides()


def test_other_user_cannot_access_browser_run(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _fake_browser(monkeypatch, "Risk score card and safer rerouting recommendation are visible.")
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        run = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs").json()
        _clear_overrides()

        other_client = _client(store, OTHER_USER_ID)
        response = other_client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs/{run['id']}")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_browser_executor_missing_plan_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "website_verification_plan_not_found"
    finally:
        _clear_overrides()


def test_browser_executor_missing_evidence_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post("/api/v1/student/skill-evidence/missing/website-browser-verification-runs")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_browser_executor_non_website_evidence_returns_422() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com/student/project",
                "evidence_description": "GitHub repository proof.",
            },
        ).json()
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "website_browser_verification_run_not_allowed"
    finally:
        _clear_overrides()


def test_browser_execution_error_is_stored_safely(monkeypatch) -> None:
    from app.services.website_browser_verification_executor_service import WebsiteBrowserExecutionError

    def fake_run(self, website_url: str, steps: list) -> _BrowserRunResult:
        raise WebsiteBrowserExecutionError("browser_execution_error")

    monkeypatch.setattr("app.services.website_browser_verification_executor_service.WebsiteBrowserAutomationAdapter.run", fake_run)
    store: dict = {}
    client = _client(store)
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-browser-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["browser_execution_status"] == "execution_error"
        assert data["browser_metadata"]["browser_error"] == "browser_execution_error"
    finally:
        _clear_overrides()
