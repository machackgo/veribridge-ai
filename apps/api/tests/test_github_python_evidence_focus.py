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


# ── Code role classifier (descriptive label, never proof strength) ────────────

from app.services.github_python_evidence_focus import (  # noqa: E402
    CODE_ROLE_KEYS,
    CODE_ROLE_LABELS,
    ROLE_API_ROUTE_SHELL,
    ROLE_CONFIG_CONSTANTS,
    ROLE_DATA_LOADING,
    ROLE_DEPLOYMENT_SERVING,
    ROLE_DOCUMENTATION_HEADER,
    ROLE_EVALUATION_METRICS,
    ROLE_FEATURE_ENGINEERING,
    ROLE_IMPORTS_SETUP,
    ROLE_MODEL_TRAINING,
    ROLE_PREDICTION_INFERENCE,
    ROLE_REPOSITORY_CONTEXT,
    ROLE_UNKNOWN_NEEDS_REVIEW,
    classify_code_role,
    code_role_from_grade,
    describe_code_role,
    effective_code_role,
)


def test_code_role_labels_cover_every_key_and_fail_closed() -> None:
    assert set(CODE_ROLE_KEYS) == set(CODE_ROLE_LABELS)
    assert describe_code_role(ROLE_DOCUMENTATION_HEADER) == "Documentation / usage header"
    assert describe_code_role(ROLE_IMPORTS_SETUP) == "Imports / setup context"
    assert describe_code_role(ROLE_CONFIG_CONSTANTS) == "Config / constants"
    assert describe_code_role(ROLE_API_ROUTE_SHELL) == "API route shell"
    assert describe_code_role(ROLE_DATA_LOADING) == "Data loading context"
    assert describe_code_role(ROLE_FEATURE_ENGINEERING) == "Feature engineering context"
    assert describe_code_role(ROLE_MODEL_TRAINING) == "Model training context"
    assert describe_code_role(ROLE_EVALUATION_METRICS) == "Evaluation / metrics context"
    assert describe_code_role(ROLE_PREDICTION_INFERENCE) == "Prediction / inference context"
    assert describe_code_role(ROLE_DEPLOYMENT_SERVING) == "Deployment / serving context"
    assert describe_code_role(ROLE_REPOSITORY_CONTEXT) == "Repository-level context"
    assert describe_code_role(ROLE_UNKNOWN_NEEDS_REVIEW) == "Unknown / needs review"
    # Unknown / missing keys fail closed to the honest "Unknown / needs review".
    assert describe_code_role(None) == "Unknown / needs review"
    assert describe_code_role("made_up_role") == "Unknown / needs review"


def test_docstring_mentioning_model_fit_is_documentation_header_never_training() -> None:
    # Scenario 1: a usage header whose PROSE mentions model.fit — the grade is
    # comment_or_docstring, so the role is documentation, never model training,
    # and the row can never be implementation_body.
    snippet = '"""Retrain pipeline.\n\nUsage: model.fit(X, y) then model.predict(X).\n"""'
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    role = classify_code_role(grade=grade, code_snippet=snippet, selection_reason="ML training call")
    assert role == ROLE_DOCUMENTATION_HEADER
    assert not is_strong_grade(grade)


def test_import_block_is_imports_setup_never_training() -> None:
    # Scenario 2: sklearn imports mention classifiers, but an import-only block
    # keeps its honest imports role whatever the stale reason claims.
    snippet = (
        "import pandas as pd\n"
        "from sklearn.ensemble import RandomForestClassifier\n"
        "from lightgbm import LGBMClassifier\n"
    )
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_IMPORT_ONLY
    role = classify_code_role(grade=grade, code_snippet=snippet, selection_reason="ML training call")
    assert role == ROLE_IMPORTS_SETUP
    assert not is_strong_grade(grade)


def test_config_constants_block_is_config_role_never_implementation() -> None:
    # Scenario 3.
    snippet = 'MODEL_PATH = "models/stroke.joblib"\nRANDOM_STATE = 42\nTHRESHOLD = 0.5\n'
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_CONFIG_OR_CONSTANT
    role = classify_code_role(grade=grade, code_snippet=snippet, selection_reason="Model configuration")
    assert role == ROLE_CONFIG_CONSTANTS
    assert not is_strong_grade(grade)


def test_route_decorator_shell_is_api_route_shell_not_ml_implementation() -> None:
    # Scenario 4: a bare endpoint shell (decorator + signature, no inference).
    snippet = '@app.post("/predict")\ndef predict(req: PredictRequest):\n    ...\n'
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_ROUTE_DECORATOR_ONLY
    role = classify_code_role(grade=grade, code_snippet=snippet)
    assert role == ROLE_API_ROUTE_SHELL
    assert not is_strong_grade(grade)
    # And an ungraded route-shell snippet still reads as an API route shell from
    # its executable structure (never ML training).
    assert (
        classify_code_role(grade=None, code_snippet='@router.get("/health")\ndef health():\n    return {"ok": True}\n')
        == ROLE_API_ROUTE_SHELL
    )


def test_real_training_body_is_model_training_and_valid_ml_implementation() -> None:
    # Scenario 5: real executable LGBMClassifier + fit.
    snippet = (
        "clf = LGBMClassifier(n_estimators=200)\n"
        "clf.fit(X_train, y_train)\n"
        "joblib.dump(clf, MODEL_PATH)\n"
    )
    role = classify_code_role(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet)
    assert role == ROLE_MODEL_TRAINING
    # Existing executable-ML validation accepts it as implementation_body.
    assert ml_implementation_is_valid(code_snippet=snippet)
    assert (
        effective_evidence_grade(GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=snippet)
        == GRADE_IMPLEMENTATION_BODY
    )


def test_real_predict_proba_body_is_prediction_inference() -> None:
    # Scenario 6.
    snippet = "features = build_features(payload)\nproba = model.predict_proba(features)[:, 1]\nreturn {\"risk\": float(proba)}\n"
    role = classify_code_role(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet)
    assert role == ROLE_PREDICTION_INFERENCE
    assert ml_implementation_is_valid(code_snippet=snippet)


def test_evaluation_metrics_body_is_evaluation_role() -> None:
    # Scenario 7 (no .fit/.predict in the body — metrics only).
    snippet = "acc = accuracy_score(y_te, y_pred)\nprint(classification_report(y_te, y_pred))\n"
    assert classify_code_role(grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet) == ROLE_EVALUATION_METRICS


def test_training_body_that_also_scores_still_reads_as_model_training() -> None:
    # Priority order: training beats evaluation when both appear in one body.
    snippet = "model.fit(X_tr, y_tr)\nacc = accuracy_score(y_te, model.predict(X_te))\n"
    assert classify_code_role(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet) == ROLE_MODEL_TRAINING


def test_deployment_only_body_is_deployment_serving_not_ml_implementation() -> None:
    # Scenario 8: serving/cloud plumbing with no ML inference/training.
    snippet = 'uvicorn.run(app, host="0.0.0.0", port=8080)\n'
    role = classify_code_role(grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet)
    assert role == ROLE_DEPLOYMENT_SERVING
    assert not ml_implementation_is_valid(code_snippet=snippet)
    # The existing ML gate still downgrades it out of implementation_body.
    assert (
        effective_evidence_grade(GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=snippet)
        != GRADE_IMPLEMENTATION_BODY
    )


def test_data_loading_block_is_data_loading_role() -> None:
    # Scenario 9.
    snippet = 'df = pd.read_csv("data/stroke.csv")\ndf = df.dropna()\n'
    assert classify_code_role(grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet) == ROLE_DATA_LOADING


def test_feature_engineering_block_is_feature_role() -> None:
    # Scenario 10.
    snippet = "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)\n"
    assert classify_code_role(grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet) == ROLE_FEATURE_ENGINEERING


def test_docstring_only_snippet_never_yields_a_semantic_role() -> None:
    # Comments/docstrings are structurally stripped: prose mentioning fit/predict
    # in an otherwise weak/ungraded row falls to repository context, not training.
    snippet = "# model.fit(X, y) then model.predict_proba(X)\n"
    assert classify_code_role(grade=None, code_snippet=snippet) == ROLE_REPOSITORY_CONTEXT


def test_code_role_from_grade_conservative_fallbacks() -> None:
    assert code_role_from_grade(GRADE_COMMENT_OR_DOCSTRING) == ROLE_DOCUMENTATION_HEADER
    assert code_role_from_grade(GRADE_IMPORT_ONLY) == ROLE_IMPORTS_SETUP
    assert code_role_from_grade(GRADE_CONFIG_OR_CONSTANT) == ROLE_CONFIG_CONSTANTS
    assert code_role_from_grade(GRADE_ROUTE_DECORATOR_ONLY) == ROLE_API_ROUTE_SHELL
    assert code_role_from_grade(GRADE_REPO_LEVEL_FALLBACK) == ROLE_REPOSITORY_CONTEXT
    assert code_role_from_grade(None) == ROLE_REPOSITORY_CONTEXT
    assert code_role_from_grade("nonsense") == ROLE_REPOSITORY_CONTEXT
    # A strong grade alone says nothing about WHICH kind of body it is.
    assert code_role_from_grade(GRADE_IMPLEMENTATION_BODY) == ROLE_UNKNOWN_NEEDS_REVIEW


def test_effective_code_role_stale_weak_row_never_keeps_overclaiming_role() -> None:
    # Scenario 11: a stale weak row — whatever role/reason it carries, the
    # validated weak structural grade wins (fail closed).
    assert (
        effective_code_role(ROLE_MODEL_TRAINING, grade=GRADE_IMPORT_ONLY, selection_reason="ML training call")
        == ROLE_IMPORTS_SETUP
    )
    assert (
        effective_code_role(None, grade=GRADE_COMMENT_OR_DOCSTRING, selection_reason="Cloud deployment command")
        == ROLE_DOCUMENTATION_HEADER
    )
    # Ungraded legacy row with only a stale overclaiming reason → repository
    # context; the reason is never trusted for a weak/ungraded row.
    assert effective_code_role(None, grade=None, selection_reason="ML training call") == ROLE_REPOSITORY_CONTEXT
    assert (
        effective_code_role(None, grade=GRADE_REPO_LEVEL_FALLBACK, selection_reason="Model serving handler")
        == ROLE_REPOSITORY_CONTEXT
    )


def test_effective_code_role_keeps_server_derived_role_and_reason_hint_for_strong_rows() -> None:
    # A server-derived role on a strong row is kept as-is.
    assert effective_code_role(ROLE_MODEL_TRAINING, grade=GRADE_IMPLEMENTATION_BODY) == ROLE_MODEL_TRAINING
    # A strong row with no role and no snippet may use a conservative reason hint
    # (descriptive only — the grade is already validated elsewhere).
    assert (
        effective_code_role(None, grade=GRADE_IMPLEMENTATION_BODY, selection_reason="ML training call")
        == ROLE_MODEL_TRAINING
    )
    # A strong row with nothing to describe it stays honest.
    assert effective_code_role(None, grade=GRADE_IMPLEMENTATION_BODY) == ROLE_UNKNOWN_NEEDS_REVIEW


