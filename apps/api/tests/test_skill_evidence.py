"""Tests for Skill Proof Evidence API and mock verifier."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.github_evidence_service import GitHubFileFetchResult

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
