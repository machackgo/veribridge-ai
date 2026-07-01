"""Tests for the canonical GitHub skill-evidence extractor.

This is the single, shared filter the VBR Project Report and the Work Passport
Skill Report both use to turn stored ``analysis_snapshot.skill_code_evidence``
into safe, strength-ranked evidence. The contract:

* strong code (functions / classes / endpoints / model code) keeps its exact
  file/line/function/snippet and a safe ``…#L`` link;
* weak code (imports, sys.path/setup, package/README/metadata, notebook
  markdown/prose) is downgraded and never surfaced as primary line proof;
* GitHub line URLs prefer the pinned commit SHA, and a ``#L`` anchor is only ever
  built for a valid line range — line numbers are never fabricated.
"""

from __future__ import annotations

from app.services.github_skill_evidence_service import (
    extract_github_skill_evidence,
    focus_snippet_on_implementation,
    implementation_quality_rank,
    is_github_evidence_related_to_skill,
    is_ml_skill,
    skill_profile,
)


def _gh_row(evidence: list[dict], **overrides) -> dict:
    row = {
        "id": "gh-1",
        "repo_owner": "octocat",
        "repo_name": "Hello-World",
        "repo_url": "https://github.com/octocat/Hello-World",
        "default_branch": "main",
        "visibility": "public",
        "detected_skills": [],
        "public_safe_summary": "Repository analyzed.",
        "analysis_snapshot": {"raw_dump": "should-never-leak", "skill_code_evidence": evidence},
    }
    row.update(overrides)
    return row


# ── Strong evidence is preserved with exact locators + link ──────────────────


def test_strong_function_evidence_keeps_file_line_function_snippet_link() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/model/train.py",
                    "line_start": 10,
                    "line_end": 24,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                    "commit_sha": "abc1234def5678",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.evidence_strength == "strong"
    assert ev.file_path == "src/model/train.py"
    assert ev.line_start == 10 and ev.line_end == 24
    assert ev.function_name == "train_model"
    assert ev.evidence_kind == "function"
    assert ev.code_snippet and "train_model" in ev.code_snippet


def test_builds_github_line_url_preferring_commit_sha() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 252,
                    "line_end": 255,
                    "code_snippet": '@app.post("/predict")\ndef predict(req):\n    return model.predict(req)',
                    "commit_sha": "deadbeef1234",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.github_url == "https://github.com/octocat/Hello-World/blob/deadbeef1234/api.py#L252-L255"
    assert ev.endpoint_path == "/predict"
    assert ev.evidence_kind == "endpoint"


def test_falls_back_to_branch_when_no_commit_sha() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 5,
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.github_url == "https://github.com/octocat/Hello-World/blob/main/api.py#L5"


# ── Weak evidence is downgraded ──────────────────────────────────────────────


def test_import_only_snippet_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io\nimport time",
                }
            ]
        )
    )
    assert result.best_strong_for_skill("Python") is None
    assert "Python" in result.weak_only_skill_names
    weak = result.weak_items[0]
    assert weak.evidence_strength == "weak"
    # Weak snippets are never carried as displayable code.
    assert weak.code_snippet is None


def test_sys_path_setup_snippet_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Google Cloud",
                    "file_path": "src/predict/predictor.py",
                    "line_start": 1,
                    "line_end": 3,
                    "code_snippet": (
                        "# Ensure repo root is on sys.path so src.predict.predictor is importable\n"
                        "sys.path.insert(0, str(Path(__file__).resolve().parents[2]))"
                    ),
                }
            ]
        )
    )
    assert result.best_strong_for_skill("Google Cloud") is None
    assert "Google Cloud" in result.weak_only_skill_names


def test_package_metadata_and_notebook_markdown_classified_weak() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "requirements.txt",
                    "line_start": 1,
                    "code_snippet": "flask==2.0.1\nnumpy==1.26.0",
                },
                {
                    "skill": "API Development",
                    "file_path": "notebooks/overview.ipynb",
                    "line_start": 1,
                    "code_snippet": "## Project Overview\n- This notebook describes the API design\nhttps://example.com",
                },
            ]
        )
    )
    assert result.strong_items == []
    assert "Python" in result.weak_only_skill_names
    assert "API Development" in result.weak_only_skill_names


# ── Never fabricate line URLs / handle missing lines ─────────────────────────


def test_no_line_url_for_weak_evidence() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "code_snippet": "import sys",
                }
            ]
        )
    )
    assert all(i.github_url is None for i in result.items)


def test_strong_evidence_without_lines_has_no_line_anchor() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "code_snippet": "def predict(req):\n    return model.predict(req)",
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.line_start is None
    assert ev.github_url and "#L" not in ev.github_url


# ── Strong ranked above weak for the same skill ──────────────────────────────