# ── Code block purpose classifier (block-level explanation, never proof) ──────

from app.services.github_python_evidence_focus import (  # noqa: E402
    CODE_BLOCK_PURPOSE_KEYS,
    CODE_BLOCK_PURPOSE_LABELS,
    PURPOSE_API_PREDICTION_HANDLER,
    PURPOSE_API_REQUEST_SCHEMA,
    PURPOSE_API_ROUTE_SHELL,
    PURPOSE_ARTIFACT_PERSISTENCE,
    PURPOSE_CLOUD_STORAGE_IO,
    PURPOSE_CONFIG_PATHS_ARTIFACTS,
    PURPOSE_DATA_LOADING,
    PURPOSE_DEPLOYMENT_SERVING,
    PURPOSE_DOCUMENTATION_OVERVIEW,
    PURPOSE_FRONTEND_UI_COMPONENT,
    PURPOSE_IMPORTS_DEPENDENCIES,
    PURPOSE_MODEL_EVALUATION,
    PURPOSE_MODEL_LOADING,
    PURPOSE_MODEL_TRAINING,
    PURPOSE_PIPELINE_DOCUMENTATION,
    PURPOSE_PREDICTION_INFERENCE,
    PURPOSE_PREPROCESSING_FEATURES,
    PURPOSE_REPOSITORY_CONTEXT,
    PURPOSE_RETRAINING_DOCUMENTATION,
    PURPOSE_TEST_VALIDATION,
    PURPOSE_UNKNOWN_NEEDS_REVIEW,
    PURPOSE_USAGE_INSTRUCTIONS,
    classify_code_block_purpose,
    code_block_purpose_summary,
    describe_code_block_purpose,
    effective_code_block_purpose,
)

# The exact module docstring shape from scripts/pipeline_retrain.py lines 2-20:
# prose describing the retraining pipeline (challenger dataset, LightGBM,
# threshold tuning, GCS artifacts) — meaningful documentation, never proof.
_RETRAIN_DOC = (
    '"""Retraining pipeline.\n\n'
    "Reads the merged challenger dataset, runs spatial features + preprocessing\n"
    "+ LightGBM + threshold tuning, evaluates against the champion, and writes\n"
    'artifacts/reports to GCS.\n"""'
)


def test_purpose_labels_and_summaries_cover_every_key_and_fail_closed() -> None:
    assert set(CODE_BLOCK_PURPOSE_KEYS) == set(CODE_BLOCK_PURPOSE_LABELS)
    for key in CODE_BLOCK_PURPOSE_KEYS:
        label = describe_code_block_purpose(key)
        summary = code_block_purpose_summary(key)
        # Every purpose has a short, non-empty, recruiter-readable label + summary.
        assert label and len(label) < 60
        assert summary and len(summary) < 160
    assert describe_code_block_purpose(PURPOSE_RETRAINING_DOCUMENTATION) == (
        "Documentation describing retraining pipeline"
    )
    assert describe_code_block_purpose(PURPOSE_IMPORTS_DEPENDENCIES) == "Imports / dependency setup"
    assert describe_code_block_purpose(PURPOSE_CONFIG_PATHS_ARTIFACTS) == "Config / artifact paths"
    assert describe_code_block_purpose(PURPOSE_MODEL_TRAINING) == "Model training"
    assert describe_code_block_purpose(PURPOSE_MODEL_EVALUATION) == "Evaluation / metrics"
    assert describe_code_block_purpose(PURPOSE_PREDICTION_INFERENCE) == "Prediction / inference"
    # Unknown / missing keys fail closed.
    assert describe_code_block_purpose(None) == "Unknown / needs review"
    assert describe_code_block_purpose("made_up") == "Unknown / needs review"
    assert "needs review" in code_block_purpose_summary("made_up")


def test_retraining_docstring_is_documentation_purpose_never_implementation() -> None:
    # Task E scenario 1: the pipeline_retrain.py module docstring header.
    grade = grade_python_snippet(_RETRAIN_DOC)
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=_RETRAIN_DOC, selection_reason="ML training call"
    )
    assert purpose == PURPOSE_RETRAINING_DOCUMENTATION
    # Never implementation: the grade stays weak and the ML gate rejects prose.
    assert not is_strong_grade(grade)
    assert not has_ml_executable_signal(_RETRAIN_DOC)
    # The summary states the limitation in plain language.
    assert "not executable training code" in code_block_purpose_summary(purpose)


def test_docstring_purpose_topics_stay_inside_the_documentation_family() -> None:
    # A docstring that mentions the pipeline (but not retraining).
    doc = '"""Train the stroke model and write evaluation artifacts."""'
    assert (
        classify_code_block_purpose(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=doc)
        == PURPOSE_PIPELINE_DOCUMENTATION
    )
    # A pure usage header.
    usage = '"""Usage: python run.py --input data.csv"""'
    assert (
        classify_code_block_purpose(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=usage)
        == PURPOSE_USAGE_INSTRUCTIONS
    )
    # A docstring with no recognizable topic — generic documentation, and a
    # docstring row with NO snippet at read time also stays documentation.
    assert (
        classify_code_block_purpose(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet='"""Hello."""')
        == PURPOSE_DOCUMENTATION_OVERVIEW
    )
    assert (
        classify_code_block_purpose(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=None)
        == PURPOSE_DOCUMENTATION_OVERVIEW
    )
    # A docstring that mentions model.fit(...) is documentation ABOUT training —
    # never the executable "Model training" purpose.
    fit_doc = '"""Usage: model.fit(X, y) then model.predict(X)."""'
    purpose = classify_code_block_purpose(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=fit_doc)
    assert purpose != PURPOSE_MODEL_TRAINING
    assert purpose in {
        PURPOSE_RETRAINING_DOCUMENTATION,
        PURPOSE_PIPELINE_DOCUMENTATION,
        PURPOSE_USAGE_INSTRUCTIONS,
        PURPOSE_DOCUMENTATION_OVERVIEW,
    }


def test_import_block_purpose_is_imports_dependencies() -> None:
    # Task E scenario 2: pipeline_retrain.py lines 29-47 (imports/setup).
    snippet = "import pandas as pd\nfrom lightgbm import LGBMClassifier\n"
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_IMPORT_ONLY
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=snippet, selection_reason="ML training call"
    )
    assert purpose == PURPOSE_IMPORTS_DEPENDENCIES
    assert "not implementation proof" in code_block_purpose_summary(purpose)


def test_gcs_path_constants_purpose_is_config_or_cloud_storage() -> None:
    # Task E scenario 3: GCS paths / artifact names.
    snippet = (
        'MODEL_URI = "gs://ml-artifacts/champion/model.joblib"\n'
        'REPORT_URI = "gs://ml-artifacts/reports/latest.json"\n'
    )
    grade = grade_python_snippet(snippet)
    assert grade == GRADE_CONFIG_OR_CONSTANT
    purpose = classify_code_block_purpose(grade=grade, code_snippet=snippet)
    assert purpose in {PURPOSE_CONFIG_PATHS_ARTIFACTS, PURPOSE_CLOUD_STORAGE_IO}
    # Plain (non-cloud) constants stay config/artifact paths.
    plain = 'MODEL_PATH = "models/stroke.joblib"\nRANDOM_STATE = 42\n'
    assert (
        classify_code_block_purpose(grade=GRADE_CONFIG_OR_CONSTANT, code_snippet=plain)
        == PURPOSE_CONFIG_PATHS_ARTIFACTS
    )


def test_real_training_body_purpose_is_model_training_and_ml_valid() -> None:
    # Task E scenario 4: real LGBMClassifier + fit.
    snippet = "clf = LGBMClassifier(n_estimators=200)\nclf.fit(X_train, y_train)\n"
    purpose = classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet)
    assert purpose == PURPOSE_MODEL_TRAINING
    assert ml_implementation_is_valid(code_snippet=snippet)
    assert (
        effective_evidence_grade(GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=snippet)
        == GRADE_IMPLEMENTATION_BODY
    )


def test_real_evaluation_metrics_purpose_is_model_evaluation() -> None:
    # Task E scenario 5.
    snippet = "acc = accuracy_score(y_te, y_pred)\nprint(classification_report(y_te, y_pred))\n"
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet)
        == PURPOSE_MODEL_EVALUATION
    )


def test_real_predict_proba_purpose_is_prediction_inference() -> None:
    # Task E scenario 6.
    snippet = "proba = model.predict_proba(features)[:, 1]\nreturn float(proba)\n"
    assert (
        classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet)
        == PURPOSE_PREDICTION_INFERENCE
    )


def test_fastapi_route_and_schema_purposes_are_api_context_not_ml() -> None:
    # Task E scenario 7: a bare route shell and a request-schema class.
    shell = '@app.post("/predict")\ndef predict(req: PredictRequest):\n    ...\n'
    grade = grade_python_snippet(shell)
    assert grade == GRADE_ROUTE_DECORATOR_ONLY
    assert classify_code_block_purpose(grade=grade, code_snippet=shell) == PURPOSE_API_ROUTE_SHELL
    schema = (
        "class PredictRequest(BaseModel):\n"
        "    age: int\n"
        "    hypertension: bool\n"
        "    validate = validator('age')\n"
    )
    assert (
        classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=schema)
        == PURPOSE_API_REQUEST_SCHEMA
    )
    # Neither is valid ML implementation.
    assert not ml_implementation_is_valid(code_snippet=shell)
    assert not ml_implementation_is_valid(code_snippet=schema)
    # A route handler that ACTUALLY calls model inference is the specific
    # "API prediction handler" purpose (and passes the ML gate).
    handler = (
        '@app.post("/predict")\n'
        "def predict(req: PredictRequest):\n"
        "    proba = model.predict_proba(req.features())\n"
        "    return {\"risk\": float(proba[0, 1])}\n"
    )
    assert (
        classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=handler)
        == PURPOSE_API_PREDICTION_HANDLER
    )
    assert ml_implementation_is_valid(code_snippet=handler)


def test_deployment_and_cloud_only_purposes_are_never_ml_implementation() -> None:
    # Task E scenario 8: deployment-only / cloud-storage-only executable code.
    deploy = 'uvicorn.run(app, host="0.0.0.0", port=8080)\n'
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=deploy)
        == PURPOSE_DEPLOYMENT_SERVING
    )
    assert not ml_implementation_is_valid(code_snippet=deploy)
    assert (
        effective_evidence_grade(GRADE_IMPLEMENTATION_BODY, is_ml=True, code_snippet=deploy)
        != GRADE_IMPLEMENTATION_BODY
    )
    cloud = (
        "client = storage.Client()\n"
        "bucket = client.bucket(BUCKET)\n"
        'bucket.blob("model.joblib").upload_from_filename(path)\n'
    )
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=cloud)
        == PURPOSE_CLOUD_STORAGE_IO
    )
    assert not ml_implementation_is_valid(code_snippet=cloud)


def test_model_loading_and_artifact_persistence_purposes() -> None:
    load = "model = joblib.load(MODEL_PATH)\n"
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=load)
        == PURPOSE_MODEL_LOADING
    )
    save = "joblib.dump(scaler, SCALER_PATH)\n"
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=save)
        == PURPOSE_ARTIFACT_PERSISTENCE
    )


