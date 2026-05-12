"""Tests for Skill Proof Evidence API and mock verifier."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.github_evidence_service import GitHubFileFetchResult
from app.services.github_public_inspection_service import GitHubInspectionResult

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _python_payload() -> dict:
    return {
        "skill_name": "Python",
        "evidence_type": "GitHub file",
        "file_path": "app/main.py",
        "line_start": 20,
        "line_end": 95,
        "evidence_description": "Built FastAPI prediction endpoint.",
    }


def _website_payload() -> dict:
    return {
        "skill_name": "React",
        "evidence_type": "Deployed website URL",
        "evidence_url": "https://student-demo.example.com",
        "proof_visibility": "public",
        "evidence_description": "Built a deployed website for an interactive project dashboard.",
        "metadata": {"title": "Interactive project dashboard"},
    }


def _website_guide_payload() -> dict:
    return {
        "project_overview": "Interactive dashboard that lets users filter and inspect project metrics.",
        "feature_to_verify": "Dashboard filter interaction",
        "verification_steps": [
            "Open the live website.",
            "Select the Projects filter.",
            "Choose Active projects.",
            "Confirm the results update without a page reload.",
        ],
        "sample_inputs": {"filter": "Active projects"},
        "expected_output": "The dashboard shows only active projects and updates the visible result count.",
        "login_required": False,
        "access_notes": "No login is required for the public demo.",
        "known_limitations": "Free-tier hosting may cold start.",
        "additional_notes": "Use a desktop viewport for the clearest table layout.",
    }


def test_create_skill_evidence_verifies_python_file() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post("/api/v1/student/skill-evidence", json=_python_payload())
        assert response.status_code == 201
        data = response.json()
        assert data["skill_name"] == "Python"
        assert data["verification_status"] == "verified"
        assert data["verification_summary"] == "Python usage likely found from Python/Notebook file path."
        assert data["verifier_version"] == "mock-v1"
    finally:
        _clear_overrides()


def test_list_and_get_skill_evidence() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post("/api/v1/student/skill-evidence", json=_python_payload()).json()
        list_response = client.get("/api/v1/student/skill-evidence")
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()] == [created["id"]]

        get_response = client.get(f"/api/v1/student/skill-evidence/{created['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["file_path"] == "app/main.py"
    finally:
        _clear_overrides()


def test_update_skill_evidence_reruns_verification() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post("/api/v1/student/skill-evidence", json=_python_payload()).json()
        response = client.put(
            f"/api/v1/student/skill-evidence/{created['id']}",
            json={
                "file_path": "presentation.pdf",
                "evidence_description": "Class presentation deck.",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "skill_usage_not_found"
    finally:
        _clear_overrides()


def test_delete_skill_evidence() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post("/api/v1/student/skill-evidence", json=_python_payload()).json()
        delete_response = client.delete(f"/api/v1/student/skill-evidence/{created['id']}")
        assert delete_response.status_code == 200
        assert delete_response.json()["success"] is True

        missing = client.get(f"/api/v1/student/skill-evidence/{created['id']}")
        assert missing.status_code == 404
    finally:
        _clear_overrides()


def test_verify_endpoint_reruns_mock_verifier() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post("/api/v1/student/skill-evidence", json=_python_payload()).json()
        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/verify")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "verified"
        assert data["verifier_version"] == "mock-v1"
        assert data["evidence"]["id"] == created["id"]
    finally:
        _clear_overrides()


def test_verify_machine_learning_tree_file() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Machine Learning",
                "evidence_type": "GitHub file",
                "file_path": "Tree.py",
                "evidence_description": "Used a decision tree Machine Learning model.",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["verification_status"] == "verified"
        assert data["verification_summary"] == "Machine learning evidence likely found from file path or ML keywords."
    finally:
        _clear_overrides()


def test_verify_rag_pipeline_file() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "RAG",
                "evidence_type": "GitHub file",
                "file_path": "rag_pipeline.py",
                "evidence_description": "Built embeddings and retrieval for a RAG pipeline.",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["verification_status"] == "verified"
        assert data["verification_summary"] == "AI/LLM evidence likely found from RAG/LLM keywords."
    finally:
        _clear_overrides()


def test_verify_python_pdf_mismatch() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "Presentation deck",
                "file_path": "presentation.pdf",
                "evidence_description": "Class presentation deck.",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["verification_status"] == "skill_usage_not_found"
    finally:
        _clear_overrides()


def test_invalid_line_range_returns_validation_error() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.post(
            "/api/v1/student/skill-evidence",
            json={**_python_payload(), "line_start": 95, "line_end": 20},
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_other_user_cannot_access_evidence() -> None:
    store: dict = {}
    client = _client(store, USER_ID)
    try:
        created = client.post("/api/v1/student/skill-evidence", json=_python_payload()).json()
        _clear_overrides()

        other_client = _client(store, OTHER_USER_ID)
        response = other_client.get(f"/api/v1/student/skill-evidence/{created['id']}")
        assert response.status_code == 404

        delete_response = other_client.delete(f"/api/v1/student/skill-evidence/{created['id']}")
        assert delete_response.status_code == 404
    finally:
        _clear_overrides()


def test_missing_evidence_returns_404() -> None:
    store: dict = {}
    client = _client(store)
    try:
        response = client.get("/api/v1/student/skill-evidence/missing")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
    finally:
        _clear_overrides()


def test_api_post_uses_github_file_verifier(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)

    def fake_fetch(repository_url: str, file_path: str, branch_candidates=None) -> GitHubFileFetchResult:
        assert repository_url == "https://github.com/user/project"
        assert file_path == "app/main.py"
        return GitHubFileFetchResult(
            ok=True,
            content="from fastapi import FastAPI\n\napp = FastAPI()\n",
            branch="main",
            raw_url="https://raw.githubusercontent.com/user/project/main/app/main.py",
        )

    monkeypatch.setattr("app.services.github_evidence_service.fetch_public_github_file", fake_fetch)
    try:
        response = client.post(
            "/api/v1/student/skill-evidence",
            json={
                **_python_payload(),
                "repository_url": "https://github.com/user/project",
                "line_start": 1,
                "line_end": 3,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["verification_status"] == "verified"
        assert data["verifier_version"] == "github-file-v1"
        assert "Verified from public GitHub file" in data["verification_summary"]
    finally:
        _clear_overrides()


def test_verify_endpoint_reruns_github_file_verifier(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)
    contents = ["print('placeholder')\n", "from fastapi import FastAPI\napp = FastAPI()\n"]

    def fake_fetch(repository_url: str, file_path: str, branch_candidates=None) -> GitHubFileFetchResult:
        return GitHubFileFetchResult(ok=True, content=contents.pop(0), branch="main")

    monkeypatch.setattr("app.services.github_evidence_service.fetch_public_github_file", fake_fetch)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                **_python_payload(),
                "repository_url": "https://github.com/user/project",
                "line_start": 1,
                "line_end": 2,
            },
        ).json()
        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/verify")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "verified"
        assert data["verifier_version"] == "github-file-v1"
        assert data["evidence"]["verifier_version"] == "github-file-v1"
    finally:
        _clear_overrides()


def test_public_proof_verification_strong_match_for_github_repository_metadata() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com/student/fastapi-prediction-service",
                "evidence_description": (
                    "Built and deployed a Python FastAPI prediction service with pytest coverage "
                    "and pandas preprocessing."
                ),
                "metadata": {
                    "title": "FastAPI prediction service",
                    "repository_name": "fastapi-prediction-service",
                    "visibility": "public",
                },
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["skill_evidence_id"] == created["id"]
        assert data["verification_status"] == "strong_match"
        assert data["confidence_score"] >= 0.82
        assert data["needs_human_review"] is False
        assert data["github_inspection_used"] is False
        assert data["verifier_version"] == "public-proof-v2"
        assert "stored metadata" in data["verifier_notes"].lower()
    finally:
        _clear_overrides()


def test_public_proof_verification_weak_match_for_sparse_metadata() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "Deployed project URL",
                "evidence_url": "https://example.com/project",
                "evidence_description": "Class project.",
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["verification_status"] == "weak_match"
        assert data["needs_human_review"] is True
        assert data["github_inspection_used"] is False
        assert any("skill-relevant" in signal for signal in data["missing_signals"])
    finally:
        _clear_overrides()


def test_public_proof_verification_rejects_private_proof() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com/student/private-project",
                "evidence_description": "Built a Python project.",
                "proof_visibility": "private",
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "public_proof_not_verifiable"
    finally:
        _clear_overrides()


def test_get_latest_public_proof_verification_returns_latest_result() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "SQL",
                "evidence_type": "Public portfolio URL",
                "evidence_url": "https://student.dev/docs/analytics-project",
                "evidence_description": "Analytics project.",
                "metadata": {"title": "Analytics portfolio"},
            },
        ).json()
        first = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification").json()

        client.put(
            f"/api/v1/student/skill-evidence/{created['id']}",
            json={
                "evidence_description": (
                    "Authored SQL schema, joins, and Postgres queries for an analytics dashboard "
                    "and documented the database design."
                ),
                "metadata": {"title": "SQL analytics documentation", "visibility": "public"},
            },
        )
        second = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification").json()

        response = client.get(f"/api/v1/student/skill-evidence/{created['id']}/public-verification/latest")
        assert response.status_code == 200
        latest = response.json()
        assert latest["id"] == second["id"]
        assert latest["id"] != first["id"]
        assert latest["verification_status"] in {"plausible_match", "strong_match"}
    finally:
        _clear_overrides()


def test_public_proof_verification_uses_github_repo_inspection(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)

    def fake_inspect_url(self, url: str | None) -> GitHubInspectionResult:
        assert url == "https://github.com/student/fastapi-prediction-service"
        return GitHubInspectionResult(
            inspection_used=True,
            owner="student",
            repo="fastapi-prediction-service",
            repo_description="Python FastAPI prediction service",
            primary_language="Python",
            default_branch="main",
            readme_text="This project uses Python, FastAPI, pandas, pytest, and prediction APIs.",
            matched_signals=["GitHub repository inspected: student/fastapi-prediction-service."],
        )

    monkeypatch.setattr("app.services.public_proof_verification_service.GitHubPublicInspectionService.inspect_url", fake_inspect_url)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com/student/fastapi-prediction-service",
                "evidence_description": "Project repo.",
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["github_inspection_used"] is True
        assert data["verification_status"] in {"plausible_match", "strong_match"}
        assert any("GitHub repository inspected" in signal for signal in data["matched_signals"])
        assert "Real GitHub inspection was used" in data["verifier_notes"]
    finally:
        _clear_overrides()


def test_public_proof_verification_uses_github_blob_inspection(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)

    def fake_inspect_url(self, url: str | None) -> GitHubInspectionResult:
        assert url == "https://github.com/student/project/blob/main/app/main.py"
        return GitHubInspectionResult(
            inspection_used=True,
            owner="student",
            repo="project",
            repo_description="Student backend project",
            primary_language="Python",
            default_branch="main",
            readme_text="Backend service",
            file_path="app/main.py",
            file_name="main.py",
            file_text="from fastapi import FastAPI\nimport pandas as pd\napp = FastAPI()\n",
            matched_signals=[
                "GitHub repository inspected: student/project.",
                "GitHub blob file content was inspected: app/main.py.",
            ],
        )

    monkeypatch.setattr("app.services.public_proof_verification_service.GitHubPublicInspectionService.inspect_url", fake_inspect_url)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub file URL",
                "evidence_url": "https://github.com/student/project/blob/main/app/main.py",
                "evidence_description": "Backend file.",
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["github_inspection_used"] is True
        assert data["verification_status"] in {"plausible_match", "strong_match"}
        assert any("GitHub file proof includes skill-relevant terms" in signal for signal in data["matched_signals"])
    finally:
        _clear_overrides()


def test_public_proof_verification_invalid_github_url_uses_metadata_only() -> None:
    store: dict = {}
    client = _client(store)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com",
                "evidence_description": "Built a Python project.",
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["github_inspection_used"] is False
        assert data["verification_status"] == "rejected"
        assert any("does not clearly match GitHub" in signal for signal in data["missing_signals"])
    finally:
        _clear_overrides()


def test_public_proof_verification_github_api_failure_falls_back(monkeypatch) -> None:
    store: dict = {}
    client = _client(store)

    def fake_inspect_url(self, url: str | None) -> GitHubInspectionResult:
        return GitHubInspectionResult(
            inspection_used=False,
            owner="student",
            repo="missing-project",
            error="github_repo_not_found",
            status_code=404,
            missing_signals=["GitHub repository was not found or is not public."],
        )

    monkeypatch.setattr("app.services.public_proof_verification_service.GitHubPublicInspectionService.inspect_url", fake_inspect_url)
    try:
        created = client.post(
            "/api/v1/student/skill-evidence",
            json={
                "skill_name": "Python",
                "evidence_type": "GitHub repository URL",
                "repository_url": "https://github.com/student/missing-project",
                "evidence_description": "Built a Python project with FastAPI.",
                "metadata": {"title": "Python FastAPI project"},
            },
        ).json()

        response = client.post(f"/api/v1/student/skill-evidence/{created['id']}/public-verification")
        assert response.status_code == 200
        data = response.json()
        assert data["github_inspection_used"] is False
        assert data["verification_status"] in {"weak_match", "plausible_match"}
        assert any("not found or is not public" in signal for signal in data["missing_signals"])
        assert "attempted but unavailable" in data["verifier_notes"]
    finally:
        _clear_overrides()


def test_create_website_verification_guide() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        response = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=_website_guide_payload(),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["skill_evidence_id"] == evidence["id"]
        assert data["feature_to_verify"] == "Dashboard filter interaction"
        assert data["verification_steps"][0] == "Open the live website."
        assert data["sample_inputs"] == {"filter": "Active projects"}
        assert data["login_required"] is False
    finally:
        _clear_overrides()


def test_get_website_verification_guide() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        created = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=_website_guide_payload(),
        ).json()

        response = client.get(f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["expected_output"] == _website_guide_payload()["expected_output"]
    finally:
        _clear_overrides()


def test_website_verification_guide_requires_steps() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        payload = {**_website_guide_payload(), "verification_steps": []}
        response = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=payload,
        )

        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_website_verification_guide_requires_expected_output() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        payload = _website_guide_payload()
        payload.pop("expected_output")
        response = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=payload,
        )

        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_website_verification_guide_rejects_github_evidence() -> None:
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
        response = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=_website_guide_payload(),
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "website_verification_guide_not_allowed"
    finally:
        _clear_overrides()


def test_website_verification_guide_post_replaces_existing_guide() -> None:
    store: dict = {}
    client = _client(store)
    try:
        evidence = client.post("/api/v1/student/skill-evidence", json=_website_payload()).json()
        first = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=_website_guide_payload(),
        ).json()
        updated_payload = {
            **_website_guide_payload(),
            "feature_to_verify": "Search interaction",
            "verification_steps": ["Open the site.", "Search for analytics.", "Confirm filtered results."],
            "expected_output": "Only analytics-related results are shown.",
        }
        second = client.post(
            f"/api/v1/student/skill-evidence/{evidence['id']}/website-verification-guide",
            json=updated_payload,
        ).json()

        assert second["id"] == first["id"]
        assert second["feature_to_verify"] == "Search interaction"
        assert second["expected_output"] == "Only analytics-related results are shown."
    finally:
        _clear_overrides()