def test_prefers_strong_function_over_weak_import_for_same_skill() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Python",
                    "file_path": "api.py",
                    "line_start": 6,
                    "line_end": 9,
                    "code_snippet": "import sys\nimport io",
                },
                {
                    "skill": "Python",
                    "file_path": "src/train.py",
                    "line_start": 40,
                    "line_end": 44,
                    "function_name": "train_model",
                    "code_snippet": "def train_model(df):\n    return clf.fit(df)",
                },
            ]
        )
    )
    ev = result.best_strong_for_skill("Python")
    assert ev is not None
    assert ev.function_name == "train_model"
    assert ev.evidence_strength == "strong"
    # Python now has strong evidence, so it is NOT weak-only.
    assert "Python" not in result.weak_only_skill_names


# ── Private repos never expose a public link or snippet ──────────────────────


def test_private_repo_hides_link_and_snippet() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "api.py",
                    "line_start": 1,
                    "function_name": "predict",
                    "code_snippet": "def predict(req): ...",
                }
            ],
            visibility="private",
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.public_safe is False
    assert ev.github_url is None
    assert ev.code_snippet is None
    # The locator path/line is still known (just not publicly linkable).
    assert ev.file_path == "api.py"


def test_raw_snapshot_never_echoed() -> None:
    result = extract_github_skill_evidence(
        _gh_row([{"skill": "Python", "file_path": "api.py", "line_start": 1, "code_snippet": "import sys"}])
    )
    assert "should-never-leak" not in str([i.to_dict() for i in result.items])


# ── Canonical skill_evidence adapter (old Profile & Proof engine rows) ─────────

from app.services.github_canonical_skill_evidence_adapter import (  # noqa: E402
    collect_canonical_github_skill_evidence,
    repo_identity,
)

_USER = "00000000-0000-0000-0000-000000000042"


def _seed_skill_evidence_row(store: dict, **overrides) -> str:
    eid = overrides.pop("id", "se-1")
    row = {
        "id": eid,
        "user_id": _USER,
        "skill_name": "API Development",
        "evidence_type": "github repository",
        "repository_url": "https://github.com/octocat/Hello-World",
        "file_path": "app/api/routes.py",
        "line_start": 10,
        "line_end": 20,
        "evidence_description": "API route handler.",
        "proof_visibility": "public",
        "metadata": {
            "github_highlight_url": "https://github.com/octocat/Hello-World/blob/main/app/api/routes.py#L10-L20",
            "selection_reason": "API endpoint decorator",
            "evidence_title": "Boston Rerouting",
            "secret_token": "should-never-leak",
        },
    }
    row.update(overrides)
    store.setdefault("skill_evidence", {})[eid] = row
    return eid


def test_repo_identity_normalizes_urls_and_full_names() -> None:
    assert repo_identity("https://github.com/Octocat/Hello-World") == "octocat/hello-world"
    assert repo_identity("git@github.com:octocat/Hello-World.git") == "octocat/hello-world"
    assert repo_identity("octocat/Hello-World") == "octocat/hello-world"
    assert repo_identity("") == ""
    assert repo_identity("not a repo") == ""


def test_adapter_reads_precise_canonical_github_evidence() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store)
    items = collect_canonical_github_skill_evidence(store, _USER)
    assert len(items) == 1
    ev = items[0]
    assert ev.source == "skill_evidence"
    assert ev.display_mode == "code_line"
    assert ev.has_precise_line_evidence is True
    assert ev.file_path == "app/api/routes.py"
    assert ev.line_start == 10 and ev.line_end == 20
    assert ev.selection_reason == "API endpoint decorator"
    assert ev.github_line_url and "#L10-L20" in ev.github_line_url
    assert ev.repo_id == "octocat/hello-world"
    assert "should-never-leak" not in str(ev.to_dict())


def test_adapter_filters_by_skill_and_skips_non_github_rows() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store, id="se-gh", skill_name="API Development")
    # An extension-proof row (no github, no file_path) must be ignored.
    _seed_skill_evidence_row(
        store,
        id="se-ext",
        skill_name="React",
        evidence_type="private website (extension proof)",
        repository_url=None,
        file_path=None,
    )
    assert [e.skill_name for e in collect_canonical_github_skill_evidence(store, _USER)] == [
        "API Development"
    ]
    assert collect_canonical_github_skill_evidence(store, _USER, "react") == []


def test_adapter_hides_link_for_private_proof() -> None:
    store: dict = {}
    _seed_skill_evidence_row(store, proof_visibility="private")
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.public_safe is False
    assert ev.github_line_url is None
    # The locator path/line is still known (just not publicly linkable).
    assert ev.file_path == "app/api/routes.py"
    assert ev.to_dict()["repo_url"] is None


# ── must-fix: absolute/local paths never reach public evidence ────────────────

_HOSTILE_FILE_PATHS = [
    "/Users/alice/private/secret.py",
    "/etc/passwd",
    "C:\\Users\\alice\\private\\secret.py",
    "C:/Users/alice/private/secret.py",
    "file:///Users/alice/private/secret.py",
    "../secrets.py",
    "..\\secrets.py",
]