def test_data_loading_and_preprocessing_purposes() -> None:
    load = 'df = pd.read_csv("data/stroke.csv")\ndf = df.dropna()\n'
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=load)
        == PURPOSE_DATA_LOADING
    )
    features = "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)\n"
    assert (
        classify_code_block_purpose(grade=GRADE_SUPPORTING_LOGIC, code_snippet=features)
        == PURPOSE_PREPROCESSING_FEATURES
    )


def test_test_file_and_frontend_paths_get_honest_context_purposes() -> None:
    # A test file calling .fit() is TEST code — the purpose says so honestly
    # (the grade/ML gate is a separate concern and is not changed by the label).
    snippet = "model.fit(X, y)\nassert model.predict(X).shape == y.shape\n"
    assert (
        classify_code_block_purpose(
            grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet, file_path="tests/test_train.py"
        )
        == PURPOSE_TEST_VALIDATION
    )
    assert (
        classify_code_block_purpose(
            grade=GRADE_SUPPORTING_LOGIC,
            code_snippet="export function RiskCard() { return <div/> }\n",
            file_path="src/components/RiskCard.tsx",
        )
        == PURPOSE_FRONTEND_UI_COMPONENT
    )


def test_path_derived_purposes_are_non_promoting_even_when_ungraded() -> None:
    # A test/frontend PATH may label an ungraded row (the path is already a safe,
    # displayed locator) because both purposes are strictly NON-promoting: they
    # make a row read as test/UI context, never as ML implementation. The row's
    # grade/strength is untouched — it stays a weak, needs-review signal.
    assert (
        classify_code_block_purpose(grade=None, file_path="tests/test_train.py")
        == PURPOSE_TEST_VALIDATION
    )
    assert (
        classify_code_block_purpose(grade=None, file_path="src/App.tsx")
        == PURPOSE_FRONTEND_UI_COMPONENT
    )
    # But a weak STRUCTURAL band still wins over the path: an import block in a
    # frontend file is still an imports block.
    assert (
        classify_code_block_purpose(grade=GRADE_IMPORT_ONLY, file_path="src/App.tsx")
        == PURPOSE_IMPORTS_DEPENDENCIES
    )


def test_stale_weak_row_purpose_never_keeps_overclaiming_text() -> None:
    # Task E scenario 9: a stale weak row with an old overclaiming reason. The
    # validated weak band always wins; the reason text never decides the purpose.
    assert (
        effective_code_block_purpose(
            PURPOSE_MODEL_TRAINING, grade=GRADE_IMPORT_ONLY, selection_reason="ML training call"
        )
        == PURPOSE_IMPORTS_DEPENDENCIES
    )
    assert (
        effective_code_block_purpose(
            None, grade=GRADE_ROUTE_DECORATOR_ONLY, selection_reason="ML prediction"
        )
        == PURPOSE_API_ROUTE_SHELL
    )
    # Ungraded legacy rows fail closed to repository context.
    assert (
        effective_code_block_purpose(None, grade=None, selection_reason="ML training call")
        == PURPOSE_REPOSITORY_CONTEXT
    )
    assert (
        effective_code_block_purpose(
            None, grade=GRADE_REPO_LEVEL_FALLBACK, selection_reason="Cloud deployment command"
        )
        == PURPOSE_REPOSITORY_CONTEXT
    )


def test_effective_purpose_keeps_refined_documentation_topic_within_family() -> None:
    # A snippet-refined documentation topic computed upstream SURVIVES read-time
    # resolution (it is inside the docstring family) even when the snippet is no
    # longer available…
    assert (
        effective_code_block_purpose(
            PURPOSE_RETRAINING_DOCUMENTATION, grade=GRADE_COMMENT_OR_DOCSTRING
        )
        == PURPOSE_RETRAINING_DOCUMENTATION
    )
    # …but an executable purpose riding on a docstring row is discarded.
    assert (
        effective_code_block_purpose(PURPOSE_MODEL_TRAINING, grade=GRADE_COMMENT_OR_DOCSTRING)
        == PURPOSE_DOCUMENTATION_OVERVIEW
    )
    # A server-derived purpose on a strong row is kept as-is; a strong row with
    # nothing to describe it stays honest.
    assert (
        effective_code_block_purpose(PURPOSE_MODEL_TRAINING, grade=GRADE_IMPLEMENTATION_BODY)
        == PURPOSE_MODEL_TRAINING
    )
    assert (
        effective_code_block_purpose(None, grade=GRADE_IMPLEMENTATION_BODY)
        == PURPOSE_UNKNOWN_NEEDS_REVIEW
    )
    # A strong row with no snippet NEVER borrows an executable purpose from its
    # stored reason — reason-only rows stay Unknown / needs review.
    assert (
        effective_code_block_purpose(
            None, grade=GRADE_IMPLEMENTATION_BODY, selection_reason="ML training call"
        )
        == PURPOSE_UNKNOWN_NEEDS_REVIEW
    )


def test_reason_only_strong_row_purpose_is_unknown_needs_review() -> None:
    # Codex must-fix: a STRONG row whose only "evidence" is a stored
    # selection_reason (no trusted snippet / executable text) must NEVER be
    # labelled with an executable purpose — it fails closed to unknown.
    for reason in ("ML model training", "Prediction / inference", "Evaluation / metrics"):
        assert (
            classify_code_block_purpose(
                grade=GRADE_IMPLEMENTATION_BODY, code_snippet=None, selection_reason=reason
            )
            == PURPOSE_UNKNOWN_NEEDS_REVIEW
        )
        # A snippet that strips to nothing executable is the same as no snippet.
        assert (
            classify_code_block_purpose(
                grade=GRADE_SUPPORTING_LOGIC,
                code_snippet="# TODO: train the model here\n",
                selection_reason=reason,
            )
            == PURPOSE_UNKNOWN_NEEDS_REVIEW
        )
    # Real trusted executable text still classifies normally.
    assert (
        classify_code_block_purpose(
            grade=GRADE_IMPLEMENTATION_BODY,
            code_snippet="clf = LGBMClassifier()\nclf.fit(X_train, y_train)\n",
            selection_reason="ML model training",
        )
        == PURPOSE_MODEL_TRAINING
    )
    assert (
        classify_code_block_purpose(
            grade=GRADE_IMPLEMENTATION_BODY,
            code_snippet="proba = model.predict_proba(X)[:, 1]\n",
            selection_reason="Prediction / inference",
        )
        == PURPOSE_PREDICTION_INFERENCE
    )
    assert (
        classify_code_block_purpose(
            grade=GRADE_IMPLEMENTATION_BODY,
            code_snippet="print(classification_report(y_te, y_pred))\n",
            selection_reason="Evaluation / metrics",
        )
        == PURPOSE_MODEL_EVALUATION
    )


def test_purpose_vocabulary_is_safe_static_strings() -> None:
    # Task E scenario 10: every label/summary is a plain static string — no
    # braces/templating, no markup, nothing that could smuggle raw snippet text.
    for key, label in CODE_BLOCK_PURPOSE_LABELS.items():
        assert isinstance(key, str) and isinstance(label, str)
        for banned in ("{", "}", "<", ">", "\n"):
            assert banned not in label
    for key in CODE_BLOCK_PURPOSE_KEYS:
        summary = code_block_purpose_summary(key)
        for banned in ("{", "}", "<", ">", "\n"):
            assert banned not in summary


# ── Skill relevance (block ↔ selected skill relation, never proof) ────────────

from app.services.github_python_evidence_focus import (  # noqa: E402
    PURPOSE_AUTH_PERMISSION_CHECK,
    PURPOSE_CI_CD_WORKFLOW,
    PURPOSE_CONTAINERIZATION,
    PURPOSE_DATA_TRANSFORMATION,
    PURPOSE_DATA_VISUALIZATION,
    PURPOSE_DATABASE_OPERATION,
    PURPOSE_EMBEDDING_GENERATION,
    PURPOSE_HYPERPARAMETER_TUNING,
    PURPOSE_IMAGE_PROCESSING_CV,
    PURPOSE_LLM_CALL_WRAPPER,
    PURPOSE_RAG_RETRIEVAL,
    PURPOSE_TEXT_NLP_PROCESSING,
    RELEVANCE_CONTEXT_ONLY,
    RELEVANCE_CROSS_SKILL_CONTEXT,
    RELEVANCE_DEPLOYMENT_CONTEXT,
    RELEVANCE_DIRECT_CANDIDATE,
    RELEVANCE_DIRECT_IMPLEMENTATION,
    RELEVANCE_DOCUMENTATION_CONTEXT,
    RELEVANCE_PRODUCT_UI_CONTEXT,
    RELEVANCE_SETUP_CONTEXT,
    RELEVANCE_SUPPORTING_CONTEXT,
    RELEVANCE_SUPPORTING_IMPLEMENTATION,
    RELEVANCE_TEST_CONTEXT,
    SKILL_RELEVANCE_KEYS,
    classify_skill_relevance,
    describe_skill_relevance,
    is_skill_code_relevance,
    is_skill_implementation_relevance,
    skill_family,
    skill_relevance_summary,
)


def test_new_multiskill_purposes_classify_from_executable_source() -> None:
    cases = [
        ("gs = GridSearchCV(model, params)\ngs.fit(X, y)\n", PURPOSE_HYPERPARAMETER_TUNING),
        ("tokens = word_tokenize(text)\n", PURPOSE_TEXT_NLP_PROCESSING),
        ("model = SentenceTransformer('all-MiniLM-L6-v2')\n", PURPOSE_EMBEDDING_GENERATION),
        (
            "client = Anthropic()\nresp = client.messages.create(model='m', max_tokens=10)\n",
            PURPOSE_LLM_CALL_WRAPPER,
        ),
        ("docs = store.similarity_search(query, k=4)\n", PURPOSE_RAG_RETRIEVAL),
        ("img = cv2.imread(path)\nimg = cv2.resize(img, (224, 224))\n", PURPOSE_IMAGE_PROCESSING_CV),
        ("cursor.execute(sql, params)\nrows = cursor.fetchall()\n", PURPOSE_DATABASE_OPERATION),
        ("payload = jwt.decode(token, key, algorithms=['HS256'])\n", PURPOSE_AUTH_PERMISSION_CHECK),
        ("plt.scatter(x, y)\nplt.savefig(out)\n", PURPOSE_DATA_VISUALIZATION),
    ]
    for snippet, expected in cases:
        assert (
            classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet)
            == expected
        ), snippet


def test_infrastructure_purposes_classify_from_path() -> None:
    assert (
        classify_code_block_purpose(grade=None, file_path=".github/workflows/deploy.yml")
        == PURPOSE_CI_CD_WORKFLOW
    )
    assert (
        classify_code_block_purpose(grade=None, file_path="Dockerfile")
        == PURPOSE_CONTAINERIZATION
    )
    assert (
        classify_code_block_purpose(grade=None, file_path="services/api/docker-compose.prod.yaml")
        == PURPOSE_CONTAINERIZATION
    )


