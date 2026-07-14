"""GitHub code-purpose classification quality — platform countability contract.

Covers the strengthened shared pipeline:

* Bare name-list FRAGMENT windows (multi-line import continuations sliced from
  their opener — the real ``pipeline_retrain.py L51-52`` / ``train.py L22``
  defect) grade import-only with the honest ``insufficient_context`` purpose,
  never implementation.
* Symbol-first context expansion: a module-level anchor expands to its complete
  containing statement; function/method/class symbols are resolved.
* The COUNTABILITY CONTRACT: "purpose unknown + counted" is impossible on both
  the Skill Report and Project Report claim→evidence maps, and needs-review
  relevance never counts.
* Regression: the real ``evaluate()`` metrics body and the ``run_smoke_test()``
  inference body keep their concrete purposes and stay counted.
* Reclassification is idempotent, tenant-scoped, preserves history, and never
  duplicates or mutates the underlying ``skill_evidence`` rows.

Everything is deterministic and in-memory — no network / LLM calls.
"""

from __future__ import annotations

from app.services.claim_evidence_synthesis_service import (
    build_skill_claim_evidence_map,
    classify_github_tier,
)
from app.services.github_python_evidence_focus import (
    ANALYZER_VERSION,
    GRADE_IMPLEMENTATION_BODY,
    GRADE_IMPORT_ONLY,
    PURPOSE_INSUFFICIENT_CONTEXT,
    PURPOSE_MODEL_EVALUATION,
    PURPOSE_PREDICTION_INFERENCE,
    PURPOSE_UNKNOWN_NEEDS_REVIEW,
    RELEVANCE_CONTEXT_ONLY,
    UNRESOLVED_PURPOSE_KEYS,
    classify_code_block_purpose,
    classify_skill_relevance,
    code_block_purpose_summary,
    focus_python_range,
    focus_python_symbol,
    grade_python_snippet,
    is_countable_code_purpose,
    snippet_is_bare_name_fragment,
)
from app.services.github_skill_evidence_service import is_strong_code_snippet

# The REAL stored excerpts behind the reported defect (verbatim from the
# trusted provenance table): continuation lines of a parenthesized
# ``from sklearn.metrics import (…)`` persisted without their opening line.
FRAG_RETRAIN_L51_52 = (
    "    accuracy_score, classification_report, f1_score,\n"
    "    precision_recall_fscore_support, roc_auc_score,"
)
FRAG_TRAIN_L22 = "    accuracy_score, f1_score, classification_report, confusion_matrix"

# The REAL stored excerpts of the two good blocks (abbreviated bodies).
GOOD_EVALUATE_BODY = (
    "def evaluate(name, model, X_test, y_test, classes):\n"
    "    preds = model.predict(X_test)\n"
    "    acc   = accuracy_score(y_test, preds)\n"
    '    f1    = f1_score(y_test, preds, average="macro")\n'
    "    print(classification_report(y_test, preds, target_names=classes))\n"
    '    return {"model": name, "accuracy": round(acc, 4)}'
)
GOOD_SMOKE_TEST_BODY = (
    "def run_smoke_test(manifest: dict) -> None:\n"
    '    endpoint_id = manifest.get("vertex_endpoint_id")\n'
    "    endpoint = aiplatform.Endpoint(endpoint_name=endpoint_id)\n"
    "    response = endpoint.predict(instances=[instance])\n"
    "    for i, pred in enumerate(response.predictions):\n"
    "        print(pred.get('risk_class'))"
)


# ── Fragment detection + honest downgrade ─────────────────────────────────────


def test_real_fragment_excerpts_grade_import_only_with_insufficient_context() -> None:
    for frag in (FRAG_RETRAIN_L51_52, FRAG_TRAIN_L22):
        assert snippet_is_bare_name_fragment(frag)
        grade = grade_python_snippet(frag)
        assert grade == GRADE_IMPORT_ONLY
        purpose = classify_code_block_purpose(
            grade=grade, code_snippet=frag, file_path="src/model/train.py"
        )
        assert purpose == PURPOSE_INSUFFICIENT_CONTEXT
        assert not is_countable_code_purpose(purpose)
        # The honest fallback copy — never "counted", never a fabricated purpose.
        assert "Insufficient context" in code_block_purpose_summary(purpose)
        # Relevance fails closed to context-only for every skill / any signal.
        assert (
            classify_skill_relevance(
                purpose, skill="Machine Learning", grade=grade, ml_signal=True
            )
            == RELEVANCE_CONTEXT_ONLY
        )


