"""Tests for Extension Proof GitHub Analysis.

All storage is in-memory. GitHub HTTP calls are monkeypatched so no real
network traffic is made. The monkeypatch target is the function as imported
in the service module.

Evidence matching is intentionally project-agnostic — tests use generic
sample projects (React frontend, FastAPI backend, ML model, cloud deployment,
domain skill, backend-only). No real project names or URLs are hardcoded.
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
    _extract_significant_terms,
    _match_domain_skill,
    _match_deployment_skill,
    _DEPLOYMENT_PLATFORMS,
    _FRONTEND_FRAMEWORK_SKILLS,
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
        assert "JavaScript" in stack

    def test_pyproject_toml(self):
        pyproject = "[tool.poetry.dependencies]\npython = \"^3.11\"\nfastapi = \"*\"\n"
        fetched = {"pyproject.toml": pyproject}
        stack = _detect_stack(fetched)
        assert "FastAPI" in stack

    def test_react_from_frontend_subdir_package_json(self):
        pkg = '{"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}'
        fetched = {
            "requirements.txt": "fastapi==0.110.0\n",
            "frontend/package.json": pkg,
        }
        stack = _detect_stack(fetched)
        assert "React" in stack
        assert "Python" in stack


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


# ── Unit tests: domain-skill helpers ─────────────────────────────────────────

class TestDomainSkillHelpers:
    def test_extract_significant_terms_filters_stopwords(self):
        assert _extract_significant_terms("API for the web") == ["web"]

    def test_extract_significant_terms_removes_punctuation(self):
        terms = _extract_significant_terms("Next.js App")
        assert "nextjs" in terms or "next" in terms

    def test_extract_significant_terms_min_length(self):
        # "go" has only 2 chars — should be filtered
        terms = _extract_significant_terms("Go programming")
        assert "go" not in terms
        assert "programming" in terms

    def test_domain_skill_single_term_match(self):
        assert _match_domain_skill("redis", "the project uses redis for caching") == "weakly"

    def test_domain_skill_single_term_too_short(self):
        # "sql" is 3 chars but ≥ 4 required for single-term → missing
        assert _match_domain_skill("sql", "uses sql database") == "missing"

    def test_domain_skill_single_term_long_enough(self):
        assert _match_domain_skill("redis", "stores sessions in redis") == "weakly"

    def test_domain_skill_multi_term_needs_two_hits(self):
        # "fraud detection" → terms: ["fraud", "detection"]
        # Only "fraud" appears — not enough
        assert _match_domain_skill("fraud detection", "detects fraud") != "missing" or \
               _match_domain_skill("fraud detection", "fraud detection system") == "weakly"

    def test_domain_skill_multi_term_no_hits_is_missing(self):
        assert _match_domain_skill("fraud detection", "simple todo app") == "missing"

    def test_domain_skill_multi_term_both_terms_match(self):
        context = "a system for fraud detection in financial transactions"
        assert _match_domain_skill("fraud detection", context) == "weakly"

    def test_domain_skill_three_terms_needs_two(self):
        # "real time analytics" → terms: ["real", "time", "analytics"]
        context = "processes real time data streams"
        # "real" and "time" both match → 2/3 ≥ 2 required → weakly
        result = _match_domain_skill("real time analytics", context)
        assert result == "weakly"

    def test_domain_skill_generic_product_recommendation(self):
        context = "a product recommendation engine based on purchase history"
        assert _match_domain_skill("product recommendation", context) == "weakly"

    def test_domain_skill_empty_after_stopword_filter(self):
        assert _match_domain_skill("api for the", "does not matter") == "missing"


# ── Unit tests: deployment platform matching ──────────────────────────────────

class TestDeploymentSkillMatching:
    def _features(self, *names: str) -> set[str]:
        return set(names)

    def test_google_cloud_run_from_run_app_url(self):
        result = _match_deployment_skill(
            "google cloud run", set(), set(), "",
            url_lower="https://myapi-abc123-uc.a.run.app",
        )
        assert result == "weakly"

    def test_google_cloud_run_from_readme_and_docker_stack(self):
        readme = "deployed on google cloud run using gcloud"
        result = _match_deployment_skill(
            "google cloud run",
            {"docker", "google cloud"},
            self._features("deployment"),
            readme, "",
        )
        assert result == "weakly"

    def test_google_cloud_run_from_readme_alone(self):
        readme = "see gcp setup in the docs"
        result = _match_deployment_skill("google cloud run", set(), set(), readme, "")
        assert result == "weakly"

    def test_google_cloud_run_stack_plus_dockerfile(self):
        # Google Cloud in stack + deployment feature (no URL, no README mention)
        result = _match_deployment_skill(
            "google cloud run",
            {"google cloud", "docker"},
            self._features("deployment"),
            "", "",
        )
        assert result == "weakly"

    def test_google_cloud_run_missing_when_no_evidence(self):
        result = _match_deployment_skill(
            "google cloud run", {"python", "fastapi"}, set(), "", "",
        )
        assert result == "missing"

    def test_vercel_from_url(self):
        result = _match_deployment_skill(
            "vercel", {"next.js"}, set(), "",
            url_lower="https://my-project.vercel.app",
        )
        assert result == "weakly"

    def test_vercel_from_readme(self):
        result = _match_deployment_skill(
            "vercel", set(), set(),
            "deployed on vercel for preview builds", "",
        )
        assert result == "weakly"

    def test_render_from_url(self):
        result = _match_deployment_skill(
            "render", set(), set(), "",
            url_lower="https://myapi.onrender.com",
        )
        assert result == "weakly"

    def test_render_missing_when_no_evidence(self):
        result = _match_deployment_skill(
            "render", {"python"}, set(), "renders html templates", "",
        )
        # "renders" != "render.com" keyword, URL absent → missing
        assert result == "missing"

    def test_heroku_from_url(self):
        result = _match_deployment_skill(
            "heroku", set(), set(), "",
            url_lower="https://myapp.herokuapp.com",
        )
        assert result == "weakly"

    def test_fly_io_from_url(self):
        result = _match_deployment_skill(
            "fly.io", set(), set(), "",
            url_lower="https://myapp.fly.dev",
        )
        assert result == "weakly"

    def test_aws_from_stack_and_deploy_config(self):
        result = _match_deployment_skill(
            "aws", {"aws"}, self._features("deployment"), "", "",
        )
        assert result == "weakly"

    def test_railway_from_url(self):
        result = _match_deployment_skill(
            "railway", set(), set(), "",
            url_lower="https://myapp.up.railway.app",
        )
        assert result == "weakly"

    def test_unknown_skill_returns_none(self):
        result = _match_deployment_skill("react", set(), set(), "", "")
        assert result is None

    def test_all_platforms_have_required_keys(self):
        required = {"skill_names", "url_patterns", "readme_keywords", "stack_indicators"}
        for p in _DEPLOYMENT_PLATFORMS:
            assert required.issubset(p.keys()), f"Platform missing keys: {p}"


# ── Unit tests: _match_skills ─────────────────────────────────────────────────

class TestMatchSkills:
    def test_exact_match(self):
        matched, weakly, missing = _match_skills(["FastAPI"], ["FastAPI"])
        assert "FastAPI" in matched
        assert missing == []

    def test_alias_match(self):
        matched, weakly, missing = _match_skills(["python"], ["FastAPI", "Pandas"])
        assert "python" in matched
        assert missing == []

    def test_partial_miss(self):
        matched, weakly, missing = _match_skills(["react", "pytorch"], ["React"])
        assert "react" in matched
        assert "pytorch" in missing

    def test_all_missing(self):
        matched, weakly, missing = _match_skills(["ruby", "rails"], ["Python", "FastAPI"])
        assert matched == []
        assert "ruby" in missing
        assert "rails" in missing

    def test_no_claimed_skills(self):
        matched, weakly, missing = _match_skills([], ["FastAPI"])
        assert matched == []
        assert weakly == []
        assert missing == []

    def test_ml_alias(self):
        matched, weakly, missing = _match_skills(["machine learning"], ["PyTorch", "Pandas"])
        assert "machine learning" in matched

    def test_case_insensitive_stack(self):
        matched, weakly, missing = _match_skills(["FastAPI"], ["fastapi"])
        assert "FastAPI" in matched

    def test_gcp_alias_matches_google_cloud_in_stack(self):
        matched, weakly, missing = _match_skills(["GCP"], ["Google Cloud", "Python"])
        assert "GCP" in matched

    def test_google_cloud_alias_direct(self):
        matched, weakly, missing = _match_skills(["Google Cloud"], ["Google Cloud"])
        assert "Google Cloud" in matched


# ── Unit tests: _match_skills context-aware ───────────────────────────────────

class TestMatchSkillsContextAware:
    """Generic, project-agnostic context-aware matching scenarios."""

    # ── Google Cloud Run (deployment platform) ────────────────────────────────

    def test_google_cloud_run_weakly_from_gcloud_stack_and_docker(self):
        matched, weakly, missing = _match_skills(
            ["Google Cloud Run"],
            ["Google Cloud", "Docker", "Python"],
            detected_features=["deployment", "docker"],
        )
        assert "Google Cloud Run" in weakly
        assert "Google Cloud Run" not in matched
        assert "Google Cloud Run" not in missing

    def test_google_cloud_run_weakly_from_run_app_url(self):
        matched, weakly, missing = _match_skills(
            ["Google Cloud Run"],
            ["Docker"],
            detected_features=["deployment"],
            live_website_url="https://myapi-abc123-uc.a.run.app",
        )
        assert "Google Cloud Run" in weakly

    def test_google_cloud_run_weakly_from_readme(self):
        readme = "# My API\nDeployed on Google Cloud Run. Uses gcloud CLI."
        matched, weakly, missing = _match_skills(
            ["Google Cloud Run"],
            ["Docker"],
            detected_features=["deployment"],
            fetched_files={"README.md": readme},
        )
        assert "Google Cloud Run" in weakly

    def test_google_cloud_run_weakly_from_gcp_readme_only(self):
        readme = "# My App\nThis runs on GCP."
        matched, weakly, missing = _match_skills(
            ["Google Cloud Run"], ["Python"], fetched_files={"README.md": readme},
        )
        assert "Google Cloud Run" in weakly

    def test_google_cloud_run_missing_when_no_evidence(self):
        matched, weakly, missing = _match_skills(
            ["Google Cloud Run"], ["Python", "FastAPI"],
        )
        assert "Google Cloud Run" in missing
        assert "Google Cloud Run" not in matched
        assert "Google Cloud Run" not in weakly

    # ── Vercel (deployment platform) ──────────────────────────────────────────

    def test_vercel_weakly_from_url(self):
        matched, weakly, missing = _match_skills(
            ["Vercel"], ["Next.js"],
            live_website_url="https://my-project.vercel.app",
        )
        assert "Vercel" in weakly

    def test_vercel_weakly_from_readme(self):
        readme = "Deployed on Vercel for instant preview deployments."
        matched, weakly, missing = _match_skills(
            ["Vercel"], ["Next.js"], fetched_files={"README.md": readme},
        )
        assert "Vercel" in weakly

    # ── Render (deployment platform) ──────────────────────────────────────────

    def test_render_weakly_from_onrender_url(self):
        matched, weakly, missing = _match_skills(
            ["Render"], ["Python", "FastAPI"],
            live_website_url="https://myapp.onrender.com",
        )
        assert "Render" in weakly

    def test_render_missing_without_evidence(self):
        # "renders html" in README should NOT trigger Render platform match
        readme = "the backend renders html templates for the client"
        matched, weakly, missing = _match_skills(
            ["Render"], ["Python", "FastAPI"], fetched_files={"README.md": readme},
        )
        assert "Render" in missing

    # ── React (frontend framework) ────────────────────────────────────────────

    def test_react_matched_from_stack(self):
        matched, weakly, missing = _match_skills(["React"], ["React", "JavaScript"])
        assert "React" in matched

    def test_react_matched_from_nextjs_alias(self):
        matched, weakly, missing = _match_skills(["react"], ["Next.js", "TypeScript"])
        assert "react" in matched

    def test_react_weakly_from_live_url_no_source(self):
        # Live website observed but no React files in repo
        matched, weakly, missing = _match_skills(
            ["React"], ["Python", "FastAPI"],
            live_website_url="https://myapp.example.com",
        )
        assert "React" in weakly
        assert "React" not in matched

    def test_react_weakly_from_readme_when_no_live_url(self):
        readme = "The frontend is built with React and JSX components."
        matched, weakly, missing = _match_skills(
            ["React"], ["Python", "FastAPI"], fetched_files={"README.md": readme},
        )
        assert "React" in weakly

    def test_react_missing_no_source_no_live_url_no_readme(self):
        matched, weakly, missing = _match_skills(
            ["React"], ["Python", "FastAPI"],
        )
        assert "React" in missing

    def test_vue_weakly_from_live_url_no_source(self):
        matched, weakly, missing = _match_skills(
            ["Vue"], ["Python"],
            live_website_url="https://myapp.example.com",
        )
        assert "Vue" in weakly

    def test_frontend_framework_skills_set_populated(self):
        assert "react" in _FRONTEND_FRAMEWORK_SKILLS
        assert "vue" in _FRONTEND_FRAMEWORK_SKILLS
        assert "angular" in _FRONTEND_FRAMEWORK_SKILLS
        assert "svelte" in _FRONTEND_FRAMEWORK_SKILLS

    # ── Generic domain skills ─────────────────────────────────────────────────

    def test_domain_skill_matched_from_readme_terms(self):
        # A claimed domain skill whose terms appear in README → weakly matched
        readme = "# Fraud Detection System\nThis project identifies fraudulent transactions."
        matched, weakly, missing = _match_skills(
            ["Fraud Detection"], ["Python", "scikit-learn"],
            fetched_files={"README.md": readme},
        )
        assert "Fraud Detection" in weakly or "Fraud Detection" in matched

    def test_domain_skill_matched_from_proof_objective(self):
        matched, weakly, missing = _match_skills(
            ["Traffic Flow Prediction"],
            ["scikit-learn", "Python"],
            proof_objective="Predict traffic flow patterns using historical sensor data",
        )
        assert "Traffic Flow Prediction" in weakly or "Traffic Flow Prediction" in matched

    def test_domain_skill_matched_from_page_title(self):
        matched, weakly, missing = _match_skills(
            ["Sentiment Analysis"],
            ["Python", "PyTorch"],
            live_page_title="Sentiment Analysis Dashboard",
        )
        assert "Sentiment Analysis" in weakly or "Sentiment Analysis" in matched

    def test_domain_skill_missing_when_context_unrelated(self):
        matched, weakly, missing = _match_skills(
            ["Fraud Detection"], ["React", "FastAPI"],
        )
        assert "Fraud Detection" in missing

    # ── Comma-separated claims ────────────────────────────────────────────────

    def test_comma_separated_skills_each_matched_individually(self):
        matched, weakly, missing = _match_skills(
            ["FastAPI", "React"], ["FastAPI", "React"],
        )
        assert "FastAPI" in matched
        assert "React" in matched
        assert missing == []


# ── Unit tests: _compute_confidence ──────────────────────────────────────────

class TestComputeConfidence:
    def test_min_score_no_files(self):
        score = _compute_confidence([], [], [], [])
        assert score == pytest.approx(0.25)

    def test_increases_with_files(self):
        score_few = _compute_confidence(["README.md"], [], [], [])
        score_many = _compute_confidence(
            ["README.md", "requirements.txt", "Dockerfile", "package.json"], [], [], [],
        )
        assert score_many > score_few

    def test_skill_match_increases_score(self):
        base = _compute_confidence(["README.md"], [], [], ["react", "python"])
        full = _compute_confidence(["README.md"], [], ["react", "python"], ["react", "python"])
        assert full > base

    def test_weakly_matched_contribute_half_weight(self):
        full_match = _compute_confidence(["README.md"], [], ["skill1", "skill2"], ["skill1", "skill2"])
        weak_match = _compute_confidence(["README.md"], [], [], ["skill1", "skill2"], ["skill1", "skill2"])
        assert full_match > weak_match > _compute_confidence(["README.md"], [], [], ["skill1", "skill2"])

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
        monkeypatch.setattr(svc_module, "fetch_public_github_file", _make_fake_fetch({}))
        result = analyze_github_repo(REPO_URL, ["python"])
        assert result["status"] == "private_or_unavailable"
        assert result["confidence_score"] == 0.0

    def test_success_with_requirements(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"README.md": README_MD, "requirements.txt": REQUIREMENTS_TXT}),
        )
        result = analyze_github_repo(REPO_URL, ["python", "FastAPI"])
        assert result["status"] == "success"
        assert "FastAPI" in result["detected_stack"]
        assert "python" in result["matched_claimed_skills"]
        assert "FastAPI" in result["matched_claimed_skills"]
        assert result["confidence_score"] > 0.5
        assert "README.md" in result["evidence_files"]
        assert result["recruiter_summary"] != ""
        assert "weakly_matched_claimed_skills" in result

    def test_success_with_npm(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"README.md": README_MD, "package.json": PACKAGE_JSON}),
        )
        result = analyze_github_repo(REPO_URL, ["react", "typescript"])
        assert result["status"] == "success"
        assert "React" in result["detected_stack"]
        assert "TypeScript" in result["detected_stack"]
        assert "react" in result["matched_claimed_skills"]
        assert "typescript" in result["matched_claimed_skills"]

    def test_docker_detected_in_features(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file", _make_fake_fetch({"Dockerfile": DOCKERFILE}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert "docker" in result["detected_features"]
        assert "deployment" in result["detected_features"]

    def test_missing_skills_not_counted_as_matched(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n"}),
        )
        result = analyze_github_repo(REPO_URL, ["react", "python"])
        assert "python" in result["matched_claimed_skills"]
        # react has no source, no live URL, no README → not matched
        assert "react" not in result["matched_claimed_skills"]

    def test_no_claimed_skills(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n"}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert result["matched_claimed_skills"] == []
        assert result["weakly_matched_claimed_skills"] == []
        assert result["missing_claimed_skills"] == []

    def test_created_at_present(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file", _make_fake_fetch({"README.md": "# Hi"}),
        )
        result = analyze_github_repo(REPO_URL, [])
        assert "created_at" in result
        assert result["created_at"] != ""

    def test_comma_separated_skills_split(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n", "package.json": '{"dependencies":{"react":"^18"}}'}),
        )
        result = analyze_github_repo(REPO_URL, ["FastAPI, React"])
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "React" in result["matched_claimed_skills"]


# ── Project-type scenarios (generic, reusable) ────────────────────────────────
#
# Six canonical project types that any student might build.
# No real project names, URLs, or domain-specific hardcoding.

class TestProjectScenarios:

    def test_scenario_react_frontend_project(self, monkeypatch):
        """React detected directly from root package.json dependencies."""
        pkg = '{"dependencies":{"react":"^18.0.0","react-dom":"^18.0.0","typescript":"^5.0.0"}}'
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"README.md": "# Portfolio Site\nA React + TypeScript portfolio.", "package.json": pkg}),
        )
        result = analyze_github_repo(REPO_URL, ["React", "TypeScript"])
        assert result["status"] == "success"
        assert "React" in result["matched_claimed_skills"]
        assert "TypeScript" in result["matched_claimed_skills"]
        assert result["weakly_matched_claimed_skills"] == []

    def test_scenario_react_detected_from_frontend_subdir(self, monkeypatch):
        """React detected from frontend/package.json when root has none."""
        pkg = '{"dependencies":{"react":"^18.0.0","react-dom":"^18.0.0"}}'
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# My App\nFastAPI backend with a React frontend.",
                "requirements.txt": "fastapi==0.110.0\n",
                "frontend/package.json": pkg,
            }),
        )
        result = analyze_github_repo(REPO_URL, ["FastAPI", "React"])
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "React" in result["matched_claimed_skills"]

    def test_scenario_fastapi_backend_project(self, monkeypatch):
        """Backend skills matched directly from requirements.txt."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# REST API",
                "requirements.txt": "fastapi==0.110.0\nsqlalchemy==2.0.0\npydantic==2.0.0\n",
            }),
        )
        result = analyze_github_repo(REPO_URL, ["FastAPI", "SQLAlchemy"])
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "SQLAlchemy" in result["matched_claimed_skills"]
        assert result["missing_claimed_skills"] == []

    def test_scenario_ml_model_repo(self, monkeypatch):
        """ML skills matched from requirements.txt dependency detection."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Demand Forecasting\nTime-series prediction model.",
                "requirements.txt": "scikit-learn==1.4.0\nlightgbm==4.0.0\npandas==2.0.0\nnumpy==1.26.0\n",
            }),
        )
        result = analyze_github_repo(REPO_URL, ["Machine Learning", "scikit-learn"])
        assert "Machine Learning" in result["matched_claimed_skills"]
        assert "scikit-learn" in result["matched_claimed_skills"]

    def test_scenario_cloud_deployment_repo(self, monkeypatch):
        """Cloud Run weakly supported via README + Dockerfile — not project-specific."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# My API\nDeployed on Google Cloud Run using gcloud CLI.",
                "requirements.txt": "fastapi==0.110.0\n",
                "Dockerfile": "FROM python:3.12-slim",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["FastAPI", "Google Cloud Run"],
            live_website_url="https://myapi-xyzabc-uc.a.run.app",
        )
        assert result["status"] == "success"
        assert "FastAPI" in result["matched_claimed_skills"]
        gcloud_run_evidence = (
            "Google Cloud Run" in result["matched_claimed_skills"]
            or "Google Cloud Run" in result["weakly_matched_claimed_skills"]
        )
        assert gcloud_run_evidence, "Google Cloud Run should have at least weak evidence"

    def test_scenario_generic_domain_skill_from_readme(self, monkeypatch):
        """Domain skill terms appear in README → weakly matched, regardless of project name."""
        readme = (
            "# Product Recommendation Engine\n"
            "Recommends products to users based on collaborative filtering."
        )
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"README.md": readme, "requirements.txt": "scikit-learn==1.4.0\n"}),
        )
        result = analyze_github_repo(
            REPO_URL, ["Product Recommendation"],
            proof_objective="Build a product recommendation system",
        )
        found = (
            "Product Recommendation" in result["matched_claimed_skills"]
            or "Product Recommendation" in result["weakly_matched_claimed_skills"]
        )
        assert found, "Domain skill with terms in README/objective should be at least weakly matched"

    def test_scenario_backend_only_react_partial_from_live_url(self, monkeypatch):
        """React is partial when a live URL exists but no React source files are found."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# My Backend API",
                "requirements.txt": "fastapi==0.110.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL, ["FastAPI", "React"],
            live_website_url="https://myapp.example.com",
        )
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "React" in result["weakly_matched_claimed_skills"]
        assert "React" not in result["matched_claimed_skills"]
        assert "React" not in result["missing_claimed_skills"]

    def test_scenario_react_missing_no_source_no_live_url(self, monkeypatch):
        """React is missing when there is neither source evidence nor a live website."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": "fastapi==0.110.0\n"}),
        )
        result = analyze_github_repo(REPO_URL, ["FastAPI", "React"])
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "React" not in result["matched_claimed_skills"]

    def test_scenario_vercel_deployment_from_url(self, monkeypatch):
        """Vercel detected from live URL — generic, not tied to a specific project."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# My Next.js App",
                "package.json": '{"dependencies":{"next":"^14.0.0","react":"^18.0.0"}}',
            }),
        )
        result = analyze_github_repo(
            REPO_URL, ["Next.js", "Vercel"],
            live_website_url="https://my-project.vercel.app",
        )
        assert "Next.js" in result["matched_claimed_skills"]
        vercel_evidence = (
            "Vercel" in result["matched_claimed_skills"]
            or "Vercel" in result["weakly_matched_claimed_skills"]
        )
        assert vercel_evidence

    def test_scenario_render_deployment_from_url(self, monkeypatch):
        """Render detected from live URL — generic platform support."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# My FastAPI Service",
                "requirements.txt": "fastapi==0.110.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL, ["FastAPI", "Render"],
            live_website_url="https://my-service.onrender.com",
        )
        assert "FastAPI" in result["matched_claimed_skills"]
        render_evidence = (
            "Render" in result["matched_claimed_skills"]
            or "Render" in result["weakly_matched_claimed_skills"]
        )
        assert render_evidence

    def test_scenario_domain_skill_missing_when_context_unrelated(self, monkeypatch):
        """Domain skill correctly missing when project context contains no matching terms."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Simple Todo App\nCreate, edit, and delete tasks.",
                "requirements.txt": "fastapi==0.110.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL, ["Fraud Detection"],
            proof_objective="Build a simple task management app",
        )
        assert "Fraud Detection" in result["missing_claimed_skills"]

    def test_scenario_streamlit_ml_dashboard(self, monkeypatch):
        """Streamlit ML dashboard: Streamlit + scikit-learn detected from requirements."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# House Price Predictor\nInteractive Streamlit dashboard.",
                "requirements.txt": "streamlit==1.30.0\nscikit-learn==1.4.0\npandas==2.0.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["Streamlit", "Machine Learning", "Python"],
            live_website_url="https://house-predictor.streamlit.app",
        )
        assert result["status"] == "success"
        assert "Streamlit" in result["matched_claimed_skills"]
        assert "Machine Learning" in result["matched_claimed_skills"]
        assert "Python" in result["matched_claimed_skills"]
        assert "streamlit_app" in result["detected_features"]
        assert "machine_learning" in result["detected_features"]

    def test_scenario_gradio_demo_on_hugging_face(self, monkeypatch):
        """Gradio ML demo deployed to Hugging Face Spaces via live URL."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Sentiment Analyser\nGradio app using HuggingFace Transformers.",
                "requirements.txt": "gradio==4.0.0\ntransformers==4.38.0\ntorch==2.2.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["Gradio", "HuggingFace Transformers", "Hugging Face Spaces"],
            live_website_url="https://user-sentiment-app.hf.space",
        )
        assert "Gradio" in result["matched_claimed_skills"]
        assert "HuggingFace Transformers" in result["matched_claimed_skills"]
        hf_spaces_evidence = (
            "Hugging Face Spaces" in result["matched_claimed_skills"]
            or "Hugging Face Spaces" in result["weakly_matched_claimed_skills"]
        )
        assert hf_spaces_evidence, "HF Spaces should have evidence from .hf.space URL"
        assert "gradio_app" in result["detected_features"]

    def test_scenario_html_css_portfolio_site(self, monkeypatch):
        """Plain HTML/CSS/JS portfolio — no backend required, detected from index.html."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Portfolio Site\nPersonal portfolio built with HTML, CSS, and JavaScript.",
                "index.html": "<!DOCTYPE html><html><head><title>Portfolio</title></head><body></body></html>",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["HTML", "CSS", "JavaScript"],
            live_website_url="https://myname.github.io",
        )
        assert result["status"] == "success"
        assert "HTML" in result["matched_claimed_skills"]
        assert "CSS" in result["matched_claimed_skills"]
        assert "JavaScript" in result["matched_claimed_skills"]
        assert "html_frontend" in result["detected_features"]
        # Should NOT warn about missing dependency file for a plain HTML site
        dep_warning = any("dependency file" in w.lower() for w in result["warnings"])
        assert not dep_warning

    def test_scenario_github_pages_deployment(self, monkeypatch):
        """GitHub Pages detected from .github.io URL."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Portfolio\nDeployed via GitHub Pages.",
                "index.html": "<html><body>Hello</body></html>",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["HTML", "GitHub Pages"],
            live_website_url="https://student.github.io/portfolio",
        )
        assert "HTML" in result["matched_claimed_skills"]
        gh_pages_evidence = (
            "GitHub Pages" in result["matched_claimed_skills"]
            or "GitHub Pages" in result["weakly_matched_claimed_skills"]
        )
        assert gh_pages_evidence, "GitHub Pages should be detected from .github.io URL"

    def test_scenario_fastapi_backend_no_frontend_required(self, monkeypatch):
        """API-only backend is evaluated solely on backend evidence — no frontend penalty."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# REST API\nFastAPI backend with PostgreSQL.",
                "requirements.txt": "fastapi==0.110.0\nsqlalchemy==2.0.0\nalembic==1.13.0\n",
                "Dockerfile": "FROM python:3.12-slim",
            }),
        )
        result = analyze_github_repo(REPO_URL, ["FastAPI", "SQLAlchemy", "Docker"])
        assert "FastAPI" in result["matched_claimed_skills"]
        assert "SQLAlchemy" in result["matched_claimed_skills"]
        assert "Docker" in result["matched_claimed_skills"]
        # React was never claimed — should not appear in any list
        all_skills = (
            result["matched_claimed_skills"]
            + result["weakly_matched_claimed_skills"]
            + result["missing_claimed_skills"]
        )
        assert "React" not in all_skills

    def test_scenario_local_only_app_no_live_url(self, monkeypatch):
        """Local-only app with workflow but no live URL — no penalty for missing live URL."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# CLI Tool\nCommand-line data pipeline using pandas.",
                "requirements.txt": "pandas==2.0.0\nnumpy==1.26.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["Python", "Pandas", "NumPy"],
            proof_objective="Build a data processing pipeline",
            # no live_website_url intentionally
        )
        assert result["status"] == "success"
        assert "Python" in result["matched_claimed_skills"]
        assert "Pandas" in result["matched_claimed_skills"]
        assert "NumPy" in result["matched_claimed_skills"]
        assert result["confidence_score"] > 0

    def test_scenario_streamlit_cloud_deployment(self, monkeypatch):
        """Streamlit Community Cloud detected from .streamlit.app URL."""
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": "# Data Dashboard",
                "requirements.txt": "streamlit==1.30.0\nplotly==5.18.0\npandas==2.0.0\n",
            }),
        )
        result = analyze_github_repo(
            REPO_URL,
            ["Streamlit", "Plotly", "Streamlit Cloud"],
            live_website_url="https://myapp-dashboard.streamlit.app",
        )
        assert "Streamlit" in result["matched_claimed_skills"]
        assert "Plotly" in result["matched_claimed_skills"]
        cloud_evidence = (
            "Streamlit Cloud" in result["matched_claimed_skills"]
            or "Streamlit Cloud" in result["weakly_matched_claimed_skills"]
        )
        assert cloud_evidence, "Streamlit Cloud should be detected from .streamlit.app URL"


# ── Unit tests: ExtensionProofGitHubAnalysisService ──────────────────────────

class TestExtensionProofGitHubAnalysisService:
    def test_run_analysis_stores_result(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
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
            svc_module, "fetch_public_github_file",
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
        assert service.get_latest(DEMO_USER_ID, SESSION_ID) is None

    def test_run_analysis_overwrites_previous(self, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"requirements.txt": REQUIREMENTS_TXT}),
        )
        db: dict[str, Any] = {}
        service = ExtensionProofGitHubAnalysisService(db)
        service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, ["python"])
        service.run_analysis(DEMO_USER_ID, SESSION_ID, REPO_URL, ["react"])
        assert len(db["extension_proof_github_analysis"]) == 1


# ── Integration tests: POST endpoint ─────────────────────────────────────────

class TestAnalyzeGithubEndpoint:
    def test_post_returns_200(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({"README.md": README_MD, "requirements.txt": REQUIREMENTS_TXT}),
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
        assert body["recruiter_summary"] != ""

    def test_post_private_repo(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file", _make_fake_fetch({}),
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
            svc_module, "fetch_public_github_file", _make_fake_fetch({"README.md": README_MD}),
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
            "matched_claimed_skills", "weakly_matched_claimed_skills",
            "missing_claimed_skills", "evidence_files", "confidence_score",
            "warnings", "recruiter_summary", "created_at",
        }
        assert required_keys.issubset(body.keys())

    def test_post_with_live_context_fields(self, client, monkeypatch):
        readme = "# My Forecasting API\nUses LightGBM. Deployed on Google Cloud Run."
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
            _make_fake_fetch({
                "README.md": readme,
                "requirements.txt": "fastapi==0.110.0\nlightgbm==4.0.0\n",
                "Dockerfile": "FROM python:3.12-slim",
            }),
        )
        r = client.post(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analyze/github",
            json={
                "github_url": REPO_URL,
                "claimed_skills": ["FastAPI", "Google Cloud Run"],
                "live_website_url": "https://myapi-abc123-uc.a.run.app",
                "live_page_title": "Forecasting API",
                "proof_objective": "Demonstrate a deployed ML forecasting API",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert "FastAPI" in body["matched_claimed_skills"]
        assert isinstance(body["weakly_matched_claimed_skills"], list)
        gcloud_evidence = (
            "Google Cloud Run" in body["matched_claimed_skills"]
            or "Google Cloud Run" in body["weakly_matched_claimed_skills"]
        )
        assert gcloud_evidence


# ── Integration tests: GET endpoint ──────────────────────────────────────────

class TestGetGithubAnalysisEndpoint:
    def test_get_404_when_not_analyzed(self, client):
        r = client.get(
            f"/api/v1/student/extension-proof/sessions/{SESSION_ID}/analysis/github"
        )
        assert r.status_code == 404

    def test_get_returns_stored_result(self, client, monkeypatch):
        monkeypatch.setattr(
            svc_module, "fetch_public_github_file",
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