def test_docstring_mentioning_tuning_stays_documentation() -> None:
    # A docstring that TALKS about GridSearchCV can only ever be documentation.
    assert (
        classify_code_block_purpose(
            grade=GRADE_COMMENT_OR_DOCSTRING,
            code_snippet='"""Runs GridSearchCV hyperparameter tuning over the model."""',
        )
        == PURPOSE_PIPELINE_DOCUMENTATION
    )


def test_skill_family_detection_is_specific_first_and_fails_open_to_general() -> None:
    assert skill_family("Machine Learning") == "ml"
    assert skill_family("Deep Learning") == "ml"
    assert skill_family("NLP") == "nlp"
    assert skill_family("Natural Language Processing") == "nlp"
    assert skill_family("Computer Vision") == "cv"
    assert skill_family("Generative AI") == "genai"
    assert skill_family("React") == "frontend"
    assert skill_family("FastAPI") == "backend"
    assert skill_family("DevOps") == "devops"
    assert skill_family("Docker") == "devops"
    assert skill_family("Security") == "security"
    assert skill_family("SQL") == "data"
    assert skill_family("Python") == "language"
    assert skill_family("Interpretive Dance") == "general"
    assert skill_family(None) == "general"
    assert skill_family("") == "general"
    # Database skills are data-family (database_operation is direct evidence).
    for db_skill in ("PostgreSQL", "MySQL", "MongoDB", "Redis", "Supabase", "Firebase"):
        assert skill_family(db_skill) == "data", db_skill
    assert skill_family("Bash") == "language"
    assert skill_family("MLOps") == "devops"
    assert skill_family("GraphQL") == "backend"
    # Unmapped/future IT skills fail closed to general until mapped centrally.
    assert skill_family("Flutter") == "general"
    assert skill_family("Blockchain Development") == "general"


def test_database_and_spark_bodies_classify_specifically() -> None:
    """SQL/DBAPI and Spark ETL executable bodies get specific purposes (not
    unknown_needs_review) and direct relevance for their owning families."""
    sql = "cur.execute('SELECT id, risk FROM patients WHERE age > %s', (50,))"
    p = classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=sql)
    assert p == PURPOSE_DATABASE_OPERATION
    assert (
        classify_skill_relevance(p, skill="PostgreSQL", grade=GRADE_IMPLEMENTATION_BODY)
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    etl = (
        "out = df.withColumnRenamed('a','b').dropDuplicates()\n"
        "out.write.mode('append').saveAsTable('gold.events')"
    )
    p2 = classify_code_block_purpose(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=etl)
    assert p2 == PURPOSE_DATA_TRANSFORMATION
    assert (
        classify_skill_relevance(
            p2, skill="Data Engineering", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    spark_read = "raw = spark.read.parquet('s3://bucket/raw')\nprint(raw.count())"
    p3 = classify_code_block_purpose(
        grade=GRADE_IMPLEMENTATION_BODY, code_snippet=spark_read
    )
    assert p3 == PURPOSE_DATA_LOADING


def test_ml_training_block_is_direct_only_when_grade_is_strong() -> None:
    # Tree.py lines 13-72: executable decision-tree training for a Machine
    # Learning report — direct implementation evidence ONLY on a strong grade.
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    # HARD RULE (Codex must-fix): ``supporting_logic`` is SUPPORTING code evidence
    # — it must never read as "Direct … implementation evidence".
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="Machine Learning", grade=GRADE_SUPPORTING_LOGIC
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )
    # HARD RULE: an in-family purpose on a non-strong grade NEVER upgrades — it
    # reads as an explicit needs-review candidate.
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="Machine Learning", grade=GRADE_REPO_LEVEL_FALLBACK
        )
        == RELEVANCE_DIRECT_CANDIDATE
    )
    assert (
        classify_skill_relevance(PURPOSE_MODEL_TRAINING, skill="Machine Learning", grade=None)
        == RELEVANCE_DIRECT_CANDIDATE
    )