def test_fragment_lines_never_carry_implementation_signal_in_mixed_windows() -> None:
    # A fragment line inside a window must not lend its metric NAMES as
    # implementation signals; only the real statement decides.
    window = FRAG_TRAIN_L22 + "\nresult = 1 + 1"
    assert grade_python_snippet(window) != GRADE_IMPLEMENTATION_BODY


def test_full_import_statement_grades_import_only_with_imports_purpose() -> None:
    full = (
        "from sklearn.metrics import (\n"
        "    accuracy_score, classification_report, f1_score,\n"
        "    precision_recall_fscore_support, roc_auc_score,\n"
        ")"
    )
    grade = grade_python_snippet(full)
    assert grade == GRADE_IMPORT_ONLY
    purpose = classify_code_block_purpose(grade=grade, code_snippet=full)
    assert purpose == "imports_dependencies"


def test_fragment_is_never_strong_line_level_proof() -> None:
    assert is_strong_code_snippet("scripts/pipeline_retrain.py", FRAG_RETRAIN_L51_52, None) is False
    assert is_strong_code_snippet("src/model/train.py", FRAG_TRAIN_L22, None) is False


def test_good_bodies_keep_concrete_purposes() -> None:
    # CASE 2 — evaluation metrics body.
    grade = grade_python_snippet(GOOD_EVALUATE_BODY)
    assert grade == GRADE_IMPLEMENTATION_BODY
    assert (
        classify_code_block_purpose(
            grade=grade, code_snippet=GOOD_EVALUATE_BODY, file_path="src/model/train.py"
        )
        == PURPOSE_MODEL_EVALUATION
    )
    # CASE 1 — model inference / smoke-test body.
    grade = grade_python_snippet(GOOD_SMOKE_TEST_BODY)
    assert grade == GRADE_IMPLEMENTATION_BODY
    assert (
        classify_code_block_purpose(
            grade=grade, code_snippet=GOOD_SMOKE_TEST_BODY, file_path="scripts/vertex_deploy.py"
        )
        == PURPOSE_PREDICTION_INFERENCE
    )


# ── Symbol-first context expansion ─────────────────────────────────────────────

_MODULE_SOURCE = '''"""Module doc."""
from sklearn.metrics import (
    accuracy_score, classification_report, f1_score,
    precision_recall_fscore_support, roc_auc_score,
)

THRESHOLD = 0.5


class Trainer:
    def fit(self, X, y):
        self.model = LGBMClassifier()
        self.model.fit(X, y)
        return self.model


def evaluate(model, X_test, y_test):
    preds = model.predict(X_test)
    return accuracy_score(y_test, preds)
'''


def test_module_level_import_anchor_expands_to_complete_statement() -> None:
    # An anchor landing on the import continuation lines (the defect shape)
    # expands to the COMPLETE ``from … import (…)`` statement and grades as
    # what it is: import-only, never an implementation body.
    focused = focus_python_range(_MODULE_SOURCE, 3, 4)
    assert focused is not None
    start, end, grade = focused
    assert (start, end) == (2, 5)
    assert grade == GRADE_IMPORT_ONLY


def test_function_and_method_and_class_symbols_resolve() -> None:
    assert focus_python_symbol(_MODULE_SOURCE, 17) == ("evaluate", "function")
    assert focus_python_symbol(_MODULE_SOURCE, 12) == ("Trainer.fit", "method")
    assert focus_python_symbol(_MODULE_SOURCE, 10) == ("Trainer", "class")
    # Module level (imports / constants) has no containing symbol.
    assert focus_python_symbol(_MODULE_SOURCE, 3) == (None, None)


def test_function_anchor_focuses_to_body_and_grades_it() -> None:
    focused = focus_python_range(_MODULE_SOURCE, 18, 18, include_signature=True)
    assert focused is not None
    start, end, grade = focused
    assert start == 17  # the def line (signature kept as context)
    assert end >= 19
    assert grade == GRADE_IMPLEMENTATION_BODY


# ── Countability contract at the synthesis layer ──────────────────────────────


def _skill_report_with_github_item(item: dict) -> dict:
    return {
        "skill": "Machine Learning",
        "skill_slug": "machine-learning",
        "projects": [
            {
                "project_id": "p1",
                "project_title": "Boston Rerouting",
                "attached": True,
                "github_evidence": [item],
                "website_evidence": [],
                "document_correlations": [],
                "defense_evidence": [],
                "video_proofs": [],
            }
        ],
    }


