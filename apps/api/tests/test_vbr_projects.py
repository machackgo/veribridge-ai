"""Tests for the Verified Build Report (VBR) project API foundation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app

USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_project(client: TestClient, **overrides: object) -> dict:
    payload = {
        "title": "My Capstone Project",
        "repo_url": "https://github.com/octocat/Hello-World",
        **overrides,
    }
    response = client.post("/api/v1/student/vbr/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_project_derives_repo_full_name(client: TestClient) -> None:
    project = _create_project(client)

    assert project["title"] == "My Capstone Project"
    assert project["repo_full_name"] == "octocat/Hello-World"
    assert project["status"] == "draft"
    assert project["deployed_url"] is None


def test_list_projects_only_returns_own(client: TestClient, mem_store: dict) -> None:
    _create_project(client, title="Project A")
    _create_project(client, title="Project B")

    # Seed a project owned by another user directly.
    mem_store.setdefault("vbr_projects", {})["other-project"] = {
        "id": "other-project",
        "user_id": OTHER_USER_ID,
        "title": "Not mine",
        "repo_url": "https://github.com/example/other",
        "repo_full_name": "example/other",
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": {},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }

    response = client.get("/api/v1/student/vbr/projects")
    assert response.status_code == 200, response.text
    titles = {row["title"] for row in response.json()}
    assert titles == {"Project A", "Project B"}


def test_get_project_not_found_for_other_user(client: TestClient, mem_store: dict) -> None:
    project = _create_project(client)
    project_id = project["id"]

    # Switch to a different authenticated user.
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.get(f"/api/v1/student/vbr/projects/{project_id}")
    assert response.status_code == 404


def test_ingest_repo_writes_placeholder_facts(client: TestClient, mem_store: dict) -> None:
    project = _create_project(client)
    project_id = project["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/ingest-repo")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project_id
    assert body["facts"]["owner"] == "octocat"
    assert body["facts"]["repo"] == "Hello-World"
    assert body["facts"]["source"] == "placeholder"
    assert len(mem_store["vbr_repo_analyses"]) == 1

    # Project status moves out of draft after ingestion.
    project_after = client.get(f"/api/v1/student/vbr/projects/{project_id}").json()
    assert project_after["status"] == "repo_ingested"

    # Re-running ingestion updates the same row rather than creating a new one.
    response2 = client.post(f"/api/v1/student/vbr/projects/{project_id}/ingest-repo")
    assert response2.status_code == 200
    assert len(mem_store["vbr_repo_analyses"]) == 1


def test_check_url_without_deployed_url_returns_400(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/check-url")
    assert response.status_code == 400


def test_check_url_rejects_local_private_host(client: TestClient, mem_store: dict) -> None:
    project = _create_project(client, deployed_url="http://localhost:3000")
    project_id = project["id"]

    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/check-url")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["result"] == "unable"
    assert body["status_code"] is None
    assert len(mem_store["vbr_deployed_url_checks"]) == 1


def test_check_url_follows_redirects_and_passes(
    client: TestClient, mem_store: dict, monkeypatch
) -> None:
    """Regression: a redirecting deployed URL (http→https, apex→www — i.e. most
    real deploys) must resolve via urljoin and record a pass, not collapse to
    'unable' (a missing urljoin import previously NameError'd on every hop)."""
    from app.services import vbr_github_ingestion as ing

    calls: list[str] = []

    class _Resp:
        def __init__(self, status_code: int, headers: dict | None = None, text: str = "") -> None:
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None: ...
        def __enter__(self) -> "_FakeClient":
            return self
        def __exit__(self, *args) -> bool:
            return False
        def get(self, url: str) -> _Resp:
            calls.append(url)
            if url == "https://myapp-redirect.example.com":
                return _Resp(308, {"location": "/home"})
            return _Resp(200, {"content-type": "text/html"}, "<title>My App</title>")

    monkeypatch.setattr(ing, "_host_resolves_public", lambda hostname: True)
    monkeypatch.setattr(ing.httpx, "Client", _FakeClient)

    project = _create_project(client, deployed_url="https://myapp-redirect.example.com")
    response = client.post(f"/api/v1/student/vbr/projects/{project['id']}/check-url")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["result"] == "pass"
    assert body["status_code"] == 200
    # The relative Location header must be resolved against the current URL.
    assert calls == [
        "https://myapp-redirect.example.com",
        "https://myapp-redirect.example.com/home",
    ]


def test_create_project_rejects_non_github_repo_url(client: TestClient) -> None:
    response = client.post(
        "/api/v1/student/vbr/projects",
        json={
            "title": "Invalid Repo Project",
            "repo_url": "https://gitlab.com/example/not-supported",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "vbr_invalid_github_repo_url"


def test_ingest_repo_not_found_for_other_user(client: TestClient) -> None:
    project = _create_project(client)
    project_id = project["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/ingest-repo")

    assert response.status_code == 404


def test_check_url_not_found_for_other_user(client: TestClient) -> None:
    project = _create_project(client, deployed_url="https://example.com")
    project_id = project["id"]

    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    response = client.post(f"/api/v1/student/vbr/projects/{project_id}/check-url")

    assert response.status_code == 404