def test_frontend_ui_is_product_context_for_ml_but_direct_for_react() -> None:
    # page.tsx risk-input form: for Machine Learning it is product UI context,
    # never ML implementation; for a React report the same block is direct.
    assert (
        classify_skill_relevance(
            PURPOSE_FRONTEND_UI_COMPONENT, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_PRODUCT_UI_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_FRONTEND_UI_COMPONENT, skill="React", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    label = describe_skill_relevance(RELEVANCE_PRODUCT_UI_CONTEXT, "Machine Learning")
    assert label == "Product UI context, not Machine Learning implementation"


def test_api_shells_and_handlers_relate_by_skill() -> None:
    # A bare route shell: supporting context for Backend, adjacent for ML.
    assert (
        classify_skill_relevance(
            PURPOSE_API_ROUTE_SHELL, skill="Backend Development", grade=GRADE_ROUTE_DECORATOR_ONLY
        )
        == RELEVANCE_SUPPORTING_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_API_ROUTE_SHELL, skill="Machine Learning", grade=GRADE_ROUTE_DECORATOR_ONLY
        )
        == RELEVANCE_CROSS_SKILL_CONTEXT
    )
    # stroke_api.py predict endpoint WITH executable inference: direct backend
    # evidence, supporting ML deployment/inference evidence.
    assert (
        classify_skill_relevance(
            PURPOSE_API_PREDICTION_HANDLER, skill="FastAPI", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_API_PREDICTION_HANDLER, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )


def test_docs_imports_config_are_always_their_own_context_for_every_skill() -> None:
    for skill in ("Machine Learning", "React", "DevOps", "Python", "Anything Else"):
        assert (
            classify_skill_relevance(
                PURPOSE_RETRAINING_DOCUMENTATION, skill=skill, grade=GRADE_COMMENT_OR_DOCSTRING
            )
            == RELEVANCE_DOCUMENTATION_CONTEXT
        )
        assert (
            classify_skill_relevance(
                PURPOSE_IMPORTS_DEPENDENCIES, skill=skill, grade=GRADE_IMPORT_ONLY
            )
            == RELEVANCE_SETUP_CONTEXT
        )
        assert (
            classify_skill_relevance(
                PURPOSE_CONFIG_PATHS_ARTIFACTS, skill=skill, grade=GRADE_CONFIG_OR_CONSTANT
            )
            == RELEVANCE_SETUP_CONTEXT
        )


def test_infrastructure_reads_as_deployment_context_for_ml_but_direct_for_devops() -> None:
    for purpose in (
        PURPOSE_DEPLOYMENT_SERVING,
        PURPOSE_CI_CD_WORKFLOW,
        PURPOSE_CONTAINERIZATION,
        PURPOSE_CLOUD_STORAGE_IO,
    ):
        assert (
            classify_skill_relevance(purpose, skill="DevOps", grade=GRADE_IMPLEMENTATION_BODY)
            == RELEVANCE_DIRECT_IMPLEMENTATION
        ), purpose
    assert (
        classify_skill_relevance(
            PURPOSE_CI_CD_WORKFLOW, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DEPLOYMENT_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_CONTAINERIZATION, skill="Machine Learning", grade=None
        )
        == RELEVANCE_DEPLOYMENT_CONTEXT
    )


def test_cross_family_evidence_never_counts_toward_the_selected_skill() -> None:
    # HARD RULE: model training can never read as direct/supporting evidence for
    # a DevOps or frontend report — it stays adjacent context.
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="DevOps", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_CROSS_SKILL_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="React", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_CROSS_SKILL_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_AUTH_PERMISSION_CHECK, skill="Computer Vision", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_CROSS_SKILL_CONTEXT
    )


def test_ml_subfamilies_accept_core_ml_pipeline_as_supporting() -> None:
    assert (
        classify_skill_relevance(PURPOSE_MODEL_TRAINING, skill="NLP", grade=GRADE_IMPLEMENTATION_BODY)
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_LLM_CALL_WRAPPER, skill="Generative AI", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_IMAGE_PROCESSING_CV, skill="Computer Vision", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_EMBEDDING_GENERATION, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )


def test_language_and_general_skills_never_get_direct_claims() -> None:
    # A Python report: executable purposes are supporting language evidence.
    assert (
        classify_skill_relevance(
            PURPOSE_MODEL_TRAINING, skill="Python", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(PURPOSE_MODEL_TRAINING, skill="Python", grade=None)
        == RELEVANCE_SUPPORTING_CONTEXT
    )
    # An unrecognized skill fails closed — weak rows are context-only.
    assert (
        classify_skill_relevance(PURPOSE_MODEL_TRAINING, skill="Interpretive Dance", grade=None)
        == RELEVANCE_CONTEXT_ONLY
    )


def test_tests_and_unknowns_fail_closed() -> None:
    assert (
        classify_skill_relevance(
            PURPOSE_TEST_VALIDATION, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_TEST_CONTEXT
    )
    assert (
        classify_skill_relevance(
            PURPOSE_TEST_VALIDATION, skill="Test Automation", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(PURPOSE_REPOSITORY_CONTEXT, skill="Machine Learning", grade=None)
        == RELEVANCE_CONTEXT_ONLY
    )
    assert (
        classify_skill_relevance(PURPOSE_UNKNOWN_NEEDS_REVIEW, skill="Machine Learning", grade=None)
        == RELEVANCE_CONTEXT_ONLY
    )
    # Unknown purpose key entirely → context only (fail closed).
    assert classify_skill_relevance("no_such_purpose", skill="Machine Learning") == RELEVANCE_CONTEXT_ONLY
    assert classify_skill_relevance(None, skill="Machine Learning") == RELEVANCE_CONTEXT_ONLY


def test_skill_implementation_relevance_gate_is_a_strict_allowlist() -> None:
    """Only direct/supporting IMPLEMENTATION relevances may gate "Demonstrated" /
    primary synthesis. Every context key, the needs-review candidate, unknown keys
    and None fail closed."""
    assert is_skill_implementation_relevance(RELEVANCE_DIRECT_IMPLEMENTATION)
    assert is_skill_implementation_relevance(RELEVANCE_SUPPORTING_IMPLEMENTATION)
    for key in (
        RELEVANCE_DIRECT_CANDIDATE,
        RELEVANCE_SUPPORTING_CONTEXT,
        RELEVANCE_CROSS_SKILL_CONTEXT,
        RELEVANCE_PRODUCT_UI_CONTEXT,
        RELEVANCE_DEPLOYMENT_CONTEXT,
        RELEVANCE_DOCUMENTATION_CONTEXT,
        RELEVANCE_SETUP_CONTEXT,
        RELEVANCE_TEST_CONTEXT,
        RELEVANCE_CONTEXT_ONLY,
        "no_such_key",
        None,
    ):
        assert not is_skill_implementation_relevance(key), key


def test_skill_code_relevance_excludes_positive_other_skill_contexts() -> None:
    """Cross-skill / product-UI / deployment / docs / setup relevance is never this
    skill's code evidence (not even "supporting"); unknown/needs-review keys are
    left to the deterministic grade."""
    for key in (
        RELEVANCE_CROSS_SKILL_CONTEXT,
        RELEVANCE_PRODUCT_UI_CONTEXT,
        RELEVANCE_DEPLOYMENT_CONTEXT,
        RELEVANCE_DOCUMENTATION_CONTEXT,
        RELEVANCE_SETUP_CONTEXT,
    ):
        assert not is_skill_code_relevance(key), key
    for key in (
        RELEVANCE_DIRECT_IMPLEMENTATION,
        RELEVANCE_SUPPORTING_IMPLEMENTATION,
        RELEVANCE_DIRECT_CANDIDATE,
        RELEVANCE_SUPPORTING_CONTEXT,
        RELEVANCE_CONTEXT_ONLY,
        None,
    ):
        assert is_skill_code_relevance(key), key


def test_ml_grade_time_signal_resolves_unknown_purpose_relevance() -> None:
    """A canonical implementation body whose snippet is not re-exposed (purpose
    unknown) but whose grade-time verdict proved executable ML is direct for an
    ML-family skill, supporting for its subfamilies — and NOTHING else: the signal
    never upgrades other purposes, weaker grades, or non-ML families."""
    assert (
        classify_skill_relevance(
            PURPOSE_UNKNOWN_NEEDS_REVIEW,
            skill="Machine Learning",
            grade=GRADE_IMPLEMENTATION_BODY,
            ml_signal=True,
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_UNKNOWN_NEEDS_REVIEW,
            skill="NLP",
            grade=GRADE_IMPLEMENTATION_BODY,
            ml_signal=True,
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )
    # Non-ML family, weaker grade, resolved purpose, or no verdict → unchanged.
    assert (
        classify_skill_relevance(
            PURPOSE_UNKNOWN_NEEDS_REVIEW, skill="React",
            grade=GRADE_IMPLEMENTATION_BODY, ml_signal=True,
        )
        == RELEVANCE_CONTEXT_ONLY
    )
    assert (
        classify_skill_relevance(
            PURPOSE_UNKNOWN_NEEDS_REVIEW, skill="Machine Learning",
            grade=GRADE_SUPPORTING_LOGIC, ml_signal=True,
        )
        == RELEVANCE_CONTEXT_ONLY
    )
    assert (
        classify_skill_relevance(
            PURPOSE_UNKNOWN_NEEDS_REVIEW, skill="Machine Learning",
            grade=GRADE_IMPLEMENTATION_BODY, ml_signal=None,
        )
        == RELEVANCE_CONTEXT_ONLY
    )
    # A resolved cross-skill purpose is never overridden by the signal.
    assert (
        classify_skill_relevance(
            PURPOSE_API_ROUTE_SHELL, skill="Machine Learning",
            grade=GRADE_IMPLEMENTATION_BODY, ml_signal=True,
        )
        == RELEVANCE_CROSS_SKILL_CONTEXT
    )


def test_relevance_labels_and_summaries_are_safe_rendered_strings() -> None:
    for key in SKILL_RELEVANCE_KEYS:
        for skill in ("Machine Learning", None, "", "  ", "X" * 200):
            label = describe_skill_relevance(key, skill)
            summary = skill_relevance_summary(key, skill)
            assert label and summary
            for banned in ("{", "}", "<", ">", "\n"):
                assert banned not in label
                assert banned not in summary
    # Over-long / empty skill names collapse to the neutral phrasing.
    assert "this skill" in describe_skill_relevance(RELEVANCE_CONTEXT_ONLY, "X" * 200)
    assert "this skill" in describe_skill_relevance(RELEVANCE_CONTEXT_ONLY, None)
    # Unknown relevance key fails closed to context-only wording.
    assert describe_skill_relevance("bogus", "ML") == describe_skill_relevance(
        RELEVANCE_CONTEXT_ONLY, "ML"
    )


def test_data_visualization_supports_ml_but_is_direct_for_data_skills() -> None:
    assert (
        classify_skill_relevance(
            PURPOSE_DATA_VISUALIZATION, skill="Data Analytics", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_DATA_VISUALIZATION, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_SUPPORTING_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_DATABASE_OPERATION, skill="SQL", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert (
        classify_skill_relevance(
            PURPOSE_RAG_RETRIEVAL, skill="Generative AI", grade=GRADE_IMPLEMENTATION_BODY
        )
        == RELEVANCE_DIRECT_IMPLEMENTATION
    )


# ── Universal semantic proof agent ────────────────────────────────────────────
#
# The classifier is a UNIVERSAL engine, not an ML-only special case:
#
#  * ``code_block_purpose`` is detected from code STRUCTURE (path shape +
#    executable constructs), never from the selected skill's name;
#  * ``skill_relevance`` maps that purpose onto the selected skill through the
#    centralized family taxonomy (``_PURPOSE_DIRECT_FAMILIES`` /
#    ``_PURPOSE_SUPPORTING_FAMILIES``) — unknown/future skills fail closed to
#    conservative context, never fabricated direct proof;
#  * docstring/comment prose can only ever be documentation context; and
#  * proof strength stays in ``evidence_quality_grade`` — no purpose or
#    relevance label ever upgrades it.

from app.services.github_python_evidence_focus import (  # noqa: E402
    PURPOSE_API_PROTOCOL_DOCUMENTATION,
    PURPOSE_API_REQUEST_HANDLER,
    PURPOSE_ARCHITECTURE_DOCUMENTATION,
    PURPOSE_CONTAINER_BASE_IMAGE,
    PURPOSE_CONTAINER_DEPENDENCY_INSTALL,
    PURPOSE_CONTAINER_ENV_CONFIG,
    PURPOSE_CONTAINER_FILES_SETUP,
    PURPOSE_CONTAINER_MULTI_STAGE_BUILD,
    PURPOSE_CONTAINER_PORT_EXPOSURE,
    PURPOSE_CONTAINER_RUNTIME_COMMAND,
    PURPOSE_DEPLOYMENT_DOCUMENTATION,
    PURPOSE_FILE_IO,
    PURPOSE_FRONTEND_API_CLIENT,
    PURPOSE_FRONTEND_CHART_COMPONENT,
    PURPOSE_FRONTEND_DIALOG_ALERT,
    PURPOSE_FRONTEND_FORM_COMPONENT,
    PURPOSE_FRONTEND_PAGE_COMPONENT,
    PURPOSE_FRONTEND_PROVIDER_THEME,
    PURPOSE_FRONTEND_RESULTS_DISPLAY,
    PURPOSE_FRONTEND_STATE_MANAGEMENT,
    PURPOSE_FRONTEND_UI_PRIMITIVE,
    PURPOSE_GEO_DATA_LOADING,
    PURPOSE_GEO_DISTANCE_CALCULATION,
    PURPOSE_GEO_FEATURE_ENGINEERING,
    PURPOSE_GEO_FEATURE_HANDLING,
    PURPOSE_GEO_GEOCODING_API,
    PURPOSE_GEO_VISUALIZATION,
    PURPOSE_INPUT_VALIDATION,
    PURPOSE_REPOSITORY_CONTEXT,
    PURPOSE_SERVING_DOCUMENTATION,
    RELEVANCE_CONTEXT_ONLY,
    RELEVANCE_CROSS_SKILL_CONTEXT,
    RELEVANCE_DEPLOYMENT_CONTEXT,
    RELEVANCE_DIRECT_IMPLEMENTATION,
    RELEVANCE_DOCUMENTATION_CONTEXT,
    RELEVANCE_PRODUCT_UI_CONTEXT,
    RELEVANCE_SUPPORTING_CONTEXT,
    RELEVANCE_SUPPORTING_IMPLEMENTATION,
    SKILL_FAMILY_GENERAL,
    SKILL_FAMILY_GEO,
    describe_code_block_purpose,
    is_skill_implementation_relevance,
    skill_family,
)


def _purpose_and_relevance(
    snippet: str | None,
    *,
    path: str | None = None,
    skill: str = "Machine Learning",
) -> tuple[str, str, str]:
    """Grade → purpose → relevance for one block, exactly like the services."""
    grade = grade_evidence(file_path=path, code_snippet=snippet)
    purpose = classify_code_block_purpose(grade=grade, code_snippet=snippet, file_path=path)
    relevance = classify_skill_relevance(purpose, skill=skill, grade=grade)
    return grade, purpose, relevance


# ── Part A: docstring / comment blocks can never overclaim ────────────────────


def test_docstring_mentioning_ml_training_is_documentation_not_direct() -> None:
    doc = '"""Retrains the RandomForest model nightly.\n\nRuns model.fit(X, y) and stores accuracy_score metrics.\n"""'
    grade, purpose, relevance = _purpose_and_relevance(doc, path="src/train.py")
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    assert purpose in (PURPOSE_RETRAINING_DOCUMENTATION, PURPOSE_PIPELINE_DOCUMENTATION)
    assert relevance == RELEVANCE_DOCUMENTATION_CONTEXT
    assert not is_skill_implementation_relevance(relevance)


def test_docstring_mentioning_docker_geospatial_genai_react_stays_documentation() -> None:
    cases = {
        '"""Builds the Docker image and deploys the container to Cloud Run."""': (
            "Docker",
            PURPOSE_DEPLOYMENT_DOCUMENTATION,
        ),
        '"""Computes haversine distance between latitude/longitude pairs."""': (
            "Geospatial Analysis",
            None,
        ),
        '"""Wraps the OpenAI chat.completions.create call with retries."""': (
            "Generative AI",
            None,
        ),
        "# React form component that submits patient data via onSubmit\n# and renders <AlertDialog> on error": (
            "React",
            None,
        ),
    }
    for snippet, (skill, expected_purpose) in cases.items():
        grade, purpose, relevance = _purpose_and_relevance(
            snippet, path="src/module.py", skill=skill
        )
        assert grade == GRADE_COMMENT_OR_DOCSTRING, snippet
        if expected_purpose:
            assert purpose == expected_purpose, snippet
        assert relevance == RELEVANCE_DOCUMENTATION_CONTEXT, snippet
        # Documentation is NEVER the selected skill's implementation evidence.
        assert not is_skill_implementation_relevance(relevance), snippet


def test_mostly_docstring_range_with_lone_code_line_is_documentation() -> None:
    snippet = (
        '"""Model serving documentation.\n\n'
        "This service loads the trained classifier and serves predictions\n"
        "over a REST endpoint. The retraining pipeline refreshes artifacts\n"
        "nightly and evaluates f1_score before promotion.\n"
        '"""\n'
        "model.fit(X_train, y_train)\n"
    )
    assert grade_python_snippet(snippet) == GRADE_COMMENT_OR_DOCSTRING


def test_comment_dominated_block_is_documentation_even_with_skill_keywords() -> None:
    snippet = (
        "# The training pipeline fits a RandomForestClassifier\n"
        "# using train_test_split and evaluates accuracy_score.\n"
        "# It then stores the model with joblib.dump for serving.\n"
        "# See docs/architecture.md for the full design.\n"
        "MODEL_PATH = 'artifacts/model.joblib'\n"
    )
    assert grade_python_snippet(snippet) == GRADE_COMMENT_OR_DOCSTRING


def test_documentation_topics_refine_serving_api_architecture() -> None:
    serving = '"""Documents how the model is served for inference behind the API."""'
    api = '"""Request/response payload reference for the public REST API endpoints."""'
    arch = '"""High-level architecture overview of the system components."""'
    assert classify_code_block_purpose(
        grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=serving
    ) == PURPOSE_SERVING_DOCUMENTATION
    assert classify_code_block_purpose(
        grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=api
    ) == PURPOSE_API_PROTOCOL_DOCUMENTATION
    assert classify_code_block_purpose(
        grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=arch
    ) == PURPOSE_ARCHITECTURE_DOCUMENTATION


# ── Part B: React / frontend blocks get semantic purposes ─────────────────────

REACT_PAGE_TSX = """
export default function Home() {
  return (
    <main className="container">
      <Hero />
      <section>{children}</section>
    </main>
  )
}
"""

REACT_FORM_TSX = """
export function PatientForm() {
  const [age, setAge] = useState("")
  const handleSubmit = async (e) => {
    e.preventDefault()
    onSubmitRisk({ age })
  }
  return <form onSubmit={handleSubmit}><input value={age} /></form>
}
"""

REACT_RESULTS_TSX = """
export function ResultsPanel({ prediction }) {
  return (
    <section>
      <h2>Risk score</h2>
      <p>{prediction.riskLevel}</p>
    </section>
  )
}
"""

REACT_DIALOG_TSX = """
const AlertDialog = AlertDialogPrimitive.Root
const AlertDialogTrigger = AlertDialogPrimitive.Trigger
export { AlertDialog, AlertDialogTrigger }
"""

REACT_THEME_TSX = """
export function ThemeProvider({ children, ...props }) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>
}
"""

REACT_API_CLIENT_TSX = """
export async function usePrediction(payload) {
  const res = await fetch("/api/predict", { method: "POST" })
  return res.json()
}
"""


def test_react_page_component_purpose() -> None:
    grade, purpose, _ = _purpose_and_relevance(
        REACT_PAGE_TSX, path="app/page.tsx", skill="React"
    )
    assert purpose == PURPOSE_FRONTEND_PAGE_COMPONENT
    assert describe_code_block_purpose(purpose) == "React page / route component"


def test_react_form_component_purpose_and_state_handling() -> None:
    _, purpose, _ = _purpose_and_relevance(
        REACT_FORM_TSX, path="components/patient-form.tsx", skill="React"
    )
    assert purpose == PURPOSE_FRONTEND_FORM_COMPONENT
    # A form block inside page.tsx is still a form (block beats file identity).
    _, purpose_in_page, _ = _purpose_and_relevance(
        REACT_FORM_TSX, path="app/page.tsx", skill="React"
    )
    assert purpose_in_page == PURPOSE_FRONTEND_FORM_COMPONENT


def test_react_results_panel_dialog_theme_provider_purposes() -> None:
    _, results, _ = _purpose_and_relevance(
        REACT_RESULTS_TSX, path="components/results-panel.tsx", skill="React"
    )
    assert results == PURPOSE_FRONTEND_RESULTS_DISPLAY
    _, dialog, _ = _purpose_and_relevance(
        REACT_DIALOG_TSX, path="components/ui/alert-dialog.tsx", skill="React"
    )
    assert dialog == PURPOSE_FRONTEND_DIALOG_ALERT
    _, theme, _ = _purpose_and_relevance(
        REACT_THEME_TSX, path="components/theme-provider.tsx", skill="React"
    )
    assert theme == PURPOSE_FRONTEND_PROVIDER_THEME
    _, client, _ = _purpose_and_relevance(
        REACT_API_CLIENT_TSX, path="src/lib/api.tsx", skill="React"
    )
    assert client == PURPOSE_FRONTEND_API_CLIENT


def test_react_rows_are_frontend_evidence_for_react_but_ui_context_for_ml() -> None:
    grade, purpose, react_rel = _purpose_and_relevance(
        REACT_FORM_TSX, path="components/patient-form.tsx", skill="React"
    )
    assert react_rel in (
        RELEVANCE_DIRECT_IMPLEMENTATION,
        RELEVANCE_SUPPORTING_IMPLEMENTATION,
    )
    ml_rel = classify_skill_relevance(purpose, skill="Machine Learning", grade=grade)
    assert ml_rel == RELEVANCE_PRODUCT_UI_CONTEXT
    backend_rel = classify_skill_relevance(purpose, skill="Backend Development", grade=grade)
    assert backend_rel == RELEVANCE_PRODUCT_UI_CONTEXT
    assert not is_skill_implementation_relevance(ml_rel)


def test_react_comment_only_block_never_gets_component_purpose() -> None:
    snippet = "// Renders the patient risk-input form\n// and submits via onSubmit"
    grade = grade_evidence(file_path="components/patient-form.tsx", code_snippet=snippet)
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=snippet, file_path="components/patient-form.tsx"
    )
    relevance = classify_skill_relevance(purpose, skill="React", grade=grade)
    assert relevance == RELEVANCE_DOCUMENTATION_CONTEXT


# ── Part C: geospatial blocks get semantic purposes ───────────────────────────

GEO_DISTANCE_PY = """
def route_distance_km(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None:
        raise ValueError("origin coordinates required")
    d = haversine_distance(lat1, lon1, lat2, lon2)
    return round(d, 3)
"""

GEO_GEOCODE_PY = """
def locate(address):
    geolocator = Nominatim(user_agent="risk-app")
    location = geolocator.geocode(address)
    return location.latitude, location.longitude
"""

GEO_DATA_PY = """
def load_zones(path):
    gdf = gpd.read_file(path)
    return gdf.to_crs("EPSG:4326")
"""

GEO_LATLON_PY = """
def add_location_features(df):
    df["lat_bucket"] = (df["latitude"] * 10).astype(int)
    df["lon_bucket"] = (df["longitude"] * 10).astype(int)
    return df
"""

GEO_VIZ_PY = """
def render_map(df):
    m = folium.Map(location=[42.36, -71.05])
    return m
"""


def test_geospatial_purposes_from_executable_signals() -> None:
    for snippet, expected in (
        (GEO_DISTANCE_PY, PURPOSE_GEO_DISTANCE_CALCULATION),
        (GEO_GEOCODE_PY, PURPOSE_GEO_GEOCODING_API),
        (GEO_DATA_PY, PURPOSE_GEO_DATA_LOADING),
        (GEO_LATLON_PY, PURPOSE_GEO_FEATURE_HANDLING),
        (GEO_VIZ_PY, PURPOSE_GEO_VISUALIZATION),
    ):
        grade = grade_evidence(file_path="src/features/geo.py", code_snippet=snippet)
        purpose = classify_code_block_purpose(
            grade=grade, code_snippet=snippet, file_path="src/features/geo.py"
        )
        assert purpose == expected, snippet


def test_geospatial_relevance_direct_for_geo_supporting_for_ml_cross_for_devops() -> None:
    assert skill_family("Geospatial Analysis") == SKILL_FAMILY_GEO
    grade = grade_evidence(file_path="src/geo.py", code_snippet=GEO_DISTANCE_PY)
    assert grade == GRADE_IMPLEMENTATION_BODY
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=GEO_DISTANCE_PY, file_path="src/geo.py"
    )
    assert classify_skill_relevance(
        purpose, skill="Geospatial Analysis", grade=grade
    ) == RELEVANCE_DIRECT_IMPLEMENTATION
    assert classify_skill_relevance(
        purpose, skill="Machine Learning", grade=grade
    ) == RELEVANCE_SUPPORTING_IMPLEMENTATION
    assert classify_skill_relevance(
        purpose, skill="DevOps", grade=grade
    ) == RELEVANCE_CROSS_SKILL_CONTEXT


def test_geospatial_without_line_level_code_fails_closed() -> None:
    # Repository title mentions geospatial but there is NO trusted snippet.
    grade = grade_evidence(file_path=None, code_snippet=None, selection_reason=None)
    assert grade == GRADE_REPO_LEVEL_FALLBACK
    purpose = classify_code_block_purpose(grade=grade, code_snippet=None)
    assert purpose == PURPOSE_REPOSITORY_CONTEXT
    relevance = classify_skill_relevance(purpose, skill="Geospatial Analysis", grade=grade)
    assert relevance == RELEVANCE_CONTEXT_ONLY
    assert not is_skill_implementation_relevance(relevance)


def test_docstring_latitude_mention_is_never_geospatial_feature_handling() -> None:
    snippet = (
        "def transform(df):\n"
        '    """Adds latitude and longitude derived features."""\n'
        "    return df.dropna()\n"
    )
    grade = grade_evidence(file_path="src/geo.py", code_snippet=snippet)
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=snippet, file_path="src/geo.py"
    )
    assert purpose != PURPOSE_GEO_FEATURE_HANDLING


# ── Part D: Dockerfile blocks get instruction-level purposes ──────────────────


def test_dockerfile_instruction_purposes() -> None:
    cases = (
        ("FROM python:3.11-slim", PURPOSE_CONTAINER_BASE_IMAGE),
        ("RUN pip install -r requirements.txt", PURPOSE_CONTAINER_DEPENDENCY_INSTALL),
        ("WORKDIR /app\nCOPY . /app", PURPOSE_CONTAINER_FILES_SETUP),
        ("ENV PORT=8080\nARG BUILD_ENV=prod", PURPOSE_CONTAINER_ENV_CONFIG),
        ("EXPOSE 8080", PURPOSE_CONTAINER_PORT_EXPOSURE),
        ('CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]', PURPOSE_CONTAINER_RUNTIME_COMMAND),
        (
            "FROM node:20 AS build\nRUN npm ci\nFROM nginx:alpine",
            PURPOSE_CONTAINER_MULTI_STAGE_BUILD,
        ),
    )
    for snippet, expected in cases:
        grade = grade_evidence(file_path="Dockerfile", code_snippet=snippet)
        purpose = classify_code_block_purpose(
            grade=grade, code_snippet=snippet, file_path="Dockerfile"
        )
        assert purpose == expected, snippet


def test_dockerfile_grading_exec_vs_declarative() -> None:
    assert grade_evidence(
        file_path="Dockerfile", code_snippet="RUN pip install -r requirements.txt"
    ) == GRADE_IMPLEMENTATION_BODY
    assert grade_evidence(
        file_path="Dockerfile", code_snippet="FROM python:3.11\nEXPOSE 8080"
    ) == GRADE_CONFIG_OR_CONSTANT
    assert grade_evidence(
        file_path="Dockerfile", code_snippet="# Build the serving image\n# then push to ECR"
    ) == GRADE_COMMENT_OR_DOCSTRING


def test_dockerfile_direct_for_docker_deployment_context_for_ml() -> None:
    snippet = 'RUN pip install -r requirements.txt\nCMD ["uvicorn", "main:app"]'
    grade = grade_evidence(file_path="Dockerfile", code_snippet=snippet)
    assert grade == GRADE_IMPLEMENTATION_BODY
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=snippet, file_path="Dockerfile"
    )
    assert classify_skill_relevance(purpose, skill="Docker", grade=grade) == (
        RELEVANCE_DIRECT_IMPLEMENTATION
    )
    assert classify_skill_relevance(purpose, skill="MLOps", grade=grade) == (
        RELEVANCE_DIRECT_IMPLEMENTATION
    )
    # For an ML skill a Dockerfile is deployment context — and the ML read-time
    # gate additionally downgrades the grade (no ML executable signal).
    assert classify_skill_relevance(purpose, skill="Machine Learning", grade=grade) == (
        RELEVANCE_DEPLOYMENT_CONTEXT
    )
    assert effective_evidence_grade(
        grade, is_ml=True, code_snippet=snippet, file_path="Dockerfile"
    ) == GRADE_SUPPORTING_LOGIC
    assert not has_ml_executable_signal(snippet)


# ── Part E: universal fallback for unknown / future skills ────────────────────

API_HANDLER_PY = """
@app.post("/subscriptions")
def create_subscription(payload: dict):
    if not payload.get("plan"):
        raise HTTPException(status_code=422)
    return service.create(payload)
"""

FILE_IO_PY = """
def export_report(rows, dest):
    with open(dest, "w") as fh:
        for row in rows:
            fh.write(row)
"""

VALIDATION_PY = """
def check_payload(data):
    cleaned = validate_schema(data)
    return cleaned
"""


def test_unknown_skill_gets_purpose_but_conservative_relevance() -> None:
    # Truly out-of-taxonomy skills fall to the general family (fail closed);
    # "GraphQL" (backend) and "Redis" (data) deliberately map via the taxonomy.
    assert skill_family("Flutter") == SKILL_FAMILY_GENERAL
    assert skill_family("Quantum Basket Weaving") == SKILL_FAMILY_GENERAL
    for snippet, expected_purpose in (
        (API_HANDLER_PY, PURPOSE_API_REQUEST_HANDLER),
        (FILE_IO_PY, PURPOSE_FILE_IO),
        (VALIDATION_PY, PURPOSE_INPUT_VALIDATION),
    ):
        grade = grade_evidence(file_path="src/service.py", code_snippet=snippet)
        purpose = classify_code_block_purpose(
            grade=grade, code_snippet=snippet, file_path="src/service.py"
        )
        assert purpose == expected_purpose, snippet
        relevance = classify_skill_relevance(purpose, skill="Flutter", grade=grade)
        # Unknown skill: conservative context, NEVER direct implementation.
        assert relevance in (RELEVANCE_SUPPORTING_CONTEXT, RELEVANCE_CONTEXT_ONLY), snippet
        assert not is_skill_implementation_relevance(relevance), snippet


def test_unknown_skill_never_reaches_direct_implementation() -> None:
    for purpose in CODE_BLOCK_PURPOSE_KEYS:
        for grade in (GRADE_IMPLEMENTATION_BODY, GRADE_SUPPORTING_LOGIC, None):
            relevance = classify_skill_relevance(
                purpose, skill="Quantum Basket Weaving", grade=grade
            )
            assert relevance != RELEVANCE_DIRECT_IMPLEMENTATION, (purpose, grade)
            assert not is_skill_implementation_relevance(relevance), (purpose, grade)


def test_universal_purposes_have_closed_labels_and_summaries() -> None:
    for key in (
        PURPOSE_API_REQUEST_HANDLER,
        PURPOSE_FILE_IO,
        PURPOSE_INPUT_VALIDATION,
        PURPOSE_FRONTEND_FORM_COMPONENT,
        PURPOSE_GEO_FEATURE_ENGINEERING,
        PURPOSE_CONTAINER_RUNTIME_COMMAND,
    ):
        assert key in CODE_BLOCK_PURPOSE_KEYS
        label = describe_code_block_purpose(key)
        summary = code_block_purpose_summary(key)
        assert label and summary
        for banned in ("{", "}", "<", ">"):
            assert banned not in label
            assert banned not in summary


# ── Part G: ML wins are preserved by the universal engine ─────────────────────


def test_ml_bodies_still_classify_ahead_of_universal_fallbacks() -> None:
    training = "def train(df):\n    X_train, X_test, y_train, y_test = train_test_split(X, y)\n    model.fit(X_train, y_train)\n    return model\n"
    grade = grade_evidence(file_path="src/train.py", code_snippet=training)
    assert grade == GRADE_IMPLEMENTATION_BODY
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=training, file_path="src/train.py"
    )
    assert purpose == PURPOSE_MODEL_TRAINING
    assert classify_skill_relevance(purpose, skill="Machine Learning", grade=grade) == (
        RELEVANCE_DIRECT_IMPLEMENTATION
    )


def test_frontend_and_container_purposes_never_anchor_ml_demonstrated() -> None:
    for purpose in (
        PURPOSE_FRONTEND_PAGE_COMPONENT,
        PURPOSE_FRONTEND_FORM_COMPONENT,
        PURPOSE_FRONTEND_CHART_COMPONENT,
        PURPOSE_CONTAINER_RUNTIME_COMMAND,
        PURPOSE_CONTAINER_DEPENDENCY_INSTALL,
    ):
        relevance = classify_skill_relevance(
            purpose, skill="Machine Learning", grade=GRADE_IMPLEMENTATION_BODY
        )
        assert relevance in (RELEVANCE_PRODUCT_UI_CONTEXT, RELEVANCE_DEPLOYMENT_CONTEXT)
        assert not is_skill_implementation_relevance(relevance)


# ── Import / header precision: importing a library is never using it ──────────
#
# Manual validation showed docstring / comment / header / import blocks sometimes
# read as executable skill evidence: a library NAME on an import line matched
# executable purpose signals (FAISS → RAG, nltk → NLP, geopy/shapely → geospatial,
# recharts/useState → React), and an import- or prose-dominated range could grade
# as an implementation body off its import text. These lock in the conservative
# contract: an import states a dependency; docstrings/comments/headers are
# documentation context; only a real usage line in the selected range is
# implementation evidence.

ML_IMPORTS_PY = (
    "import lightgbm as lgb\n"
    "from sklearn.ensemble import RandomForestClassifier\n"
    "from sklearn.metrics import accuracy_score, f1_score\n"
    "from sklearn.model_selection import train_test_split\n"
)

GENAI_IMPORTS_PY = (
    "from langchain.vectorstores import FAISS\n"
    "from langchain_openai import ChatOpenAI\n"
    "import openai\n"
)

GEO_IMPORTS_PY = (
    "from geopy.distance import geodesic\n"
    "from shapely.geometry import Point, Polygon\n"
    "import geopandas as gpd\n"
)

REACT_IMPORTS_TSX = (
    'import { useState, useEffect } from "react"\n'
    'import { LineChart, ResponsiveContainer } from "recharts"\n'
    'import axios from "axios"\n'
)


def test_ml_imports_are_dependency_setup_not_direct_ml() -> None:
    grade, purpose, relevance = _purpose_and_relevance(ML_IMPORTS_PY, path="src/train.py")
    assert grade == GRADE_IMPORT_ONLY
    assert purpose == PURPOSE_IMPORTS_DEPENDENCIES
    assert relevance == RELEVANCE_SETUP_CONTEXT
    assert not is_skill_implementation_relevance(relevance)
    # Importing sklearn / lightgbm / keras is never itself an ML executable signal.
    assert not has_ml_executable_signal(ML_IMPORTS_PY)
    assert not has_ml_executable_signal("from keras.models import Sequential\n")
    # Real usage of the imported estimator still is.
    assert has_ml_executable_signal("model = RandomForestClassifier()\nmodel.fit(X, y)\n")


def test_ml_docstring_mentioning_training_and_evaluation_is_documentation() -> None:
    doc = (
        '"""Trains the LightGBM model with train_test_split and evaluates\n'
        'accuracy_score / f1_score before promotion."""\n'
    )
    grade, purpose, relevance = _purpose_and_relevance(doc, path="src/train.py")
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    assert purpose in (PURPOSE_PIPELINE_DOCUMENTATION, PURPOSE_RETRAINING_DOCUMENTATION)
    assert relevance == RELEVANCE_DOCUMENTATION_CONTEXT
    assert not is_skill_implementation_relevance(relevance)


def test_genai_imports_are_dependency_setup_not_rag_or_llm() -> None:
    grade, purpose, relevance = _purpose_and_relevance(
        GENAI_IMPORTS_PY, path="src/rag.py", skill="Generative AI"
    )
    assert grade == GRADE_IMPORT_ONLY
    assert purpose == PURPOSE_IMPORTS_DEPENDENCIES
    assert relevance == RELEVANCE_SETUP_CONTEXT
    # Even riding on a stale strong grade, import text never yields an executable
    # purpose — the block fails closed to needs-review, never RAG / LLM work.
    stale = classify_code_block_purpose(
        grade=GRADE_IMPLEMENTATION_BODY, code_snippet=GENAI_IMPORTS_PY, file_path="src/rag.py"
    )
    assert stale == PURPOSE_UNKNOWN_NEEDS_REVIEW


def test_react_imports_are_dependency_setup_not_react_implementation() -> None:
    grade = grade_evidence(
        file_path="components/risk-chart.tsx", code_snippet=REACT_IMPORTS_TSX
    )
    assert grade == GRADE_IMPORT_ONLY
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=REACT_IMPORTS_TSX, file_path="components/risk-chart.tsx"
    )
    assert purpose == PURPOSE_IMPORTS_DEPENDENCIES
    relevance = classify_skill_relevance(purpose, skill="React", grade=grade)
    assert relevance == RELEVANCE_SETUP_CONTEXT
    assert not is_skill_implementation_relevance(relevance)


def test_geospatial_imports_are_dependency_setup_not_geo_implementation() -> None:
    grade, purpose, relevance = _purpose_and_relevance(
        GEO_IMPORTS_PY, path="src/geo_features.py", skill="Geospatial Analysis"
    )
    assert grade == GRADE_IMPORT_ONLY
    assert purpose == PURPOSE_IMPORTS_DEPENDENCIES
    assert relevance == RELEVANCE_SETUP_CONTEXT
    assert not is_skill_implementation_relevance(relevance)


def test_docker_comment_about_container_serving_is_documentation_not_docker_proof() -> None:
    snippet = (
        "# Serves the model API inside the container\n"
        "# docker run -p 8080:8080 risk-api\n"
    )
    grade = grade_evidence(file_path="Dockerfile", code_snippet=snippet)
    assert grade == GRADE_COMMENT_OR_DOCSTRING
    purpose = classify_code_block_purpose(
        grade=grade, code_snippet=snippet, file_path="Dockerfile"
    )
    assert purpose in (PURPOSE_SERVING_DOCUMENTATION, PURPOSE_DEPLOYMENT_DOCUMENTATION)
    relevance = classify_skill_relevance(purpose, skill="Docker", grade=grade)
    assert relevance == RELEVANCE_DOCUMENTATION_CONTEXT
    assert not is_skill_implementation_relevance(relevance)


def test_library_name_imports_never_yield_executable_purposes() -> None:
    cases = (
        ("import nltk\nfrom nltk.corpus import stopwords\n", PURPOSE_TEXT_NLP_PROCESSING),
        ("import torchvision\nfrom torchvision import transforms\n", PURPOSE_IMAGE_PROCESSING_CV),
        ("from hyperopt import fmin, tpe\n", PURPOSE_HYPERPARAMETER_TUNING),
        ("import uvicorn\n", PURPOSE_DEPLOYMENT_SERVING),
        (GEO_IMPORTS_PY, PURPOSE_GEO_DISTANCE_CALCULATION),
        ("from langchain.vectorstores import FAISS\n", PURPOSE_RAG_RETRIEVAL),
    )
    for snippet, forbidden in cases:
        assert grade_python_snippet(snippet) == GRADE_IMPORT_ONLY, snippet
        stale = classify_code_block_purpose(
            grade=GRADE_IMPLEMENTATION_BODY, code_snippet=snippet
        )
        assert stale != forbidden, snippet
        assert stale == PURPOSE_UNKNOWN_NEEDS_REVIEW, snippet


def test_parenthesized_multiline_import_is_import_only_and_never_rag() -> None:
    snippet = (
        "from langchain.vectorstores import (\n"
        "    FAISS,\n"
        "    Chroma,\n"
        ")\n"
    )
    assert grade_python_snippet(snippet) == GRADE_IMPORT_ONLY
    stale = classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet
    )
    assert stale != PURPOSE_RAG_RETRIEVAL