def _canonical_item(**overrides) -> dict:
    item = {
        "source_id": "se-1",
        "title": "boston-rerouting",
        "file_path": "scripts/pipeline_retrain.py",
        "line_start": 51,
        "line_end": 52,
        "display_mode": "code_line",
        "evidence_quality_grade": GRADE_IMPLEMENTATION_BODY,
        "skill_relevance_key": "direct_implementation",
        "code_block_purpose_key": "model_training",
        "code_block_purpose_summary": "This block trains a model.",
        "attached_project_ids": ["p1"],
    }
    item.update(overrides)
    return item


def test_unresolved_purpose_never_counts_in_skill_report_map() -> None:
    for purpose in sorted(UNRESOLVED_PURPOSE_KEYS):
        item = _canonical_item(
            code_block_purpose_key=purpose,
            skill_relevance_key="context_only_needs_review",
            code_block_purpose_summary=code_block_purpose_summary(purpose),
        )
        cem = build_skill_claim_evidence_map(_skill_report_with_github_item(item))
        gh = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
        assert gh and all(not c["counted_as_direct_evidence"] for c in gh), purpose
        # The forbidden combination is impossible: no counted citation may carry
        # an unresolved-purpose explanation.
        for c in cem["citations"]:
            if c["counted_as_direct_evidence"]:
                assert "could not be determined" not in (c.get("explanation") or "")
                assert "Insufficient context" not in (c.get("explanation") or "")


def test_needs_review_relevance_never_counts_even_with_strong_grade() -> None:
    tier, reason = classify_github_tier(
        _canonical_item(
            skill_relevance_key="context_only_needs_review",
            code_block_purpose_key=PURPOSE_UNKNOWN_NEEDS_REVIEW,
        )
    )
    assert tier == "weak_signal"
    assert "never counted" in reason or "not counted" in reason

    tier, _ = classify_github_tier(
        _canonical_item(
            skill_relevance_key="direct_candidate_needs_review",
            code_block_purpose_key="model_training",
        )
    )
    assert tier == "weak_signal"


def test_concrete_purpose_with_implementation_relevance_still_counts() -> None:
    cem = build_skill_claim_evidence_map(
        _skill_report_with_github_item(_canonical_item())
    )
    gh = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert gh and gh[0]["counted_as_direct_evidence"] is True
    assert gh[0]["strength"] == "Primary implementation"


def test_analyzed_context_lines_flow_into_citation() -> None:
    item = _canonical_item(
        context_start_line=38,
        context_end_line=67,
        analysis_version=ANALYZER_VERSION,
    )
    cem = build_skill_claim_evidence_map(_skill_report_with_github_item(item))
    gh = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"][0]
    assert gh["start_line"] == 51 and gh["end_line"] == 52  # target never rewritten
    assert gh["context_start_line"] == 38 and gh["context_end_line"] == 67
    assert gh["analysis_version"] == ANALYZER_VERSION


def test_project_report_fragment_trace_is_visible_but_never_counted() -> None:
    from app.services.claim_evidence_synthesis_service import build_project_claim_evidence_map

    report = {
        "project_id": "p1",
        "project_title": "Boston Rerouting",
        "skill_evidence": [
            {"skill": "Machine Learning", "evidence_traces": ["t-frag", "t-good"]},
        ],
        "evidence_traces": [
            {
                "trace_id": "t-frag",
                "source_type": "GitHub Proof",
                "source_title": "boston-rerouting",
                "file_path": "scripts/pipeline_retrain.py",
                "line_start": 51,
                "line_end": 52,
                "code_snippet": FRAG_RETRAIN_L51_52,
                "safe_summary": "ML evaluation metrics",
            },
            {
                "trace_id": "t-good",
                "source_type": "GitHub Proof",
                "source_title": "boston-rerouting",
                "file_path": "src/model/train.py",
                "line_start": 46,
                "line_end": 61,
                "code_snippet": GOOD_EVALUATE_BODY,
                "safe_summary": "Evaluation metrics implementation",
            },
        ],
    }
    cem = build_project_claim_evidence_map(report)
    gh = [c for c in cem["citations"] if c["proof_type"] == "GitHub Proof"]
    assert len(gh) == 2
    frag = next(c for c in gh if c["start_line"] == 51)
    good = next(c for c in gh if c["start_line"] == 46)
    assert frag["counted_as_direct_evidence"] is False
    assert good["counted_as_direct_evidence"] is True


# ── Reclassification (idempotent, tenant-scoped, history-preserving) ───────────


class _FakeQuery:
    def __init__(self, table: "_FakeTable") -> None:
        self._table = table
        self._filters: list[tuple[str, str]] = []

    def select(self, *_args) -> "_FakeQuery":
        return self

    def eq(self, key: str, value) -> "_FakeQuery":
        self._filters.append((key, str(value)))
        return self

    def execute(self):
        rows = [
            r
            for r in self._table.rows.values()
            if all(str(r.get(k)) == v for k, v in self._filters)
        ]

        class _R:  # minimal response shim
            data = rows

        return _R()