def test_extractor_drops_absolute_and_local_file_paths() -> None:
    # Service path (github_skill_evidence_service line ~489): a row whose
    # file_path is absolute/local/Windows/file:// must be dropped, not
    # lstrip("/")-ed into a fake repo-relative locator.
    evidence = [
        {"skill": f"Skill {i}", "file_path": p, "line_start": 1, "line_end": 2}
        for i, p in enumerate(_HOSTILE_FILE_PATHS)
    ]
    evidence.append({"skill": "Safe", "file_path": "apps/api/main.py", "line_start": 1, "line_end": 2})
    result = extract_github_skill_evidence(_gh_row(evidence))
    paths = [item.file_path for item in result.items]
    assert paths == ["apps/api/main.py"]
    blob = "\n".join(filter(None, [item.github_url for item in result.items] + paths))
    for leaked in ("Users/alice", "etc/passwd", "secret.py", ".."):
        assert leaked not in blob


def test_adapter_drops_absolute_and_local_file_paths() -> None:
    # Adapter path (github_canonical_skill_evidence_adapter line ~197): same
    # rejection from the skill_evidence-row source.
    store: dict = {}
    for i, p in enumerate(_HOSTILE_FILE_PATHS):
        _seed_skill_evidence_row(store, id=f"se-bad-{i}", file_path=p, metadata={})
    items = collect_canonical_github_skill_evidence(store, _USER)
    assert items == []



# ── ML skills prefer real ML-pipeline code over generic lines ────────────────


def test_ml_skill_prefers_pipeline_code_over_generic_line() -> None:
    # Two strong code locations for the same ML skill: one is a generic helper,
    # the other is real model training/eval. The ML-pipeline code must rank first
    # so best_strong_for_skill surfaces the meaningful evidence.
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/utils/helpers.py",
                    "line_start": 3,
                    "line_end": 6,
                    "function_name": "format_row",
                    "code_snippet": "def format_row(row):\n    return {k: str(v) for k, v in row.items()}",
                },
                {
                    "skill": "Machine Learning",
                    "file_path": "src/model/train.py",
                    "line_start": 40,
                    "line_end": 55,
                    "function_name": "train_model",
                    "code_snippet": (
                        "def train_model(X, y):\n"
                        "    clf = RandomForestClassifier()\n"
                        "    clf.fit(X, y)\n"
                        "    return f1_score(y, clf.predict(X))"
                    ),
                },
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    assert ev.file_path == "src/model/train.py"
    assert ev.function_name == "train_model"


def test_ml_ranking_does_not_reorder_non_ml_skill() -> None:
    # For a non-ML skill the ML tie-breaker is neutral: ordering stays driven by
    # strength + line presence, exactly as before.
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Backend Development",
                    "file_path": "api/routes.py",
                    "line_start": 10,
                    "line_end": 14,
                    "function_name": "list_users",
                    "code_snippet": "def list_users():\n    return db.query(User).all()",
                },
                {
                    "skill": "Backend Development",
                    "file_path": "api/health.py",
                    "line_start": 2,
                    "line_end": 3,
                    "function_name": "healthcheck",
                    "code_snippet": "def healthcheck():\n    return {'ok': True}",
                },
            ]
        )
    )
    order = [i.file_path for i in result.strong_for_skill("Backend Development")]
    assert order == ["api/routes.py", "api/health.py"]


# ── conservative GitHub evidence skill relation ───────────────────────────────


def test_is_ml_skill_recognizes_ml_family() -> None:
    assert is_ml_skill("Machine Learning")
    assert is_ml_skill("Machine Learning Engineering")
    assert is_ml_skill("Deep Learning")
    assert not is_ml_skill("Python")
    assert not is_ml_skill("Backend Development")


def test_relation_rejects_non_ml_target_skill() -> None:
    # The relation layer only ever broadens ML target skills — never others.
    assert not is_github_evidence_related_to_skill(
        "Python",
        evidence_skill="Machine Learning",
        file_path="src/train.py",
        mapping_reason="model training",
    )


def test_relation_admits_ml_engineering_row() -> None:
    # A Machine Learning Engineering row is in-family for a Machine Learning report.
    assert is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="Machine Learning Engineering",
        file_path="serving/main.py",
        mapping_reason="model serving endpoint",
    )


def test_relation_admits_ml_specific_python_rows() -> None:
    # Python-tagged rows with ML-specific structured evidence reasons are admitted.
    cases = [
        ("src/model/train.py", "model instantiation"),
        ("src/model/train.py", "evaluation metrics"),
        ("serving/main.py", "prediction/inference endpoint"),
        ("scripts/pipeline_retrain.py", "pipeline retrain"),
        ("scripts/vertex_deploy.py", "prediction/inference"),
    ]
    for file_path, reason in cases:
        assert is_github_evidence_related_to_skill(
            "Machine Learning",
            evidence_skill="Python",
            file_path=file_path,
            mapping_reason=reason,
        ), f"expected related: {file_path} / {reason}"


