"""Tests for deterministic Python AST evidence focusing + quality grading.

The contract these lock in (MVP GitHub evidence-quality hardening):

* a line anchor that lands on a decorator / signature / module docstring / import
  block is FOCUSED onto the enclosing function/class implementation body — never
  surfaced as decorator-only / import-only / docstring-only proof;
* every range/snippet carries a deterministic ``evidence_quality_grade`` so
  ranking can keep imports / docstrings / constants / bare route decorators out
  of TOP evidence whenever a real implementation body exists;
* nothing here calls an LLM or a live GitHub scan — pure ``ast`` + regex.
"""

from __future__ import annotations

from app.services.github_python_evidence_focus import (
    ANALYZER_NAME,
    ANALYZER_VERSION,
    GRADE_COMMENT_OR_DOCSTRING,
    GRADE_CONFIG_OR_CONSTANT,
    GRADE_IMPLEMENTATION_BODY,
    GRADE_IMPORT_ONLY,
    GRADE_ROUTE_DECORATOR_ONLY,
    GRADE_SUPPORTING_LOGIC,
    RESERVED_PROVENANCE_FIELDS,
    SERVER_PROVENANCE_KEY,
    build_server_provenance,
    effective_evidence_grade,
    focus_python_range,
    grade_evidence,
    grade_python_snippet,
    GRADE_REPO_LEVEL_FALLBACK,
    grade_rank,
    has_ml_executable_signal,
    is_overclaiming_reason,
    is_strong_grade,
    is_weak_grade,
    ml_implementation_is_valid,
    redact_secrets,
    safe_selection_reason,
    strip_client_provenance,
    trusted_provenance,
)

_REDACTION_PLACEHOLDER = "[REDACTED_SECRET]"

# ── Realistic source fixtures (Boston-/Stroke-style) ──────────────────────────

# A FastAPI ML serving file: module docstring + imports + constants + a route
# whose handler body does the real validation / model inference work.
BOSTON_API_PY = '''"""Boston accident-risk serving API.

Exposes a /predict endpoint backed by the trained model.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

import joblib

MODEL_PATH = os.environ.get("MODEL_PATH", "model.joblib")
BATCH_SIZE = 32

app = FastAPI()


class PredictRequest(BaseModel):
    features: list[float]


@app.post("/predict")
def predict(payload: PredictRequest):
    """Run inference for one accident-risk request."""
    if not payload.features:
        raise HTTPException(status_code=422, detail="features required")
    model = joblib.load(MODEL_PATH)
    proba = model.predict_proba([payload.features])[0]
    risk = "high" if proba[1] > 0.7 else "low"
    return {"risk": risk, "score": float(proba[1])}
'''

# A scikit-learn training/evaluation body (Stroke "Tree.py" style).
STROKE_TREE_PY = '''"""Decision-tree stroke model training + evaluation."""

import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.metrics import classification_report, f1_score


def train_and_evaluate(path):
    """Train a tuned decision tree and report metrics."""
    df = pd.read_csv(path)
    X = df.drop("stroke", axis=1)
    y = df["stroke"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    grid = GridSearchCV(DecisionTreeClassifier(), {"max_depth": [3, 5, 7]})
    grid.fit(X_train, y_train)
    preds = grid.predict(X_test)
    print(classification_report(y_test, preds))
    return f1_score(y_test, preds)
'''