def test_import_header_with_lone_trailing_statement_never_grades_implementation() -> None:
    # ``accuracy_score`` on an IMPORT line + one trivial statement used to grade
    # as implementation_body off the import text.
    snippet = ML_IMPORTS_PY + "print(lgb.__version__)\n"
    assert grade_python_snippet(snippet) == GRADE_IMPORT_ONLY


def test_docstring_and_import_header_with_trailing_fit_is_conservative() -> None:
    # A range dominated by header prose + imports stays documentation, even when
    # a lone executable line inside it would prove the skill elsewhere.
    snippet = (
        '"""Training pipeline entrypoint.\n\n'
        "Loads the dataset, engineers features, and fits the champion model\n"
        "before evaluation and artifact upload.\n"
        '"""\n'
        "from sklearn.ensemble import RandomForestClassifier\n"
        "import pandas as pd\n"
        "model.fit(X, y)\n"
    )
    assert grade_python_snippet(snippet) == GRADE_COMMENT_OR_DOCSTRING


def test_recharts_import_does_not_make_a_block_a_chart_component() -> None:
    snippet = (
        'import { LineChart } from "recharts"\n'
        "export function Legend() {\n"
        "  return <span>legend</span>\n"
        "}\n"
    )
    purpose = classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=snippet, file_path="components/legend.tsx"
    )
    assert purpose != PURPOSE_FRONTEND_CHART_COMPONENT


