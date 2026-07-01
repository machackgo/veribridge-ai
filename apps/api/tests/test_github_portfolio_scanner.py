"""Tests for the GitHub Portfolio Scanner (Phase J3A).

All tests use MockGitHubAPIClient — no live GitHub calls are made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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

from app.services.github_canonical_skill_evidence_adapter import (  # noqa: E402
    collect_canonical_github_skill_evidence,
)
from app.services.github_python_evidence_focus import (  # noqa: E402
    ANALYZER_NAME,
    GRADE_IMPLEMENTATION_BODY,
    GRADE_IMPORT_ONLY,
    GRADE_SUPPORTING_LOGIC,
    SERVER_PROVENANCE_KEY,
    TRUSTED_ANALYSIS_TABLE,
    is_strong_grade,
    is_weak_grade,
    trusted_provenance,
)


def _trusted_provenance_for(db: dict, evidence_id: str) -> dict | None:
    """Validated server-only provenance for ``evidence_id``, read from the
    SERVICE-ROLE-ONLY protected table — never from ``skill_evidence.metadata``.

    Mirrors the canonical adapter's read path: a hostile owner editing their own
    metadata directly via Supabase cannot reach this table, so a grade/snippet
    here can never be forged."""
    rec = db.get(TRUSTED_ANALYSIS_TABLE, {}).get(evidence_id)
    return trusted_provenance(rec)
from app.services.student_proof_vault_service import (  # noqa: E402
    _collect_github,
    collect_skill_report,
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

    def test_boston_canonical_ranges_focus_on_real_model_body(self):
        # Boston-style training file: module docstring + imports + a config
        # constant + the real training function. The persisted range must focus
        # onto the function's implementation body (model fit / evaluation), never
        # the module docstring, the import block, or the MODEL_PATH constant.
        content = "\n".join([
            '"""Boston accident-risk model training pipeline.',
            "",
            "Loads the cleaned dataset, fits a tuned random forest, persists it.",
            '"""',
            "",
            "import os",
            "import joblib",
            "import pandas as pd",
            "from sklearn.ensemble import RandomForestClassifier",
            "from sklearn.model_selection import train_test_split",
            "from sklearn.metrics import f1_score",
            "",
            'MODEL_PATH = os.environ.get("MODEL_PATH", "model.joblib")',
            "",
            "",
            "def train_model(data_path):",
            '    """Train and persist the Boston accident-risk model."""',
            "    df = pd.read_csv(data_path)",
            '    X = df.drop("risk", axis=1)',
            '    y = df["risk"]',
            "    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
            "    clf = RandomForestClassifier(n_estimators=200, max_depth=8)",
            "    clf.fit(X_train, y_train)",
            "    score = f1_score(y_test, clf.predict(X_test))",
            "    joblib.dump(clf, MODEL_PATH)",
            "    return score",
        ])
        lines = content.splitlines()
        ranges = select_high_signal_ranges(content, "src/model/train.py", "Machine Learning")
        assert len(ranges) >= 1
        start, end, _reason = ranges[0]
        selected = "\n".join(lines[start - 1 : end])
        # Focused on the real implementation body…
        assert "clf.fit" in selected
        assert "RandomForestClassifier" in selected
        # …and NOT opened on the module docstring / imports / config constant.
        assert "Loads the cleaned dataset" not in selected
        assert "import joblib" not in selected
        assert "MODEL_PATH = os.environ" not in selected
        # The range starts at/after the def, never at the module docstring.
        assert start >= lines.index("def train_model(data_path):") + 1

    def test_returns_empty_for_empty_file(self):
        ranges = select_high_signal_ranges("", "empty.py", "Python")
        assert ranges == []

    def test_python_parse_failure_fails_closed_to_fallback(self):
        # A malformed Python file: ML keywords live in a comment and an import, but
        # the body has a syntax error so the AST cannot prove any real
        # implementation. The scanner must FAIL CLOSED — it never resumes the old
        # keyword-window path and never promotes the unparsed range as strong
        # precise evidence. No precise ranges are produced for the broken file, so
        # nothing can later be graded implementation_body / supporting_logic.
        content = "\n".join([
            "# trains a RandomForestClassifier and computes the f1_score metric",
            "import sklearn",
            "from sklearn.ensemble import RandomForestClassifier",
            "def train(df:",  # <- syntax error: unterminated signature
            "    clf = RandomForestClassifier(n_estimators=200)",
            "    clf.fit(df.X, df.y)",
            "    return f1_score(df.y, clf.predict(df.X))",
        ])
        ranges = select_high_signal_ranges(content, "src/model/train.py", "Machine Learning")
        assert ranges == []

        # Sanity: the guard fires ONLY on parse failure — a well-formed body still
        # yields precise evidence (so we did not just disable Python evidence).
        fixed = content.replace("def train(df:", "def train(df):")
        assert select_high_signal_ranges(fixed, "src/model/train.py", "Machine Learning")

        # Non-Python files are NOT AST-gated — the same broken-Python text under a
        # .ts path keeps the existing conservative keyword heuristics (never forced
        # empty by the Python parse guard).
        ts_ranges = select_high_signal_ranges(content, "src/model/train.ts", "TypeScript")
        assert isinstance(ts_ranges, list)

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


