"""Tests for Extension Proof GitHub Analysis.

All storage is in-memory. GitHub HTTP calls are monkeypatched so no real
network traffic is made. The monkeypatch target is the function as imported
in the service module.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user_id, get_db
import app.services.extension_proof_github_analysis_service as svc_module
from app.services.extension_proof_github_analysis_service import (
    ExtensionProofGitHubAnalysisService,
    analyze_github_repo,
    _detect_stack,
    _detect_features,
    _match_skills,
    _compute_confidence,
)
from app.services.github_evidence_service import GitHubFileFetchResult

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
SESSION_ID = "ssssssss-0000-0000-0000-000000000001"
REPO_URL = "https://github.com/example/myrepo"

# ── Helpers ───────────────────────────────────────────────────────────────────

REQUIREMENTS_TXT = """\
fastapi==0.110.0
pydantic==2.0.0
sqlalchemy==2.0.0
pytest==8.0.0
openai==1.0.0
"""

PACKAGE_JSON = """\
{
  "name": "myapp",
  "dependencies": {
    "react": "^18.0.0",
    "next": "^14.0.0",
    "@supabase/supabase-js": "^2.0.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0",
    "vitest": "^1.0.0"
  }
}
"""

README_MD = "# My Project\n\nA full-stack app."
DOCKERFILE = "FROM python:3.12-slim\nCMD [\"uvicorn\", \"app.main:app\"]"


def _make_fake_fetch(files: dict[str, str | None]):
    """Return a monkeypatch replacement for fetch_public_github_file."""
    def fake_fetch(repo_url: str, file_path: str, branch_candidates=None):
        content = files.get(file_path)
        if content is None:
            return GitHubFileFetchResult(ok=False, error="file_not_found", status_code=404)
        return GitHubFileFetchResult(ok=True, content=content, branch="main", status_code=200)
    return fake_fetch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Unit tests: _detect_stack ─────────────────────────────────────────────────

class TestDetectStack:
    def test_python_from_requirements(self):
        fetched = {"requirements.txt": REQUIREMENTS_TXT}
        stack = _detect_stack(fetched)
        assert "Python" in stack
        assert "FastAPI" in stack
        assert "SQLAlchemy" in stack
        assert "pytest" in stack
        assert "OpenAI" in stack

    def test_js_from_package_json(self):
        fetched = {"package.json": PACKAGE_JSON}
        stack = _detect_stack(fetched)
        assert "React" in stack
        assert "Next.js" in stack
        assert "Supabase" in stack
        assert "TypeScript" in stack

    def test_docker_detected(self):
        fetched = {"Dockerfile": DOCKERFILE}
        stack = _detect_stack(fetched)
        assert "Docker" in stack

    def test_docker_compose_detected(self):
        fetched = {"docker-compose.yml": "version: '3'\nservices:\n  web:\n    build: ."}
        stack = _detect_stack(fetched)
        assert "Docker Compose" in stack

    def test_empty_fetched(self):
        stack = _detect_stack({})
        assert stack == []

    def test_malformed_package_json(self):
        fetched = {"package.json": "not-json"}
        stack = _detect_stack(fetched)
        # Should not raise; JavaScript added but no deps parsed
        assert "JavaScript" in stack

    def test_pyproject_toml(self):
        pyproject = "[tool.poetry.dependencies]\npython = \"^3.11\"\nfastapi = \"*\"\n"
        fetched = {"pyproject.toml": pyproject}
        stack = _detect_stack(fetched)
        assert "FastAPI" in stack


# ── Unit tests: _detect_features ─────────────────────────────────────────────

class TestDetectFeatures:
    def test_readme_detected(self):
        fetched = {"README.md": "# Repo"}
        features = _detect_features(fetched, [])
        assert "readme" in features

    def test_docker_feature(self):
        fetched = {"Dockerfile": DOCKERFILE}
        features = _detect_features(fetched, ["Docker"])
        assert "docker" in features
        assert "deployment" in features

    def test_testing_from_reqs(self):
        fetched = {"requirements.txt": "pytest==8.0.0\n"}
        features = _detect_features(fetched, ["pytest"])
        assert "testing" in features

    def test_testing_from_npm(self):
        fetched = {"package.json": '{"devDependencies": {"vitest": "^1.0.0"}}'}
        features = _detect_features(fetched, [])
        assert "testing" in features

    def test_ml_feature(self):
        features = _detect_features({}, ["PyTorch", "scikit-learn"])
        assert "machine_learning" in features

    def test_ai_llm_feature(self):
        features = _detect_features({}, ["OpenAI", "LangChain"])
        assert "ai_llm" in features

    def test_api_framework_feature(self):
        features = _detect_features({}, ["FastAPI"])
        assert "api_framework" in features

    def test_database_feature(self):
        features = _detect_features({}, ["SQLAlchemy", "Redis"])
        assert "database" in features


# ── Unit tests: _match_skills ─────────────────────────────────────────────────

class TestMatchSkills:
    def test_exact_match(self):
        matched, missing = _match_skills(["FastAPI"], ["FastAPI"])
        assert "FastAPI" in matched
        assert missing == []

    def test_alias_match(self):
        matched, missing = _match_skills(["python"], ["FastAPI", "Pandas"])
        assert "python" in matched
        assert missing == []

    def test_partial_miss(self):
        matched, missing = _match_skills(["react", "pytorch"], ["React"])
        assert "react" in matched
        assert "pytorch" in missing

    def test_all_missing(self):
        matched, missing = _match_skills(["ruby", "rails"], ["Python", "FastAPI"])
        assert matched == []
        assert "ruby" in missing
        assert "rails" in missing

    def test_no_claimed_skills(self):
        matched, missing = _match_skills([], ["FastAPI"])
        assert matched == []
        assert missing == []

    def test_ml_alias(self):
        matched, missing = _match_skills(["machine learning"], ["PyTorch", "Pandas"])
        assert "machine learning" in matched

    def test_case_insensitive_stack(self):
        matched, missing = _match_skills(["FastAPI"], ["fastapi"])
        assert "FastAPI" in matched


# ── Unit tests: _compute_confidence ──────────────────────────────────────────

class TestComputeConfidence:
    def test_min_score_no_files(self):
        score = _compute_confidence([], [], [], [])
        assert score == pytest.approx(0.25)

    def test_increases_with_files(self):
        score_few = _compute_confidence(["README.md"], [], [], [])
        score_many = _compute_confidence(["README.md", "requirements.txt", "Dockerfile", "package.json"], [], [], [])
        assert score_many > score_few

    def test_skill_match_increases_score(self):
        base = _compute_confidence(["README.md"], [], [], ["react", "python"])
        full = _compute_confidence(["README.md"], [], ["react", "python"], ["react", "python"])
        assert full > base

    def test_capped_at_095(self):
        files = ["README.md", "requirements.txt", "package.json", "Dockerfile", "Makefile", ".env.example"]
        score = _compute_confidence(files, ["FastAPI", "React"], ["skill1", "skill2"], ["skill1", "skill2"])
        assert score <= 0.95


# ── Unit tests: analyze_github_repo (pure function) ──────────────────────────

class TestAnalyzeGithubRepo:
    def test_invalid_url_returns_failed(self):
        result = analyze_github_repo("not-a-url", [])
        assert result["status"] == "failed"
        assert result["confidence_score"] == 0.0
        assert any("parse" in w.lower() or "url" in w.lower() for w in result["warnings"])

    def test_private_repo_returns_private_or_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({}),
        )
        result = analyze_github_repo(REPO_URL, ["python"])
        assert result["status"] == "private_or_unavailable"
        assert result["confidence_score"] == 0.0

    def test_success_with_requirements(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": README_MD,
                "requirements.txt": REQUIREMENTS_TXT,
            }),
        )
        result = analyze_github_repo(REPO_URL, ["python", "FastAPI"])
        assert result["status"] == "success"
        assert "FastAPI" in result["detected_stack"]
        assert "python" in result["matched_claimed_skills"]
        assert "FastAPI" in result["matched_claimed_skills"]
        assert result["confidence_score"] > 0.5
        assert "README.md" in result["evidence_files"]
        assert result["recruiter_summary"] != ""

    def test_success_with_npm(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": README_MD,
                "package.json": PACKAGE_JSON,
            }),
        )
        result = analyze_github_repo(REPO_URL, ["react", "typescript"])
        assert result["status"] == "success"
        assert "React" in result["detected_stack"]
        assert "TypeScript" in result["detected_stack"]
        assert "react" in result["matched_claimed_skills"]
        assert "typescript" in result["matched_claimed_skills"]

    def test_docker_detected_in_features(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"Dockerfile": DOCKERFILE}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert "docker" in result["detected_features"]
        assert "deployment" in result["detected_features"]

    def test_missing_skills_reported(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n"}),
        )
        result = analyze_github_repo(REPO_URL, ["react", "python"])
        assert "python" in result["matched_claimed_skills"]
        assert "react" in result["missing_claimed_skills"]

    def test_no_claimed_skills(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n"}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert result["matched_claimed_skills"] == []
        assert result["missing_claimed_skills"] == []

    def test_created_at_present(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"README.md": "# Hi"}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert "created_at" in result
        assert result["created_at"] != ""


# ── Unit tests: ExtensionProofGitHubAnalysisService ──────────────────────────

class TestExtensionProofGitHubAnalysisService:
    def test_run_analysis_stores_result(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": REQUIREMENTS_TXT}),
        )
        db: dict[str, Any] = {}
        service = ExtensionProofGitHubAnalysisService(db)
        row = service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, ["python"])
        assert row["proof_session_id"] == SESSION_ID
        assert row["status"] == "success"
        assert "extension_proof_github_analysis" in db
        assert SESSION_ID in db["extension_proof_github_analysis"]

    def test_get_latest_returns_stored(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"README.md": README_MD}),
        )
        db: dict[str, Any] = {}
        service = ExtensionProofGitHubAnalysisService(db)
        service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, [])
        result = service.get_latest(DEMO_USER_ID, SESSION_ID)
        assert result is not None
        assert result["proof_session_id"] == SESSION_ID

    def test_get_latest_returns_none_if_not_analyzed(self):
        db: dict[str, Any] = {}
        service = ExtensionProofGitHubAnalysisService(db)
        result = service.get_latest(DEMO_USER_ID, SESSION_ID)
        assert result is None

    def test_run_analysis_overwrites_previous(self, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": REQUIREMENTS_TXT}),
        )
        db: dict[str, Any] = {}
        service = ExtensionProofGitHubAnalysisService(db)
        service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, ["python"])
        service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, ["react"])
        # Should have exactly one entry per session
        assert len(db["extension_proof_github_analysis"]) == 1


# ── Integration tests: POST endpoint ─────────────────────────────────────────

class TestAnalyzeGithubEndpoint:
    def test_post_returns_200(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": README_MD,
                "requirements.txt": REQUIREMENTS_TXT,
            }),
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": REPO_URL, "claimed_skills": ["python", "FastAPI"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["proof_session_id"] == SESSION_ID
        assert body["status"] == "success"
        assert isinstance(body["detected_stack"], list)
        assert isinstance(body["confidence_score"], float)
        assert isinstance(body["recruiter_summary"], str)
        assert body["recruiter_summary"] != ""

    def test_post_private_repo(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({}),
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": REPO_URL, "claimed_skills": []},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "private_or_unavailable"

    def test_post_invalid_url(self, client):
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": "not-a-url", "claimed_skills": []},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "failed"

    def test_post_missing_github_url(self, client):
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"claimed_skills": []},
        )
        assert r.status_code == 422

    def test_post_empty_github_url(self, client):
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": "", "claimed_skills": []},
        )
        assert r.status_code == 422

    def test_post_response_schema(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"README.md": README_MD}),
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": REPO_URL, "claimed_skills": ["python"]},
        )
        assert r.status_code == 200
        body = r.json()
        required_keys = {
            "id", "proof_session_id", "repo_url", "status",
            "detected_stack", "detected_features",
            "matched_claimed_skills", "missing_claimed_skills",
            "evidence_files", "confidence_score",
            "warnings", "recruiter_summary", "created_at",
        }
        assert required_keys.issubset(body.keys())


# ── Integration tests: GET endpoint ──────────────────────────────────────────

class TestGetGithubAnalysisEndpoint:
    def test_get_404_when_not_analyzed(self, client):
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analysis/github"
        )
        assert r.status_code == 404

    def test_get_returns_stored_result(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module,
            "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": REQUIREMENTS_TXT}),
        )
        client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={"github_url": REPO_URL, "claimed_skills": ["python"]},
        )
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analysis/github"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["proof_session_id"] == SESSION_ID
        assert body["status"] == "success"