def test_relation_rejects_generic_python_rows() -> None:
    # Generic plumbing tagged Python never joins Machine Learning.
    cases = [
        ("src/__init__.py", "import statements"),
        ("src/config.py", "configuration constants"),
        ("src/utils/helpers.py", "generic helper"),
        ("src/logging_setup.py", "logging setup"),
        ("src/settings.py", "environment variable loading"),
    ]
    for file_path, reason in cases:
        assert not is_github_evidence_related_to_skill(
            "Machine Learning",
            evidence_skill="Python",
            file_path=file_path,
            mapping_reason=reason,
        ), f"expected rejected: {file_path} / {reason}"


def test_relation_rejects_python_import_even_in_ml_file() -> None:
    # An import line tagged Python is plumbing even when it lives in train.py —
    # rejected unless the code itself is a real ML-pipeline call.
    assert not is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="Python",
        file_path="src/model/train.py",
        mapping_reason="import sklearn",
        code_snippet="import sklearn\nimport numpy as np",
    )
    # But a genuine ML-pipeline call in the snippet overrides a generic reason.
    assert is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="Python",
        file_path="src/model/train.py",
        mapping_reason="helper",
        code_snippet="clf = RandomForestClassifier()\nclf.fit(X, y)",
    )


# ── deterministic implementation-quality scoring (all skills) ─────────────────


def test_skill_profile_maps_families() -> None:
    assert skill_profile("Machine Learning") == "ml"
    assert skill_profile("Machine Learning Engineering") == "mle"
    assert skill_profile("MLOps") == "mle"
    assert skill_profile("API Development") == "api"
    assert skill_profile("Backend Development") == "api"
    assert skill_profile("React") == "react"
    assert skill_profile("Frontend Engineering") == "react"
    assert skill_profile("Security Engineering") == "security"
    assert skill_profile("Authentication & Authorization") == "security"
    assert skill_profile("Cloud / DevOps") == "devops"
    # An unprofiled skill is ranked purely on generic implementation signals.
    assert skill_profile("Technical Writing") == ""


def _rank(skill: str, code: str, *, file_path: str = "app.py", symbol: str | None = None) -> int:
    return implementation_quality_rank(skill, file_path, code, symbol)


def test_ml_training_outranks_constants_and_comments() -> None:
    train = _rank("Machine Learning", "def train(X, y):\n    clf.fit(X, y)\n    return f1_score(y, clf.predict(X))")
    const = _rank("Machine Learning", "MODEL_PATH = 'model.pkl'\nN_ESTIMATORS = 100")
    comment = _rank("Machine Learning", "# Train the model on the cleaned dataset")
    assert train == 0
    assert train < const and train < comment


def test_ml_engineering_prefers_serving_over_generic_deploy_config() -> None:
    serving = _rank(
        "Machine Learning Engineering",
        "def serve():\n    model = joblib.load('model.pkl')\n    return model.predict(features)",
        file_path="serving/main.py",
    )
    deploy_cfg = _rank(
        "Machine Learning Engineering",
        "FROM python:3.11\nRUN pip install -r requirements.txt\nENV PORT=8080",
        file_path="Dockerfile",
    )
    assert serving == 0
    assert serving < deploy_cfg


def test_api_prefers_route_handler_logic_over_app_setup() -> None:
    handler = _rank(
        "API Development",
        '@router.post("/users")\ndef create_user(body: UserIn):\n'
        "    if not body.email:\n        raise HTTPException(400)\n    return db.execute(stmt)",
        file_path="api/users.py",
    )
    app_setup = _rank(
        "API Development",
        "app = FastAPI()\napp.add_middleware(CORSMiddleware)\nif __name__ == '__main__':\n    app.run()",
        file_path="main.py",
    )
    health = _rank("API Development", '@app.get("/health")\ndef health():\n    return {"ok": True}', file_path="health.py")
    assert handler == 0
    assert handler < app_setup
    assert handler < health


def test_react_prefers_stateful_component_over_static_markup() -> None:
    stateful = _rank(
        "React",
        "function Counter() {\n  const [n, setN] = useState(0)\n"
        "  return <button onClick={() => setN(n + 1)}>{n}</button>\n}",
        file_path="Counter.tsx",
    )
    static = _rank(
        "React",
        'function Footer() {\n  return (\n    <footer className="ft">\n      <span>© 2026</span>\n    </footer>\n  )\n}',
        file_path="Footer.tsx",
    )
    assert stateful == 0
    assert stateful < static


def test_security_prefers_permission_check_over_config_constant() -> None:
    check = _rank(
        "Security",
        "def require_owner(user, resource):\n    if not user.can_access(resource):\n        raise Forbidden()",
        file_path="auth/guards.py",
    )
    config = _rank("Security", "SECRET_KEY = os.environ['SECRET_KEY']\nALGORITHM = 'HS256'", file_path="settings.py")
    assert check == 0
    assert check < config


def test_devops_prefers_pipeline_steps_over_version_constant() -> None:
    pipeline = _rank(
        "Cloud / DevOps",
        "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n      - run: kubectl apply -f k8s/",
        file_path=".github/workflows/deploy.yml",
    )
    version = _rank("Cloud / DevOps", "VERSION: '1.2.3'\nREPLICAS: 3", file_path="vars.yml")
    assert pipeline == 0
    assert pipeline < version