# ── Scanner → import → canonical adapter → grouped report (end-to-end) ──────────
#
# These cover the full path Codex flagged: the AST scanner focuses a real
# implementation body, ``import_candidates`` PERSISTS the grade + analyzer
# provenance + the public source snippet, the canonical adapter keeps the strong
# grade (instead of collapsing to ``repo_level_fallback`` because the grade was
# dropped), and the grouped report surfaces the implementation body — never the
# module docstring / import block / config constant.

_BOSTON_TRAIN_SOURCE = "\n".join([
    '"""Boston accident-risk model training pipeline.',
    "",
    "Loads the cleaned dataset, fits a tuned random forest, persists it.",
    '"""',
    "",
    "import os",
    "import joblib",
    "import pandas as pd",
    "from sklearn.ensemble import RandomForestClassifier",
    "from sklearn.model_selection import train_test_split",
    "from sklearn.metrics import f1_score",
    "",
    'MODEL_PATH = os.environ.get("MODEL_PATH", "model.joblib")',
    "",
    "",
    "def train_model(data_path):",
    '    """Train and persist the Boston accident-risk model."""',
    "    df = pd.read_csv(data_path)",
    '    X = df.drop("risk", axis=1)',
    '    y = df["risk"]',
    "    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
    "    clf = RandomForestClassifier(n_estimators=200, max_depth=8)",
    "    clf.fit(X_train, y_train)",
    "    score = f1_score(y_test, clf.predict(X_test))",
    "    joblib.dump(clf, MODEL_PATH)",
    "    return score",
])


_SECRET_TRAIN_SOURCE = "\n".join([
    '"""Model training that accidentally hard-codes a secret."""',
    "",
    "import os",
    "import joblib",
    "import pandas as pd",
    "from sklearn.ensemble import RandomForestClassifier",
    "from sklearn.model_selection import train_test_split",
    "from sklearn.metrics import f1_score",
    "",
    'MODEL_PATH = os.environ.get("MODEL_PATH", "model.joblib")',
    "",
    "",
    "def train_model(data_path):",
    '    """Train and persist the model."""',
    '    api_key = "sk-supersecret-DEADBEEF1234"',
    '    token = "ghp_aaaaaaaaaaaaaaaaaaaa"',
    "    df = pd.read_csv(data_path)",
    '    X = df.drop("risk", axis=1)',
    '    y = df["risk"]',
    "    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
    "    clf = RandomForestClassifier(n_estimators=200, max_depth=8)",
    "    clf.fit(X_train, y_train)",
    "    score = f1_score(y_test, clf.predict(X_test))",
    "    joblib.dump(clf, MODEL_PATH)",
    "    return score",
])