def _lineno(source: str, needle: str) -> int:
    """1-indexed line number of the first line containing ``needle``."""
    for i, line in enumerate(source.splitlines(), start=1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found")


# ── grade vocabulary ──────────────────────────────────────────────────────────


def test_grade_rank_orders_strong_above_weak() -> None:
    assert grade_rank(GRADE_IMPLEMENTATION_BODY) < grade_rank(GRADE_SUPPORTING_LOGIC)
    assert grade_rank(GRADE_SUPPORTING_LOGIC) < grade_rank(GRADE_CONFIG_OR_CONSTANT)
    assert grade_rank(GRADE_CONFIG_OR_CONSTANT) < grade_rank(GRADE_IMPORT_ONLY)
    assert is_strong_grade(GRADE_IMPLEMENTATION_BODY)
    assert is_strong_grade(GRADE_SUPPORTING_LOGIC)
    for weak in (
        GRADE_CONFIG_OR_CONSTANT,
        GRADE_COMMENT_OR_DOCSTRING,
        GRADE_IMPORT_ONLY,
        GRADE_ROUTE_DECORATOR_ONLY,
    ):
        assert is_weak_grade(weak)
        assert not is_strong_grade(weak)


# ── snippet grading ───────────────────────────────────────────────────────────


def test_grade_python_snippet_import_block_is_import_only() -> None:
    assert grade_python_snippet("import os\nfrom fastapi import FastAPI") == GRADE_IMPORT_ONLY


def test_grade_python_snippet_module_docstring_is_comment_or_docstring() -> None:
    assert grade_python_snippet('"""Module docstring.\n\nProse only.\n"""') == GRADE_COMMENT_OR_DOCSTRING


def test_grade_python_snippet_constants_are_config_or_constant() -> None:
    assert grade_python_snippet('MODEL_PATH = "m.pkl"\nBATCH_SIZE = 32') == GRADE_CONFIG_OR_CONSTANT


def test_route_decorator_requires_handler_body() -> None:
    # A bare route decorator + signature + docstring (no body) is decorator-only.
    decorator_only = '@app.post("/predict")\ndef predict():\n    """doc."""\n    ...'
    assert grade_python_snippet(decorator_only) == GRADE_ROUTE_DECORATOR_ONLY
    # The same route WITH a real handler body is an implementation body.
    with_body = (
        '@app.post("/predict")\n'
        "def predict(payload):\n"
        "    if not payload.features:\n"
        "        raise HTTPException(status_code=422)\n"
        "    return model.predict_proba([payload.features])\n"
    )
    assert grade_python_snippet(with_body) == GRADE_IMPLEMENTATION_BODY


def test_stroke_tree_training_body_is_strong() -> None:
    body = "\n".join(STROKE_TREE_PY.splitlines()[9:])  # the function body region
    grade = grade_python_snippet(body)
    assert grade == GRADE_IMPLEMENTATION_BODY
    assert is_strong_grade(grade)


# ── AST focusing ──────────────────────────────────────────────────────────────


def test_python_ast_focuses_anchor_to_enclosing_function_body() -> None:
    # Anchor on the decorator line — focus must move into the handler body.
    deco_line = _lineno(BOSTON_API_PY, '@app.post("/predict")')
    focused = focus_python_range(BOSTON_API_PY, deco_line, deco_line)
    assert focused is not None
    start, end, grade = focused
    body_lines = BOSTON_API_PY.splitlines()[start - 1 : end]
    joined = "\n".join(body_lines)
    assert "predict_proba" in joined  # the real inference body is included
    assert grade == GRADE_IMPLEMENTATION_BODY
    # Default focus opens on the body, not the module docstring/imports.
    assert "import joblib" not in joined
    assert "Boston accident-risk serving API." not in joined


def test_python_ast_excludes_module_docstring_and_imports() -> None:
    # Anchor on a module-level import — it must NOT be promoted to a strong body.
    import_line = _lineno(BOSTON_API_PY, "import joblib")
    focused = focus_python_range(BOSTON_API_PY, import_line, import_line)
    assert focused is not None
    _start, _end, grade = focused
    assert grade in (GRADE_IMPORT_ONLY, GRADE_CONFIG_OR_CONSTANT)
    assert is_weak_grade(grade)

    # Anchor on the module docstring stays docstring-graded (never implementation).
    doc_line = _lineno(BOSTON_API_PY, "Boston accident-risk serving API.")
    doc_focus = focus_python_range(BOSTON_API_PY, doc_line, doc_line)
    assert doc_focus is not None
    assert is_weak_grade(doc_focus[2])


def test_include_signature_keeps_decorator_but_grades_body() -> None:
    # The scanner keeps the decorator/signature as context (include_signature) but
    # the grade still reflects the body, so a real handler grades strong.
    deco_line = _lineno(BOSTON_API_PY, '@app.post("/predict")')
    focused = focus_python_range(
        BOSTON_API_PY, deco_line, deco_line, include_signature=True
    )
    assert focused is not None
    start, end, grade = focused
    joined = "\n".join(BOSTON_API_PY.splitlines()[start - 1 : end])
    assert '@app.post("/predict")' in joined  # decorator retained as context
    assert "predict_proba" in joined  # body retained
    assert grade == GRADE_IMPLEMENTATION_BODY


def test_focus_never_fabricates_line_numbers() -> None:
    total = len(BOSTON_API_PY.splitlines())
    for anchor in (1, 5, 20, total):
        focused = focus_python_range(BOSTON_API_PY, anchor, anchor)
        assert focused is not None
        start, end, _grade = focused
        assert 1 <= start <= end <= total


def test_focus_returns_none_on_unparseable_source() -> None:
    assert focus_python_range("def (:\n  not python", 1, 1) is None


def test_unparseable_python_keyword_window_grades_weak_not_strong() -> None:
    # A malformed/keyword-window snippet whose ML signals live only in a comment
    # and an import must grade to a WEAK band — never implementation_body /
    # supporting_logic — so a parse failure can never masquerade as a real body.
    window = "# RandomForestClassifier f1_score training pipeline\nimport sklearn"
    grade = grade_python_snippet(window)
    assert is_weak_grade(grade)
    assert not is_strong_grade(grade)


# ── metadata-only grading (no snippet) ────────────────────────────────────────


def test_grade_evidence_metadata_import_reason_is_import_only() -> None:
    grade = grade_evidence(
        file_path="api.py",
        code_snippet=None,
        selection_reason="Analyzer located import statements for FastAPI in api.py.",
    )
    assert grade == GRADE_IMPORT_ONLY


def test_grade_evidence_metadata_decorator_reason_is_route_decorator_only() -> None:
    grade = grade_evidence(
        file_path="api.py",
        code_snippet=None,
        selection_reason="API endpoint decorator",
        evidence_kind="endpoint",
    )
    assert grade == GRADE_ROUTE_DECORATOR_ONLY


def test_grade_evidence_metadata_handler_reason_is_supporting_at_most() -> None:
    # A real handler reason with a line range is supporting logic — but metadata
    # alone NEVER claims implementation_body (only a real body can).
    grade = grade_evidence(
        file_path="api.py",
        code_snippet=None,
        selection_reason="Handler body with request validation and service call",
        evidence_kind="function",
        line_start=275,
        line_end=323,
    )
    assert grade == GRADE_SUPPORTING_LOGIC
    assert not is_strong_grade(grade) or grade == GRADE_SUPPORTING_LOGIC


def test_grade_evidence_prefers_snippet_over_metadata() -> None:
    # Even if the reason text says "import", a real body snippet grades strong.
    body = (
        "def train(df):\n"
        "    clf = RandomForestClassifier()\n"
        "    clf.fit(df.X, df.y)\n"
        "    return clf.predict(df.X)\n"
    )
    grade = grade_evidence(
        file_path="train.py",
        code_snippet=body,
        selection_reason="import block",
    )
    assert grade == GRADE_IMPLEMENTATION_BODY


# ── secret redaction (before any snippet/excerpt persistence) ──────────────────


def test_redact_openai_sk_key() -> None:
    out = redact_secrets('api_key = "sk-supersecret-DEADBEEF1234567890"')
    assert "sk-supersecret-DEADBEEF1234567890" not in out
    assert _REDACTION_PLACEHOLDER in out


def test_redact_github_classic_and_fine_grained_tokens() -> None:
    classic = "token = ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB"
    assert "ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB" not in redact_secrets(classic)
    for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
        raw = f"{prefix}{'x' * 24}"
        assert raw not in redact_secrets(f"GH_TOKEN = {raw}")
    pat = "github_pat_11ABCDEFG0aaaaaaaaaaaa_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert pat not in redact_secrets(f"GH = {pat}")
    assert _REDACTION_PLACEHOLDER in redact_secrets(f"GH = {pat}")


def test_redact_slack_tokens() -> None:
    for raw in (
        "xoxb-123456789012-abcdefghijklmnopqrst",
        "xoxp-123456789012-abcdefghijklmnopqrst",
        "xoxa-2-abcdefghijklmnopqrst",
        "xoxr-abcdefghijklmnopqrst",
        "xoxs-abcdefghijklmnopqrst",
    ):
        out = redact_secrets(f"SLACK = {raw}")
        assert raw not in out
        assert _REDACTION_PLACEHOLDER in out


def test_redact_jwt_token() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    out = redact_secrets(f"Authorization header carried {jwt}")
    assert jwt not in out
    assert _REDACTION_PLACEHOLDER in out


def test_redact_aws_access_key_ids() -> None:
    for raw in ("AKIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE"):
        out = redact_secrets(f"aws_key = {raw}")
        assert raw not in out
        assert _REDACTION_PLACEHOLDER in out


def test_redact_authorization_bearer() -> None:
    out = redact_secrets("Authorization: Bearer abc123.def456-XYZ_secrettoken")
    assert "abc123.def456-XYZ_secrettoken" not in out
    assert _REDACTION_PLACEHOLDER in out


def test_redact_aws_signed_url_params() -> None:
    url = (
        "https://bucket.s3.amazonaws.com/key?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKIAEXAMPLE%2F20240101%2Fus-east-1"
        "&X-Amz-Signature=abcdef0123456789abcdef0123456789"
        "&X-Amz-Security-Token=FwoGZXIvYXdzEExampleToken"
    )
    out = redact_secrets(url)
    assert "abcdef0123456789abcdef0123456789" not in out
    assert "AKIAEXAMPLE" not in out
    assert "FwoGZXIvYXdzEExampleToken" not in out
    assert _REDACTION_PLACEHOLDER in out


def test_redact_secret_assignments_including_connection_strings() -> None:
    samples = [
        'password = "hunter2-very-secret"',
        "client_secret: 'abcDEF123456'",
        'DATABASE_URL = "postgres://user:p4ssw0rd@host:5432/db"',
        'POSTGRES_URL="postgresql://u:secretpw@h/db"',
        'SUPABASE_SERVICE_ROLE_KEY = "eyJsupabaseRoleKeyValue123456"',
    ]
    for sample in samples:
        out = redact_secrets(sample)
        assert _REDACTION_PLACEHOLDER in out
    joined = redact_secrets("\n".join(samples))
    for leak in ("hunter2", "abcDEF123456", "p4ssw0rd", "secretpw", "supabaseRoleKeyValue"):
        assert leak not in joined


def test_redacted_snippet_never_contains_raw_secret() -> None:
    # A focused body that mixes real code with several hard-coded secrets: the
    # redacted excerpt keeps the implementation lines but no raw secret survives.
    snippet = "\n".join([
        "def train(df):",
        '    api_key = "sk-DEADBEEFsupersecretkey0001"',
        "    token = ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB",
        "    slack = xoxb-123456789012-abcdefghijklmnopqrst",
        "    clf = RandomForestClassifier()",
        "    return clf.fit(df.X, df.y)",
    ])
    out = redact_secrets(snippet)
    for leak in (
        "sk-DEADBEEFsupersecretkey0001",
        "ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB",
        "xoxb-123456789012-abcdefghijklmnopqrst",
    ):
        assert leak not in out
    # Real implementation structure preserved (so grading is unchanged).
    assert "clf.fit(df.X, df.y)" in out
    assert _REDACTION_PLACEHOLDER in out


def test_redact_preserves_grade_of_implementation_body() -> None:
    # Redaction must not change the evidence grade of a real body.
    snippet = "\n".join([
        "def train(df):",
        '    secret = "sk-DEADBEEFsupersecretkey0001"',
        "    clf = RandomForestClassifier()",
        "    clf.fit(df.X, df.y)",
        "    return clf.predict(df.X)",
    ])
    assert grade_python_snippet(snippet) == GRADE_IMPLEMENTATION_BODY
    assert grade_python_snippet(redact_secrets(snippet)) == GRADE_IMPLEMENTATION_BODY


# ── server-only provenance (forgery boundary) ─────────────────────────────────


def test_build_server_provenance_redacts_snippet_and_hashes_redacted() -> None:
    prov = build_server_provenance(
        grade=GRADE_IMPLEMENTATION_BODY,
        code_snippet='def f():\n    token = ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB\n    return 1',
    )
    assert prov["analyzer_name"] == ANALYZER_NAME
    assert prov["analyzer_version"] == ANALYZER_VERSION
    assert prov["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    # The persisted excerpt is already redacted; the hash is of the REDACTED text.
    assert "ghp_aaaaaaaaaaaaaaaaaaaaBBBBBBBBBBBB" not in prov["safe_excerpt"]
    assert _REDACTION_PLACEHOLDER in prov["safe_excerpt"]
    assert prov["snippet_hash"]


def test_trusted_provenance_requires_recognized_analyzer_and_version() -> None:
    good = build_server_provenance(grade=GRADE_IMPLEMENTATION_BODY)
    good["analyzer_version"] = ANALYZER_VERSION
    assert trusted_provenance(good) is not None
    # Unknown analyzer name fails closed.
    bad_name = {**good, "analyzer_name": "totally-trusted-scanner"}
    assert trusted_provenance(bad_name) is None
    # Stale / unrecognized analyzer version fails closed.
    bad_version = {**good, "analyzer_version": "999-unrecognized"}
    assert trusted_provenance(bad_version) is None
    # Non-dict / empty inputs fail closed.
    assert trusted_provenance(None) is None
    assert trusted_provenance("implementation_body") is None


def test_user_metadata_cannot_forge_trusted_provenance() -> None:
    # A hostile owner crafts metadata mimicking the scanner's provenance shape AND
    # nests it under the legacy server-provenance namespace. strip_client_provenance
    # removes every reserved field and the namespace key, so nothing provenance-
    # shaped can even be persisted from a public create/update payload.
    forged = {
        "evidence_title": "Legit Project",  # kept (not provenance)
        "analyzer": ANALYZER_NAME,
        "analyzer_name": ANALYZER_NAME,
        "analyzer_version": ANALYZER_VERSION,
        "evidence_quality_grade": GRADE_IMPLEMENTATION_BODY,
        "code_snippet": "def train(): clf.fit(X, y)",
        "safe_excerpt": "def train(): clf.fit(X, y)",
        "snippet_hash": "deadbeef",
        SERVER_PROVENANCE_KEY: {
            "analyzer_name": ANALYZER_NAME,
            "analyzer_version": ANALYZER_VERSION,
            "evidence_quality_grade": GRADE_IMPLEMENTATION_BODY,
        },
    }
    cleaned = strip_client_provenance(forged)
    assert cleaned == {"evidence_title": "Legit Project"}
    for field in RESERVED_PROVENANCE_FIELDS:
        assert field not in cleaned
    assert SERVER_PROVENANCE_KEY not in cleaned
    # A non-dict value is returned unchanged.
    assert strip_client_provenance("not-a-dict") == "not-a-dict"


# ── Read-time selection-reason neutralisation (stale evidence hardening) ────────


def test_is_overclaiming_reason_matches_ml_and_deploy_labels() -> None:
    for reason in (
        "ML model instantiation",
        "ML training call",
        "ML prediction/inference",
        "Cloud deployment command",
        "model instantiation",
    ):
        assert is_overclaiming_reason(reason), reason
    for reason in ("import statements", "module docstring or header comment", "", None):
        assert not is_overclaiming_reason(reason), reason


def test_safe_selection_reason_neutralises_stale_ml_label_on_weak_row() -> None:
    """A docstring/import row that persisted a stale "ML model instantiation" reason
    is relabelled honestly — never presented as ML implementation."""
    assert (
        safe_selection_reason(GRADE_COMMENT_OR_DOCSTRING, "ML model instantiation")
        == "module docstring or header comment"
    )
    assert (
        safe_selection_reason(GRADE_IMPORT_ONLY, "ML training call") == "import statements"
    )


def test_safe_selection_reason_neutralises_stale_deploy_label_on_weak_row() -> None:
    """A config/decorator row that persisted a stale "Cloud deployment command"
    reason is not shown as deployment implementation."""
    assert (
        safe_selection_reason(GRADE_ROUTE_DECORATOR_ONLY, "Cloud deployment command")
        == "route decorator without a handler body"
    )


def test_safe_selection_reason_fails_closed_for_fallback_and_ungraded() -> None:
    # Fallback / legacy-ungraded rows with an overclaiming reason fail closed.
    assert (
        safe_selection_reason(GRADE_REPO_LEVEL_FALLBACK, "ML model instantiation")
        == "Weak GitHub signal; not primary implementation proof"
    )
    assert (
        safe_selection_reason(None, "Cloud deployment command")
        == "Weak GitHub signal; not primary implementation proof"
    )
    # An ungraded row with no reason at all becomes a repository-level label.
    assert safe_selection_reason(None, None) == "Repository-level GitHub signal"


def test_safe_selection_reason_keeps_precise_reason_for_strong_body() -> None:
    """A validated implementation/supporting body keeps its precise stored reason —
    only weak/ungraded rows are neutralised."""
    assert (
        safe_selection_reason(GRADE_IMPLEMENTATION_BODY, "ML model instantiation")
        == "ML model instantiation"
    )
    assert (
        safe_selection_reason(GRADE_SUPPORTING_LOGIC, "feature engineering")
        == "feature engineering"
    )


def test_safe_selection_reason_drops_arbitrary_technical_reason_on_weak_row() -> None:
    """A weak row must NOT preserve a stored reason that dodges the overclaiming
    keyword denylist — neutralisation is grade-derived, not phrase-derived. A
    "model serving inference handler" (which is NOT matched by the narrow denylist)
    is still replaced with the honest grade label."""
    assert not is_overclaiming_reason("model serving inference handler")
    assert (
        safe_selection_reason(GRADE_COMMENT_OR_DOCSTRING, "model serving inference handler")
        == "module docstring or header comment"
    )
    # Any arbitrary technical phrase is likewise discarded on a weak band.
    assert (
        safe_selection_reason(GRADE_CONFIG_OR_CONSTANT, "custom neural pipeline orchestrator")
        == "configuration/constant definitions"
    )
    # A fallback/ungraded row with such a phrase fails closed, never preserving it.
    assert (
        safe_selection_reason(GRADE_REPO_LEVEL_FALLBACK, "model serving inference handler")
        == "Weak GitHub signal; not primary implementation proof"
    )
    assert (
        safe_selection_reason(None, "bespoke transformer feature graph")
        == "Weak GitHub signal; not primary implementation proof"
    )


# ── Read-time ML semantic validation ──────────────────────────────────────────


def test_has_ml_executable_signal_detects_real_code_but_not_prose() -> None:
    # Concrete executable ML code constructs ARE signals.
    for text in (
        "clf.fit(X, y)",
        "model.predict(rows)",
        "model.predict_proba(rows)",
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y)",
        "joblib.dump(model, path)",
        "accuracy_score(y_true, y_pred)",
        "f1_score(y_true, y_pred)",
        "roc_auc_score(y_true, scores)",
        "clf = LGBMClassifier(n_estimators=200)",
        "reg = RandomForestRegressor()",
        "loss.backward()",
    ):
        assert has_ml_executable_signal(text), text
    # Natural-language PROSE / labels / filenames / function names are NOT signals —
    # a label can never be executable proof of ML implementation.
    for text in (
        "ML model instantiation",
        "model.fit training loop",
        "scripts/pipeline_retrain.py training call",
        "train.py",
        "train_model",
        "model serving inference handler",
        "Cloud deployment command",
        "gcloud run deploy",
        "Dockerfile CMD uvicorn serving app",
        "",
        None,
    ):
        assert not has_ml_executable_signal(text), text


def test_ml_valid_rejects_stale_reason_filename_function_name_alone() -> None:
    """Labels alone (stale reason / filename / function name) never validate ML —
    only a trusted executable body/snippet/provenance can."""
    # Stale reason "ML model instantiation" alone → not valid.
    assert not ml_implementation_is_valid(reason="ML model instantiation")
    # Filename train.py alone → not valid.
    assert not ml_implementation_is_valid(file_path="src/model/train.py")
    # Function name train_model alone → not valid.
    assert not ml_implementation_is_valid(function_name="train_model")
    # Even all three labels together, with no executable body, do not validate.
    assert not ml_implementation_is_valid(
        reason="ML model instantiation",
        file_path="src/model/train.py",
        function_name="train_model",
    )
    # No trusted body at all → fails closed.
    assert not ml_implementation_is_valid()


def test_ml_valid_requires_executable_body_signal() -> None:
    """A trusted snippet/provenance carrying a real ML executable call validates."""
    assert ml_implementation_is_valid(
        code_snippet="clf = LGBMClassifier()\nclf.fit(X_train, y_train)"
    )
    assert ml_implementation_is_valid(code_snippet="proba = model.predict_proba(X_test)")
    assert ml_implementation_is_valid(
        code_snippet=(
            "X_tr, X_te, y_tr, y_te = train_test_split(X, y)\n"
            "print(classification_report(y_te, preds))"
        )
    )
    # Provenance body (server-side) also counts as trusted executable evidence.
    assert ml_implementation_is_valid(provenance="model.fit(X, y)\naccuracy_score(y, p)")
    # A serving/deployment body with no ML executable call does NOT validate.
    assert not ml_implementation_is_valid(
        code_snippet="@app.post('/health')\ndef health():\n    return {'ok': True}"
    )


def test_ml_signal_ignores_docstring_and_comment_mentions() -> None:
    """Docstrings / comments that merely MENTION ML calls are stripped before signal
    matching, so a deployment body annotated with ML prose never validates."""
    # Module docstring mentioning model.fit — not executable, must not signal.
    assert not has_ml_executable_signal('"""Later call model.fit(...) here."""')
    # Function docstring mentioning predict_proba, no executable ML call in body.
    fn_with_docstring = (
        "def serve(req):\n"
        '    """Returns a score; internally would call model.predict_proba(rows)."""\n'
        "    return {'ok': True}"
    )
    assert not has_ml_executable_signal(fn_with_docstring)
    assert not ml_implementation_is_valid(code_snippet=fn_with_docstring)
    # Single-line comments mentioning train_test_split / fit — not executable.
    commented = (
        "# would call train_test_split(X, y) then clf.fit(X, y)\n"
        "def deploy():\n"
        "    return start_server()  # fit the app to the port\n"
    )
    assert not has_ml_executable_signal(commented)
    assert not ml_implementation_is_valid(code_snippet=commented)
    # A deployment body whose only ML text is a docstring stays supporting_logic.
    deploy_body = (
        "def deploy_model():\n"
        '    """Deploy step. Later call model.fit(...) and predict_proba(...)."""\n'
        "    subprocess.run(['gcloud', 'run', 'deploy'])\n"
    )
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=deploy_body
        )
        == GRADE_SUPPORTING_LOGIC
    )


