"""Tests for public GitHub repository/blob inspection."""

from __future__ import annotations

import base64
from typing import Any

from app.services.github_public_inspection_service import GitHubPublicInspectionService


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeGitHubClient:
    routes: dict[str, _FakeResponse] = {}
    requests: list[tuple[str, dict[str, Any] | None]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_FakeGitHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.requests.append((path, params))
        return self.routes.get(path, _FakeResponse(404, {}))


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def test_inspect_github_repository_url_fetches_repo_and_readme(monkeypatch) -> None:
    _FakeGitHubClient.requests = []
    _FakeGitHubClient.routes = {
        "/repos/student/project": _FakeResponse(
            200,
            {
                "description": "Python FastAPI prediction service",
                "language": "Python",
                "default_branch": "main",
            },
        ),
        "/repos/student/project/readme": _FakeResponse(
            200,
            {"encoding": "base64", "content": _b64("Built with Python, FastAPI, pandas, and pytest.")},
        ),
    }
    monkeypatch.setattr("app.services.github_public_inspection_service.httpx.Client", _FakeGitHubClient)

    result = GitHubPublicInspectionService().inspect_url("https://github.com/student/project")

    assert result.inspection_used is True
    assert result.owner == "student"
    assert result.repo == "project"
    assert result.repo_description == "Python FastAPI prediction service"
    assert result.primary_language == "Python"
    assert "FastAPI" in (result.readme_text or "")
    assert ("/repos/student/project/readme", {"ref": "main"}) in _FakeGitHubClient.requests


def test_inspect_github_blob_url_fetches_file_content(monkeypatch) -> None:
    _FakeGitHubClient.requests = []
    _FakeGitHubClient.routes = {
        "/repos/student/project": _FakeResponse(
            200,
            {
                "description": "Backend project",
                "language": "Python",
                "default_branch": "main",
            },
        ),
        "/repos/student/project/readme": _FakeResponse(404, {}),
        "/repos/student/project/contents/app/main.py": _FakeResponse(
            200,
            {
                "type": "file",
                "size": 80,
                "encoding": "base64",
                "content": _b64("from fastapi import FastAPI\nimport pandas as pd\napp = FastAPI()\n"),
            },
        ),
    }
    monkeypatch.setattr("app.services.github_public_inspection_service.httpx.Client", _FakeGitHubClient)

    result = GitHubPublicInspectionService().inspect_url("https://github.com/student/project/blob/main/app/main.py")

    assert result.inspection_used is True
    assert result.file_path == "app/main.py"
    assert result.file_name == "main.py"
    assert "FastAPI" in (result.file_text or "")
    assert ("/repos/student/project/contents/app/main.py", {"ref": "main"}) in _FakeGitHubClient.requests


def test_inspect_missing_github_repo_returns_safe_failure(monkeypatch) -> None:
    _FakeGitHubClient.requests = []
    _FakeGitHubClient.routes = {
        "/repos/student/missing": _FakeResponse(404, {}),
    }
    monkeypatch.setattr("app.services.github_public_inspection_service.httpx.Client", _FakeGitHubClient)

    result = GitHubPublicInspectionService().inspect_url("https://github.com/student/missing")

    assert result.inspection_used is False
    assert result.error == "github_repo_not_found"
    assert result.status_code == 404
    assert any("not found" in signal for signal in result.missing_signals)


def test_inspect_invalid_github_url_returns_safe_failure() -> None:
    result = GitHubPublicInspectionService().inspect_url("https://github.com")

    assert result.inspection_used is False
    assert result.error == "invalid_github_url"
    assert any("not a supported" in signal for signal in result.missing_signals)
