"""Tests for the GitHub Portfolio Scan API endpoints (Phase J3B).

All tests inject a MockGitHubAPIClient — no live GitHub calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_current_user_id, get_db
from app.main import app
from scripts.github_portfolio_scanner import MockGitHubAPIClient

USER_ID = "00000000-0000-0000-0000-000000000099"

# ── Shared fixtures ────────────────────────────────────────────────────────────

def _client(store: dict, user_id: str = USER_ID) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear() -> None:
    app.dependency_overrides.clear()


def _mock_github_client() -> MockGitHubAPIClient:
    """A mock client with one public Python repo containing ML training code."""
    return MockGitHubAPIClient(
        repos_by_user={
            "testuser": [
                {
                    "name": "ml-project",
                    "html_url": "https://github.com/testuser/ml-project",
                    "description": "A machine learning project using scikit-learn",
                    "homepage": None,
                    "default_branch": "main",
                    "languages": {"Python": 10000},
                    "topics": ["machine-learning", "sklearn"],
                    "stargazers_count": 5,
                    "owner": {"login": "testuser"},
                    "fork": False,
                    "archived": False,
                }
            ]
        },
        trees_by_repo={
            "testuser/ml-project": [
                {"path": "train.py", "type": "blob"},
                {"path": "README.md", "type": "blob"},
            ]
        },
        files_by_path={
            "testuser/ml-project/train.py": (
                "import pandas as pd\n"
                "from sklearn.ensemble import RandomForestClassifier\n"
                "from sklearn.model_selection import train_test_split\n"
                "from sklearn.metrics import accuracy_score\n"
                "\n"
                "X_train, X_test, y_train, y_test = train_test_split(X, y)\n"
                "model = RandomForestClassifier(n_estimators=100)\n"
                "model.fit(X_train, y_train)\n"
                "y_pred = model.predict(X_test)\n"
                "print(accuracy_score(y_test, y_pred))\n"
            ),
            "testuser/ml-project/README.md": (
                "# ML Project\nA machine learning project using scikit-learn for classification.\n"
            ),
        },
    )


def _mock_github_client_no_repos() -> MockGitHubAPIClient:
    return MockGitHubAPIClient(repos_by_user={"emptyuser": []})


def _mock_github_client_no_candidates() -> MockGitHubAPIClient:
    """Repo exists but only has import-only code (weak evidence)."""
    return MockGitHubAPIClient(
        repos_by_user={
            "weakuser": [
                {
                    "name": "import-only-repo",
                    "html_url": "https://github.com/weakuser/import-only-repo",
                    "description": None,
                    "homepage": None,
                    "default_branch": "main",
                    "languages": {"Python": 500},
                    "topics": [],
                    "stargazers_count": 0,
                    "owner": {"login": "weakuser"},
                    "fork": False,
                    "archived": False,
                }
            ]
        },
        trees_by_repo={
            "weakuser/import-only-repo": [{"path": "main.py", "type": "blob"}]
        },
        files_by_path={
            "weakuser/import-only-repo/main.py": (
                "import os\nimport sys\nimport pathlib\nimport json\nimport re\n"
                "import collections\nimport itertools\nimport functools\n"
            )
        },
    )


# ── Scan endpoint tests ────────────────────────────────────────────────────────


def test_scan_returns_dry_run_candidates() -> None:
    store: dict = {}
    client = _client(store)
    try:
        with patch(
            "app.services.github_portfolio_scan_service.GitHubAPIClient",
            return_value=_mock_github_client(),
        ), patch(
            "app.services.github_portfolio_scan_service._FilteredGitHubAPIClient",
            side_effect=lambda *args, **kw: args[0],
        ):
            resp = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_username": "testuser", "max_repos": 5},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_username"] == "testuser"
        assert data["candidate_count"] >= 1
        assert data["detected_skill_count"] >= 1
        candidates = data["proof_candidates"]
        assert len(candidates) >= 1
        c = candidates[0]
        assert "candidate_id" in c
        assert "skill_label" in c
        assert "repo_name" in c
        assert "file_path" in c
        assert "line_start" in c
        assert "line_end" in c
        assert "github_highlight_url" in c
        assert "suggested_status" in c
        assert "import_key" in c
    finally:
        _clear()


def test_scan_accepts_github_profile_url() -> None:
    store: dict = {}
    client = _client(store)
    try:
        with patch(
            "app.services.github_portfolio_scan_service.GitHubAPIClient",
            return_value=_mock_github_client(),
        ), patch(
            "app.services.github_portfolio_scan_service._FilteredGitHubAPIClient",
            side_effect=lambda *args, **kw: args[0],
        ):
            resp = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_profile_url": "https://github.com/testuser"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_username"] == "testuser"
    finally:
        _clear()


def test_scan_rejects_invalid_github_profile_url() -> None:
    store: dict = {}
    client = _client(store)
    try:
        resp = client.post(
            "/api/v1/student/github-portfolio/scan",
            json={"github_profile_url": "not-a-valid-url"},
        )
        assert resp.status_code in (422, 503)
    finally:
        _clear()


def test_scan_rejects_missing_identifier() -> None:
    store: dict = {}
    client = _client(store)
    try:
        resp = client.post(
            "/api/v1/student/github-portfolio/scan",
            json={"max_repos": 5},
        )
        assert resp.status_code == 422
    finally:
        _clear()


def test_scan_no_public_repos_returns_zero_candidates() -> None:
    store: dict = {}
    client = _client(store)
    try:
        with patch(
            "app.services.github_portfolio_scan_service.GitHubAPIClient",
            return_value=_mock_github_client_no_repos(),
        ), patch(
            "app.services.github_portfolio_scan_service._FilteredGitHubAPIClient",
            side_effect=lambda *args, **kw: args[0],
        ):
            resp = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_username": "emptyuser"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate_count"] == 0
        assert data["proof_candidates"] == []
    finally:
        _clear()


def test_scan_no_strong_evidence_returns_zero_candidates() -> None:
    store: dict = {}
    client = _client(store)
    try:
        with patch(
            "app.services.github_portfolio_scan_service.GitHubAPIClient",
            return_value=_mock_github_client_no_candidates(),
        ), patch(
            "app.services.github_portfolio_scan_service._FilteredGitHubAPIClient",
            side_effect=lambda *args, **kw: args[0],
        ):
            resp = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_username": "weakuser"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate_count"] == 0
    finally:
        _clear()


def test_scan_candidate_ids_are_deterministic() -> None:
    """Two scan calls for the same username return the same candidate_ids."""
    store: dict = {}
    client = _client(store)
    mock = _mock_github_client()
    try:
        with patch(
            "app.services.github_portfolio_scan_service.GitHubAPIClient",
            return_value=mock,
        ), patch(
            "app.services.github_portfolio_scan_service._FilteredGitHubAPIClient",
            side_effect=lambda *args, **kw: args[0],
        ):
            resp1 = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_username": "testuser"},
            )
            resp2 = client.post(
                "/api/v1/student/github-portfolio/scan",
                json={"github_username": "testuser"},
            )
        ids1 = {c["candidate_id"] for c in resp1.json()["proof_candidates"]}
        ids2 = {c["candidate_id"] for c in resp2.json()["proof_candidates"]}
        assert ids1 == ids2
    finally:
        _clear()


# ── Import-selected endpoint tests ────────────────────────────────────────────


def _make_candidate_payload(
    repo_name: str = "ml-project",
    skill_label: str = "Machine Learning",
    candidate_id: str = "abc123",
    file_path: str = "train.py",
    line_start: int = 6,
    line_end: int = 10,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "repo_name": repo_name,
        "repo_url": f"https://github.com/testuser/{repo_name}",
        "project_title": "Ml Project",
        "skill_label": skill_label,
        "evidence_description": f"I used {skill_label} in the {repo_name} repo.",
        "student_claim": f"Built {skill_label} in {repo_name}.",
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "github_highlight_url": f"https://github.com/testuser/{repo_name}/blob/main/{file_path}#L{line_start}-L{line_end}",
        "confidence_label": "high",
        "selection_reason": "ML training call",
        "website_url": None,
        "suggested_status": "suggested",
        "warnings": [],
        "import_key": f"|https://github.com/testuser/{repo_name}|{file_path}|{line_start}|{line_end}|{skill_label}",
    }


def test_import_selected_creates_proof_evidence() -> None:
    store: dict = {}
    client = _client(store)
    try:
        resp = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [_make_candidate_payload()]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 1
        assert data["skipped_duplicate_count"] == 0
        assert data["failed_count"] == 0
        assert len(data["imported_evidence_ids"]) == 1
        results = data["per_candidate_results"]
        assert len(results) == 1
        assert results[0]["status"] == "imported"
        assert results[0]["evidence_id"] is not None
        # Verify the evidence was written to the mock store
        evidence_table = store.get("skill_evidence", {})
        assert len(evidence_table) == 1
    finally:
        _clear()


def test_import_selected_skips_duplicate() -> None:
    store: dict = {}
    client = _client(store)
    candidate = _make_candidate_payload()
    try:
        # First import
        resp1 = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [candidate]},
        )
        assert resp1.status_code == 200
        assert resp1.json()["imported_count"] == 1

        # Second import of the same candidate
        resp2 = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [candidate]},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["imported_count"] == 0
        assert data2["skipped_duplicate_count"] == 1
        assert data2["per_candidate_results"][0]["status"] == "skipped_duplicate"
    finally:
        _clear()


def test_import_selected_per_candidate_results() -> None:
    store: dict = {}
    client = _client(store)
    c1 = _make_candidate_payload(candidate_id="cand1", line_start=6, line_end=10)
    c2 = _make_candidate_payload(candidate_id="cand2", line_start=20, line_end=30)
    try:
        resp = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [c1, c2]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported_count"] == 2
        by_cid = {r["candidate_id"]: r for r in data["per_candidate_results"]}
        assert by_cid["cand1"]["status"] == "imported"
        assert by_cid["cand2"]["status"] == "imported"
    finally:
        _clear()


def test_import_selected_mixed_duplicate_and_new() -> None:
    store: dict = {}
    client = _client(store)
    c_existing = _make_candidate_payload(candidate_id="existing", line_start=6, line_end=10)
    c_new = _make_candidate_payload(candidate_id="new", line_start=50, line_end=60)
    try:
        # Pre-seed the existing one
        client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [c_existing]},
        )

        # Import both
        resp = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [c_existing, c_new]},
        )
        data = resp.json()
        assert data["imported_count"] == 1
        assert data["skipped_duplicate_count"] == 1
    finally:
        _clear()


def test_import_selected_rejects_empty_candidates() -> None:
    store: dict = {}
    client = _client(store)
    try:
        resp = client.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": []},
        )
        assert resp.status_code == 422
    finally:
        _clear()


def test_import_selected_ownership_uses_current_user() -> None:
    """Each import saves under the requesting user_id, not a global user."""
    store: dict = {}
    user_a = "00000000-0000-0000-0000-000000000001"
    user_b = "00000000-0000-0000-0000-000000000002"
    candidate = _make_candidate_payload(candidate_id="ownership-test")

    # Import as user_a
    app.dependency_overrides[get_current_user_id] = lambda: user_a
    app.dependency_overrides[get_db] = lambda: store
    c_a = TestClient(app)
    try:
        c_a.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [candidate]},
        )
        evidence_table = store.get("skill_evidence", {})
        user_a_rows = [r for r in evidence_table.values() if r["user_id"] == user_a]
        assert len(user_a_rows) == 1

        # Import the same candidate as user_b — should NOT be considered a duplicate
        app.dependency_overrides[get_current_user_id] = lambda: user_b
        c_b = TestClient(app)
        resp_b = c_b.post(
            "/api/v1/student/github-portfolio/import-selected",
            json={"proof_candidates": [candidate]},
        )
        assert resp_b.json()["imported_count"] == 1
        user_b_rows = [r for r in store.get("skill_evidence", {}).values() if r["user_id"] == user_b]
        assert len(user_b_rows) == 1
    finally:
        _clear()


# ── Schema helper tests ────────────────────────────────────────────────────────


def test_extract_github_username_from_url() -> None:
    from app.schemas.github_portfolio import extract_github_username

    assert extract_github_username("https://github.com/machackgo", None) == "machackgo"
    assert extract_github_username("https://github.com/machackgo/", None) == "machackgo"
    assert extract_github_username("github.com/machackgo", None) == "machackgo"
    assert extract_github_username(None, "machackgo") == "machackgo"
    assert extract_github_username(None, "@machackgo") == "machackgo"
    assert extract_github_username(None, None) is None
    assert extract_github_username("https://github.com/machackgo/some-repo", None) is None
    assert extract_github_username("not-a-url", None) is None