def test_ml_signal_still_detects_real_executable_code_after_stripping() -> None:
    """Real executable ML code (even alongside docstrings/comments) still validates —
    stripping only removes comments/strings, never executable calls."""
    lgbm_body = (
        "def train():\n"
        '    """Train the classifier."""  # entrypoint\n'
        "    clf = LGBMClassifier(n_estimators=200)\n"
        "    clf.fit(X_train, y_train)  # fit call\n"
    )
    assert has_ml_executable_signal(lgbm_body)
    assert ml_implementation_is_valid(code_snippet=lgbm_body)
    proba_body = (
        "def score(rows):\n"
        '    """Score rows."""\n'
        "    return model.predict_proba(rows)\n"
    )
    assert has_ml_executable_signal(proba_body)
    assert ml_implementation_is_valid(code_snippet=proba_body)
    split_body = (
        "# split and evaluate\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y)\n"
        "print(classification_report(y_te, preds))\n"
    )
    assert has_ml_executable_signal(split_body)
    assert ml_implementation_is_valid(code_snippet=split_body)
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=lgbm_body
        )
        == GRADE_IMPLEMENTATION_BODY
    )


def test_effective_grade_downgrades_deployment_only_ml_implementation_body() -> None:
    """A trusted implementation_body that is deployment/serving-only (no ML
    executable signal) is downgraded for an ML skill so it can never present as
    primary ML implementation proof."""
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="model serving inference handler",
            file_path="serving/main.py",
            code_snippet="CMD [\"uvicorn\", \"main:app\"]  # serving container entrypoint",
        )
        == GRADE_SUPPORTING_LOGIC
    )
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="Cloud deployment command",
            file_path="deploy/run.sh",
            code_snippet="gcloud run deploy risk-api --region us-central1",
        )
        == GRADE_SUPPORTING_LOGIC
    )


