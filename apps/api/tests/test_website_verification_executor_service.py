"""Tests for static website verification execution runs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.website_public_inspection_service import WebsiteInspectionResult

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


def _static_guide_payload() -> dict:
    return {
        "project_overview": "Public dashboard for accident risk rerouting.",
        "feature_to_verify": (
            "After a visitor opens the public route dashboard, the website explains accident risk for planned trips "
            "and shows a safer rerouting recommendation for route planning."
        ),
        "verification_steps": [
            "Open the live website.",
            "Review the landing page content.",
            "Confirm accident risk rerouting information is visible.",
        ],
        "sample_inputs": None,
        "expected_output": "Accident risk score and safer rerouting recommendation are visible on the public page.",
        "login_required": False,
    }


def _dynamic_guide_payload() -> dict:
    return {
        **_static_guide_payload(),
        "verification_steps": [
            "Open the live website.",
            "Enter Boston Common as the origin.",
            "Enter Fenway Park as the destination.",
            "Click the route risk button.",
            "Confirm a risk score card appears.",
        ],
        "sample_inputs": {"origin": "Boston Common", "destination": "Fenway Park"},
    }


def _create_evidence_guide_plan(client: TestClient, guide: dict | None = None) -> tuple[dict, dict, dict]:
    evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
    guide_response = client.post(
        f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
        json=guide or _static_guide_payload(),
    ).json()
    plan = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-plan").json()
    return evidence, guide_response, plan


def _matching_inspection() -> WebsiteInspectionResult:
    return WebsiteInspectionResult(
        inspection_used=True,
        final_url="https://student-demo.example.com",
        status_code=200,
        page_title="Accident Risk Rerouting Dashboard",
        meta_description="Accident risk score and safer rerouting recommendation dashboard.",
        headings=["Accident risk score", "Safer rerouting recommendation"],
        visible_text=(
            "The public page explains an accident risk score and safer rerouting recommendation "
            "for route planning."
        ),
        public_markers=["links"],
    )


def _non_matching_inspection() -> WebsiteInspectionResult:
    return WebsiteInspectionResult(
        inspection_used=True,
        final_url="https://student-demo.example.com",
        status_code=200,
        page_title="Portfolio",
        meta_description="Personal website.",
        headings=["Welcome"],
        visible_text="This page contains a short biography and contact links.",
        public_markers=["links"],
    )


def _mock_inspection(monkeypatch, result: WebsiteInspectionResult) -> None:
    def fake_inspect_url(self, url: str | None) -> WebsiteInspectionResult:
        assert url == "https://student-demo.example.com"
        return result

    monkeypatch.setattr("app.services.website_verification_executor_service.WebsitePublicInspectionService.inspect_url", fake_inspect_url)


def test_executor_creates_run_from_latest_plan(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, plan = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["evidence_id"] == evidence["id"]
        assert data["plan_id"] == plan["id"]
        assert data["user_id"] == USER_ID
        assert data["executor_version"] == "website-executor-static-v1"
        assert data["checks_attempted"] == len(data["checks"])
        assert data["checks_passed"] >= 4
        assert data["execution_status"] == "static_verified"
    finally:
        _clear_overrides()


def test_executor_plan_requiring_browser_interaction_returns_needs_browser_execution(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _dynamic_guide_payload())
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["execution_status"] == "needs_browser_execution"
        assert any(check["check_status"] == "browser_required" for check in data["checks"])
        assert data["checks_needing_review"] >= 1
    finally:
        _clear_overrides()


def test_executor_no_matching_content_returns_failed_static_checks(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _non_matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["execution_status"] == "failed_static_checks"
        assert data["checks_failed"] >= 3
    finally:
        _clear_overrides()


def test_executor_website_timeout_returns_execution_error(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(
        monkeypatch,
        WebsiteInspectionResult(
            inspection_used=False,
            error="website_timeout",
            missing_signals=["Website request timed out."],
        ),
    )
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        data = response.json()
        assert data["execution_status"] == "execution_error"
        assert "website_timeout" in data["execution_summary"]
        assert data["raw_executor_notes"]["inspection_error"] == "website_timeout"
    finally:
        _clear_overrides()


def test_executor_invalid_localhost_url_is_safe_execution_error(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post(
            "/api/v1/student/skill-evidence",
            json={
                **_website_payload(),
                "evidence_url": "http://localhost:3000",
            },
        ).json()
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "website_verification_run_not_allowed"
    finally:
        _clear_overrides()


def test_executor_checks_include_pass_failed_and_browser_required(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _non_matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client, _dynamic_guide_payload())
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        statuses = {check["check_status"] for check in response.json()["checks"]}
        assert "passed" in statuses
        assert "failed" in statuses
        assert "browser_required" in statuses
    finally:
        _clear_overrides()


def test_latest_run_endpoint_returns_newest_run(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        first = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()
        second = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs/latest")

        assert response.status_code == 200
        latest = response.json()
        assert latest["id"] == second["id"]
        assert latest["id"] != first["id"]
    finally:
        _clear_overrides()


def test_list_runs_endpoint_returns_newest_first(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        first = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()
        second = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 200
        runs = response.json()["runs"]
        assert [run["id"] for run in runs] == [second["id"], first["id"]]
    finally:
        _clear_overrides()


def test_get_one_run_endpoint(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        run = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs/{run['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == run["id"]
        assert response.json()["checks"]
    finally:
        _clear_overrides()


def test_other_user_cannot_access_run(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    _mock_inspection(monkeypatch, _matching_inspection())
    try:
        evidence, _, _ = _create_evidence_guide_plan(client)
        run = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs").json()
        _clear_overrides()

        other_client = _client(store, OTHER_USER_ID)
        response = other_client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs/{run['id']}")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_executor_missing_plan_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "website_verification_plan_not_found"
    finally:
        _clear_overrides()


def test_executor_missing_evidence_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post("/api/v1/student/skill-evidence/missing/website-verification-runs")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_executor_non_website_evidence_returns_422() -> None:
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
        response = client.post(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-runs")

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "website_verification_run_not_allowed"
    finally:
        _clear_overrides()