def test_all_boilerplate_snippet_is_demoted_for_any_skill() -> None:
    # An import/comment-only snippet (even if it name-drops the skill) ranks at the
    # weakest band, below any real implementation row.
    boilerplate = _rank("Machine Learning", "import torch  # for the model\nfrom sklearn import metrics")
    real = _rank("Machine Learning", "loss = criterion(model(x), y)\nloss.backward()")
    assert boilerplate == 3
    assert real < boilerplate


def test_extractor_ranks_implementation_logic_above_boilerplate_strong_row() -> None:
    # Two rows tagged the same skill: a config-style "strong" row (it has a class
    # def so it passes the strength gate) and a real API handler. The handler must
    # rank first so best_strong_for_skill surfaces the meaningful implementation.
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "API Development",
                    "file_path": "app/main.py",
                    "line_start": 1,
                    "line_end": 3,
                    "code_snippet": "app = FastAPI()\napp.add_middleware(CORSMiddleware)\nif __name__ == '__main__':\n    app.run()",
                },
                {
                    "skill": "API Development",
                    "file_path": "app/routes/users.py",
                    "line_start": 20,
                    "line_end": 26,
                    "function_name": "create_user",
                    "code_snippet": (
                        '@router.post("/users")\n'
                        "def create_user(body: UserIn):\n"
                        "    if not body.email:\n"
                        "        raise HTTPException(400)\n"
                        "    return db.execute(insert_user(body))"
                    ),
                },
            ]
        )
    )
    ev = result.best_strong_for_skill("API Development")
    assert ev is not None
    assert ev.file_path == "app/routes/users.py"
    assert ev.function_name == "create_user"


# ── snippet focusing onto the implementation body ────────────────────────────


def test_focus_snippet_trims_leading_comment_and_import_lines() -> None:
    snippet = "# train the model\nimport numpy as np\ndef train(X, y):\n    return clf.fit(X, y)"
    focused, new_start = focus_snippet_on_implementation(snippet, 10, 13)
    assert focused.startswith("def train")
    # Two leading plumbing lines were trimmed → start advances by exactly two.
    assert new_start == 12


def test_focus_snippet_never_advances_past_line_end() -> None:
    # The stored range is smaller than the snippet's plumbing prefix — don't fake a
    # start past the end; leave the snippet/line unchanged.
    snippet = "# a\n# b\n# c\ndef f():\n    return 1"
    focused, new_start = focus_snippet_on_implementation(snippet, 5, 6)
    assert (focused, new_start) == (snippet, 5)


def test_focus_snippet_noop_when_starts_on_code() -> None:
    snippet = "def predict(req):\n    return model.predict(req)"
    assert focus_snippet_on_implementation(snippet, 7, 8) == (snippet, 7)


def test_extractor_focuses_displayed_snippet_and_line_onto_body() -> None:
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning",
                    "file_path": "src/model/train.py",
                    "line_start": 40,
                    "line_end": 46,
                    "code_snippet": (
                        "# Build and fit the gradient boosting model\n"
                        "import numpy as np\n"
                        "def train_model(X, y):\n"
                        "    clf = GradientBoostingClassifier()\n"
                        "    return clf.fit(X, y)"
                    ),
                }
            ]
        )
    )
    ev = result.best_strong_for_skill("Machine Learning")
    assert ev is not None
    # The displayed snippet opens on the function body, not the comment/import.
    assert ev.code_snippet.startswith("def train_model")
    assert "import numpy" not in ev.code_snippet
    # line_start advanced by the two trimmed leading lines, and the URL anchor too.
    assert ev.line_start == 42
    assert ev.github_url and "#L42-L46" in ev.github_url


# ── evidence_quality_grade: AST/body focusing affects real report rows ─────────
#
# These lock the GitHub evidence-quality hardening at the SERVICE/CANONICAL layer
# (not just the isolated AST helper): a docstring / import / bare route decorator
# row never wins TOP evidence when a real implementation body exists for the same
# skill, and stale canonical rows are regraded + demoted at projection time.

from app.services.github_python_evidence_focus import (  # noqa: E402
    ANALYZER_NAME,
    ANALYZER_VERSION,
    GRADE_COMMENT_OR_DOCSTRING,
    GRADE_IMPLEMENTATION_BODY,
    GRADE_IMPORT_ONLY,
    GRADE_REPO_LEVEL_FALLBACK,
    GRADE_SUPPORTING_LOGIC,
    SERVER_PROVENANCE_KEY,
    TRUSTED_ANALYSIS_TABLE,
    build_server_provenance,
    is_strong_grade,
    is_weak_grade,
)


def _seed_trusted_provenance(store: dict, evidence_id: str, **kwargs) -> dict:
    """Stamp server-only trusted provenance into the SERVICE-ROLE-ONLY protected
    table exactly as the offline scanner does through the service role — the ONLY
    trusted path for a persisted strong grade / focused source excerpt to reach
    the canonical adapter at render time.

    Authenticated users have NO insert/update policy on this table (migration
    053), so this can never be forged via ``skill_evidence.metadata``. Returns the
    stored record for convenient mutation (e.g. forcing a stale analyzer version).
    """
    record = {
        "skill_evidence_id": evidence_id,
        "user_id": _USER,
        **build_server_provenance(**kwargs),
    }
    store.setdefault(TRUSTED_ANALYSIS_TABLE, {})[evidence_id] = record
    return record


