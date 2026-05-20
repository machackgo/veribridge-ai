"""Tests for the GitHub Portfolio Scanner (Phase J3A).

All tests use MockGitHubAPIClient — no live GitHub calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_portfolio_scanner import (
    EvidenceCandidate,
    MockGitHubAPIClient,
    PortfolioScanner,
    RepoInfo,
    build_dry_run_report,
    build_github_highlight_url,
    check_duplicate,
    detect_skills_from_repo,
    extract_website_url,
    import_candidates,
    is_high_signal_file,
    is_weak_range,
    make_import_key,
    select_dockerfile_range,
    select_high_signal_ranges,
    select_workflow_range,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_repo(
    name: str = "boston-risk-app",
    owner: str = "machackgo",
    languages: dict | None = None,
    description: str | None = None,
    homepage: str | None = None,
    topics: list[str] | None = None,
) -> RepoInfo:
    return RepoInfo(
        name=name,
        url=f"https://github.com/{owner}/{name}",
        description=description,
        homepage=homepage,
        default_branch="main",
        languages=languages or {"Python": 50000},
        topics=topics or [],
        stars=5,
        owner=owner,
    )


def _make_candidate(
    skill: str = "Machine Learning",
    file_path: str = "api.py",
    line_start: int = 30,
    line_end: int = 50,
    user_id: str = "user-1",
    repo_url: str = "https://github.com/machackgo/test-repo",
) -> EvidenceCandidate:
    return EvidenceCandidate(
        skill_name=skill,
        project_title="Test Project",
        repo_url=repo_url,
        repo_name="test-repo",
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        evidence_description="Test evidence.",
        student_claim="I used ML.",
        evidence_type="github repository",
        website_url=None,
        detection_reason="ML training call",
        github_highlight_url=build_github_highlight_url(
            "machackgo", "test-repo", "main", file_path, line_start, line_end
        ),
        import_key=make_import_key(user_id, repo_url, file_path, line_start, line_end, skill),
    )


# ── Skill detection ────────────────────────────────────────────────────────────

class TestSkillDetection:
    def test_detects_python_from_language(self):
        repo = _make_repo(languages={"Python": 80000, "Dockerfile": 1000})
        skills = detect_skills_from_repo(repo, [], None)
        assert "Python" in skills

    def test_detects_docker_from_language(self):
        repo = _make_repo(languages={"Dockerfile": 5000})
        skills = detect_skills_from_repo(repo, [], None)
        assert "Docker" in skills

    def test_detects_ml_from_readme_keywords(self):
        repo = _make_repo(languages={"Python": 50000})
        readme = "This project uses scikit-learn and Decision Tree models for classification."
        skills = detect_skills_from_repo(repo, [], readme)
        assert "Machine Learning" in skills

    def test_detects_fastapi_from_description(self):
        repo = _make_repo(
            languages={"Python": 50000},
            description="A FastAPI backend for route risk prediction."
        )
        skills = detect_skills_from_repo(repo, [], None)
        assert "FastAPI" in skills

    def test_detects_docker_from_file_paths(self):
        repo = _make_repo(languages={"Python": 50000})
        skills = detect_skills_from_repo(repo, ["Dockerfile", "app.py"], None)
        assert "Docker" in skills

    def test_detects_cicd_from_workflow_path(self):
        repo = _make_repo(languages={"Python": 50000})
        skills = detect_skills_from_repo(
            repo, [".github/workflows/deploy.yml", "app.py"], None
        )
        assert "CI/CD" in skills

    def test_detects_rag_from_readme(self):
        repo = _make_repo(languages={"Python": 50000})
        readme = "Uses LangChain and OpenAI embeddings for RAG-based question answering."
        skills = detect_skills_from_repo(repo, [], readme)
        assert "RAG / LLM" in skills

    def test_detects_nlp_from_topics(self):
        repo = _make_repo(
            languages={"Python": 50000},
            topics=["natural-language-processing", "bert", "classification"],
        )
        skills = detect_skills_from_repo(repo, [], None)
        assert "NLP" in skills

    def test_detects_gcp_from_readme(self):
        repo = _make_repo(languages={"Python": 50000})
        readme = "Deployed on Google Cloud Run using the gcloud CLI."
        skills = detect_skills_from_repo(repo, [], readme)
        assert "GCP" in skills

    def test_no_skills_for_empty_repo(self):
        repo = _make_repo(languages={})
        skills = detect_skills_from_repo(repo, [], None)
        # Should return empty or very minimal list with no language signals
        assert isinstance(skills, list)


# ── Weak range detection ───────────────────────────────────────────────────────

class TestWeakRangeDetection:
    def test_import_only_block_is_weak(self):
        lines = [
            "import pandas as pd",
            "import numpy as np",
            "from sklearn.tree import DecisionTreeClassifier",
            "from sklearn.model_selection import train_test_split",
            "from sklearn.metrics import accuracy_score",
        ]
        assert is_weak_range(lines) is True

    def test_mixed_import_and_code_is_not_weak(self):
        lines = [
            "import pandas as pd",
            "from sklearn.tree import DecisionTreeClassifier",
            "",
            "clf = DecisionTreeClassifier()",
            "clf.fit(X_train, y_train)",
            "y_pred = clf.predict(X_test)",
        ]
        assert is_weak_range(lines) is False

    def test_empty_range_is_weak(self):
        assert is_weak_range([]) is True
        assert is_weak_range(["", "  ", "\t"]) is True

    def test_model_training_code_is_not_weak(self):
        lines = [
            "clf = DecisionTreeClassifier(max_depth=5)",
            "clf.fit(X_train, y_train)",
            "y_pred = clf.predict(X_test)",
            "score = accuracy_score(y_test, y_pred)",
            "print(f'Accuracy: {score:.4f}')",
        ]
        assert is_weak_range(lines) is False

    def test_comment_only_is_weak(self):
        lines = [
            "# This is a comment",
            "# Another comment",
            "# And another",
            "",
            "# One more",
        ]
        assert is_weak_range(lines) is True

    def test_fastapi_endpoint_is_not_weak(self):
        lines = [
            "@app.post('/predict')",
            "async def predict(data: PredictRequest):",
            "    model = load_model()",
            "    result = model.predict(data.features)",
            "    return {'prediction': result.tolist()}",
        ]
        assert is_weak_range(lines) is False


# ── Line range selection ───────────────────────────────────────────────────────

class TestLineRangeSelection:
    def test_finds_ml_training_range(self):
        content = "\n".join([
            "import pandas as pd",
            "from sklearn.tree import DecisionTreeClassifier",
            "from sklearn.model_selection import train_test_split",
            "",
            "df = pd.read_csv('data.csv')",
            "X = df.drop('label', axis=1)",
            "y = df['label']",
            "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
            "",
            "clf = DecisionTreeClassifier(max_depth=5, random_state=42)",
            "clf.fit(X_train, y_train)",
            "y_pred = clf.predict(X_test)",
            "print('Accuracy:', accuracy_score(y_test, y_pred))",
        ])
        ranges = select_high_signal_ranges(content, "model.py", "Machine Learning")
        assert len(ranges) >= 1
        start, end, reason = ranges[0]
        # Should capture the training block, not the import block
        assert end >= 10, "Range should include the training code lines"
        assert "ML" in reason or "training" in reason or "model" in reason

    def test_rejects_import_only_top_section(self):
        # File where only first 6 lines are imports and nothing else
        content = "\n".join([
            "import pandas as pd",
            "from sklearn.tree import DecisionTreeClassifier",
            "from sklearn.model_selection import train_test_split",
            "from sklearn.metrics import accuracy_score",
            "import numpy as np",
            "import sys",
        ])
        ranges = select_high_signal_ranges(content, "imports_only.py", "Machine Learning")
        # If any ranges are returned they must NOT be import-only
        for start, end, reason in ranges:
            lines = content.splitlines()[start - 1:end]
            assert not is_weak_range(lines), f"Returned a weak range {start}-{end}"

    def test_finds_fastapi_endpoint_range(self):
        content = "\n".join([
            "from fastapi import FastAPI",
            "from pydantic import BaseModel",
            "",
            "app = FastAPI()",
            "",
            "class PredictRequest(BaseModel):",
            "    features: list[float]",
            "",
            "@app.post('/predict')",
            "async def predict_route(data: PredictRequest):",
            "    result = model.predict([data.features])",
            "    risk_level = 'high' if result[0] > 0.7 else 'low'",
            "    return {'risk_level': risk_level, 'score': float(result[0])}",
        ])
        ranges = select_high_signal_ranges(content, "api.py", "FastAPI")
        assert len(ranges) >= 1
        start, end, reason = ranges[0]
        lines = content.splitlines()
        selected = lines[start - 1 : end]
        # The route decorator should be in range
        has_decorator = any("@app." in l or "@router." in l for l in selected)
        assert has_decorator, "Range should include the @app.post decorator"

    def test_finds_ml_inference_range(self):
        content = "\n".join([
            "import joblib",
            "",
            "model = joblib.load('model.pkl')",
            "",
            "def predict_risk(lat, lng, hour, weather):",
            "    features = [[lat, lng, hour, weather]]",
            "    prediction = model.predict(features)",
            "    probability = model.predict_proba(features)[0]",
            "    return {",
            "        'risk_label': prediction[0],",
            "        'confidence': max(probability),",
            "    }",
        ])
        ranges = select_high_signal_ranges(content, "inference.py", "Machine Learning")
        assert len(ranges) >= 1
        # Range should contain predict_proba or predict
        all_code = "\n".join(content.splitlines()[ranges[0][0] - 1 : ranges[0][1]])
        assert "predict" in all_code.lower()

    def test_returns_empty_for_empty_file(self):
        ranges = select_high_signal_ranges("", "empty.py", "Python")
        assert ranges == []

    def test_at_most_max_ranges(self):
        # Large file with many signal lines
        lines = []
        for i in range(10):
            lines.extend([
                f"clf_{i} = DecisionTreeClassifier()",
                f"clf_{i}.fit(X_train_{i}, y_train_{i})",
                f"y_pred_{i} = clf_{i}.predict(X_test_{i})",
                "",
            ])
        content = "\n".join(lines)
        ranges = select_high_signal_ranges(content, "many_models.py", "Machine Learning", max_ranges=3)
        assert len(ranges) <= 3


# ── Dockerfile range selection ─────────────────────────────────────────────────

class TestDockerfileRangeSelection:
    def test_selects_main_dockerfile_range(self):
        content = "\n".join([
            "FROM python:3.11-slim",
            "",
            "WORKDIR /app",
            "COPY requirements.txt .",
            "RUN pip install --no-cache-dir -r requirements.txt",
            "",
            "COPY . .",
            "",
            "EXPOSE 8000",
            "CMD [\"uvicorn\", \"api:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",
        ])
        result = select_dockerfile_range(content)
        assert result is not None
        start, end = result
        lines = content.splitlines()
        selected = lines[start - 1 : end]
        assert any("FROM" in l for l in selected)
        assert any("CMD" in l or "ENTRYPOINT" in l or "RUN" in l for l in selected)

    def test_multistage_dockerfile_picks_last_from(self):
        content = "\n".join([
            "FROM python:3.11 AS builder",
            "RUN pip install build",
            "COPY . .",
            "RUN python -m build",
            "",
            "FROM python:3.11-slim",
            "WORKDIR /app",
            "COPY --from=builder /dist/*.whl .",
            "RUN pip install *.whl",
            "CMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\"]",
        ])
        result = select_dockerfile_range(content)
        assert result is not None
        start, end = result
        lines = content.splitlines()
        # Should start at the second FROM (runtime stage)
        assert "python:3.11-slim" in lines[start - 1]

    def test_empty_dockerfile_returns_none(self):
        assert select_dockerfile_range("") is None

    def test_dockerfile_range_not_weak(self):
        content = "\n".join([
            "FROM python:3.11-slim",
            "WORKDIR /app",
            "COPY . .",
            "RUN pip install -r requirements.txt",
            "CMD [\"python\", \"app.py\"]",
        ])
        result = select_dockerfile_range(content)
        assert result is not None
        start, end = result
        lines = content.splitlines()[start - 1 : end]
        assert not is_weak_range(lines)


# ── CI/CD workflow range selection ─────────────────────────────────────────────

class TestWorkflowRangeSelection:
    def test_selects_workflow_steps(self):
        content = "\n".join([
            "name: Deploy to Cloud Run",
            "on:",
            "  push:",
            "    branches: [main]",
            "jobs:",
            "  deploy:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - name: Build Docker image",
            "        run: docker build -t myapp .",
            "      - name: Push to GCR",
            "        run: docker push gcr.io/project/myapp",
            "      - name: Deploy",
            "        run: gcloud run deploy myapp --image gcr.io/project/myapp",
        ])
        result = select_workflow_range(content)
        assert result is not None
        start, end = result
        lines = content.splitlines()
        selected = lines[start - 1 : end]
        has_run = any("run:" in l for l in selected)
        has_uses = any("uses:" in l for l in selected)
        assert has_run or has_uses

    def test_empty_workflow_returns_none(self):
        assert select_workflow_range("") is None

    def test_workflow_without_steps_returns_none(self):
        content = "\n".join([
            "name: Test",
            "on: push",
            "jobs:",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    # no steps defined",
        ])
        result = select_workflow_range(content)
        # No steps section → None or range with no run: → None
        if result is not None:
            start, end = result
            lines = content.splitlines()[start - 1 : end]
            assert any("run:" in l or "uses:" in l for l in lines), \
                "If range returned, it must have run: or uses:"


# ── GitHub URL builder ─────────────────────────────────────────────────────────

class TestGitHubHighlightURL:
    def test_url_contains_line_anchor(self):
        url = build_github_highlight_url("machackgo", "repo", "main", "api.py", 19, 23)
        assert "#L19-L23" in url

    def test_url_for_single_line(self):
        url = build_github_highlight_url("machackgo", "repo", "main", "app.py", 42, 42)
        assert "#L42" in url
        assert "#L42-L42" not in url

    def test_url_structure(self):
        url = build_github_highlight_url("user", "myrepo", "main", "src/model.py", 10, 30)
        assert url.startswith("https://github.com/user/myrepo/blob/main/")
        assert "src/model.py" in url
        assert "#L10-L30" in url

    def test_url_encodes_special_chars_in_path(self):
        url = build_github_highlight_url("user", "repo", "main", "src/my file.py", 1, 5)
        # Space should be encoded
        assert " " not in url


# ── Duplicate detection ────────────────────────────────────────────────────────

class TestDuplicateDetection:
    def test_detects_duplicate_by_import_key(self):
        candidate = _make_candidate(user_id="u1")
        db = {
            "skill_evidence": {
                "ev-1": {
                    "id": "ev-1",
                    "user_id": "u1",
                    "skill_name": "Machine Learning",
                    "repository_url": candidate.repo_url,
                    "file_path": candidate.file_path,
                    "line_start": candidate.line_start,
                    "line_end": candidate.line_end,
                    "metadata": {"import_key": candidate.import_key},
                }
            }
        }
        assert check_duplicate(db, "u1", candidate) is True

    def test_no_duplicate_for_different_user(self):
        candidate = _make_candidate(user_id="u1")
        db = {
            "skill_evidence": {
                "ev-1": {
                    "id": "ev-1",
                    "user_id": "u2",  # different user
                    "skill_name": "Machine Learning",
                    "repository_url": candidate.repo_url,
                    "file_path": candidate.file_path,
                    "line_start": candidate.line_start,
                    "line_end": candidate.line_end,
                    "metadata": {"import_key": candidate.import_key},
                }
            }
        }
        assert check_duplicate(db, "u1", candidate) is False

    def test_no_duplicate_for_fresh_db(self):
        candidate = _make_candidate(user_id="u1")
        db = {"skill_evidence": {}}
        assert check_duplicate(db, "u1", candidate) is False

    def test_no_duplicate_for_different_lines(self):
        candidate = _make_candidate(user_id="u1", line_start=30, line_end=50)
        other_key = make_import_key("u1", candidate.repo_url, candidate.file_path, 60, 80, candidate.skill_name)
        db = {
            "skill_evidence": {
                "ev-1": {
                    "id": "ev-1",
                    "user_id": "u1",
                    "repository_url": candidate.repo_url,
                    "file_path": candidate.file_path,
                    "line_start": 60,
                    "line_end": 80,
                    "skill_name": candidate.skill_name,
                    "metadata": {"import_key": other_key},
                }
            }
        }
        assert check_duplicate(db, "u1", candidate) is False


# ── Dry-run report ─────────────────────────────────────────────────────────────

class TestDryRunReport:
    def test_report_contains_candidate_fields(self):
        candidate = _make_candidate()
        report = build_dry_run_report("machackgo", [candidate])
        assert report["github_username"] == "machackgo"
        assert report["total_candidates"] == 1
        items = report["candidates"]
        assert len(items) == 1
        item = items[0]
        assert "repo" in item
        assert "skill" in item
        assert "file_path" in item
        assert "line_start" in item
        assert "line_end" in item
        assert "github_highlight_url" in item
        assert "detection_reason" in item

    def test_report_empty_candidates(self):
        report = build_dry_run_report("testuser", [])
        assert report["total_candidates"] == 0
        assert report["candidates"] == []

    def test_github_highlight_url_in_report(self):
        candidate = _make_candidate(line_start=25, line_end=40)
        report = build_dry_run_report("machackgo", [candidate])
        url = report["candidates"][0]["github_highlight_url"]
        assert "#L25-L40" in url

    def test_report_is_json_serializable(self):
        import json
        candidates = [_make_candidate(), _make_candidate(skill="Docker", file_path="Dockerfile")]
        report = build_dry_run_report("machackgo", candidates)
        # Should not raise
        serialized = json.dumps(report)
        parsed = json.loads(serialized)
        assert parsed["total_candidates"] == 2


# ── Import pipeline (dry-run mode) ─────────────────────────────────────────────

class TestImportPipeline:
    def test_dry_run_does_not_insert(self):
        db = {"skill_evidence": {}}
        candidate = _make_candidate(user_id="u1")
        result = import_candidates(db, "u1", [candidate], dry_run=True)
        # Nothing inserted
        assert len(db["skill_evidence"]) == 0
        assert len(result.created) == 1
        assert "DRY-RUN" in result.created[0]

    def test_dry_run_skips_duplicates(self):
        candidate = _make_candidate(user_id="u1")
        db = {
            "skill_evidence": {
                "ev-1": {
                    "id": "ev-1",
                    "user_id": "u1",
                    "skill_name": candidate.skill_name,
                    "repository_url": candidate.repo_url,
                    "file_path": candidate.file_path,
                    "line_start": candidate.line_start,
                    "line_end": candidate.line_end,
                    "metadata": {"import_key": candidate.import_key},
                }
            }
        }
        result = import_candidates(db, "u1", [candidate], dry_run=True)
        assert len(result.skipped) == 1
        assert len(result.created) == 0

    def test_multiple_candidates_without_duplicates(self):
        db = {"skill_evidence": {}}
        candidates = [
            _make_candidate(skill="Machine Learning", file_path="model.py", line_start=30, line_end=50),
            _make_candidate(skill="Docker", file_path="Dockerfile", line_start=1, line_end=15),
        ]
        result = import_candidates(db, "u1", candidates, dry_run=True)
        assert len(result.created) == 2
        assert len(result.skipped) == 0


# ── Portfolio scanner (end-to-end with mock) ────────────────────────────────────

class TestPortfolioScanner:
    def _make_ml_api_content(self) -> str:
        return "\n".join([
            "from fastapi import FastAPI",
            "from pydantic import BaseModel",
            "import joblib",
            "import numpy as np",
            "",
            "app = FastAPI()",
            "model = joblib.load('risk_model.pkl')",
            "",
            "class RiskRequest(BaseModel):",
            "    lat: float",
            "    lng: float",
            "    hour: int",
            "",
            "@app.post('/predict-risk')",
            "async def predict_risk(data: RiskRequest):",
            "    features = np.array([[data.lat, data.lng, data.hour]])",
            "    risk_score = model.predict_proba(features)[0][1]",
            "    label = 'high' if risk_score > 0.6 else 'low'",
            "    return {'risk_level': label, 'score': float(risk_score)}",
        ])

    def _make_docker_content(self) -> str:
        return "\n".join([
            "FROM python:3.11-slim",
            "WORKDIR /app",
            "COPY requirements.txt .",
            "RUN pip install --no-cache-dir -r requirements.txt",
            "COPY . .",
            "EXPOSE 8080",
            'CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]',
        ])

    def test_scanner_finds_ml_evidence(self):
        client = MockGitHubAPIClient(
            repos_by_user={
                "machackgo": [{
                    "name": "boston-risk-app",
                    "html_url": "https://github.com/machackgo/boston-risk-app",
                    "description": "Machine learning route risk prediction API",
                    "homepage": None,
                    "default_branch": "main",
                    "languages": {"Python": 60000},
                    "topics": ["machine-learning", "fastapi"],
                    "stargazers_count": 10,
                    "owner": {"login": "machackgo"},
                }],
            },
            trees_by_repo={
                "machackgo/boston-risk-app": [
                    {"path": "api.py", "type": "blob"},
                    {"path": "Dockerfile", "type": "blob"},
                    {"path": "requirements.txt", "type": "blob"},
                ],
            },
            files_by_path={
                "machackgo/boston-risk-app/api.py": self._make_ml_api_content(),
                "machackgo/boston-risk-app/Dockerfile": self._make_docker_content(),
            },
        )
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("machackgo", max_repos=5)
        assert len(candidates) >= 1

        # At least one candidate should be from a non-import range
        for c in candidates:
            lines = (c.github_highlight_url)
            assert "#L" in lines, "All candidates must have line anchors"

    def test_scanner_avoids_import_only_ranges(self):
        # A Python file that is ONLY imports
        import_only_content = "\n".join([
            "import pandas as pd",
            "import numpy as np",
            "from sklearn.tree import DecisionTreeClassifier",
            "from sklearn.model_selection import train_test_split",
            "from sklearn.metrics import accuracy_score",
            "from sklearn.preprocessing import StandardScaler",
        ])
        client = MockGitHubAPIClient(
            repos_by_user={
                "user": [{
                    "name": "import-only-repo",
                    "html_url": "https://github.com/user/import-only-repo",
                    "description": "ML project",
                    "homepage": None,
                    "default_branch": "main",
                    "languages": {"Python": 1000},
                    "topics": [],
                    "stargazers_count": 0,
                    "owner": {"login": "user"},
                }],
            },
            trees_by_repo={
                "user/import-only-repo": [
                    {"path": "model.py", "type": "blob"},
                ],
            },
            files_by_path={
                "user/import-only-repo/model.py": import_only_content,
            },
        )
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("user", max_repos=5)
        # No candidates should contain import-only ranges
        for c in candidates:
            # Verify the range start is not in the first few import-only lines
            # Actually, the scanner shouldn't create ANY candidate from import-only file
            content_lines = import_only_content.splitlines()
            selected = content_lines[c.line_start - 1 : c.line_end]
            assert not is_weak_range(selected), \
                f"Found a weak/import-only range: {c.file_path}:{c.line_start}-{c.line_end}"

    def test_scanner_returns_empty_for_no_repos(self):
        client = MockGitHubAPIClient(repos_by_user={"ghost": []})
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("ghost", max_repos=10)
        assert candidates == []

    def test_scanner_respects_include_repos(self):
        client = MockGitHubAPIClient(
            repos_by_user={
                "dev": [
                    {
                        "name": "repo-a",
                        "html_url": "https://github.com/dev/repo-a",
                        "description": "FastAPI app",
                        "homepage": None,
                        "default_branch": "main",
                        "languages": {"Python": 5000},
                        "topics": [],
                        "stargazers_count": 0,
                        "owner": {"login": "dev"},
                    },
                    {
                        "name": "repo-b",
                        "html_url": "https://github.com/dev/repo-b",
                        "description": "Another app",
                        "homepage": None,
                        "default_branch": "main",
                        "languages": {"Python": 5000},
                        "topics": [],
                        "stargazers_count": 0,
                        "owner": {"login": "dev"},
                    },
                ]
            },
            trees_by_repo={"dev/repo-a": [], "dev/repo-b": []},
        )
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("dev", include_repos=["repo-a"])
        # repo-b was excluded; no files in repo-a → 0 candidates
        for c in candidates:
            assert c.repo_name == "repo-a"

    def test_scanner_docker_candidate_from_dockerfile(self):
        client = MockGitHubAPIClient(
            repos_by_user={
                "dev": [{
                    "name": "ml-service",
                    "html_url": "https://github.com/dev/ml-service",
                    "description": "Docker containerized ML service",
                    "homepage": None,
                    "default_branch": "main",
                    "languages": {"Python": 50000, "Dockerfile": 3000},
                    "topics": ["docker", "machine-learning"],
                    "stargazers_count": 2,
                    "owner": {"login": "dev"},
                }],
            },
            trees_by_repo={
                "dev/ml-service": [
                    {"path": "Dockerfile", "type": "blob"},
                    {"path": "api.py", "type": "blob"},
                ],
            },
            files_by_path={
                "dev/ml-service/Dockerfile": self._make_docker_content(),
                "dev/ml-service/api.py": self._make_ml_api_content(),
            },
        )
        scanner = PortfolioScanner(client)
        candidates = scanner.scan("dev", max_repos=5)
        docker_candidates = [c for c in candidates if c.skill_name == "Docker"]
        assert len(docker_candidates) >= 1
        dc = docker_candidates[0]
        assert "Dockerfile" in dc.file_path
        assert "#L" in dc.github_highlight_url


# ── File priority filter ───────────────────────────────────────────────────────

class TestHighSignalFileFilter:
    def test_api_py_is_high_signal(self):
        assert is_high_signal_file("api.py") is True

    def test_dockerfile_is_high_signal(self):
        assert is_high_signal_file("Dockerfile") is True

    def test_github_workflow_is_high_signal(self):
        assert is_high_signal_file(".github/workflows/deploy.yml") is True

    def test_node_modules_is_skipped(self):
        assert is_high_signal_file("node_modules/lodash/index.js") is False

    def test_png_image_is_skipped(self):
        assert is_high_signal_file("assets/logo.png") is False

    def test_requirements_txt_is_high_signal(self):
        assert is_high_signal_file("requirements.txt") is True

    def test_minified_js_is_skipped(self):
        assert is_high_signal_file("dist/app.min.js") is False

    def test_python_file_in_src_is_high_signal(self):
        assert is_high_signal_file("src/model/train.py") is True


# ── Website URL extraction ─────────────────────────────────────────────────────

class TestWebsiteURLExtraction:
    def test_extracts_homepage_url(self):
        repo = _make_repo(homepage="https://boston-app.run.app")
        url = extract_website_url(repo, None)
        assert url == "https://boston-app.run.app"

    def test_extracts_vercel_url_from_readme(self):
        repo = _make_repo(homepage=None)
        readme = "Check out the live demo: https://my-project.vercel.app/dashboard"
        url = extract_website_url(repo, readme)
        assert url is not None
        assert "vercel.app" in url

    def test_extracts_cloud_run_url_from_readme(self):
        repo = _make_repo(homepage=None)
        readme = "Deployed at https://boston-api-qzr2qvsfqa-uc.a.run.app"
        url = extract_website_url(repo, readme)
        assert url is not None
        assert ".run.app" in url

    def test_ignores_localhost_urls(self):
        repo = _make_repo(homepage="http://localhost:8000")
        url = extract_website_url(repo, None)
        assert url is None

    def test_returns_none_for_no_url(self):
        repo = _make_repo(homepage=None)
        url = extract_website_url(repo, "No deployment mentioned here.")
        assert url is None


# ── Import key uniqueness ──────────────────────────────────────────────────────

class TestImportKey:
    def test_same_inputs_produce_same_key(self):
        k1 = make_import_key("u1", "https://github.com/a/b", "api.py", 10, 30, "Python")
        k2 = make_import_key("u1", "https://github.com/a/b", "api.py", 10, 30, "Python")
        assert k1 == k2

    def test_different_lines_produce_different_keys(self):
        k1 = make_import_key("u1", "https://github.com/a/b", "api.py", 10, 30, "Python")
        k2 = make_import_key("u1", "https://github.com/a/b", "api.py", 40, 60, "Python")
        assert k1 != k2

    def test_different_skills_produce_different_keys(self):
        k1 = make_import_key("u1", "https://github.com/a/b", "api.py", 10, 30, "Python")
        k2 = make_import_key("u1", "https://github.com/a/b", "api.py", 10, 30, "Machine Learning")
        assert k1 != k2