class _FakeTable:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.upserts: int = 0

    def query(self) -> _FakeQuery:
        return _FakeQuery(self)


class _FakeDB:
    def __init__(self) -> None:
        self.tables: dict[str, _FakeTable] = {}

    def table(self, name: str):
        t = self.tables.setdefault(name, _FakeTable())

        class _Chain:
            def __init__(self, table: _FakeTable) -> None:
                self._t = table

            def select(self, *a):
                return t.query().select(*a)

            def upsert(self, record: dict, on_conflict: str = "skill_evidence_id"):
                self._t.upserts += 1
                key = str(record.get(on_conflict))
                existing = self._t.rows.get(key, {})
                self._t.rows[key] = {**existing, **record}

                class _E:
                    @staticmethod
                    def execute():
                        return None

                return _E()

        return _Chain(t)


def _seed_fake_db() -> _FakeDB:
    db = _FakeDB()
    se = db.tables.setdefault("skill_evidence", _FakeTable())
    prov = db.tables.setdefault("trusted_github_evidence_analysis", _FakeTable())
    se.rows["ev-1"] = {
        "id": "ev-1",
        "user_id": "user-a",
        "skill_name": "Python",
        "file_path": "scripts/pipeline_retrain.py",
        "line_start": 51,
        "line_end": 52,
        "repository_url": "https://github.com/nosuch/nosuch-repo",
        "metadata": {"selection_reason": "ML evaluation metrics"},
    }
    prov.rows["ev-1"] = {
        "skill_evidence_id": "ev-1",
        "user_id": "user-a",
        "analyzer_name": "veribridge_github_ast_focus",
        "analyzer_version": "1",
        "evidence_quality_grade": "implementation_body",
        "focused_start_line": 51,
        "focused_end_line": 52,
        "safe_excerpt": FRAG_RETRAIN_L51_52,
        "snippet_hash": "stale",
        "analysis_history": [],
    }
    # A second tenant that must never be touched.
    se.rows["ev-other"] = {
        "id": "ev-other",
        "user_id": "user-b",
        "skill_name": "Python",
        "file_path": "x.py",
        "line_start": 1,
        "line_end": 2,
        "repository_url": "https://github.com/nosuch/other",
        "metadata": {},
    }
    prov.rows["ev-other"] = {
        "skill_evidence_id": "ev-other",
        "user_id": "user-b",
        "analyzer_name": "veribridge_github_ast_focus",
        "analyzer_version": "1",
        "safe_excerpt": "x = 1",
        "snippet_hash": "other",
        "analysis_history": [],
    }
    return db


def test_reclassification_is_idempotent_tenant_scoped_and_preserves_history(monkeypatch) -> None:
    import scripts.reclassify_github_evidence_purposes as recls

    # Offline: source fetch fails → the stored excerpt is re-graded in place.
    monkeypatch.setattr(recls, "_fetch_raw", lambda *a, **k: None)
    db = _seed_fake_db()

    counters = recls.reclassify_user(db, "user-a", apply=True)
    assert counters["examined"] == 1 and counters["updated"] == 1

    prov = db.tables["trusted_github_evidence_analysis"].rows["ev-1"]
    # Re-graded with CURRENT logic: the fragment excerpt is import-only now.
    assert prov["analyzer_version"] == ANALYZER_VERSION
    assert prov["evidence_quality_grade"] == GRADE_IMPORT_ONLY
    # Prior analysis preserved in history; underlying evidence row untouched.
    assert len(prov["analysis_history"]) == 1
    assert prov["analysis_history"][0]["analyzer_version"] == "1"
    assert prov["analysis_history"][0]["evidence_quality_grade"] == "implementation_body"
    se_row = db.tables["skill_evidence"].rows["ev-1"]
    assert (se_row["line_start"], se_row["line_end"]) == (51, 52)
    assert len(db.tables["skill_evidence"].rows) == 2  # no duplicates

    # Tenant isolation: the other user's provenance is untouched.
    other = db.tables["trusted_github_evidence_analysis"].rows["ev-other"]
    assert other["analyzer_version"] == "1"

    # Idempotent: the second run is a no-op.
    counters2 = recls.reclassify_user(db, "user-a", apply=True)
    assert counters2["updated"] == 0 and counters2["skipped_current"] == 1
    assert len(db.tables["trusted_github_evidence_analysis"].rows["ev-1"]["analysis_history"]) == 1