def test_api_skill_prefers_handler_body_over_decorator() -> None:
    # A bare route decorator (no handler body) and a real handler with request
    # validation + a db query + an error raise. The handler body must be TOP
    # evidence; the decorator-only row is demoted out of strong evidence.
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "API Development",
                    "file_path": "app/routes/health.py",
                    "line_start": 5,
                    "line_end": 8,
                    "function_name": "health",
                    "code_snippet": (
                        '@app.get("/health")\n'
                        "def health():\n"
                        '    """Health probe."""\n'
                        "    ..."
                    ),
                },
                {
                    "skill": "API Development",
                    "file_path": "app/routes/users.py",
                    "line_start": 20,
                    "line_end": 27,
                    "function_name": "create_user",
                    "code_snippet": (
                        '@app.post("/users")\n'
                        "def create_user(payload):\n"
                        "    if not payload.email:\n"
                        "        raise HTTPException(status_code=422)\n"
                        "    user = db.query(User).filter(User.email == payload.email).first()\n"
                        "    return JSONResponse(user.id)"
                    ),
                },
            ]
        )
    )
    best = result.best_strong_for_skill("API Development")
    assert best is not None
    assert best.file_path == "app/routes/users.py"
    assert best.evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
    # The bare-decorator handler is graded weak and dropped from TOP evidence.
    strong_files = [i.file_path for i in result.strong_for_skill("API Development")]
    assert "app/routes/health.py" not in strong_files


def test_ml_engineering_prefers_serving_inference_body_over_deploy_config() -> None:
    # serving/main.py loads the model and runs inference; deploy/config.py is just
    # deployment constants. The serving body is TOP; the config row is not strong.
    result = extract_github_skill_evidence(
        _gh_row(
            [
                {
                    "skill": "Machine Learning Engineering",
                    "file_path": "deploy/config.py",
                    "line_start": 1,
                    "line_end": 4,
                    "code_snippet": (
                        'DEPLOY_REGION = "us-central1"\n'
                        'MACHINE_TYPE = "n1-standard-4"\n'
                        "MIN_REPLICAS = 1\n"
                        "MAX_REPLICAS = 3"
                    ),
                },
                {
                    "skill": "Machine Learning Engineering",
                    "file_path": "serving/main.py",
                    "line_start": 30,
                    "line_end": 35,
                    "function_name": "predict",
                    "code_snippet": (
                        "def predict(request):\n"
                        "    model = joblib.load(MODEL_PATH)\n"
                        '    features = request.json["features"]\n'
                        "    proba = model.predict_proba([features])[0]\n"
                        '    return {"score": float(proba[1])}'
                    ),
                },
            ]
        )
    )
    best = result.best_strong_for_skill("Machine Learning Engineering")
    assert best is not None
    assert best.file_path == "serving/main.py"
    assert best.evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
    strong_files = [i.file_path for i in result.strong_for_skill("Machine Learning Engineering")]
    assert "deploy/config.py" not in strong_files


def test_ml_report_excludes_generic_react_ui_components() -> None:
    # A connected Machine Learning report must NOT pull in a generic React UI
    # component (a dashboard / footer with no ML pipeline signal) from the same
    # repo, while a genuine ML-pipeline Python row IS admitted.
    ui_snippet = (
        "export default function Dashboard() {\n"
        "  const data = useMemo(() => rows, [rows])\n"
        '  return <div className="grid"><Card title="Risk" /></div>\n'
        "}"
    )
    assert not is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="React",
        file_path="components/Dashboard.tsx",
        code_snippet=ui_snippet,
        mapping_reason="renders the dashboard layout",
    )
    assert not is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="Frontend Development",
        file_path="components/Footer.tsx",
        code_snippet="return <footer>copyright</footer>",
        mapping_reason="UI layout component",
    )
    # A genuine ML-pipeline Python row from the same repo is still admitted.
    assert is_github_evidence_related_to_skill(
        "Machine Learning",
        evidence_skill="Python",
        file_path="src/model/train.py",
        code_snippet="clf = RandomForestClassifier()\nclf.fit(X, y)",
        mapping_reason="model instantiation",
    )


# ── canonical (old engine) rows are regraded + demoted at projection time ──────