def test_real_library_usage_still_classifies_as_executable_evidence() -> None:
    # Real sklearn / lightgbm usage in the selected range is still direct ML proof.
    ml_body = (
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n"
        "model = lgb.LGBMClassifier(n_estimators=200)\n"
        "model.fit(X_train, y_train)\n"
        "print(accuracy_score(y_test, model.predict(X_test)))\n"
    )
    grade, purpose, relevance = _purpose_and_relevance(ml_body, path="src/train.py")
    assert grade == GRADE_IMPLEMENTATION_BODY
    assert purpose == PURPOSE_MODEL_TRAINING
    assert relevance == RELEVANCE_DIRECT_IMPLEMENTATION
    assert has_ml_executable_signal(ml_body)
    # Real RAG / LLM usage still classifies (never from the import lines above it).
    rag = (
        "store = FAISS.from_documents(chunks, embeddings)\n"
        "hits = store.similarity_search(query, k=4)\n"
    )
    assert classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=rag, file_path="src/rag.py"
    ) == PURPOSE_RAG_RETRIEVAL
    llm = (
        "client = OpenAI()\n"
        "resp = client.chat.completions.create(model=MODEL, messages=msgs)\n"
    )
    assert classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=llm, file_path="src/llm.py"
    ) == PURPOSE_LLM_CALL_WRAPPER
    # Real geospatial usage still classifies.
    geo = "d_km = geodesic((a.lat, a.lon), (b.lat, b.lon)).km\n"
    assert classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=geo, file_path="src/geo.py"
    ) == PURPOSE_GEO_DISTANCE_CALCULATION
    # Real React state usage still classifies as frontend state management.
    state = "const [count, setCount] = useState(0)\nreturn <div>{count}</div>\n"
    assert classify_code_block_purpose(
        grade=GRADE_SUPPORTING_LOGIC, code_snippet=state, file_path="components/counter.tsx"
    ) == PURPOSE_FRONTEND_STATE_MANAGEMENT


