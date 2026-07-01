"""Deterministic Python AST evidence focusing + quality grading.

The GitHub Portfolio scanner and the GitHub Proof analyzer both pin
``skill_code_evidence`` to *line anchors* and expand each anchor by a fixed
context window. That window frequently opens on weak proof — a module/function
docstring, an ``import`` block, a ``sys.path`` bootstrap, a bare
``@app.get(...)`` route decorator with no handler body, or a block of
constants/config — none of which is recruiter-worthy "I implemented this skill"
evidence.

This module is the single, deterministic (NO LLM) place that:

* **focuses** a Python line anchor onto the *enclosing function/class/method
  body* using :mod:`ast`, skipping the leading docstring + decorator/signature
  so the range opens on real implementation code (never fabricating a line
  number — the focused range always stays inside the parsed source); and
* **grades** a code range / snippet into one deterministic
  ``evidence_quality_grade`` band so ranking can keep imports / docstrings /
  constants / bare route decorators out of *top* evidence whenever a real
  implementation body exists for the same repo + skill.

It depends only on stdlib (``ast`` / ``re``) so both the offline scanner
(``apps/api/scripts/github_portfolio_scanner.py``) and the read-time services
can import it without a dependency cycle.
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize
from typing import Any

__all__ = [
    "GRADE_IMPLEMENTATION_BODY",
    "GRADE_SUPPORTING_LOGIC",
    "GRADE_CONFIG_OR_CONSTANT",
    "GRADE_COMMENT_OR_DOCSTRING",
    "GRADE_IMPORT_ONLY",
    "GRADE_ROUTE_DECORATOR_ONLY",
    "GRADE_REPO_LEVEL_FALLBACK",
    "EVIDENCE_QUALITY_GRADES",
    "ANALYZER_NAME",
    "ANALYZER_VERSION",
    "TRUSTED_ANALYSIS_TABLE",
    "SERVER_PROVENANCE_KEY",
    "RESERVED_PROVENANCE_FIELDS",
    "is_trusted_analyzer",
    "strip_client_provenance",
    "build_server_provenance",
    "trusted_provenance",
    "redact_secrets",
    "grade_rank",
    "is_weak_grade",
    "is_strong_grade",
    "grade_python_snippet",
    "grade_evidence",
    "describe_grade",
    "is_overclaiming_reason",
    "safe_selection_reason",
    "has_ml_executable_signal",
    "ml_implementation_is_valid",
    "effective_evidence_grade",
    "docstring_and_comment_lines",
    "focus_python_anchor",
    "focus_python_range",
]


# ── Analyzer provenance ───────────────────────────────────────────────────────
#
# A single, controlled marker that the VeriBridge GitHub AST scanner stamps onto
# every grade it computes FROM REAL SOURCE at scan time. Read-time consumers use
# :func:`is_trusted_analyzer` to decide whether a *persisted* strong grade may be
# trusted without re-validating a source body. User-supplied / descriptive
# metadata cannot forge this marker, so it can never assert a strong grade on its
# own. Bump ``ANALYZER_VERSION`` whenever the grading logic changes materially.
ANALYZER_NAME = "veribridge_github_ast_focus"
ANALYZER_VERSION = "1"

# Historical analyzer names that still count as our own controlled provenance.
_TRUSTED_ANALYZERS = frozenset({ANALYZER_NAME.lower()})
# Analyzer versions whose persisted grade is still trusted. A grade stamped by a
# version we no longer recognize fails closed (the read-time consumer re-grades
# from source or caps to a weak fallback) — so a bumped grader never silently
# trusts stale strong grades it can no longer reproduce.
_TRUSTED_ANALYZER_VERSIONS = frozenset({ANALYZER_VERSION})


def is_trusted_analyzer(name: str | None) -> bool:
    """True only for a grade-provenance marker produced by the VeriBridge scanner."""
    return str(name or "").strip().lower() in _TRUSTED_ANALYZERS


# ── Server-only evidence provenance (forgery boundary) ────────────────────────
#
# Analyzer provenance (which grade was computed FROM REAL SOURCE at scan time) and
# the focused source excerpt are SERVER-ONLY facts. They must NEVER be trusted
# from the user-editable ``skill_evidence.metadata`` JSONB column: ``skill_evidence``
# carries an "own row ALL" RLS policy, so a hostile owner can UPDATE their own
# metadata directly via Supabase — bypassing the FastAPI schema — and would
# otherwise forge ``evidence_quality_grade="implementation_body"`` with no real
# source behind it. FastAPI-layer stripping alone is not a security boundary.
#
# So trusted provenance lives in a dedicated, SERVICE-ROLE-ONLY table
# (:data:`TRUSTED_ANALYSIS_TABLE`, migration 053) that authenticated users can
# neither write nor read. The offline scanner stamps it through the service role;
# read-time services fetch it through the service role and validate it with
# :func:`trusted_provenance`. ``skill_evidence.metadata`` is never again sufficient
# to establish implementation quality.
#
# The metadata-side defenses below are kept purely as DEFENSE IN DEPTH at the
# FastAPI create/update boundary: :func:`strip_client_provenance` scrubs any
# provenance-shaped keys a client tries to submit so they never even reach the
# stored metadata. Trust, however, no longer reads metadata at all.
TRUSTED_ANALYSIS_TABLE = "trusted_github_evidence_analysis"

# Legacy metadata namespace key — retained ONLY so the FastAPI schema strips it
# from any user-submitted metadata (it is never read for trust anymore).
SERVER_PROVENANCE_KEY = "server_evidence_provenance"

# Flat metadata fields that can prove implementation quality / carry source. NEVER
# accepted from user-submitted (public create/update) metadata. ``strip_client_
# provenance`` removes these (and the namespace key) before persistence.
RESERVED_PROVENANCE_FIELDS = frozenset(
    {
        "analyzer",
        "analyzer_name",
        "analyzer_version",
        "evidence_analyzer",
        "evidence_analyzer_version",
        "evidence_quality_grade",
        "evidence_quality_provenance",
        "evidence_quality_reason",
        "code_snippet",
        "source_snippet",
        "snippet",
        "safe_excerpt",
        "snippet_hash",
        "body",
        "focused_start_line",
        "focused_end_line",
        "focused_reason",
    }
)


def strip_client_provenance(metadata: object) -> object:
    """Strip provenance-shaped keys from user-submitted metadata (defense in depth).

    Removes every reserved flat provenance field AND the legacy server provenance
    namespace key (case-insensitively) so a public create/update payload can never
    even park a forged analyzer marker / grade / snippet in the stored metadata.
    Trusted provenance lives in :data:`TRUSTED_ANALYSIS_TABLE` (service-role only),
    not here. A non-dict value is returned unchanged.
    """
    if not isinstance(metadata, dict):
        return metadata
    cleaned: dict[Any, Any] = {}
    for key, value in metadata.items():
        k = str(key).strip().lower()
        if k in RESERVED_PROVENANCE_FIELDS or k == SERVER_PROVENANCE_KEY:
            continue
        cleaned[key] = value
    return cleaned


def build_server_provenance(
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
    focused_start_line: int | None = None,
    focused_end_line: int | None = None,
    focused_reason: str | None = None,
) -> dict[str, Any]:
    """Build the server-only provenance record persisted into
    :data:`TRUSTED_ANALYSIS_TABLE` by the scanner (service role only).

    Keys mirror the table columns so the same dict serves both the in-memory
    (dict-backed) store and the Supabase row. The snippet (public repo source) is
    run through :func:`redact_secrets` so a stray ``api_key = "sk-…"`` / token /
    password is never persisted verbatim; ``snippet_hash`` is taken of the
    REDACTED excerpt so it can never be used to recover a secret.
    """
    prov: dict[str, Any] = {
        "analyzer_name": ANALYZER_NAME,
        "analyzer_version": ANALYZER_VERSION,
    }
    if grade:
        prov["evidence_quality_grade"] = grade
    if code_snippet:
        redacted = redact_secrets(code_snippet)
        if redacted:
            prov["safe_excerpt"] = redacted
            prov["snippet_hash"] = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
    if focused_start_line is not None:
        prov["focused_start_line"] = focused_start_line
    if focused_end_line is not None:
        prov["focused_end_line"] = focused_end_line
    if focused_reason:
        prov["evidence_quality_reason"] = focused_reason
    return prov


def trusted_provenance(record: object) -> dict[str, Any] | None:
    """Return a trusted-analysis record ONLY when it is trustworthy.

    ``record`` is a row read from the SERVICE-ROLE-ONLY
    :data:`TRUSTED_ANALYSIS_TABLE` (never ``skill_evidence.metadata``). Trust
    requires our controlled analyzer name AND a recognized analyzer version. A
    record stamped by an analyzer version we no longer recognize FAILS CLOSED, so
    a stale strong grade we can no longer reproduce is never trusted. Anything a
    user could have forged in their own metadata can satisfy none of this — it is
    not even read here.
    """
    if not isinstance(record, dict):
        return None
    if not is_trusted_analyzer(record.get("analyzer_name") or record.get("analyzer")):
        return None
    if str(record.get("analyzer_version") or "").strip() not in _TRUSTED_ANALYZER_VERSIONS:
        return None
    return record


# ── Deterministic secret redaction ────────────────────────────────────────────
#
# A focused public source excerpt may still contain a hard-coded secret. Redact
# common shapes deterministically before persisting/echoing any snippet so a
# token/key/password is never stored verbatim. Structure (line shapes) is
# preserved, so redaction never changes an evidence grade.

_REDACTED = "[REDACTED_SECRET]"

# key = "value" / key: value — assignment to a secret-ish variable. Covers
# api_key / secret / client_secret / access key (+ id) / auth(orization) token /
# token / password / passphrase, and connection-string / service-role style names
# (database_url, postgres_url, supabase_service_role_key, *_api_key, *_secret …).
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(?P<prefix>(?:[A-Za-z0-9_]*"
    r"(?:api[_-]?key|secret(?:[_-]?key)?|client[_-]?secret"
    r"|access[_-]?key(?:[_-]?id)?|auth(?:orization)?(?:[_-]?token)?|auth[_-]?token"
    r"|service[_-]?role[_-]?key|database[_-]?url|postgres[_-]?url|conn(?:ection)?[_-]?string"
    r"|private[_-]?key|passphrase|token|password|passwd|pwd))\s*[:=]\s*)"
    r"(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s,;)\]}]+)"
)
# Provider-style standalone tokens (match regardless of surrounding assignment).
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}")
# GitHub classic (ghp_/gho_/ghu_/ghs_/ghr_) + fine-grained (github_pat_) tokens.
_GITHUB_TOKEN_RE = re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,})")
# Slack tokens (bot/user/app/refresh/legacy/config).
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{8,}")
# AWS access key IDs (long-term AKIA / temporary ASIA).
_AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,}\b")
# JWT-like token: header.payload.signature, each a long base64url segment.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
# Authorization: Bearer <token> (and bare ``Bearer <token>``).
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{6,}")
# AWS SigV4 signed-URL query params (presigned S3 links etc).
_SIGNED_URL_PARAM_RE = re.compile(
    r"(?i)(?P<key>X-Amz-(?:Signature|Credential|Security-Token)=)(?P<value>[^&\s\"'<>]+)"
)


def _redact_assignment(match: re.Match[str]) -> str:
    value = match.group("value")
    quote = value[0] if value[:1] in "\"'" else ""
    return f"{match.group('prefix')}{quote}{_REDACTED}{quote}"


def redact_secrets(text: str | None) -> str | None:
    """Deterministically redact common secret shapes before persistence / display.

    Covers secret assignments (api_key/token/password/DATABASE_URL/service-role …),
    provider tokens (OpenAI ``sk-``; GitHub ``ghp_``/``gho_``/``ghu_``/``ghs_``/
    ``ghr_``/``github_pat_``; Slack ``xox*``), AWS access key IDs (AKIA/ASIA), JWTs,
    ``Authorization: Bearer`` tokens, and AWS SigV4 presigned-URL params. Replaces
    each with a stable :data:`_REDACTED` placeholder while preserving surrounding
    line structure, so a snippet's evidence grade is unchanged. Does NOT touch
    ordinary code identifiers — only the high-signal token/secret shapes above.
    """
    if not text:
        return text
    # Bearer first: ``Authorization: Bearer <token>`` would otherwise be partially
    # matched by the secret-assignment rule (which redacts only the word "Bearer"
    # and leaves the token), so the whole token must be scrubbed before that runs.
    out = _BEARER_RE.sub(f"Bearer {_REDACTED}", text)
    out = _SECRET_ASSIGN_RE.sub(_redact_assignment, out)
    out = _SIGNED_URL_PARAM_RE.sub(lambda m: f"{m.group('key')}{_REDACTED}", out)
    out = _JWT_RE.sub(_REDACTED, out)
    out = _GITHUB_TOKEN_RE.sub(_REDACTED, out)
    out = _SLACK_TOKEN_RE.sub(_REDACTED, out)
    out = _SK_KEY_RE.sub(_REDACTED, out)
    out = _AWS_KEY_RE.sub(_REDACTED, out)
    return out


# ── Grade vocabulary (ordered strongest → weakest) ────────────────────────────

GRADE_IMPLEMENTATION_BODY = "implementation_body"
GRADE_SUPPORTING_LOGIC = "supporting_logic"
GRADE_CONFIG_OR_CONSTANT = "config_or_constant"
GRADE_COMMENT_OR_DOCSTRING = "comment_or_docstring"
GRADE_IMPORT_ONLY = "import_only"
GRADE_ROUTE_DECORATOR_ONLY = "route_decorator_only"
GRADE_REPO_LEVEL_FALLBACK = "repo_level_fallback"

EVIDENCE_QUALITY_GRADES = (
    GRADE_IMPLEMENTATION_BODY,
    GRADE_SUPPORTING_LOGIC,
    GRADE_CONFIG_OR_CONSTANT,
    GRADE_COMMENT_OR_DOCSTRING,
    GRADE_IMPORT_ONLY,
    GRADE_ROUTE_DECORATOR_ONLY,
    GRADE_REPO_LEVEL_FALLBACK,
)

# Lower rank = stronger / preferred as top evidence. ``implementation_body`` and
# ``supporting_logic`` are the only "strong" grades that may be shown as TOP
# evidence; everything else is weak supporting/fallback evidence that is only
# surfaced when no stronger grade exists for the same repo + skill.
_GRADE_RANK = {
    GRADE_IMPLEMENTATION_BODY: 0,
    GRADE_SUPPORTING_LOGIC: 1,
    GRADE_CONFIG_OR_CONSTANT: 2,
    GRADE_ROUTE_DECORATOR_ONLY: 3,
    GRADE_COMMENT_OR_DOCSTRING: 4,
    GRADE_IMPORT_ONLY: 5,
    GRADE_REPO_LEVEL_FALLBACK: 6,
}

_STRONG_GRADES = frozenset({GRADE_IMPLEMENTATION_BODY, GRADE_SUPPORTING_LOGIC})


def grade_rank(grade: str | None) -> int:
    """Sort key for a grade — lower is stronger. Unknown grades sort last."""
    return _GRADE_RANK.get(grade or "", 9)


def is_strong_grade(grade: str | None) -> bool:
    """True only for grades fit to be TOP evidence (implementation/supporting)."""
    return grade in _STRONG_GRADES


def is_weak_grade(grade: str | None) -> bool:
    """True for a weak grade (config/comment/import/decorator/repo fallback)."""
    return bool(grade) and grade not in _STRONG_GRADES


# Honest, recruiter-readable label for each grade. Used to replace a stale
# keyword-derived selection reason ("ML model instantiation", "Cloud deployment
# command") when a focused range turns out to be a docstring / import / config /
# bare route decorator — the reason must describe what the range ACTUALLY is, so a
# module docstring is never presented as ML implementation evidence.
_GRADE_REASON: dict[str, str] = {
    GRADE_IMPLEMENTATION_BODY: "implementation body",
    GRADE_SUPPORTING_LOGIC: "supporting implementation logic",
    GRADE_CONFIG_OR_CONSTANT: "configuration/constant definitions",
    GRADE_COMMENT_OR_DOCSTRING: "module docstring or header comment",
    GRADE_IMPORT_ONLY: "import statements",
    GRADE_ROUTE_DECORATOR_ONLY: "route decorator without a handler body",
    GRADE_REPO_LEVEL_FALLBACK: "repository-level context",
}


def describe_grade(grade: str | None) -> str:
    """Return an honest, human-readable selection reason for a grade band."""
    return _GRADE_REASON.get(grade or "", "repository-level context")


# Persisted selection-reason phrases (from the keyword scanner) that OVERCLAIM an
# implementation. On a WEAK / fallback / ungraded row these must never be shown as
# an implementation label — the range was never validated as a real ML body or an
# executed deployment. Matched at read/render time so a legacy row can never
# present a docstring / import / config / bare deploy line as ML implementation.
_OVERCLAIMING_REASON_RE = re.compile(
    r"ML\s+(?:model\s+instantiation|training\s+call|prediction|inference)"
    r"|model\s+instantiation|training\s+call|prediction/inference"
    r"|Cloud\s+deployment\s+command|deployment\s+command",
    re.IGNORECASE,
)

# Conservative, honest replacements for a neutralized weak/ungraded row.
_SAFE_WEAK_REASON = "Weak GitHub signal; not primary implementation proof"
_SAFE_REPO_REASON = "Repository-level GitHub signal"


def is_overclaiming_reason(reason: str | None) -> bool:
    """True when a persisted selection reason claims ML/deployment implementation
    (e.g. "ML model instantiation", "Cloud deployment command")."""
    return bool(reason) and bool(_OVERCLAIMING_REASON_RE.search(reason))


def safe_selection_reason(grade: str | None, reason: str | None) -> str:
    """Read-time neutraliser for a persisted GitHub ``selection_reason``.

    A row is trusted to keep its stored reason ONLY when its deterministic quality
    grade is STRONG (``implementation_body`` / ``supporting_logic``) — those bodies
    were validated as real implementation / supporting logic. Every WEAK / fallback
    / ungraded / unknown row is fail-closed and NEVER preserves its stored reason —
    not even when the stale text sounds technical (e.g. "model serving inference
    handler", an arbitrary phrase no keyword denylist can enumerate). Such rows are
    relabelled from the GRADE alone:

    * a KNOWN weak band (import / docstring / config / route-decorator) always shows
      its honest grade-derived label (:func:`describe_grade`), discarding whatever
      reason was stored;
    * a FALLBACK grade or legacy ungraded / unknown row shows a conservative
      repository-level label — "Weak GitHub signal; not primary implementation
      proof" when any stale reason was stored, else "Repository-level GitHub signal".

    The result is safe to render/synthesize: a stale reason on a weak row can never
    be presented as implementation evidence, regardless of how technical it reads.
    The narrow overclaiming-keyword denylist (:func:`is_overclaiming_reason`) is NOT
    consulted here — neutralisation is grade-derived, not phrase-derived, so it can
    never miss a stale label that simply avoids the known keywords.
    """
    reason = (reason or "").strip()
    if grade in _STRONG_GRADES:
        return reason or describe_grade(grade)
    # KNOWN weak band → grade-derived label ONLY (the stored reason is discarded,
    # even when it reads as technical). ``_GRADE_RANK`` enumerates every known band.
    if grade and grade in _GRADE_RANK and grade != GRADE_REPO_LEVEL_FALLBACK:
        return describe_grade(grade)
    # Fallback grade or legacy ungraded / unknown row → fail closed, reason dropped.
    return _SAFE_WEAK_REASON if reason else _SAFE_REPO_REASON


# ── Read-time ML semantic validation (implementation_body → primary ML gate) ──
#
# A persisted ``implementation_body`` grade proves the range was a real code body at
# scan time. For a Machine Learning skill, "primary implementation proof" requires
# MORE: the trusted EXECUTABLE body / snippet / server-side provenance must itself
# carry an actual ML executable signal — a ``.fit(`` / ``.predict(`` /
# ``.predict_proba(`` call, ``train_test_split(``, an evaluation metric call
# (``accuracy_score`` / ``f1_score`` / ``roc_auc_score`` / ``r2_score`` …), an
# sklearn / xgboost / lightgbm estimator constructor, a torch / tensorflow / keras
# training or inference call, or a model-artifact ``joblib``/``pickle`` save-load.
#
# It FAILS CLOSED: the stale ``selection_reason``, the file path, and the function
# name are LABELS, never proof. A stale reason like "ML model instantiation", a
# ``train.py`` filename, or a ``train_model`` function name can NO LONGER, by
# themselves, preserve a Machine Learning ``implementation_body``. Deployment-only /
# serving-only / cloud-only / FastAPI-route-only / config-only / import-only bodies
# therefore never survive unless the executable body carries a real ML signal. Read-
# time consumers validate with :func:`ml_implementation_is_valid` and downgrade via
# :func:`effective_evidence_grade`.
#
# The regex matches CONCRETE executable code constructs (a call paren or a framework
# module reference), never natural-language prose — so a reason phrase that merely
# *mentions* "training" or "prediction" is not mistaken for executable ML code.
_ML_EXECUTABLE_SIGNAL_RE = re.compile(
    # concrete ML method CALLS on a model / estimator (the call paren is required)
    r"\.(?:fit|fit_transform|fit_predict|partial_fit|predict|predict_proba|"
    r"predict_log_proba|decision_function|evaluate|score|transform|inverse_transform)\s*\("
    # data split / cross-validation / hyperparameter search (call form)
    r"|\b(?:train_test_split|cross_val_score|cross_validate|GridSearchCV|"
    r"RandomizedSearchCV|StratifiedKFold|KFold)\s*\("
    # evaluation metric CALLS
    r"|\b(?:accuracy_score|f1_score|precision_score|recall_score|roc_auc_score|"
    r"roc_curve|confusion_matrix|classification_report|mean_squared_error|"
    r"mean_absolute_error|r2_score|log_loss)\s*\("
    # estimator / model CONSTRUCTORS used in an executable body (call paren required)
    r"|\b(?:RandomForest(?:Classifier|Regressor)|XGB(?:Classifier|Regressor)|"
    r"LGBM(?:Classifier|Regressor)|LightGBM|GradientBoosting(?:Classifier|Regressor)|"
    r"LogisticRegression|LinearRegression|DecisionTree(?:Classifier|Regressor)|"
    r"KMeans|KNeighbors(?:Classifier|Regressor)|SVC|SVR|GaussianNB|MLPClassifier)\s*\("
    # feature transformers inside an ML pipeline body (constructor call form)
    r"|\b(?:StandardScaler|MinMaxScaler|RobustScaler|OneHotEncoder|LabelEncoder|"
    r"CountVectorizer|TfidfVectorizer|ColumnTransformer|Pipeline|make_pipeline)\s*\("
    # deep-learning framework training / inference calls
    r"|\bnn\.(?:Module|Linear|Conv\w*|LSTM|GRU|Sequential)\b"
    r"|\btorch\.(?:load|save|no_grad|tensor|from_numpy)\b"
    r"|\btf\.(?:keras|GradientTape)\b|\bkeras\.(?:models|layers|Sequential)\b"
    r"|\.backward\s*\(|optimizer\.(?:step|zero_grad)\s*\("
    # model artifact save / load (call form) — a strong ML persistence signal
    r"|\b(?:joblib|pickle)\.(?:load|dump)\s*\(",
    re.IGNORECASE,
)


def _strip_comments_and_docstrings(text: str) -> str:
    """Return an EXECUTABLE-ONLY representation of ``text`` with every comment and
    string literal (module/class/function docstrings, triple-quoted blocks, and
    ordinary string literals) removed, so a docstring or comment that merely
    *mentions* ``model.fit(...)`` / ``predict_proba`` / ``train_test_split`` can
    never be mistaken for executable ML code.

    A structural :mod:`tokenize` pass is preferred: it deletes ``COMMENT`` and
    ``STRING`` tokens (which cover every docstring, since a docstring is just a
    bare string-literal expression) while preserving the surrounding executable
    tokens verbatim. Because a persisted excerpt is frequently a *fragment* of a
    larger body (an indented function slice with no enclosing ``def``), tokenizing
    can fail with :class:`(IndentationError, TokenError, SyntaxError)`; in that
    case we fall back to a conservative regex strip of triple-quoted blocks and
    ``#`` line comments. Both paths only ever REMOVE text, so real executable ML
    calls are always preserved.
    """
    try:
        pieces: list[str] = []
        last_end = (1, 0)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                # Preserve newlines so downstream line structure survives, but
                # drop the comment/string content itself.
                start_row, _ = tok.start
                end_row, _ = tok.end
                pieces.append("\n" * (end_row - start_row))
                last_end = tok.end
                continue
            start_row, start_col = tok.start
            end_row, end_col = tok.end
            last_row, last_col = last_end
            if start_row > last_row:
                pieces.append("\n" * (start_row - last_row))
                pieces.append(" " * start_col)
            elif start_col > last_col:
                pieces.append(" " * (start_col - last_col))
            pieces.append(tok.string)
            last_end = tok.end
        return "".join(pieces)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # Fragment / unparseable excerpt: conservative regex strip that only
        # removes triple-quoted blocks and single-line ``#`` comments.
        stripped = _TRIPLE_QUOTED_BLOCK_RE.sub("", text)
        stripped = _LINE_COMMENT_RE.sub("", stripped)
        return stripped


_TRIPLE_QUOTED_BLOCK_RE = re.compile(
    r"[rRbBuUfF]{0,3}(?:'''.*?'''|\"\"\".*?\"\"\")",
    re.DOTALL,
)
# A ``#`` that is not inside a string literal begins a comment to end of line.
# On the regex fallback path triple-quoted blocks are already gone, so this only
# needs to avoid ``#`` chars sitting inside ordinary single-line quotes.
_LINE_COMMENT_RE = re.compile(
    r"""(?m)(?<!['"])#.*$""",
)


def has_ml_executable_signal(*parts: str | None) -> bool:
    """True when any provided text carries a concrete ML EXECUTABLE code signal
    (a ``.fit(`` / ``.predict(`` / ``.predict_proba(`` call, ``train_test_split(``,
    a metric call, an estimator constructor, a torch/tf/keras training-or-inference
    call, or a ``joblib``/``pickle`` model save-load).

    Only concrete code constructs match, and only in EXECUTABLE code: comments and
    string/docstring literals are structurally stripped (via
    :func:`_strip_comments_and_docstrings`) BEFORE matching, so a docstring or
    comment that merely mentions ``model.fit(...)`` / ``predict_proba`` /
    ``train_test_split`` is NOT a signal. Natural-language prose — a reason phrase
    like "ML model instantiation", "model serving inference handler", "training
    call", or a bare ``train.py`` / ``train_model`` mention — is likewise never a
    signal: those are labels, and a label can never be executable proof.
    """
    haystack = " ".join(p for p in parts if p)
    if not haystack.strip():
        return False
    executable = _strip_comments_and_docstrings(haystack)
    return bool(executable.strip()) and bool(
        _ML_EXECUTABLE_SIGNAL_RE.search(executable)
    )


def ml_implementation_is_valid(
    *,
    reason: str | None = None,
    code_snippet: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
    provenance: str | None = None,
    ml_signal: bool | None = None,
) -> bool:
    """Read-time ML gate for a persisted ``implementation_body`` on an ML skill.

    Returns True only when a TRUSTED executable body proves ML — the persisted code
    snippet or the server-side analyzer provenance carries a real ML executable
    signal (fit / predict / predict_proba / train_test_split / metric call /
    estimator constructor / framework training / model save-load). Otherwise it
    returns False and the caller downgrades the row.

    ``ml_signal`` is an authoritative GRADE-TIME verdict for rows whose trusted
    executable body is inspected where it is available (the canonical adapter grades
    the server-side provenance excerpt, then discards the raw snippet rather than
    re-exposing it). It is tri-state: ``True`` = the trusted body carried a real ML
    executable signal → valid; ``False`` = the trusted body was inspected and carried
    NONE → fail closed; ``None`` = no grade-time verdict, fall back to any read-time
    trusted ``code_snippet`` / ``provenance`` body.

    It FAILS CLOSED. ``reason``, ``file_path`` and ``function_name`` are accepted for
    caller convenience but are LABELS, never proof: a stale "ML model instantiation"
    reason, a ``train.py`` filename, or a ``train_model`` function name can no longer
    preserve a Machine Learning ``implementation_body`` on their own. A deployment-
    only / serving-only / cloud-only / FastAPI-route-only / config-only / import-only
    body — anything whose executable snippet lacks a real ML inference / training /
    evaluation signal — is rejected. When no trusted body is available at read time,
    the row is downgraded (conservative), never given the benefit of the doubt.
    """
    # An authoritative grade-time verdict (from the trusted provenance body) wins.
    if ml_signal is True:
        return True
    if ml_signal is False:
        return False
    # No grade-time verdict: only the trusted EXECUTABLE body / provenance may prove
    # ML. reason / file_path / function_name are deliberately excluded — they are
    # labels, and a label can never be executable proof.
    trusted_body = " ".join(p for p in (code_snippet, provenance) if p)
    return has_ml_executable_signal(trusted_body)


def effective_evidence_grade(
    grade: str | None,
    *,
    is_ml: bool = False,
    reason: str | None = None,
    code_snippet: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
    provenance: str | None = None,
    ml_signal: bool | None = None,
) -> str | None:
    """Read-time semantic validation of a persisted ``evidence_quality_grade``.

    Only a Machine Learning ``implementation_body`` is re-validated: it stays
    ``implementation_body`` ONLY when the trusted executable body / snippet /
    provenance carries a real ML executable signal, otherwise it FAILS CLOSED and is
    DOWNGRADED to ``supporting_logic`` so a trusted deployment-only / serving-only /
    route-only body — or one whose only "ML" evidence is a stale reason, a
    ``train.py`` filename, or a ``train_model`` function name — can never present as
    Machine Learning primary implementation proof (it is still a real body, just not
    proven ML). Non-ML skills and every non-implementation grade are returned
    unchanged. The caller supplies ``is_ml`` (e.g. ``is_ml_skill(skill)``) so this
    stdlib-only module never depends on the skill-taxonomy service.
    """
    if grade != GRADE_IMPLEMENTATION_BODY or not is_ml:
        return grade
    if ml_implementation_is_valid(
        reason=reason,
        code_snippet=code_snippet,
        file_path=file_path,
        function_name=function_name,
        provenance=provenance,
        ml_signal=ml_signal,
    ):
        return grade
    return GRADE_SUPPORTING_LOGIC


# ── Line-shape classifiers (snippet grading) ──────────────────────────────────

_IMPORT_RE = re.compile(r"^\s*(?:import\s+\w|from\s+[\w.]+\s+import\b|from\s+\.+\s*import\b)")
_COMMENT_RE = re.compile(r"^\s*(?:#|//)")
# A triple-quoted docstring delimiter (opens or closes a docstring block).
_DOCSTRING_DELIM_RE = re.compile(r"^\s*[rRbBuUfF]*(?:\"\"\"|''')")
_DECORATOR_RE = re.compile(r"^\s*@")
_ROUTE_DECORATOR_RE = re.compile(
    r"^\s*@(?:app|router|api|bp|blueprint|\w+)\.(?:get|post|put|delete|patch|route|websocket)\s*\(",
    re.IGNORECASE,
)
_SIGNATURE_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(|^\s*class\s+\w+\b")
# A constant / config / dunder / type-only assignment line — plumbing, not logic.
_CONSTANT_RE = re.compile(
    r"^\s*[A-Z_][A-Z0-9_]{1,}\s*[:=]"  # CONST = ... / CONST: type = ...
    r"|^\s*__\w+__\s*="  # __version__ = ...
    r"|^\s*\w+\s*[:=]\s*(?:str|int|float|bool|bytes|list|dict|tuple|set|"
    r"List|Dict|Tuple|Set|Optional|Any|Sequence|Mapping)\b[^()]*$",  # type-only / literal const
)
_SETUP_RE = re.compile(
    r"sys\.path|__file__|os\.environ|load_dotenv|dotenv|PYTHONPATH|Path\(__file__\)",
    re.IGNORECASE,
)
_PASS_ELLIPSIS_RE = re.compile(r"^\s*(?:pass|\.\.\.|raise\s+NotImplementedError)\s*$")

# Real implementation signals — ML pipeline, API handler logic, control flow,
# data access, model artifacts, security checks. Mirrors the service-layer
# profile signals so the offline scanner and read-time grading agree.
_IMPL_SIGNAL_RE = re.compile(
    r"\.(?:fit|fit_transform|predict|predict_proba|transform|evaluate|score|"
    r"compile|forward|cluster|classify|detect|render|query|execute|fetchone|"
    r"fetchall|commit|filter|save|create|delete|insert|first|all|scalar|"
    r"map|reduce|apply|groupby|merge|dropna|fillna|encode|decode|load|dump)\s*\("
    r"|\b(?:if|elif|else|for|while|try|except|with|return\s+\S|raise|await|yield)\b"
    r"|accuracy_score|f1_score|precision_score|recall_score|roc_auc|confusion_matrix"
    r"|classification_report|mean_squared_error|r2_score|train_test_split"
    r"|StandardScaler|MinMaxScaler|OneHotEncoder|LabelEncoder|CountVectorizer|TfidfVectorizer"
    r"|RandomForest|XGB|LogisticRegression|GradientBoosting|DecisionTree|KMeans|Sequential"
    r"|joblib\.(?:load|dump)|pickle\.(?:load|dump)|torch\.(?:load|save)"
    r"|HTTPException|JSONResponse|jsonify|status_code|validate|serializ|BaseModel"
    r"|request\.(?:json|args|form|get_json)|current_user|require_auth|permission|authoriz"
    r"|verify_token|sanitiz|is_safe|consent"
    r"|\b(?:model|clf|net|pipeline|regressor|classifier|estimator|df|dataset|scaler|encoder)\s*=",
    re.IGNORECASE,
)


def _line_kind(line: str) -> str:
    """Classify ONE source line into a coarse kind used by snippet grading.

    Returns ``""`` for a blank line (ignored by callers).
    """
    s = line.strip()
    if not s:
        return ""
    if _COMMENT_RE.match(s):
        return "comment"
    if _IMPORT_RE.match(s):
        return "import"
    if _ROUTE_DECORATOR_RE.match(s):
        return "route_decorator"
    if _DECORATOR_RE.match(s):
        return "decorator"
    if _SIGNATURE_RE.match(s):
        return "signature"
    if _PASS_ELLIPSIS_RE.match(s):
        return "filler"
    if _SETUP_RE.search(s):
        return "setup"
    if _CONSTANT_RE.match(s):
        return "constant"
    return "code"


def _strip_docstrings(lines: list[str]) -> tuple[list[str], bool]:
    """Drop triple-quoted docstring/string blocks. Returns (kept, had_docstring).

    A line-anchored snippet can include a docstring with prose that would
    otherwise read as "code"; we remove whole ``\"\"\"…\"\"\"`` blocks (and the
    single-line ``\"\"\"doc\"\"\"`` form) so grading sees only real statements.
    """
    kept: list[str] = []
    had_doc = False
    in_doc = False
    delim = ""
    for line in lines:
        s = line.strip()
        if in_doc:
            had_doc = True
            if delim and delim in s:
                in_doc = False
            continue
        m = _DOCSTRING_DELIM_RE.match(s)
        if m:
            had_doc = True
            d = '"""' if '"""' in s else "'''"
            # Single-line docstring (opens and closes on the same line).
            rest = s[s.index(d) + 3 :]
            if d in rest:
                continue
            in_doc = True
            delim = d
            continue
        kept.append(line)
    return kept, had_doc


def grade_python_snippet(snippet: str | None) -> str:
    """Grade a Python source snippet into one ``evidence_quality_grade``.

    Deterministic, regex/structural only. The ordering of checks matters: an
    all-import / all-comment / all-constant block is graded by what it *is*; a
    bare route decorator (no handler body) is ``route_decorator_only``; a block
    that contains real implementation signals is ``implementation_body``; a
    plain ``def``/``class`` with statements but no notable logic is
    ``supporting_logic``.
    """
    if not snippet or not snippet.strip():
        return GRADE_REPO_LEVEL_FALLBACK

    raw_lines = [ln for ln in snippet.splitlines()]
    non_blank = [ln for ln in raw_lines if ln.strip()]
    if not non_blank:
        return GRADE_REPO_LEVEL_FALLBACK

    kinds = [_line_kind(ln) for ln in non_blank]
    substantive_kinds = [k for k in kinds if k not in ("comment",)]

    # Pure comment block.
    if substantive_kinds and all(k == "comment" for k in kinds):
        return GRADE_COMMENT_OR_DOCSTRING

    # Strip docstrings, then re-evaluate what real statements remain.
    body_lines, had_doc = _strip_docstrings(non_blank)
    body_kinds = [_line_kind(ln) for ln in body_lines if ln.strip()]
    real = [ln for ln, k in zip(body_lines, body_kinds) if k not in ("comment",)]

    if not real:
        # Nothing but a docstring (and/or comments) survived.
        return GRADE_COMMENT_OR_DOCSTRING if had_doc or non_blank else GRADE_REPO_LEVEL_FALLBACK

    real_kinds = [_line_kind(ln) for ln in real]

    # All imports (with optional comments) → import-only.
    if all(k == "import" for k in real_kinds):
        return GRADE_IMPORT_ONLY

    # Bare route decorator(s) + at most a signature/decorator/filler — no body.
    has_route = any(k == "route_decorator" for k in real_kinds)
    body_logic = [k for k in real_kinds if k in ("code",)]
    has_impl_signal = bool(_IMPL_SIGNAL_RE.search("\n".join(real)))
    if has_route and not has_impl_signal and not body_logic:
        return GRADE_ROUTE_DECORATOR_ONLY

    # All constants / setup / type-decls (with optional decorators/signatures that
    # carry no body) → config/constant.
    if all(k in ("constant", "setup", "import") for k in real_kinds):
        return GRADE_CONFIG_OR_CONSTANT

    # Real implementation logic anywhere → implementation body.
    if has_impl_signal:
        return GRADE_IMPLEMENTATION_BODY

    # Has a def/class with statements, or assignments/calls, but no notable logic
    # signal → supporting logic. An all-filler (pass/...) body is config-like.
    if all(k in ("filler", "signature", "decorator", "route_decorator") for k in real_kinds):
        return GRADE_ROUTE_DECORATOR_ONLY if has_route else GRADE_COMMENT_OR_DOCSTRING
    return GRADE_SUPPORTING_LOGIC


# ── Metadata-only grading (no snippet available) ──────────────────────────────

# Natural-language reasons that imply real implementation evidence.
_IMPL_REASON_RE = re.compile(
    r"handler\s+body|implementation|model\s+(?:train|fit|predict|serv|inference|definition)"
    r"|train(?:ing)?\b|predict|inference|evaluat|metric|preprocess|feature[\s_-]*engineer"
    r"|validation|service\s+call|db\s+call|database|query|permission|auth|sanitiz|consent"
    r"|retrain|pipeline|serving|deployment\s+logic",
    re.IGNORECASE,
)
_WEAK_REASON_RE = re.compile(
    r"\bimport\b|docstring|comment|module\s+doc|constant|config|setup|sys\.path"
    r"|decorator\s+only|signature\s+only|boilerplate|metadata|requirement",
    re.IGNORECASE,
)
_ROUTE_REASON_RE = re.compile(r"route\s+decorator|endpoint\s+decorator", re.IGNORECASE)


def grade_evidence(
    *,
    file_path: str | None = None,
    code_snippet: str | None = None,
    selection_reason: str | None = None,
    evidence_kind: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Grade one evidence row, preferring the source snippet when available.

    * When a Python ``code_snippet`` is present, grade it structurally (the
      strongest, most honest signal) via :func:`grade_python_snippet`.
    * Otherwise fall back to CONSERVATIVE metadata grading from
      ``selection_reason`` / ``evidence_kind`` — a weak/decorator/import reason is
      NEVER upgraded to an implementation body; only an explicit implementation
      reason yields ``supporting_logic`` (never ``implementation_body`` without a
      body to back it). With nothing to go on, returns ``repo_level_fallback``.
    """
    path = (file_path or "").lower()
    is_python = path.endswith(".py") or path.endswith(".pyi")

    snippet = code_snippet or ""
    if snippet.strip() and (is_python or not path):
        return grade_python_snippet(snippet)

    # Non-Python snippet present: a light structural read (imports/comments only).
    if snippet.strip():
        non_blank = [ln for ln in snippet.splitlines() if ln.strip()]
        kinds = [_line_kind(ln) for ln in non_blank]
        real = [k for k in kinds if k != "comment"]
        if real and all(k == "import" for k in real):
            return GRADE_IMPORT_ONLY
        if non_blank and all(k == "comment" for k in kinds):
            return GRADE_COMMENT_OR_DOCSTRING
        if _IMPL_SIGNAL_RE.search(snippet):
            return GRADE_IMPLEMENTATION_BODY
        return GRADE_SUPPORTING_LOGIC

    # No snippet — conservative metadata grading.
    reason = selection_reason or ""
    kind = (evidence_kind or "").lower()
    if _ROUTE_REASON_RE.search(reason) and not _IMPL_REASON_RE.search(reason):
        return GRADE_ROUTE_DECORATOR_ONLY
    if _WEAK_REASON_RE.search(reason) and not _IMPL_REASON_RE.search(reason):
        if re.search(r"\bimport\b", reason, re.IGNORECASE):
            return GRADE_IMPORT_ONLY
        if re.search(r"docstring|comment|module\s+doc", reason, re.IGNORECASE):
            return GRADE_COMMENT_OR_DOCSTRING
        return GRADE_CONFIG_OR_CONSTANT
    if kind in ("endpoint", "function", "class") or _IMPL_REASON_RE.search(reason):
        # A located function/class/endpoint with a real line range is supporting
        # logic at minimum — but without a body we never claim implementation_body.
        if isinstance(line_start, int) and isinstance(line_end, int) and line_end > line_start:
            return GRADE_SUPPORTING_LOGIC
        if kind == "endpoint":
            return GRADE_ROUTE_DECORATOR_ONLY
        return GRADE_SUPPORTING_LOGIC
    return GRADE_REPO_LEVEL_FALLBACK


# ── AST focusing ──────────────────────────────────────────────────────────────


def _enclosing_def(tree: ast.AST, anchor: int) -> ast.AST | None:
    """Return the INNERMOST function/class node enclosing 1-indexed ``anchor``.

    Prefers the most deeply nested (smallest) enclosing node so a method inside a
    class focuses to the method body, not the whole class.
    """
    best: ast.AST | None = None
    best_span = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None:
            continue
        # A decorated def's ``lineno`` is the ``def`` line; include decorators so an
        # anchor that landed on a decorator still maps into the function.
        deco_start = start
        for deco in getattr(node, "decorator_list", []) or []:
            dline = getattr(deco, "lineno", None)
            if dline is not None:
                deco_start = min(deco_start, dline)
        if deco_start <= anchor <= end:
            span = end - deco_start
            if best_span is None or span < best_span:
                best = node
                best_span = span
    return best


def _body_start_line(node: ast.AST) -> int:
    """First body line AFTER the signature + docstring (1-indexed)."""
    body = list(getattr(node, "body", []) or [])
    if not body:
        return getattr(node, "lineno", 1)
    first = body[0]
    # Skip a leading docstring (an Expr wrapping a string constant).
    if (
        isinstance(first, ast.Expr)
        and isinstance(getattr(first, "value", None), ast.Constant)
        and isinstance(first.value.value, str)
    ):
        if len(body) > 1:
            return getattr(body[1], "lineno", getattr(first, "end_lineno", first.lineno) + 1)
        # Body is ONLY a docstring — fall back to the docstring line itself.
        return getattr(first, "lineno", node.lineno)
    return getattr(first, "lineno", node.lineno)


def _decorator_start_line(node: ast.AST) -> int:
    """The first decorator line of a node, else its own ``lineno`` (1-indexed)."""
    start = getattr(node, "lineno", 1)
    for deco in getattr(node, "decorator_list", []) or []:
        dline = getattr(deco, "lineno", None)
        if dline is not None:
            start = min(start, dline)
    return start


def focus_python_range(
    source: str,
    anchor_start: int,
    anchor_end: int | None = None,
    *,
    max_lines: int = 80,
    min_lines: int = 4,
    include_signature: bool = False,
) -> tuple[int, int, str] | None:
    """Focus a Python line anchor onto its enclosing function/class body.

    Returns ``(line_start, line_end, evidence_quality_grade)`` — 1-indexed,
    clamped to the source — or ``None`` when the source cannot be parsed. The
    returned range:

    * opens on the first real body statement (after the signature + docstring),
      never on a decorator/signature/docstring-only line;
    * is bounded to ``max_lines`` (keeps a giant function readable);
    * carries the grade of the *focused* body so callers can demote a range that
      focuses to nothing but a docstring / constants.

    When the anchor is NOT inside any function/class (module-level imports /
    constants / docstring), the original anchor window is graded in place and
    returned, so the caller can demote it rather than promote module plumbing.
    """
    if not source.strip():
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    total = len(source.splitlines())
    if total == 0:
        return None
    anchor_start = max(1, min(anchor_start, total))
    a_end = anchor_end if isinstance(anchor_end, int) and anchor_end >= anchor_start else anchor_start
    a_end = min(a_end, total)

    node = _enclosing_def(tree, anchor_start)
    src_lines = source.splitlines()

    if node is None:
        # Module-level anchor — grade the anchor window itself; do not promote.
        window = "\n".join(src_lines[anchor_start - 1 : a_end])
        return anchor_start, a_end, grade_python_snippet(window)

    body_start = _body_start_line(node)
    node_end = getattr(node, "end_lineno", a_end)
    # ``include_signature`` keeps the decorator + ``def``/``class`` line as context
    # (so a recruiter sees what the body belongs to); otherwise the range opens on
    # the first real body statement (after the docstring). The GRADE is always
    # computed from the body (signature/decorator/docstring stripped) so a
    # decorator+signature+docstring-only function still grades weak.
    range_start = _decorator_start_line(node) if include_signature else body_start
    start = max(1, min(range_start, total))
    end = min(node_end, total, start + max_lines - 1)
    if end < start:
        end = min(start + min_lines - 1, total)
    # Ensure a minimum readable window when the body is tiny but real.
    if end - start + 1 < min_lines:
        end = min(start + min_lines - 1, total)

    # Grade the body region (after the signature + docstring), never the signature.
    body_end = min(node_end, total)
    body_region = "\n".join(src_lines[min(body_start, total) - 1 : body_end])
    grade = grade_python_snippet(body_region)
    return start, end, grade


def docstring_and_comment_lines(source: str) -> set[int]:
    """Return the 1-indexed line numbers that are docstrings, bare string
    expressions, or ``#`` comments in ``source``.

    Used by the offline scanner so a keyword sitting inside a module/function
    docstring (prose such as "... fits a RandomForest ...") is never chosen as a
    high-signal implementation anchor. Falls back to a comment-only scan when the
    source cannot be parsed. Never raises.
    """
    lines: set[int] = set()
    src_lines = source.splitlines()
    for i, raw in enumerate(src_lines, start=1):
        if _COMMENT_RE.match(raw.strip()):
            lines.add(i)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return lines
    for node in ast.walk(tree):
        # A bare string statement is a docstring (module/class/function) or a
        # stray string literal used as prose — never executable logic.
        if (
            isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
        ):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", start)
            if start is not None and end is not None:
                lines.update(range(start, end + 1))
    return lines


def focus_python_anchor(
    source: str, anchor_line: int, *, max_lines: int = 80
) -> tuple[int, int, str] | None:
    """Convenience: focus a single 1-indexed ``anchor_line``. See
    :func:`focus_python_range`."""
    return focus_python_range(source, anchor_line, anchor_line, max_lines=max_lines)