def test_canonical_docstring_range_is_not_strong() -> None:
    # An old canonical row whose persisted snippet is only a module docstring is
    # regraded comment_or_docstring and demoted from "strong" to "medium".
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-doc",
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        metadata={"selection_reason": "module docstring"},
    )
    _seed_trusted_provenance(
        store,
        "se-doc",
        code_snippet='"""Boston rerouting model package.\n\nProse only.\n"""',
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_COMMENT_OR_DOCSTRING
    assert is_weak_grade(ev.evidence_quality_grade)
    assert ev.evidence_strength == "medium"  # demoted out of "strong"


def test_canonical_import_range_is_not_top_evidence() -> None:
    # Two canonical rows for the same skill: an import block and a real training
    # body. The implementation body sorts first; the import row is demoted and is
    # never the top canonical evidence.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-imp",
        skill_name="Machine Learning",
        file_path="src/model/__init__.py",
        metadata={"selection_reason": "imports"},
    )
    _seed_trusted_provenance(
        store,
        "se-imp",
        code_snippet="import os\nimport joblib\nfrom sklearn.ensemble import RandomForestClassifier",
    )
    _seed_skill_evidence_row(
        store,
        id="se-body",
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        metadata={"selection_reason": "model training"},
    )
    _seed_trusted_provenance(
        store,
        "se-body",
        code_snippet=(
            "def train(df):\n"
            "    clf = RandomForestClassifier()\n"
            "    clf.fit(df.X, df.y)\n"
            "    return clf.predict(df.X)"
        ),
    )
    items = collect_canonical_github_skill_evidence(store, _USER, "machine learning")
    assert items[0].file_path == "src/model/train.py"
    assert items[0].evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
    assert is_strong_grade(items[0].evidence_quality_grade)
    import_row = next(i for i in items if i.file_path == "src/model/__init__.py")
    assert import_row.evidence_quality_grade == GRADE_IMPORT_ONLY
    assert import_row is not items[0]
    assert import_row.evidence_strength == "medium"  # demoted


def test_existing_canonical_rows_are_regraded_during_backfill_or_projection() -> None:
    # An old engine persisted a "strong" row whose reason is really docstring/import
    # plumbing (no snippet). Projection regrades it weak + demotes it, and it sorts
    # BELOW a genuine implementation-body row — i.e. stale rows are repaired at
    # read time, not trusted as persisted.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-stale",
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=1,
        line_end=4,
        metadata={"selection_reason": "Module docstring and import statements for the package."},
    )
    _seed_skill_evidence_row(
        store,
        id="se-real",
        skill_name="Machine Learning",
        file_path="src/model/fit.py",
        metadata={"selection_reason": "model training"},
    )
    _seed_trusted_provenance(
        store,
        "se-real",
        code_snippet="def train(df):\n    clf = RandomForestClassifier()\n    return clf.fit(df.X, df.y)",
    )
    items = collect_canonical_github_skill_evidence(store, _USER, "machine learning")
    by_id = {i.source_id: i for i in items}
    stale = by_id["se-stale"]
    real = by_id["se-real"]
    # The stale row was regraded weak and demoted off "strong".
    assert is_weak_grade(stale.evidence_quality_grade)
    assert stale.evidence_strength == "medium"
    # The genuine body kept its strong grade and sorts ahead of the stale row.
    assert is_strong_grade(real.evidence_quality_grade)
    assert items.index(real) < items.index(stale)


def test_canonical_import_only_metadata_without_snippet_fails_closed() -> None:
    # Live Boston failure: a STALE canonical row for an import-only api.py:19-23
    # range carries NO source snippet, yet its descriptive reason reads like real
    # model-serving implementation. Metadata alone must NOT establish precise
    # implementation evidence — without a body (or a trusted persisted grade) the
    # row fails closed to repo_level_fallback and is never graded supporting_logic.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-stale-import",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        evidence_description="Model serving inference endpoint.",
        metadata={"selection_reason": "model serving inference handler"},  # no snippet
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert ev.evidence_strength == "medium"  # no longer "strong" precise proof


def test_canonical_trusted_persisted_grade_is_honored_without_snippet() -> None:
    # A grade the VeriBridge scanner computed FROM REAL SOURCE at scan time — and
    # which carries the controlled analyzer provenance marker in the SERVER-ONLY
    # provenance namespace — is trusted even without a re-stored snippet, so a
    # genuine source-backed row is not needlessly demoted by the fail-closed path.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-trusted",
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=40,
        line_end=60,
        metadata={"selection_reason": "model training"},
    )
    _seed_trusted_provenance(store, "se-trusted", grade=GRADE_IMPLEMENTATION_BODY)
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
    assert is_strong_grade(ev.evidence_quality_grade)


def test_untrusted_persisted_implementation_grade_fails_closed() -> None:
    # User-controlled metadata asserts a STRONG grade (implementation_body) but
    # carries NO server provenance namespace and NO source snippet. The known-band
    # safety check alone must not promote it — the row fails closed to a weak,
    # non-top band so forged metadata can never reach top evidence.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-forged",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={
            "selection_reason": "model serving inference handler",
            "evidence_quality_grade": GRADE_IMPLEMENTATION_BODY,
            # No server provenance namespace — provenance is missing.
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    # Fails closed: a forged strong grade NEVER survives as a strong band.
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert is_weak_grade(ev.evidence_quality_grade)
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK


def test_forged_flat_analyzer_marker_does_not_promote_strong_grade() -> None:
    # HOSTILE: a public create/update payload sets the analyzer marker AND a strong
    # grade as FLAT metadata (mimicking the scanner) with no server provenance
    # namespace. This must NOT be trusted — only the server-only namespace counts.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-forged-marker",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={
            "selection_reason": "model serving inference handler",
            "evidence_quality_grade": GRADE_IMPLEMENTATION_BODY,
            "evidence_analyzer": ANALYZER_NAME,
            "evidence_analyzer_version": ANALYZER_VERSION,
            "analyzer": ANALYZER_NAME,
            "analyzer_name": ANALYZER_NAME,
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK


def test_metadata_server_provenance_namespace_is_ignored() -> None:
    # HOSTILE: a hostile owner UPDATEs their own ``skill_evidence.metadata`` (the
    # row's RLS is "own row ALL") to embed a PERFECTLY-SHAPED server provenance
    # namespace — correct analyzer name + recognized version + strong grade + a
    # real-looking body. Because trust now reads ONLY the service-role-only
    # protected table (never metadata), this forgery is ignored and the row fails
    # closed. Nothing is seeded into TRUSTED_ANALYSIS_TABLE.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-meta-forge",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={
            "selection_reason": "model serving inference handler",
            SERVER_PROVENANCE_KEY: build_server_provenance(
                grade=GRADE_IMPLEMENTATION_BODY,
                code_snippet=(
                    "def train(df):\n"
                    "    clf = RandomForestClassifier()\n"
                    "    return clf.fit(df.X, df.y)"
                ),
            ),
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK


def test_server_provenance_with_unknown_analyzer_version_fails_closed() -> None:
    # A protected-table provenance record stamped by an analyzer VERSION we no
    # longer recognize must fail closed — the grader may have changed, so a stale
    # strong grade can't be reproduced and must not be trusted.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-stale-version",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={"selection_reason": "model serving"},
    )
    prov = _seed_trusted_provenance(store, "se-stale-version", grade=GRADE_IMPLEMENTATION_BODY)
    prov["analyzer_version"] = "999-unrecognized"
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK


def test_canonical_weak_persisted_grade_trusted_without_provenance() -> None:
    # A WEAK persisted grade can be honored as-is even without provenance: a weak
    # band never promotes a row to top evidence, and we want weak rows to STAY weak.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-weak",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=1,
        line_end=5,
        metadata={
            "selection_reason": "imports",
            "evidence_quality_grade": GRADE_IMPORT_ONLY,
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_IMPORT_ONLY
    assert is_weak_grade(ev.evidence_quality_grade)


def test_canonical_source_snippet_validates_implementation_body() -> None:
    # A SERVER-trusted source snippet (stamped by the scanner under the server-only
    # provenance namespace) establishes implementation_body via the AST quality
    # logic — the snippet is the strongest, most honest signal.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-snippet",
        skill_name="Machine Learning",
        file_path="src/model/train.py",
        line_start=40,
        line_end=48,
        metadata={"selection_reason": "model training"},
    )
    _seed_trusted_provenance(
        store,
        "se-snippet",
        grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet="\n".join([
            "def train_model(df):",
            "    X_train, X_test, y_train, y_test = train_test_split(X, y)",
            "    clf = RandomForestClassifier(n_estimators=200)",
            "    clf.fit(X_train, y_train)",
            "    return f1_score(y_test, clf.predict(X_test))",
        ]),
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_IMPLEMENTATION_BODY
    assert is_strong_grade(ev.evidence_quality_grade)


def test_forged_flat_code_snippet_is_not_trusted_as_source_validation() -> None:
    # HOSTILE: a public payload sets a FLAT ``code_snippet`` with a fake real-looking
    # implementation body (and no server provenance). It must NOT be read as source
    # validation — without server provenance the row fails closed to a weak band.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-forged-snippet",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={
            "selection_reason": "model serving inference handler",
            "code_snippet": "\n".join([
                "def train_model(df):",
                "    clf = RandomForestClassifier(n_estimators=200)",
                "    clf.fit(df.X, df.y)",
                "    return f1_score(df.y, clf.predict(df.X))",
            ]),
            "source_snippet": "clf.fit(X, y)",
            "body": "model.predict(X)",
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert not is_strong_grade(ev.evidence_quality_grade)
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK


def test_canonical_untrusted_persisted_grade_string_is_not_honored() -> None:
    # A bogus / unknown persisted grade string (not in the known vocabulary) is
    # NEVER trusted — the row fails closed instead of echoing arbitrary metadata.
    store: dict = {}
    _seed_skill_evidence_row(
        store,
        id="se-bogus",
        skill_name="Machine Learning",
        file_path="api.py",
        line_start=19,
        line_end=23,
        metadata={
            "selection_reason": "model serving inference handler",
            "evidence_quality_grade": "totally_verified_★",
        },
    )
    ev = collect_canonical_github_skill_evidence(store, _USER)[0]
    assert ev.evidence_quality_grade == GRADE_REPO_LEVEL_FALLBACK
    assert not is_strong_grade(ev.evidence_quality_grade)