# ── Two-stage classifier: Stage-1 block kinds + historical provenance ─────────
#
# Regression guard for the "everything collapsed to Repository-level context"
# incident: bumping ANALYZER_VERSION must never discard the redacted excerpts our
# own scanner already captured (they are version-independent source text) — only
# the stale persisted GRADE of a historical record may fail closed, and the
# excerpt is re-graded with the CURRENT logic instead.

from app.services.github_python_evidence_focus import (  # noqa: E402
    BLOCK_KIND_CONFIG_CONSTANTS_ONLY,
    BLOCK_KIND_DOCUMENTATION_ONLY,
    BLOCK_KIND_EXECUTABLE_CODE,
    BLOCK_KIND_IMPORT_ONLY,
    BLOCK_KIND_MIXED,
    BLOCK_KIND_REPOSITORY_ONLY,
    BLOCK_KIND_UNKNOWN,
    classify_block_kind,
)

_RETRAIN_DOCSTRING = (
    '"""Stroke model retraining pipeline.\n'
    "\n"
    "Usage: python pipeline_retrain.py --input gs://bucket/data.csv\n"
    "Retrains the LGBMClassifier, evaluates with f1_score / roc_auc_score,\n"
    "and writes model artifacts back to GCS.\n"
    '"""\n'
)
_ML_IMPORT_BLOCK = (
    "import pandas as pd\n"
    "from lightgbm import LGBMClassifier\n"
    "from sklearn.model_selection import train_test_split\n"
    "from sklearn.metrics import f1_score, roc_auc_score\n"
    "from geopy.distance import geodesic\n"
)
_TRAINING_BODY = (
    "def train(df):\n"
    "    X_train, X_test, y_train, y_test = train_test_split(df.X, df.y)\n"
    "    model = LGBMClassifier(n_estimators=300)\n"
    "    model.fit(X_train, y_train)\n"
    "    return model, X_test, y_test\n"
)


def test_trusted_provenance_historical_version_keeps_excerpt_never_grade() -> None:
    rec = build_server_provenance(
        grade=GRADE_IMPLEMENTATION_BODY, code_snippet=_TRAINING_BODY
    )
    rec["analyzer_version"] = "1"  # a version our scanner really stamped
    validated = trusted_provenance(rec)
    # The excerpt (our own service-role source capture) survives for re-grading …
    assert validated is not None
    assert validated["safe_excerpt"]
    # … but the stale persisted grade computed by outdated logic fails closed.
    assert "evidence_quality_grade" not in validated
    # The CURRENT version keeps its grade (current logic would reproduce it).
    current = build_server_provenance(
        grade=GRADE_IMPLEMENTATION_BODY, code_snippet=_TRAINING_BODY
    )
    validated_current = trusted_provenance(current)
    assert validated_current is not None
    assert validated_current["evidence_quality_grade"] == GRADE_IMPLEMENTATION_BODY
    # A version our scanner NEVER stamped still fails closed entirely.
    forged = {**current, "analyzer_version": "999-unrecognized"}
    assert trusted_provenance(forged) is None


def test_block_kind_stage1_weak_bands_come_from_the_validated_grade() -> None:
    # Stage 1 for the weak structural bands is the validated grade itself — a
    # docstring range IS documentation even though its prose names fit/metrics.
    assert (
        classify_block_kind(grade=GRADE_COMMENT_OR_DOCSTRING, code_snippet=_RETRAIN_DOCSTRING)
        == BLOCK_KIND_DOCUMENTATION_ONLY
    )
    assert (
        classify_block_kind(grade=GRADE_IMPORT_ONLY, code_snippet=_ML_IMPORT_BLOCK)
        == BLOCK_KIND_IMPORT_ONLY
    )
    assert (
        classify_block_kind(grade=GRADE_CONFIG_OR_CONSTANT, code_snippet='MODEL_PATH = "m.joblib"\n')
        == BLOCK_KIND_CONFIG_CONSTANTS_ONLY
    )
    # A bare route decorator is declaration-only plumbing (config kind); Stage 2
    # still refines its purpose to the API route shell via the grade.
    assert (
        classify_block_kind(grade=GRADE_ROUTE_DECORATOR_ONLY, code_snippet='@app.get("/health")\n')
        == BLOCK_KIND_CONFIG_CONSTANTS_ONLY
    )


def test_block_kind_stage1_executable_mixed_and_fallbacks() -> None:
    # A pure executable range is executable_code.
    assert (
        classify_block_kind(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=_TRAINING_BODY)
        == BLOCK_KIND_EXECUTABLE_CODE
    )
    # Docstring/imports sliced together with a real body in the SAME range → mixed.
    mixed = _RETRAIN_DOCSTRING + "\n" + _ML_IMPORT_BLOCK + "\n" + _TRAINING_BODY
    assert (
        classify_block_kind(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=mixed)
        == BLOCK_KIND_MIXED
    )
    # A validated strong grade whose trusted body is not re-exposed at read time
    # is still executable (the grade is the trusted structural verdict).
    assert (
        classify_block_kind(grade=GRADE_IMPLEMENTATION_BODY, code_snippet=None)
        == BLOCK_KIND_EXECUTABLE_CODE
    )
    # No trusted content and no strong grade → repository-only; garbage → unknown.
    assert classify_block_kind(grade=None, code_snippet=None) == BLOCK_KIND_REPOSITORY_ONLY
    assert (
        classify_block_kind(grade=GRADE_REPO_LEVEL_FALLBACK, code_snippet=None)
        == BLOCK_KIND_REPOSITORY_ONLY
    )
    assert classify_block_kind(grade="totally-forged", code_snippet=None) == BLOCK_KIND_UNKNOWN


def test_mixed_range_with_substantial_executable_classifies_by_the_executable() -> None:
    # Spec case: a selected range that carries the module docstring + the import
    # block AND a real training body. The executable code inside the range decides
    # both the grade and the purpose — the header can never drown out the body,
    # and the body can never be demoted to documentation/import context.
    mixed = _RETRAIN_DOCSTRING + "\n" + _ML_IMPORT_BLOCK + "\n" + _TRAINING_BODY
    grade = grade_python_snippet(mixed)
    assert grade == GRADE_IMPLEMENTATION_BODY
    purpose = classify_code_block_purpose(grade=grade, code_snippet=mixed, file_path="pipeline_retrain.py")
    assert purpose == PURPOSE_MODEL_TRAINING
    relevance = classify_skill_relevance(purpose, skill="Machine Learning", grade=grade)
    assert relevance == RELEVANCE_DIRECT_IMPLEMENTATION
    # And the converse: the same header with only a TINY trailing statement stays
    # conservative (documentation/import context, never implementation).
    tiny = _RETRAIN_DOCSTRING + "\n" + _ML_IMPORT_BLOCK + "\nmodel = LGBMClassifier()\n"
    tiny_grade = grade_python_snippet(tiny)
    assert tiny_grade in (GRADE_COMMENT_OR_DOCSTRING, GRADE_IMPORT_ONLY)
