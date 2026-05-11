"""Tests for public GitHub Skill Proof Evidence verification."""

from __future__ import annotations

import httpx

from app.services.github_evidence_service import (
    GitHubFileFetchResult,
    build_raw_github_url,
    extract_line_range,
    fetch_public_github_file,
    inspect_skill_usage,
    parse_github_repo_url,
    verify_github_file_evidence,
)
from app.services.skill_evidence_service import verify_evidence


class _StreamContext:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx.Response:
        return self.response

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.response.close()


class _FakeClient:
    responses: list[httpx.Response] = []
    requested_urls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def stream(self, method: str, url: str) -> _StreamContext:
        self.requested_urls.append(url)
        response = self.responses.pop(0)
        response._request = httpx.Request(method, url)
        return _StreamContext(response)


def test_parse_github_repo_url() -> None:
    repo = parse_github_repo_url("https://github.com/user/project/blob/main/app/main.py")
    assert repo is not None
    assert repo.owner == "user"
    assert repo.repo == "project"
    assert repo.branch == "main"
    assert repo.file_path == "app/main.py"


def test_build_raw_url_for_main_branch() -> None:
    raw_url = build_raw_github_url("https://github.com/user/project", "app/main.py")
    assert raw_url == "https://raw.githubusercontent.com/user/project/main/app/main.py"


def test_fetch_public_file_falls_back_from_main_to_master(monkeypatch) -> None:
    _FakeClient.responses = [
        httpx.Response(404, content=b"not found"),
        httpx.Response(200, content=b"print('ok')\n"),
    ]
    _FakeClient.requested_urls = []
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    result = fetch_public_github_file("https://github.com/user/project", "app/main.py")

    assert result.ok is True
    assert result.branch == "master"
    assert result.content == "print('ok')\n"
    assert _FakeClient.requested_urls == [
        "https://raw.githubusercontent.com/user/project/main/app/main.py",
        "https://raw.githubusercontent.com/user/project/master/app/main.py",
    ]


def test_fetch_public_file_success_mocked(monkeypatch) -> None:
    _FakeClient.responses = [httpx.Response(200, content=b"from fastapi import FastAPI\n")]
    _FakeClient.requested_urls = []
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    result = fetch_public_github_file("https://github.com/user/project", "app/main.py", branch_candidates=["main"])

    assert result.ok is True
    assert result.branch == "main"
    assert result.content == "from fastapi import FastAPI\n"


def test_fetch_file_not_found_returns_needs_review(monkeypatch) -> None:
    def fake_fetch(repository_url: str, file_path: str, branch_candidates=None) -> GitHubFileFetchResult:
        return GitHubFileFetchResult(ok=False, error="file_not_found", status_code=404)

    monkeypatch.setattr("app.services.github_evidence_service.fetch_public_github_file", fake_fetch)
    result = verify_github_file_evidence(
        {
            "skill_name": "Python",
            "repository_url": "https://github.com/user/project",
            "file_path": "missing.py",
        }
    )
    assert result is not None
    assert result["status"] == "needs_review"
    assert "Could not fetch the public GitHub file" in result["summary"]


def test_extract_line_range_correctly() -> None:
    result = extract_line_range("a\nb\nc\nd\n", 2, 3)
    assert result.ok is True
    assert result.content == "b\nc"
    assert result.summary_range == "lines 2-3"


def test_python_content_verifies_python() -> None:
    assert inspect_skill_usage("Python", "from fastapi import FastAPI\n\ndef predict():\n    pass")


def test_tree_py_with_decision_tree_verifies_machine_learning() -> None:
    assert inspect_skill_usage(
        "Machine Learning",
        "from sklearn.tree import DecisionTreeClassifier\nmodel = DecisionTreeClassifier()\nmodel.fit(X, y)",
    )


def test_rag_pipeline_content_verifies_rag_llm() -> None:
    assert inspect_skill_usage("RAG", "embeddings = OpenAIEmbeddings()\nretrieval_chain = rag(vector_store)")


def test_selected_lines_without_skill_returns_skill_usage_not_found(monkeypatch) -> None:
    def fake_fetch(repository_url: str, file_path: str, branch_candidates=None) -> GitHubFileFetchResult:
        return GitHubFileFetchResult(
            ok=True,
            content="README notes\nplain text\ncourse overview only\n",
            branch="main",
        )

    monkeypatch.setattr("app.services.github_evidence_service.fetch_public_github_file", fake_fetch)
    result = verify_github_file_evidence(
        {
            "skill_name": "Machine Learning",
            "repository_url": "https://github.com/user/project",
            "file_path": "notes.txt",
            "line_start": 1,
            "line_end": 2,
            "evidence_description": "Course notes.",
        }
    )
    assert result is not None
    assert result["status"] == "skill_usage_not_found"


def test_no_github_url_falls_back_to_mock_verifier() -> None:
    result = verify_evidence(
        {
            "skill_name": "Python",
            "evidence_type": "GitHub file",
            "file_path": "app/main.py",
            "evidence_description": "Built FastAPI endpoint.",
        }
    )
    assert result["status"] == "verified"
    assert result["verifier_version"] == "mock-v1"