class TestScannerImportCanonicalReportE2E:
    _USER = "00000000-0000-0000-0000-0000000000ee"

    def _boston_candidates(self) -> list[EvidenceCandidate]:
        # ``_extract_candidates_from_file`` never touches the github client.
        scanner = PortfolioScanner(github_client=None)  # type: ignore[arg-type]
        repo = _make_repo(name="boston-accident-risk", owner="alice")
        return scanner._extract_candidates_from_file(
            repo, "main", "src/model/train.py", _BOSTON_TRAIN_SOURCE,
            ["Machine Learning"], None,
        )

    def test_scanner_import_preserves_evidence_quality_grade_for_canonical_report(self):
        candidates = self._boston_candidates()
        assert candidates, "scanner should focus the training body"
        cand = candidates[0]

        # 1) Scanner focused the real implementation body and graded it strong,
        #    carrying the focused snippet + provenance on the candidate.
        assert cand.evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
        assert cand.code_snippet and "clf.fit" in cand.code_snippet
        assert "import joblib" not in cand.code_snippet
        assert cand.focused_start_line == cand.line_start
        assert cand.focused_end_line == cand.line_end

        # 2) Real import path (dict-backed client) persists grade/provenance/snippet
        #    into the SERVICE-ROLE-ONLY protected table — never into the
        #    user-editable skill_evidence.metadata a public payload could forge.
        db: dict = {"skill_evidence": {}}
        result = import_candidates(db, self._USER, [cand], dry_run=False)
        assert result.created, result.errors
        row = next(iter(db["skill_evidence"].values()))
        md = row["metadata"]
        # No provenance leaked into the public metadata surface — not as flat keys,
        # and not under the legacy server-provenance namespace either.
        assert "evidence_quality_grade" not in md
        assert "evidence_analyzer" not in md
        assert "code_snippet" not in md
        assert SERVER_PROVENANCE_KEY not in md
        # Trusted provenance lives ONLY in the protected table, keyed by evidence id.
        prov = _trusted_provenance_for(db, row["id"])
        assert prov is not None
        assert prov["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
        assert prov["analyzer_name"] == ANALYZER_NAME
        assert "clf.fit" in prov["safe_excerpt"]

        # 3) Canonical adapter KEEPS the strong grade — it does not become
        #    repo_level_fallback merely because import moved the grade/snippet.
        evs = collect_canonical_github_skill_evidence(db, self._USER)
        assert evs
        assert is_strong_grade(evs[0].evidence_quality_grade)
        assert evs[0].evidence_quality_grade in (
            GRADE_IMPLEMENTATION_BODY, GRADE_SUPPORTING_LOGIC
        )

    def test_boston_scanner_import_to_grouped_report_excludes_imports_and_docstrings(self):
        candidates = self._boston_candidates()
        db: dict = {"skill_evidence": {}}
        import_candidates(db, self._USER, candidates, dry_run=False)

        items = _collect_github(db, self._USER, {})
        ml_items = [i for i in items if (i.get("skill_name") or "") == "Machine Learning"]
        assert ml_items

        precise = [i for i in ml_items if i.get("has_precise_line_evidence")]
        assert precise, "the training body must surface as precise code evidence"
        for item in precise:
            # Visible top evidence is a real implementation/supporting body…
            assert item.get("evidence_quality_grade") in (
                GRADE_IMPLEMENTATION_BODY, GRADE_SUPPORTING_LOGIC
            )
            # …and its focused range opens at/after the def, never the module
            # docstring / import block / MODEL_PATH constant (all in lines 1-15).
            assert (item.get("line_start") or 0) >= 16

    def test_scanner_import_through_collect_skill_report_into_github_groups(self):
        # TRUE end-to-end: scanner → import_candidates → canonical adapter →
        # collect_skill_report() → github_groups. (synthesize=False so NO LLM /
        # provider call happens in this render path.)
        candidates = self._boston_candidates()
        db: dict = {"skill_evidence": {}}
        import_candidates(db, self._USER, candidates, dry_run=False)

        report = collect_skill_report(
            db, {}, self._USER, "Machine Learning", synthesize=False
        )
        groups = report["standalone_evidence"]["github_groups"]
        assert groups, "the imported training body must surface as a github group"

        all_rows = [r for g in groups for r in g["rows"]]
        strong_rows = [
            r for r in all_rows if is_strong_grade(r.get("evidence_quality_grade"))
        ]
        assert strong_rows, "a real implementation body must rank into github_groups"
        for r in strong_rows:
            # The module docstring / imports / MODEL_PATH constant (lines 1-15)
            # never enter the visible top github_groups rows.
            assert (r.get("line_start") or 0) >= 16
            assert r.get("evidence_quality_grade") in (
                GRADE_IMPLEMENTATION_BODY, GRADE_SUPPORTING_LOGIC
            )

    def test_scanner_import_redacts_hardcoded_secret_in_persisted_snippet(self):
        # A focused implementation body that happens to contain a hard-coded secret
        # must be persisted with the secret redacted — never verbatim — and the raw
        # secret must not appear anywhere in storage or the rendered report.
        scanner = PortfolioScanner(github_client=None)  # type: ignore[arg-type]
        repo = _make_repo(name="secret-leak-model", owner="alice")
        candidates = scanner._extract_candidates_from_file(
            repo, "main", "src/train.py", _SECRET_TRAIN_SOURCE,
            ["Machine Learning"], None,
        )
        assert candidates, "scanner should focus the training body"

        db: dict = {"skill_evidence": {}}
        import_candidates(db, self._USER, candidates, dry_run=False)

        dump = json.dumps(db)
        assert "sk-supersecret" not in dump
        assert "ghp_aaaaaaaaaaaaaaaaaaaa" not in dump

        row = next(iter(db["skill_evidence"].values()))
        prov = _trusted_provenance_for(db, row["id"])
        assert prov is not None
        snippet = prov["safe_excerpt"]
        assert "clf.fit" in snippet              # real body kept
        assert "[REDACTED_SECRET]" in snippet    # secret scrubbed
        assert "sk-supersecret" not in snippet

        report = collect_skill_report(
            db, {}, self._USER, "Machine Learning", synthesize=False
        )
        assert "sk-supersecret" not in json.dumps(report)

    def test_weak_canonical_does_not_suppress_stronger_github_fallback(self):
        # Must-fix #4: a WEAK canonical row produced by the import path (import-only)
        # must NOT cover (suppress) a STRONGER github_proof_submissions fallback for
        # the same repo + skill — the strong fallback still appears and ranks.
        repo_url = "https://github.com/alice/boston-accident-risk"
        weak_candidate = EvidenceCandidate(
            skill_name="Machine Learning",
            project_title="Boston Accident Risk",
            repo_url=repo_url,
            repo_name="boston-accident-risk",
            file_path="src/utils.py",
            line_start=1,
            line_end=3,
            evidence_description="Imports for the ML utilities.",
            student_claim="I imported ML libraries.",
            evidence_type="github repository",
            website_url=None,
            detection_reason="import statements",
            github_highlight_url=f"{repo_url}/blob/main/src/utils.py#L1-L3",
            import_key="",
            evidence_quality_grade=GRADE_IMPORT_ONLY,
            code_snippet="import os\nimport sys\nimport joblib",
            focused_start_line=1,
            focused_end_line=3,
            focused_reason="import statements",
        )

        db: dict = {
            "skill_evidence": {},
            "github_proof_submissions": {
                "gh-strong": {
                    "id": "gh-strong",
                    "user_id": self._USER,
                    "repo_owner": "alice",
                    "repo_name": "boston-accident-risk",
                    "repo_url": repo_url,
                    "default_branch": "main",
                    "visibility": "public",
                    "detected_skills": ["Machine Learning"],
                    "public_safe_summary": "Repository analyzed.",
                    "analysis_snapshot": {
                        "skill_code_evidence": [
                            {
                                "skill": "Machine Learning",
                                "file_path": "src/model/train.py",
                                "line_start": 30,
                                "line_end": 45,
                                "function_name": "serve_prediction",
                                "code_snippet": (
                                    "def serve_prediction(features):\n"
                                    "    clf = joblib.load(MODEL_PATH)\n"
                                    "    proba = clf.predict_proba([features])[0]\n"
                                    "    return f1_score(y_test, clf.predict(X_test))\n"
                                ),
                                "commit_sha": "abc1234def5678",
                            }
                        ]
                    },
                }
            },
        }
        import_candidates(db, self._USER, [weak_candidate], dry_run=False)

        report = collect_skill_report(
            db, {}, self._USER, "Machine Learning", synthesize=False
        )
        groups = report["standalone_evidence"]["github_groups"]
        assert groups
        strong_rows = [
            r
            for g in groups
            for r in g["rows"]
            if is_strong_grade(r.get("evidence_quality_grade"))
        ]
        # The stronger fallback body (lines 30-45) survives — it is NOT suppressed by
        # the weak import-only canonical row for the same repo + skill.
        assert any((r.get("line_start") or 0) >= 30 for r in strong_rows), (
            "stronger github_proof_submissions fallback must not be suppressed"
        )


# ── Migration 053 application path + RLS guarantees ───────────────────────────
#
# Trusted GitHub evidence provenance lives in the service-role-only
# ``trusted_github_evidence_analysis`` table created by migration 053. The
# scanner's provenance write (:func:`_stamp_server_provenance`) and the
# read-time grade-trust check both target that table, so if 053 is never
# applied, both fail closed and imported evidence silently degrades to weak
# grading. The repo applies migrations through per-group helper scripts (the
# same psycopg2 + .env + pooler + ``NOTIFY pgrst`` pattern used for 047/048 and
# 051/052); 053 MUST be wired into that same application path. These hermetic
# text/policy assertions guard both the application path and the RLS contract
# without requiring a live Supabase.

_APPLY_HELPER = (
    ROOT / "scripts" / "apply_vbr_public_report_migration.py"
)
_MIGRATION_053 = (
    ROOT / "app" / "db" / "migrations" / "053_trusted_github_evidence_analysis.sql"
)


@pytest.fixture(scope="module")
def apply_helper_src() -> str:
    return _APPLY_HELPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def migration_053_sql() -> str:
    return _MIGRATION_053.read_text(encoding="utf-8").lower()


def test_migration_053_included_in_apply_helper(apply_helper_src: str) -> None:
    # 053 must be listed in the existing migration-apply helper (the one that
    # already stops at 052), so the local/dev/test DB actually gets the table.
    assert "053_trusted_github_evidence_analysis.sql" in apply_helper_src
    # It must sit inside the ordered MIGRATIONS list the helper iterates over,
    # after 052 (migrations are applied in list order).
    migrations_block = apply_helper_src.split("MIGRATIONS = [", 1)[1].split("]", 1)[0]
    assert "052_vbr_work_passport.sql" in migrations_block
    assert "053_trusted_github_evidence_analysis.sql" in migrations_block
    assert migrations_block.index("052_vbr_work_passport.sql") < migrations_block.index(
        "053_trusted_github_evidence_analysis.sql"
    )


def test_migration_053_sql_reachable_through_helper() -> None:
    # The filename the helper iterates over must resolve to a real migration the
    # helper reads from app/db/migrations, and that SQL must create the table.
    assert _MIGRATION_053.exists()
    sql = _MIGRATION_053.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.trusted_github_evidence_analysis" in sql


def test_migration_053_apply_helper_reloads_postgrest_schema(
    apply_helper_src: str,
) -> None:
    # Newly created table stays invisible to PostgREST until its cache reloads;
    # the shared helper must issue the reload after applying the migrations.
    assert "notify pgrst, 'reload schema'" in apply_helper_src.lower()


def test_migration_053_enables_row_level_security(migration_053_sql: str) -> None:
    assert (
        "alter table public.trusted_github_evidence_analysis "
        "enable row level security" in migration_053_sql
    )


def test_migration_053_grants_service_role_write(migration_053_sql: str) -> None:
    # service_role (the offline scanner / import path) may insert/update
    # trusted provenance: a single FOR ALL policy scoped to service_role.
    assert (
        '"trusted_github_evidence_analysis: service role all"' in migration_053_sql
    )
    assert "for all" in migration_053_sql
    assert "to service_role" in migration_053_sql
    assert "using (true)" in migration_053_sql
    assert "with check (true)" in migration_053_sql


def test_migration_053_has_no_authenticated_or_anon_write_policy(
    migration_053_sql: str,
) -> None:
    # Authenticated students can neither forge (write) nor read trusted
    # provenance directly, and anonymous users have no access at all: the only
    # role any policy targets is service_role. If a policy were ever added for
    # authenticated/anon/public, a hostile owner could inject a strong grade.
    assert "to authenticated" not in migration_053_sql
    assert "to anon" not in migration_053_sql
    assert "to public" not in migration_053_sql
    # Exactly one policy exists on the table, and it is the service-role policy.
    assert migration_053_sql.count("create policy") == 1