def test_effective_grade_downgrades_fastapi_route_only_ml_body() -> None:
    """A FastAPI endpoint body with NO model.predict/predict_proba/training/eval
    call is not Machine Learning primary implementation proof."""
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="ML prediction endpoint",
            file_path="app/api.py",
            function_name="predict",
            code_snippet=(
                "@app.post('/predict')\n"
                "def predict(payload: Payload):\n"
                "    return {'status': 'ok', 'id': payload.id}"
            ),
        )
        == GRADE_SUPPORTING_LOGIC
    )


def test_effective_grade_downgrades_ml_body_backed_only_by_stale_labels() -> None:
    """implementation_body whose only "ML" evidence is a stale reason / train.py
    filename / train_model function name (no executable snippet) is downgraded."""
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="ML model instantiation",
            file_path="src/model/train.py",
            function_name="train_model",
        )
        == GRADE_SUPPORTING_LOGIC
    )


def test_effective_grade_keeps_real_ml_implementation_body() -> None:
    """A real ML implementation body (executable fit/predict/split signals in the
    trusted snippet) stays primary."""
    # LGBMClassifier + fit in the executable body.
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="model training",
            file_path="src/model/train.py",
            function_name="train_model",
            code_snippet="clf = LGBMClassifier(n_estimators=300)\nclf.fit(X_train, y_train)",
        )
        == GRADE_IMPLEMENTATION_BODY
    )
    # predict_proba inference in the executable body.
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="inference",
            file_path="app/serve.py",
            code_snippet="proba = model.predict_proba(features)[:, 1]",
        )
        == GRADE_IMPLEMENTATION_BODY
    )
    # train_test_split + evaluation metrics in the executable body.
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=True,
            reason="training + evaluation",
            file_path="src/pipeline.py",
            code_snippet=(
                "X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)\n"
                "model.fit(X_tr, y_tr)\n"
                "print(classification_report(y_te, model.predict(X_te)))"
            ),
        )
        == GRADE_IMPLEMENTATION_BODY
    )


def test_effective_grade_is_noop_for_non_ml_and_non_implementation() -> None:
    # Non-ML skill: a deployment-only body is NOT downgraded (only ML skills gate).
    assert (
        effective_evidence_grade(
            GRADE_IMPLEMENTATION_BODY,
            is_ml=False,
            reason="model serving inference handler",
            code_snippet="gcloud run deploy",
        )
        == GRADE_IMPLEMENTATION_BODY
    )
    # Non-implementation grades are always returned unchanged.
    assert (
        effective_evidence_grade(GRADE_SUPPORTING_LOGIC, is_ml=True, reason="serving handler")
        == GRADE_SUPPORTING_LOGIC
    )
    assert not ml_implementation_is_valid(code_snippet="model serving inference handler")
    assert ml_implementation_is_valid(code_snippet="clf.fit(X, y)")
