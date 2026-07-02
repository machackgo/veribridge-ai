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
    "CODE_ROLE_KEYS",
    "CODE_ROLE_LABELS",
    "ROLE_DOCUMENTATION_HEADER",
    "ROLE_IMPORTS_SETUP",
    "ROLE_CONFIG_CONSTANTS",
    "ROLE_API_ROUTE_SHELL",
    "ROLE_DATA_LOADING",
    "ROLE_FEATURE_ENGINEERING",
    "ROLE_MODEL_TRAINING",
    "ROLE_EVALUATION_METRICS",
    "ROLE_PREDICTION_INFERENCE",
    "ROLE_DEPLOYMENT_SERVING",
    "ROLE_REPOSITORY_CONTEXT",
    "ROLE_UNKNOWN_NEEDS_REVIEW",
    "describe_code_role",
    "code_role_from_grade",
    "classify_code_role",
    "effective_code_role",
    "CODE_BLOCK_PURPOSE_KEYS",
    "CODE_BLOCK_PURPOSE_LABELS",
    "PURPOSE_RETRAINING_DOCUMENTATION",
    "PURPOSE_PIPELINE_DOCUMENTATION",
    "PURPOSE_USAGE_INSTRUCTIONS",
    "PURPOSE_DOCUMENTATION_OVERVIEW",
    "PURPOSE_IMPORTS_DEPENDENCIES",
    "PURPOSE_CONFIG_PATHS_ARTIFACTS",
    "PURPOSE_DATA_LOADING",
    "PURPOSE_PREPROCESSING_FEATURES",
    "PURPOSE_MODEL_TRAINING",
    "PURPOSE_MODEL_EVALUATION",
    "PURPOSE_PREDICTION_INFERENCE",
    "PURPOSE_API_REQUEST_SCHEMA",
    "PURPOSE_API_ROUTE_SHELL",
    "PURPOSE_API_PREDICTION_HANDLER",
    "PURPOSE_MODEL_LOADING",
    "PURPOSE_ARTIFACT_PERSISTENCE",
    "PURPOSE_DEPLOYMENT_SERVING",
    "PURPOSE_CLOUD_STORAGE_IO",
    "PURPOSE_FRONTEND_UI_COMPONENT",
    "PURPOSE_TEST_VALIDATION",
    "PURPOSE_REPOSITORY_CONTEXT",
    "PURPOSE_UNKNOWN_NEEDS_REVIEW",
    "PURPOSE_HYPERPARAMETER_TUNING",
    "PURPOSE_TEXT_NLP_PROCESSING",
    "PURPOSE_EMBEDDING_GENERATION",
    "PURPOSE_LLM_CALL_WRAPPER",
    "PURPOSE_RAG_RETRIEVAL",
    "PURPOSE_IMAGE_PROCESSING_CV",
    "PURPOSE_DATABASE_OPERATION",
    "PURPOSE_AUTH_PERMISSION_CHECK",
    "PURPOSE_CI_CD_WORKFLOW",
    "PURPOSE_CONTAINERIZATION",
    "PURPOSE_DATA_VISUALIZATION",
    "PURPOSE_ARCHITECTURE_DOCUMENTATION",
    "PURPOSE_API_PROTOCOL_DOCUMENTATION",
    "PURPOSE_SERVING_DOCUMENTATION",
    "PURPOSE_DEPLOYMENT_DOCUMENTATION",
    "PURPOSE_FRONTEND_PAGE_COMPONENT",
    "PURPOSE_FRONTEND_LAYOUT_COMPONENT",
    "PURPOSE_FRONTEND_FORM_COMPONENT",
    "PURPOSE_FRONTEND_STATE_MANAGEMENT",
    "PURPOSE_FRONTEND_API_CLIENT",
    "PURPOSE_FRONTEND_RESULTS_DISPLAY",
    "PURPOSE_FRONTEND_CHART_COMPONENT",
    "PURPOSE_FRONTEND_TABLE_LIST",
    "PURPOSE_FRONTEND_DIALOG_ALERT",
    "PURPOSE_FRONTEND_NAVIGATION",
    "PURPOSE_FRONTEND_PROVIDER_THEME",
    "PURPOSE_FRONTEND_LOADING_ERROR",
    "PURPOSE_FRONTEND_UI_PRIMITIVE",
    "PURPOSE_GEO_FEATURE_HANDLING",
    "PURPOSE_GEO_FEATURE_ENGINEERING",
    "PURPOSE_GEO_DISTANCE_CALCULATION",
    "PURPOSE_GEO_GEOCODING_API",
    "PURPOSE_GEO_DATA_LOADING",
    "PURPOSE_GEO_VISUALIZATION",
    "PURPOSE_CONTAINER_BASE_IMAGE",
    "PURPOSE_CONTAINER_DEPENDENCY_INSTALL",
    "PURPOSE_CONTAINER_FILES_SETUP",
    "PURPOSE_CONTAINER_ENV_CONFIG",
    "PURPOSE_CONTAINER_PORT_EXPOSURE",
    "PURPOSE_CONTAINER_RUNTIME_COMMAND",
    "PURPOSE_CONTAINER_MULTI_STAGE_BUILD",
    "PURPOSE_CONTAINER_BUILD_STEP",
    "PURPOSE_CONTAINER_HEALTHCHECK",
    "PURPOSE_INPUT_VALIDATION",
    "PURPOSE_FILE_IO",
    "PURPOSE_NETWORK_API_CALL",
    "PURPOSE_ERROR_HANDLING",
    "PURPOSE_LOGGING_MONITORING",
    "PURPOSE_DATA_TRANSFORMATION",
    "PURPOSE_API_REQUEST_HANDLER",
    "describe_code_block_purpose",
    "code_block_purpose_summary",
    "BLOCK_KINDS",
    "BLOCK_KIND_DOCUMENTATION_ONLY",
    "BLOCK_KIND_IMPORT_ONLY",
    "BLOCK_KIND_CONFIG_CONSTANTS_ONLY",
    "BLOCK_KIND_EXECUTABLE_CODE",
    "BLOCK_KIND_MIXED",
    "BLOCK_KIND_REPOSITORY_ONLY",
    "BLOCK_KIND_UNKNOWN",
    "classify_block_kind",
    "classify_code_block_purpose",
    "effective_code_block_purpose",
    "SKILL_RELEVANCE_KEYS",
    "SKILL_RELEVANCE_LABELS",
    "RELEVANCE_DIRECT_IMPLEMENTATION",
    "RELEVANCE_DIRECT_CANDIDATE",
    "RELEVANCE_SUPPORTING_IMPLEMENTATION",
    "RELEVANCE_SUPPORTING_CONTEXT",
    "RELEVANCE_PRODUCT_UI_CONTEXT",
    "RELEVANCE_DEPLOYMENT_CONTEXT",
    "RELEVANCE_CROSS_SKILL_CONTEXT",
    "RELEVANCE_DOCUMENTATION_CONTEXT",
    "RELEVANCE_SETUP_CONTEXT",
    "RELEVANCE_TEST_CONTEXT",
    "RELEVANCE_CONTEXT_ONLY",
    "skill_family",
    "describe_skill_relevance",
    "skill_relevance_summary",
    "classify_skill_relevance",
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
ANALYZER_VERSION = "2"

# Historical analyzer names that still count as our own controlled provenance.
_TRUSTED_ANALYZERS = frozenset({ANALYZER_NAME.lower()})
# Analyzer versions whose persisted GRADE is still trusted. A grade stamped by a
# version we no longer recognize fails closed (the read-time consumer re-grades
# from source or caps to a weak fallback) — so a bumped grader never silently
# trusts stale strong grades it can no longer reproduce.
_TRUSTED_ANALYZER_VERSIONS = frozenset({ANALYZER_VERSION})
# Every version OUR scanner has ever stamped. A historical record's redacted
# ``safe_excerpt`` is still our own service-role source capture — the excerpt is
# real source text whose trustworthiness does not depend on which grading logic
# was current when it was stamped — so consumers may re-grade it with the CURRENT
# logic. Only the persisted grade/labels of a historical version fail closed
# (:func:`trusted_provenance` strips them). Without this split, bumping
# ``ANALYZER_VERSION`` would discard every previously captured excerpt and
# collapse all existing rows to repository-level fallback until a full re-scan.
_HISTORICAL_ANALYZER_VERSIONS = _TRUSTED_ANALYZER_VERSIONS | frozenset({"1"})


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
    requires our controlled analyzer name AND a version our scanner has actually
    stamped. Anything a user could have forged in their own metadata can satisfy
    none of this — it is not even read here.

    Versioning is two-tier:

    * a CURRENT-version record is returned as-is (its persisted grade is one the
      current logic would reproduce);
    * a HISTORICAL-version record keeps its redacted ``safe_excerpt`` (our own
      service-role source capture — the source text is version-independent) but
      has its persisted ``evidence_quality_grade`` STRIPPED, so a stale strong
      grade computed by outdated logic is never trusted; consumers re-grade the
      excerpt with the current logic instead;
    * an unrecognized version (never stamped by our scanner) FAILS CLOSED
      entirely.
    """
    if not isinstance(record, dict):
        return None
    if not is_trusted_analyzer(record.get("analyzer_name") or record.get("analyzer")):
        return None
    version = str(record.get("analyzer_version") or "").strip()
    if version not in _HISTORICAL_ANALYZER_VERSIONS:
        return None
    if version in _TRUSTED_ANALYZER_VERSIONS:
        return record
    return {k: v for k, v in record.items() if k != "evidence_quality_grade"}


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


def _import_line_flags(lines: list[str]) -> list[bool]:
    """Per-line flags marking import / require lines (Python and JS/TS forms).

    Multi-line imports are flagged whole: a parenthesized ``from x import (…)``,
    a braced JS ``import { … } from``, and a backslash-continued Python import
    all flag their continuation lines until the statement closes — so a library
    name on ANY line of an import statement is recognized as import text.
    """
    flags: list[bool] = []
    # "" = not in an import; ")" / "}" = inside a bracketed multi-line import
    # awaiting that closer; "\\" = inside a backslash-continued import.
    pending = ""
    for line in lines:
        if pending:
            flags.append(True)
            if pending == "\\":
                if not line.rstrip().endswith("\\"):
                    pending = ""
            elif pending in line:
                pending = ""
            continue
        if _IMPORT_RE.match(line):
            flags.append(True)
            if "(" in line and ")" not in line:
                pending = ")"
            elif "{" in line and "}" not in line:
                pending = "}"
            elif line.rstrip().endswith("\\"):
                pending = "\\"
            continue
        flags.append(False)
    return flags


def _strip_import_lines(text: str) -> str:
    """Drop import / require lines (Python and JS/TS forms) from ``text``.

    Importing a library is NOT the same as using it: ``from langchain.vectorstores
    import FAISS`` / ``import geopy`` / ``import { useState } from "react"`` name a
    dependency without executing anything, yet many semantic signals match the bare
    library name. Every "executable" classification therefore strips import lines
    first, so a dependency name can only ever be a signal on a real usage line.
    """
    lines = text.splitlines()
    flags = _import_line_flags(lines)
    return "\n".join(ln for ln, flagged in zip(lines, flags) if not flagged)


def has_ml_executable_signal(*parts: str | None) -> bool:
    """True when any provided text carries a concrete ML EXECUTABLE code signal
    (a ``.fit(`` / ``.predict(`` / ``.predict_proba(`` call, ``train_test_split(``,
    a metric call, an estimator constructor, a torch/tf/keras training-or-inference
    call, or a ``joblib``/``pickle`` model save-load).

    Only concrete code constructs match, and only in EXECUTABLE code: comments and
    string/docstring literals are structurally stripped (via
    :func:`_strip_comments_and_docstrings`) BEFORE matching, so a docstring or
    comment that merely mentions ``model.fit(...)`` / ``predict_proba`` /
    ``train_test_split`` is NOT a signal. Import lines are stripped too (via
    :func:`_strip_import_lines`): ``from keras.models import Sequential`` names a
    framework module without training anything, so importing sklearn / lightgbm /
    keras is never itself an ML signal — only a real usage line is. Natural-language
    prose — a reason phrase like "ML model instantiation", "model serving inference
    handler", "training call", or a bare ``train.py`` / ``train_model`` mention — is
    likewise never a signal: those are labels, and a label can never be executable
    proof.
    """
    haystack = "\n".join(p for p in parts if p)
    if not haystack.strip():
        return False
    executable = _strip_import_lines(_strip_comments_and_docstrings(haystack))
    return bool(executable.strip()) and bool(
        _ML_EXECUTABLE_SIGNAL_RE.search(executable)
    )


# ── Code role classification (descriptive label, NOT proof strength) ──────────
#
# ``code_role_label`` describes WHAT a focused code block *appears to be*
# (documentation header / imports / config / a model-training body / a
# prediction body / a deployment stanza …). It is deliberately SEPARATE from
# ``evidence_quality_grade``, which decides proof STRENGTH. A weak row (a
# docstring, an import block) may carry a useful role label — "Documentation /
# usage header", "Imports / setup context" — while STILL remaining a weak,
# needs-review signal that is never primary implementation proof.
#
# Classification is conservative and fails closed:
#  * a KNOWN weak structural band (docstring / import / config / bare route
#    decorator) takes its role FROM THE GRADE — a docstring that merely *mentions*
#    ``model.fit(...)`` stays "Documentation / usage header", never "Model
#    training"; and
#  * a richer semantic role (training / inference / evaluation / feature /
#    data-loading / deployment / API) is only assigned from a real EXECUTABLE code
#    signal (or, for a grade that is already STRONG, a conservative reason/path
#    hint). A role label NEVER promotes a row's grade — proof strength still
#    requires ``evidence_quality_grade`` + executable validation.

ROLE_DOCUMENTATION_HEADER = "documentation_header"
ROLE_IMPORTS_SETUP = "imports_setup"
ROLE_CONFIG_CONSTANTS = "config_constants"
ROLE_API_ROUTE_SHELL = "api_route_shell"
ROLE_DATA_LOADING = "data_loading"
ROLE_FEATURE_ENGINEERING = "feature_engineering"
ROLE_MODEL_TRAINING = "model_training"
ROLE_EVALUATION_METRICS = "evaluation_metrics"
ROLE_PREDICTION_INFERENCE = "prediction_inference"
ROLE_DEPLOYMENT_SERVING = "deployment_serving"
ROLE_REPOSITORY_CONTEXT = "repository_context"
ROLE_UNKNOWN_NEEDS_REVIEW = "unknown_needs_review"

CODE_ROLE_LABELS: dict[str, str] = {
    ROLE_DOCUMENTATION_HEADER: "Documentation / usage header",
    ROLE_IMPORTS_SETUP: "Imports / setup context",
    ROLE_CONFIG_CONSTANTS: "Config / constants",
    ROLE_API_ROUTE_SHELL: "API route shell",
    ROLE_DATA_LOADING: "Data loading context",
    ROLE_FEATURE_ENGINEERING: "Feature engineering context",
    ROLE_MODEL_TRAINING: "Model training context",
    ROLE_EVALUATION_METRICS: "Evaluation / metrics context",
    ROLE_PREDICTION_INFERENCE: "Prediction / inference context",
    ROLE_DEPLOYMENT_SERVING: "Deployment / serving context",
    ROLE_REPOSITORY_CONTEXT: "Repository-level context",
    ROLE_UNKNOWN_NEEDS_REVIEW: "Unknown / needs review",
}
CODE_ROLE_KEYS = tuple(CODE_ROLE_LABELS.keys())

# A KNOWN weak structural band → its honest, grade-derived role. These fail closed:
# whatever the snippet or a stale reason claims, the block IS what its grade says.
_GRADE_ROLE: dict[str, str] = {
    GRADE_COMMENT_OR_DOCSTRING: ROLE_DOCUMENTATION_HEADER,
    GRADE_IMPORT_ONLY: ROLE_IMPORTS_SETUP,
    GRADE_CONFIG_OR_CONSTANT: ROLE_CONFIG_CONSTANTS,
    GRADE_ROUTE_DECORATOR_ONLY: ROLE_API_ROUTE_SHELL,
    GRADE_REPO_LEVEL_FALLBACK: ROLE_REPOSITORY_CONTEXT,
}

# Executable-code signals for each SEMANTIC role. Matched ONLY against text that has
# had comments + docstrings structurally stripped, so a docstring/comment mention is
# never a signal. Evaluated in priority order (training → evaluation → inference →
# feature → data → route → deployment), so a training body that also computes a
# metric still reads as "Model training context".
_ROLE_MODEL_TRAINING_RE = re.compile(
    r"\.(?:fit|fit_predict|partial_fit)\s*\("
    r"|\b(?:train_test_split|GridSearchCV|RandomizedSearchCV|cross_val_score|"
    r"cross_validate|StratifiedKFold|KFold)\s*\("
    r"|\b(?:RandomForest(?:Classifier|Regressor)|XGB(?:Classifier|Regressor)|"
    r"LGBM(?:Classifier|Regressor)|LightGBM|GradientBoosting(?:Classifier|Regressor)|"
    r"LogisticRegression|LinearRegression|DecisionTree(?:Classifier|Regressor)|"
    r"KMeans|KNeighbors(?:Classifier|Regressor)|SVC|SVR|GaussianNB|MLPClassifier|"
    r"Sequential)\s*\("
    r"|\.compile\s*\(|\.backward\s*\(|optimizer\.(?:step|zero_grad)\s*\(",
    re.IGNORECASE,
)
_ROLE_EVALUATION_RE = re.compile(
    r"\b(?:accuracy_score|f1_score|precision_score|recall_score|roc_auc_score|"
    r"roc_curve|confusion_matrix|classification_report|mean_squared_error|"
    r"mean_absolute_error|r2_score|log_loss)\s*\("
    r"|\.(?:evaluate|score)\s*\(",
    re.IGNORECASE,
)
_ROLE_PREDICTION_RE = re.compile(
    r"\.(?:predict|predict_proba|predict_log_proba|decision_function)\s*\(",
    re.IGNORECASE,
)
_ROLE_FEATURE_RE = re.compile(
    r"\b(?:StandardScaler|MinMaxScaler|RobustScaler|OneHotEncoder|LabelEncoder|"
    r"OrdinalEncoder|CountVectorizer|TfidfVectorizer|ColumnTransformer|Pipeline|"
    r"make_pipeline|PCA|SelectKBest)\s*\("
    r"|\.(?:fit_transform|transform)\s*\(",
    re.IGNORECASE,
)
_ROLE_DATA_LOADING_RE = re.compile(
    r"\b(?:read_csv|read_parquet|read_json|read_excel|read_sql|read_table|"
    r"load_dataset|fetch_openml|load_svmlight_file|loadtxt|DataLoader)\s*\("
    # Spark/batch readers: spark.read.parquet(...) / .read.csv(...) etc.
    r"|\b(?:spark|session)\.read\.\w+\s*\(|\bSparkSession\b",
    re.IGNORECASE,
)
_ROLE_DEPLOYMENT_RE = re.compile(
    r"\b(?:boto3|sagemaker|docker|kubernetes|uvicorn|gunicorn|mlflow)\b"
    r"|\.deploy\s*\(|\b(?:s3|ecr|ecs)\.\w+\s*\(",
    re.IGNORECASE,
)
# Route decorator ANYWHERE in the executable block (multiline — the per-line
# ``_ROUTE_DECORATOR_RE`` below is ``^``-anchored for single-line kind checks).
_ROLE_ROUTE_RE = re.compile(
    r"^\s*@(?:app|router|api|bp|blueprint|\w+)\.(?:get|post|put|delete|patch|route|websocket)\s*\(",
    re.IGNORECASE | re.MULTILINE,
)

# Natural-language reason / path hints (a DESCRIPTIVE fallback used ONLY for a row
# whose grade is already STRONG and that carries no executable snippet at read
# time). This never changes proof strength — the grade already governs that — it
# only produces an honest role LABEL when no executable body is available to read.
_REASON_ROLE_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"train(?:ing)?\b|\.fit\b|model\s+(?:instantiat|construct|definit)", re.IGNORECASE),
     ROLE_MODEL_TRAINING),
    (re.compile(r"eval(?:uat)?|metric|accuracy|f1|precision|recall|roc|auc|confusion", re.IGNORECASE),
     ROLE_EVALUATION_METRICS),
    (re.compile(r"predict|inference|serv\w*\s+model|model\s+serv", re.IGNORECASE),
     ROLE_PREDICTION_INFERENCE),
    (re.compile(r"feature[\s_-]*engineer|preprocess|scal(?:er|ing)|encod|vectoriz", re.IGNORECASE),
     ROLE_FEATURE_ENGINEERING),
    (re.compile(r"data\s+load|load\s+data|read_csv|dataset|dataloader|ingest", re.IGNORECASE),
     ROLE_DATA_LOADING),
    (re.compile(r"deploy|docker|kubernetes|sagemaker|cloud\s+(?:deploy|serv)|serving", re.IGNORECASE),
     ROLE_DEPLOYMENT_SERVING),
    (re.compile(r"route|endpoint|api\s+handler|fastapi|flask", re.IGNORECASE),
     ROLE_API_ROUTE_SHELL),
)


def describe_code_role(key: str | None) -> str:
    """Human, recruiter-readable label for a ``code_role_key`` (fail-closed)."""
    return CODE_ROLE_LABELS.get(key or "", CODE_ROLE_LABELS[ROLE_UNKNOWN_NEEDS_REVIEW])


def code_role_from_grade(grade: str | None) -> str:
    """Conservative role derived from an ``evidence_quality_grade`` ALONE.

    For a stale/legacy row that carries no snippet (Part B), the grade is the only
    honest structural signal:

    * ``comment_or_docstring`` → Documentation / usage header
    * ``import_only`` → Imports / setup context
    * ``config_or_constant`` → Config / constants
    * ``route_decorator_only`` → API route shell
    * ``repo_level_fallback`` / ungraded / unknown → Repository-level context

    A STRONG grade (implementation/supporting) with no other signal is left as
    ``unknown_needs_review`` — it is a real body, but nothing here says which kind.
    """
    g = str(grade or "").strip().lower()
    if g in _GRADE_ROLE:
        return _GRADE_ROLE[g]
    if is_strong_grade(g):
        return ROLE_UNKNOWN_NEEDS_REVIEW
    return ROLE_REPOSITORY_CONTEXT


def _semantic_role_from_code(code_snippet: str | None) -> str | None:
    """The semantic role of an EXECUTABLE code body, or ``None``.

    Comments + docstrings are structurally stripped first (via
    :func:`_strip_comments_and_docstrings`) so prose that merely mentions ``fit`` /
    ``predict`` is never a signal, and import lines are stripped (via
    :func:`_strip_import_lines`) so a library NAME on an import line (``uvicorn``,
    ``SparkSession``) is never a signal either — only real usage lines are. Roles
    are checked in priority order so a training body that also scores a metric
    still reads as model training.
    """
    if not code_snippet or not code_snippet.strip():
        return None
    executable = _strip_import_lines(_strip_comments_and_docstrings(code_snippet))
    if not executable.strip():
        return None
    if _ROLE_MODEL_TRAINING_RE.search(executable):
        return ROLE_MODEL_TRAINING
    if _ROLE_EVALUATION_RE.search(executable):
        return ROLE_EVALUATION_METRICS
    if _ROLE_PREDICTION_RE.search(executable):
        return ROLE_PREDICTION_INFERENCE
    if _ROLE_FEATURE_RE.search(executable):
        return ROLE_FEATURE_ENGINEERING
    if _ROLE_DATA_LOADING_RE.search(executable):
        return ROLE_DATA_LOADING
    if _ROLE_ROUTE_RE.search(executable):
        return ROLE_API_ROUTE_SHELL
    if _ROLE_DEPLOYMENT_RE.search(executable):
        return ROLE_DEPLOYMENT_SERVING
    return None


def _semantic_role_from_reason(*parts: str | None) -> str | None:
    """A descriptive role guessed from a reason / file path / function name.

    Used ONLY as a fallback for a STRONG row with no executable snippet at read
    time — a stale reason can never be trusted for proof strength, but it can still
    describe what a validated body is about. Returns ``None`` when nothing matches.
    """
    haystack = " ".join(p for p in parts if p).strip()
    if not haystack:
        return None
    for pattern, role in _REASON_ROLE_RES:
        if pattern.search(haystack):
            return role
    return None


def classify_code_role(
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
    selection_reason: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
) -> str:
    """Return a conservative ``code_role_key`` describing what a code block IS.

    This is a LABEL, never a strength verdict. It fails closed:

    1. A KNOWN weak structural band (docstring / import / config / bare route
       decorator) takes its role from the GRADE — a docstring that mentions
       ``model.fit(...)`` stays "Documentation / usage header", never "Model
       training". This is the primary safety rule (weak rows keep honest labels).
    2. Otherwise, the strongest honest signal is a real EXECUTABLE snippet — its
       semantic role (training / evaluation / inference / feature / data / route /
       deployment) is used.
    3. A STRONG grade with no executable snippet falls back to a conservative
       reason/path HINT (descriptive only — never promotes the grade); if nothing
       matches it is ``unknown_needs_review``.
    4. Anything else (``repo_level_fallback`` / ungraded / unknown) → repository
       context.
    """
    g = str(grade or "").strip().lower()
    # 1. Known weak structural band → grade-derived role wins (fail closed).
    if g in _GRADE_ROLE and g != GRADE_REPO_LEVEL_FALLBACK:
        return _GRADE_ROLE[g]
    # 2. Executable snippet is the most honest semantic signal for the rest.
    role = _semantic_role_from_code(code_snippet)
    if role:
        return role
    # 3. Strong grade, no snippet → a descriptive reason/path hint (label only).
    if is_strong_grade(g):
        hint = _semantic_role_from_reason(selection_reason, file_path, function_name)
        return hint or ROLE_UNKNOWN_NEEDS_REVIEW
    # 4. repo_level_fallback / ungraded / unknown → repository-level context.
    return ROLE_REPOSITORY_CONTEXT


def effective_code_role(
    role_key: str | None,
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
    selection_reason: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
) -> str:
    """Read-time resolution of a row's code role against its VALIDATED grade.

    Applied where a report row is projected (after :func:`effective_evidence_grade`
    has validated the persisted grade), so a stale persisted row can never carry an
    inconsistent role out to a recruiter surface:

    * a VALIDATED weak structural band (docstring / import / config / bare route
      decorator) always wins — whatever an upstream role claims, the row IS what
      its validated grade says (fail closed);
    * otherwise a role computed upstream from the trusted executable body is kept
      as-is (it is server-derived, never user metadata); and
    * a row with NO role (a stale/legacy item) is classified conservatively from
      the validated grade + whatever safe signals remain — for a weak/ungraded row
      with no snippet that is always repository-level context, never a stale
      overclaiming ``selection_reason``.
    """
    g = str(grade or "").strip().lower()
    if g in _GRADE_ROLE and g != GRADE_REPO_LEVEL_FALLBACK:
        return _GRADE_ROLE[g]
    key = str(role_key or "").strip().lower()
    if key in CODE_ROLE_LABELS:
        return key
    return classify_code_role(
        grade=g,
        code_snippet=code_snippet,
        selection_reason=selection_reason,
        file_path=file_path,
        function_name=function_name,
    )


# ── Code block purpose classification (block-level explanation, NOT proof) ────
#
# ``code_block_purpose_*`` explains what ONE exact focused block appears to do —
# finer-grained than ``code_role_key`` (the broad category) and fully separate
# from ``evidence_quality_grade`` (proof strength). The three answer different
# recruiter questions:
#
#  * grade   → "how strong is this as proof?"   (implementation vs weak context)
#  * role    → "what broad kind of code is it?" ("Model training context")
#  * purpose → "what does THIS block do?"       ("Documentation describing
#               retraining pipeline", "Imports / dependency setup")
#
# Purposes are a CLOSED vocabulary: every key, label, and summary below is a
# static string from this module — a purpose surface can never echo raw prose,
# a snippet, or a stale stored reason. Classification fails closed exactly like
# roles: a weak structural band only ever gets a purpose from its own honest
# family (a docstring block can be *documentation about* training, never "Model
# training"), semantic purposes require a real EXECUTABLE code signal, and a
# purpose label NEVER promotes a row's grade or ML validity.

PURPOSE_RETRAINING_DOCUMENTATION = "retraining_documentation"
PURPOSE_PIPELINE_DOCUMENTATION = "pipeline_documentation"
PURPOSE_USAGE_INSTRUCTIONS = "usage_instructions"
PURPOSE_DOCUMENTATION_OVERVIEW = "documentation_overview"
PURPOSE_IMPORTS_DEPENDENCIES = "imports_dependencies"
PURPOSE_CONFIG_PATHS_ARTIFACTS = "config_paths_artifacts"
PURPOSE_DATA_LOADING = "data_loading"
PURPOSE_PREPROCESSING_FEATURES = "preprocessing_features"
PURPOSE_MODEL_TRAINING = "model_training"
PURPOSE_MODEL_EVALUATION = "model_evaluation"
PURPOSE_PREDICTION_INFERENCE = "prediction_inference"
PURPOSE_API_REQUEST_SCHEMA = "api_request_schema"
PURPOSE_API_ROUTE_SHELL = "api_route_shell"
PURPOSE_API_PREDICTION_HANDLER = "api_prediction_handler"
PURPOSE_MODEL_LOADING = "model_loading"
PURPOSE_ARTIFACT_PERSISTENCE = "artifact_persistence"
PURPOSE_DEPLOYMENT_SERVING = "deployment_serving"
PURPOSE_CLOUD_STORAGE_IO = "cloud_storage_io"
PURPOSE_FRONTEND_UI_COMPONENT = "frontend_ui_component"
PURPOSE_TEST_VALIDATION = "test_validation"
PURPOSE_HYPERPARAMETER_TUNING = "hyperparameter_tuning"
PURPOSE_TEXT_NLP_PROCESSING = "text_nlp_processing"
PURPOSE_EMBEDDING_GENERATION = "embedding_generation"
PURPOSE_LLM_CALL_WRAPPER = "llm_call_wrapper"
PURPOSE_RAG_RETRIEVAL = "rag_retrieval"
PURPOSE_IMAGE_PROCESSING_CV = "image_processing_cv"
PURPOSE_DATABASE_OPERATION = "database_operation"
PURPOSE_AUTH_PERMISSION_CHECK = "auth_permission_check"
PURPOSE_CI_CD_WORKFLOW = "ci_cd_workflow"
PURPOSE_CONTAINERIZATION = "containerization"
PURPOSE_DATA_VISUALIZATION = "data_visualization"
PURPOSE_REPOSITORY_CONTEXT = "repository_context"
PURPOSE_UNKNOWN_NEEDS_REVIEW = "unknown_needs_review"

# Documentation TOPIC purposes (docstring/comment blocks only — never executable).
PURPOSE_ARCHITECTURE_DOCUMENTATION = "architecture_documentation"
PURPOSE_API_PROTOCOL_DOCUMENTATION = "api_protocol_documentation"
PURPOSE_SERVING_DOCUMENTATION = "serving_documentation"
PURPOSE_DEPLOYMENT_DOCUMENTATION = "deployment_documentation"

# Frontend component purposes, detected from TSX/JSX structure + path shape (a
# closed refinement of the generic ``frontend_ui_component``).
PURPOSE_FRONTEND_PAGE_COMPONENT = "frontend_page_component"
PURPOSE_FRONTEND_LAYOUT_COMPONENT = "frontend_layout_component"
PURPOSE_FRONTEND_FORM_COMPONENT = "frontend_form_component"
PURPOSE_FRONTEND_STATE_MANAGEMENT = "frontend_state_management"
PURPOSE_FRONTEND_API_CLIENT = "frontend_api_client"
PURPOSE_FRONTEND_RESULTS_DISPLAY = "frontend_results_display"
PURPOSE_FRONTEND_CHART_COMPONENT = "frontend_chart_component"
PURPOSE_FRONTEND_TABLE_LIST = "frontend_table_list"
PURPOSE_FRONTEND_DIALOG_ALERT = "frontend_dialog_alert"
PURPOSE_FRONTEND_NAVIGATION = "frontend_navigation"
PURPOSE_FRONTEND_PROVIDER_THEME = "frontend_provider_theme"
PURPOSE_FRONTEND_LOADING_ERROR = "frontend_loading_error"
PURPOSE_FRONTEND_UI_PRIMITIVE = "frontend_ui_primitive"

# Geospatial purposes, detected from executable geospatial constructs only.
PURPOSE_GEO_FEATURE_HANDLING = "geospatial_feature_handling"
PURPOSE_GEO_FEATURE_ENGINEERING = "geospatial_feature_engineering"
PURPOSE_GEO_DISTANCE_CALCULATION = "geospatial_distance_calculation"
PURPOSE_GEO_GEOCODING_API = "geospatial_geocoding_api"
PURPOSE_GEO_DATA_LOADING = "geospatial_data_loading"
PURPOSE_GEO_VISUALIZATION = "geospatial_visualization"

# Container/Dockerfile instruction purposes (a closed refinement of the generic
# ``containerization`` for line-level Dockerfile blocks).
PURPOSE_CONTAINER_BASE_IMAGE = "container_base_image"
PURPOSE_CONTAINER_DEPENDENCY_INSTALL = "container_dependency_install"
PURPOSE_CONTAINER_FILES_SETUP = "container_files_setup"
PURPOSE_CONTAINER_ENV_CONFIG = "container_env_config"
PURPOSE_CONTAINER_PORT_EXPOSURE = "container_port_exposure"
PURPOSE_CONTAINER_RUNTIME_COMMAND = "container_runtime_command"
PURPOSE_CONTAINER_MULTI_STAGE_BUILD = "container_multi_stage_build"
PURPOSE_CONTAINER_BUILD_STEP = "container_build_step"
PURPOSE_CONTAINER_HEALTHCHECK = "container_healthcheck"

# Universal fallback purposes — generic code structure any language/skill can hit.
PURPOSE_INPUT_VALIDATION = "input_validation"
PURPOSE_FILE_IO = "file_io"
PURPOSE_NETWORK_API_CALL = "network_api_call"
PURPOSE_ERROR_HANDLING = "error_handling"
PURPOSE_LOGGING_MONITORING = "logging_monitoring"
PURPOSE_DATA_TRANSFORMATION = "data_transformation"
PURPOSE_API_REQUEST_HANDLER = "api_request_handler"

CODE_BLOCK_PURPOSE_LABELS: dict[str, str] = {
    PURPOSE_RETRAINING_DOCUMENTATION: "Documentation describing retraining pipeline",
    PURPOSE_PIPELINE_DOCUMENTATION: "Documentation describing pipeline",
    PURPOSE_USAGE_INSTRUCTIONS: "Usage instructions",
    PURPOSE_DOCUMENTATION_OVERVIEW: "Documentation / usage header",
    PURPOSE_IMPORTS_DEPENDENCIES: "Imports / dependency setup",
    PURPOSE_CONFIG_PATHS_ARTIFACTS: "Config / artifact paths",
    PURPOSE_DATA_LOADING: "Data loading",
    PURPOSE_PREPROCESSING_FEATURES: "Preprocessing / feature engineering",
    PURPOSE_MODEL_TRAINING: "Model training",
    PURPOSE_MODEL_EVALUATION: "Evaluation / metrics",
    PURPOSE_PREDICTION_INFERENCE: "Prediction / inference",
    PURPOSE_API_REQUEST_SCHEMA: "API request schema",
    PURPOSE_API_ROUTE_SHELL: "API route shell",
    PURPOSE_API_PREDICTION_HANDLER: "API prediction handler",
    PURPOSE_MODEL_LOADING: "Model loading",
    PURPOSE_ARTIFACT_PERSISTENCE: "Artifact save/load",
    PURPOSE_DEPLOYMENT_SERVING: "Deployment / serving",
    PURPOSE_CLOUD_STORAGE_IO: "Cloud storage I/O",
    PURPOSE_FRONTEND_UI_COMPONENT: "Frontend UI component",
    PURPOSE_TEST_VALIDATION: "Test / validation logic",
    PURPOSE_HYPERPARAMETER_TUNING: "Hyperparameter tuning",
    PURPOSE_TEXT_NLP_PROCESSING: "Text / NLP processing",
    PURPOSE_EMBEDDING_GENERATION: "Embedding generation",
    PURPOSE_LLM_CALL_WRAPPER: "LLM call / prompt handling",
    PURPOSE_RAG_RETRIEVAL: "RAG / vector retrieval",
    PURPOSE_IMAGE_PROCESSING_CV: "Image processing / computer vision",
    PURPOSE_DATABASE_OPERATION: "Database operation",
    PURPOSE_AUTH_PERMISSION_CHECK: "Authentication / permission check",
    PURPOSE_CI_CD_WORKFLOW: "CI/CD workflow",
    PURPOSE_CONTAINERIZATION: "Containerized service configuration",
    PURPOSE_DATA_VISUALIZATION: "Data visualization",
    PURPOSE_ARCHITECTURE_DOCUMENTATION: "Architecture notes",
    PURPOSE_API_PROTOCOL_DOCUMENTATION: "API protocol documentation",
    PURPOSE_SERVING_DOCUMENTATION: "Model serving documentation",
    PURPOSE_DEPLOYMENT_DOCUMENTATION: "Deployment notes",
    PURPOSE_FRONTEND_PAGE_COMPONENT: "React page / route component",
    PURPOSE_FRONTEND_LAYOUT_COMPONENT: "Page layout component",
    PURPOSE_FRONTEND_FORM_COMPONENT: "Input form and form state handling",
    PURPOSE_FRONTEND_STATE_MANAGEMENT: "UI state management",
    PURPOSE_FRONTEND_API_CLIENT: "Frontend API client integration",
    PURPOSE_FRONTEND_RESULTS_DISPLAY: "Results display panel",
    PURPOSE_FRONTEND_CHART_COMPONENT: "Chart / data visualization component",
    PURPOSE_FRONTEND_TABLE_LIST: "Table / list rendering",
    PURPOSE_FRONTEND_DIALOG_ALERT: "Modal / dialog / alert UI",
    PURPOSE_FRONTEND_NAVIGATION: "Navigation / breadcrumb component",
    PURPOSE_FRONTEND_PROVIDER_THEME: "Theme / provider setup",
    PURPOSE_FRONTEND_LOADING_ERROR: "Loading / error state handling",
    PURPOSE_FRONTEND_UI_PRIMITIVE: "Reusable UI primitive",
    PURPOSE_GEO_FEATURE_HANDLING: "Latitude/longitude feature handling",
    PURPOSE_GEO_FEATURE_ENGINEERING: "Geospatial feature engineering",
    PURPOSE_GEO_DISTANCE_CALCULATION: "Distance / proximity calculation",
    PURPOSE_GEO_GEOCODING_API: "Map / geocoding API integration",
    PURPOSE_GEO_DATA_LOADING: "Spatial data loading",
    PURPOSE_GEO_VISUALIZATION: "Geospatial visualization",
    PURPOSE_CONTAINER_BASE_IMAGE: "Container base image",
    PURPOSE_CONTAINER_DEPENDENCY_INSTALL: "Container dependency installation",
    PURPOSE_CONTAINER_FILES_SETUP: "Application files copied into image",
    PURPOSE_CONTAINER_ENV_CONFIG: "Container environment configuration",
    PURPOSE_CONTAINER_PORT_EXPOSURE: "Exposed service port",
    PURPOSE_CONTAINER_RUNTIME_COMMAND: "Container runtime command",
    PURPOSE_CONTAINER_MULTI_STAGE_BUILD: "Multi-stage container build",
    PURPOSE_CONTAINER_BUILD_STEP: "Container build step",
    PURPOSE_CONTAINER_HEALTHCHECK: "Container health check",
    PURPOSE_INPUT_VALIDATION: "Input validation logic",
    PURPOSE_FILE_IO: "File I/O operation",
    PURPOSE_NETWORK_API_CALL: "Network / external API call",
    PURPOSE_ERROR_HANDLING: "Error handling logic",
    PURPOSE_LOGGING_MONITORING: "Logging / monitoring",
    PURPOSE_DATA_TRANSFORMATION: "Data transformation logic",
    PURPOSE_API_REQUEST_HANDLER: "API request handler",
    PURPOSE_REPOSITORY_CONTEXT: "Repository-level context",
    PURPOSE_UNKNOWN_NEEDS_REVIEW: "Unknown / needs review",
}
CODE_BLOCK_PURPOSE_KEYS = tuple(CODE_BLOCK_PURPOSE_LABELS.keys())

# One short, safe helper sentence per purpose. Context purposes state their own
# limitation ("not executable implementation proof") so a weak row's summary can
# never read as implementation; executable purposes describe the block without
# asserting proof strength (the grade still governs that).
_CODE_BLOCK_PURPOSE_SUMMARIES: dict[str, str] = {
    PURPOSE_RETRAINING_DOCUMENTATION: (
        "This header describes the planned retraining workflow and artifacts, "
        "but it is not executable training code."
    ),
    PURPOSE_PIPELINE_DOCUMENTATION: (
        "This block is prose describing the pipeline — documentation, not "
        "executable implementation proof."
    ),
    PURPOSE_USAGE_INSTRUCTIONS: (
        "This block explains how to run or use the code; it is not "
        "executable implementation proof."
    ),
    PURPOSE_DOCUMENTATION_OVERVIEW: (
        "This block is documentation prose, not executable implementation proof."
    ),
    PURPOSE_IMPORTS_DEPENDENCIES: (
        "This block imports libraries used elsewhere; it is not implementation "
        "proof by itself."
    ),
    PURPOSE_CONFIG_PATHS_ARTIFACTS: (
        "This block defines paths/configuration used by the pipeline, not model logic."
    ),
    PURPOSE_DATA_LOADING: "This block loads data used by the pipeline.",
    PURPOSE_PREPROCESSING_FEATURES: (
        "This block prepares or transforms features used by the model."
    ),
    PURPOSE_MODEL_TRAINING: "This block contains executable model-training calls.",
    PURPOSE_MODEL_EVALUATION: "This block computes evaluation metrics for a model.",
    PURPOSE_PREDICTION_INFERENCE: "This block runs model prediction / inference calls.",
    PURPOSE_API_REQUEST_SCHEMA: (
        "This block defines an API request/response schema; it is not ML "
        "implementation by itself."
    ),
    PURPOSE_API_ROUTE_SHELL: (
        "This block declares an API route; it is not model implementation by itself."
    ),
    PURPOSE_API_PREDICTION_HANDLER: "This API handler invokes model inference.",
    PURPOSE_MODEL_LOADING: "This block loads a persisted model artifact.",
    PURPOSE_ARTIFACT_PERSISTENCE: "This block saves or loads pipeline artifacts.",
    PURPOSE_DEPLOYMENT_SERVING: (
        "This block is deployment/serving setup around the pipeline, not ML "
        "implementation by itself."
    ),
    PURPOSE_CLOUD_STORAGE_IO: (
        "This block reads/writes cloud storage; it supports the pipeline but is "
        "not model logic."
    ),
    PURPOSE_FRONTEND_UI_COMPONENT: (
        "This block is frontend UI code supporting the application."
    ),
    PURPOSE_TEST_VALIDATION: (
        "This block is test/validation logic exercising the implementation."
    ),
    PURPOSE_HYPERPARAMETER_TUNING: (
        "This block runs executable hyperparameter search / tuning over a model."
    ),
    PURPOSE_TEXT_NLP_PROCESSING: (
        "This block processes text with NLP tooling (tokenization / normalization)."
    ),
    PURPOSE_EMBEDDING_GENERATION: (
        "This block generates vector embeddings from input data."
    ),
    PURPOSE_LLM_CALL_WRAPPER: (
        "This block calls a large-language-model API and handles its response."
    ),
    PURPOSE_RAG_RETRIEVAL: (
        "This block performs vector-store / retrieval operations for RAG."
    ),
    PURPOSE_IMAGE_PROCESSING_CV: (
        "This block loads or transforms images with computer-vision tooling."
    ),
    PURPOSE_DATABASE_OPERATION: (
        "This block performs database queries or persistence operations."
    ),
    PURPOSE_AUTH_PERMISSION_CHECK: (
        "This block performs authentication / authorization checks."
    ),
    PURPOSE_CI_CD_WORKFLOW: (
        "This file defines a CI/CD workflow; it is automation config, not "
        "application implementation by itself."
    ),
    PURPOSE_CONTAINERIZATION: (
        "This file defines a container build; it is packaging config, not "
        "application implementation by itself."
    ),
    PURPOSE_DATA_VISUALIZATION: (
        "This block renders charts / plots from data."
    ),
    PURPOSE_ARCHITECTURE_DOCUMENTATION: (
        "This block is prose describing the system architecture — documentation, "
        "not executable implementation proof."
    ),
    PURPOSE_API_PROTOCOL_DOCUMENTATION: (
        "This block documents an API's request/response protocol; it is not "
        "executable implementation proof."
    ),
    PURPOSE_SERVING_DOCUMENTATION: (
        "This block documents how the model is served; it is not executable "
        "serving or inference code."
    ),
    PURPOSE_DEPLOYMENT_DOCUMENTATION: (
        "This block documents deployment steps; it is not executable deployment "
        "or implementation code."
    ),
    PURPOSE_FRONTEND_PAGE_COMPONENT: (
        "This block defines a page-level / route component laying out the UI."
    ),
    PURPOSE_FRONTEND_LAYOUT_COMPONENT: (
        "This block defines a shared layout wrapper for the UI."
    ),
    PURPOSE_FRONTEND_FORM_COMPONENT: (
        "This block renders an input form and manages its form state."
    ),
    PURPOSE_FRONTEND_STATE_MANAGEMENT: (
        "This block manages UI component state."
    ),
    PURPOSE_FRONTEND_API_CLIENT: (
        "This block calls a backend API from the frontend and handles its response."
    ),
    PURPOSE_FRONTEND_RESULTS_DISPLAY: (
        "This block renders a results / output display panel."
    ),
    PURPOSE_FRONTEND_CHART_COMPONENT: (
        "This block renders a chart / data visualization in the UI."
    ),
    PURPOSE_FRONTEND_TABLE_LIST: (
        "This block renders tabular or list data in the UI."
    ),
    PURPOSE_FRONTEND_DIALOG_ALERT: (
        "This block implements modal / dialog / alert UI behavior."
    ),
    PURPOSE_FRONTEND_NAVIGATION: (
        "This block implements navigation / breadcrumb UI."
    ),
    PURPOSE_FRONTEND_PROVIDER_THEME: (
        "This block wires up a theme / context provider for the UI."
    ),
    PURPOSE_FRONTEND_LOADING_ERROR: (
        "This block handles loading / error states in the UI."
    ),
    PURPOSE_FRONTEND_UI_PRIMITIVE: (
        "This block is a reusable UI primitive shared across the app."
    ),
    PURPOSE_GEO_FEATURE_HANDLING: (
        "This block works with latitude/longitude values in executable code."
    ),
    PURPOSE_GEO_FEATURE_ENGINEERING: (
        "This block performs spatial operations / geospatial feature engineering."
    ),
    PURPOSE_GEO_DISTANCE_CALCULATION: (
        "This block computes distance / proximity between locations."
    ),
    PURPOSE_GEO_GEOCODING_API: (
        "This block integrates a map / geocoding API."
    ),
    PURPOSE_GEO_DATA_LOADING: (
        "This block loads spatial / geographic data."
    ),
    PURPOSE_GEO_VISUALIZATION: (
        "This block renders a map-based / geospatial visualization."
    ),
    PURPOSE_CONTAINER_BASE_IMAGE: (
        "This block selects the container base image; it is packaging config, "
        "not application implementation."
    ),
    PURPOSE_CONTAINER_DEPENDENCY_INSTALL: (
        "This block installs dependencies inside the container image."
    ),
    PURPOSE_CONTAINER_FILES_SETUP: (
        "This block copies application files / sets the working directory "
        "inside the image."
    ),
    PURPOSE_CONTAINER_ENV_CONFIG: (
        "This block configures environment variables / build arguments for "
        "the container."
    ),
    PURPOSE_CONTAINER_PORT_EXPOSURE: (
        "This block exposes the service port of the container."
    ),
    PURPOSE_CONTAINER_RUNTIME_COMMAND: (
        "This block defines the container's runtime command / entrypoint."
    ),
    PURPOSE_CONTAINER_MULTI_STAGE_BUILD: (
        "This block defines a multi-stage container build."
    ),
    PURPOSE_CONTAINER_BUILD_STEP: (
        "This block runs a build step inside the container image."
    ),
    PURPOSE_CONTAINER_HEALTHCHECK: (
        "This block defines a container health check."
    ),
    PURPOSE_INPUT_VALIDATION: (
        "This block validates / sanitizes input data."
    ),
    PURPOSE_FILE_IO: (
        "This block reads or writes files."
    ),
    PURPOSE_NETWORK_API_CALL: (
        "This block calls an external network / API service."
    ),
    PURPOSE_ERROR_HANDLING: (
        "This block handles errors / exceptional cases."
    ),
    PURPOSE_LOGGING_MONITORING: (
        "This block emits logging / monitoring signals."
    ),
    PURPOSE_DATA_TRANSFORMATION: (
        "This block transforms / reshapes data."
    ),
    PURPOSE_API_REQUEST_HANDLER: (
        "This block handles an API request end-to-end."
    ),
    PURPOSE_REPOSITORY_CONTEXT: (
        "Repository-level signal only — no trusted line-level code was "
        "available for this row; proof strength remains needs review."
    ),
    PURPOSE_UNKNOWN_NEEDS_REVIEW: (
        "The purpose of this block could not be determined; it needs review."
    ),
}

# Each KNOWN weak structural band may only ever carry a purpose from its own
# honest family — so a stale/inconsistent purpose (e.g. "Model training" riding
# on an import-only row) can never survive read-time resolution.
_GRADE_PURPOSE_FAMILY: dict[str, frozenset[str]] = {
    GRADE_COMMENT_OR_DOCSTRING: frozenset(
        {
            PURPOSE_RETRAINING_DOCUMENTATION,
            PURPOSE_PIPELINE_DOCUMENTATION,
            PURPOSE_USAGE_INSTRUCTIONS,
            PURPOSE_DOCUMENTATION_OVERVIEW,
            PURPOSE_ARCHITECTURE_DOCUMENTATION,
            PURPOSE_API_PROTOCOL_DOCUMENTATION,
            PURPOSE_SERVING_DOCUMENTATION,
            PURPOSE_DEPLOYMENT_DOCUMENTATION,
        }
    ),
    GRADE_IMPORT_ONLY: frozenset({PURPOSE_IMPORTS_DEPENDENCIES}),
    GRADE_CONFIG_OR_CONSTANT: frozenset(
        {
            PURPOSE_CONFIG_PATHS_ARTIFACTS,
            PURPOSE_CLOUD_STORAGE_IO,
            # A Dockerfile block whose instructions are declarative-only
            # (FROM/ENV/ARG/EXPOSE/WORKDIR/LABEL) grades as config; its honest
            # instruction-level purpose stays within the container family.
            PURPOSE_CONTAINER_BASE_IMAGE,
            PURPOSE_CONTAINER_FILES_SETUP,
            PURPOSE_CONTAINER_ENV_CONFIG,
            PURPOSE_CONTAINER_PORT_EXPOSURE,
            PURPOSE_CONTAINERIZATION,
        }
    ),
    GRADE_ROUTE_DECORATOR_ONLY: frozenset(
        {PURPOSE_API_ROUTE_SHELL, PURPOSE_API_REQUEST_SCHEMA}
    ),
}

# Documentation TOPIC hints — matched against docstring/comment PROSE only to
# choose among the closed documentation purposes above. The prose itself is
# never echoed; only a static label/summary is ever surfaced.
_DOC_RETRAINING_RE = re.compile(r"\bre-?train", re.IGNORECASE)
_DOC_SERVING_RE = re.compile(
    r"model\s+(?:is\s+)?serv|serv(?:e|es|ed|ing)\s+(?:the\s+)?(?:model|predictions?)"
    r"|inference\s+(?:api|endpoint|server)",
    re.IGNORECASE,
)
_DOC_API_PROTOCOL_RE = re.compile(
    r"\bapi\b|\bendpoints?\b|\brequest\b|\bresponse\b|\bpayload\b|\bprotocol\b|"
    r"\brest\b|\bgraphql\b|status\s+code",
    re.IGNORECASE,
)
_DOC_DEPLOYMENT_RE = re.compile(
    r"\bdeploy|\bdocker|\bcontainer|\bkubernetes\b|\bk8s\b|\bci\s*/?\s*cd\b|"
    r"\bhelm\b|\bterraform\b|infrastructure",
    re.IGNORECASE,
)
_DOC_ARCHITECTURE_RE = re.compile(
    r"\barchitecture\b|system\s+design|high-?level\s+(?:design|overview)|"
    r"module\s+structure|component\s+(?:overview|diagram)|design\s+decision",
    re.IGNORECASE,
)
_DOC_PIPELINE_RE = re.compile(
    r"\bpipeline\b|\btrain(?:ing|s|ed)?\b|\bmodel\b|\bpreprocess|\bfeature|"
    r"\bdataset\b|\bevaluat|\binference\b|\bthreshold\b|\bartifact",
    re.IGNORECASE,
)
_DOC_USAGE_RE = re.compile(
    r"\busage\b|\bhow\s+to\b|\brun\b|\bexample\b|\binstall\b|\bcli\b|\bcommand\b",
    re.IGNORECASE,
)

# Purpose-only executable signals (the role regexes above cover the rest).
_PURPOSE_MODEL_LOADING_RE = re.compile(
    r"\b(?:joblib|pickle)\.load\s*\(|\btorch\.load\s*\(|\bload_model\s*\(",
    re.IGNORECASE,
)
_PURPOSE_ARTIFACT_PERSISTENCE_RE = re.compile(
    r"\b(?:joblib|pickle)\.dump\s*\(|\btorch\.save\s*\(|\.save_model\s*\(|"
    r"\.to_(?:csv|parquet|pickle)\s*\(",
    re.IGNORECASE,
)
_PURPOSE_REQUEST_SCHEMA_RE = re.compile(
    r"class\s+\w+\s*\([^)]*\bBaseModel\b[^)]*\)",
)
_PURPOSE_CLOUD_IO_RE = re.compile(
    r"\bstorage\.Client\s*\(|\bboto3\b|\bgcsfs\b|\bs3fs\b|"
    r"\b(?:bucket|blob)\.(?:blob|upload\w*|download\w*|open|exists)\s*\(|"
    r"\bupload_(?:file|blob|from)\w*\s*\(|\bdownload_(?:file|blob|to)\w*\s*\(",
    re.IGNORECASE,
)
# Cloud URI schemes live inside string literals (stripped from executable text),
# so they are checked against the RAW snippet — a scheme match is a safe,
# non-prose infrastructure signal.
_CLOUD_URI_RE = re.compile(r"\b(?:gs|s3)://", re.IGNORECASE)

_TEST_PATH_RE = re.compile(r"(?:^|/)tests?/|(?:^|/)test_[^/]*\.py$|_test\.py$|(?:^|/)conftest\.py$")
_FRONTEND_PATH_RE = re.compile(r"\.(?:tsx|jsx|vue|svelte)$")
# Infrastructure files are identified by PATH (they are not Python bodies): a
# GitHub Actions / GitLab / Jenkins workflow file, or a Dockerfile / compose file.
_CI_CD_PATH_RE = re.compile(
    r"(?:^|/)\.github/workflows/[^/]+\.ya?ml$|(?:^|/)\.gitlab-ci\.ya?ml$"
    r"|(?:^|/)jenkinsfile$|(?:^|/)azure-pipelines\.ya?ml$"
)
_CONTAINER_PATH_RE = re.compile(
    r"(?:^|/)dockerfile(?:\.[\w.-]+)?$|(?:^|/)docker-compose[\w.-]*\.ya?ml$"
)

# Executable signals for the multi-skill purpose families (matched against
# comment/docstring-stripped text only, like the role regexes above).
_PURPOSE_TUNING_RE = re.compile(
    r"\b(?:GridSearchCV|RandomizedSearchCV|BayesSearchCV)\s*\(|\boptuna\.\w+"
    r"|\bstudy\.optimize\s*\(|\.suggest_(?:float|int|categorical|loguniform)\s*\("
    r"|\bhyperopt\b|\bfmin\s*\(",
    re.IGNORECASE,
)
_PURPOSE_NLP_RE = re.compile(
    r"\bnltk\b|\bspacy\.load\s*\(|\b(?:word_tokenize|sent_tokenize)\s*\("
    r"|\bAutoTokenizer\b|\.tokenize\s*\(|\bPorterStemmer\s*\(|\bWordNetLemmatizer\s*\("
    r"|\bstopwords\b",
    re.IGNORECASE,
)
_PURPOSE_EMBEDDING_RE = re.compile(
    r"\bSentenceTransformer\s*\(|\bembeddings?\.create\s*\(|\.embed_(?:documents|query)\s*\("
    r"|\bWord2Vec\s*\(|\bfasttext\b",
    re.IGNORECASE,
)
_PURPOSE_LLM_RE = re.compile(
    r"\bchat\.completions\.create\s*\(|\bmessages\.create\s*\(|\bresponses\.create\s*\("
    r"|\bChatCompletion\b|\bgenerate_content\s*\(|\bChat(?:OpenAI|Anthropic|Google\w*|Bedrock\w*)\s*\("
    r"|\b(?:OpenAI|AsyncOpenAI|Anthropic|AsyncAnthropic)\s*\(|\binvoke_model\s*\(",
)
_PURPOSE_RAG_RE = re.compile(
    r"\bsimilarity_search\w*\s*\(|\bas_retriever\s*\(|\b(?:FAISS|Chroma|chromadb|Pinecone|"
    r"Weaviate|Qdrant|pgvector)\b|\bvector_?store\b",
    re.IGNORECASE,
)
_PURPOSE_CV_RE = re.compile(
    r"\bcv2\.\w+\s*\(|\bImage\.open\s*\(|\btorchvision\b|\bimread\s*\("
    r"|\bImageDataGenerator\s*\(|\balbumentations\b",
)
_PURPOSE_DATABASE_RE = re.compile(
    # Common DBAPI/ORM receivers only (cur/cursor/conn/db/engine/session/tx/…) —
    # a bare ``.execute(`` on an arbitrary object is not a database signal.
    r"\b(?:cur|cursor|conn|connection|db|database|engine|session|tx|client)\w*"
    r"\.execute(?:many)?\s*\("
    r"|\bsession\.(?:query|add|delete|commit)\s*\("
    r"|\bcreate_engine\s*\(|\bsupabase\.(?:table|from_|rpc)\s*\(",
    re.IGNORECASE,
)
_PURPOSE_AUTH_RE = re.compile(
    r"\bjwt\.(?:encode|decode)\s*\(|\bOAuth\w*\s*\(|\bverify_(?:token|password|jwt)\w*\s*\("
    r"|\bcheck_permission\w*\s*\(|\blogin_required\b|\bget_current_user\b|\bHTTPBearer\s*\("
    r"|\bpasslib\b|\bbcrypt\.\w+\s*\(",
)
_PURPOSE_VISUALIZATION_RE = re.compile(
    r"\bplt\.\w+\s*\(|\bsns\.\w+\s*\(|\bpx\.\w+\s*\(|\bgo\.Figure\s*\(|\baltair\b",
)

# ── Geospatial executable signals ─────────────────────────────────────────────
# Matched against comment/docstring-stripped text (like every executable signal)
# EXCEPT the lat/lon column check, which runs on string-preserving code (column
# names live inside quotes) with prose stripped via :func:`_executable_with_strings`.
_PURPOSE_GEO_DISTANCE_RE = re.compile(
    r"\bhaversine\w*\s*\(|\bgeodesic\s*\(|\bgreat_circle\s*\(|\bgeopy\.distance\b"
    r"|\bvincenty\s*\(|\bdistance_matrix\s*\(|\bcKDTree\s*\(|\bBallTree\s*\(",
    re.IGNORECASE,
)
_PURPOSE_GEO_GEOCODE_RE = re.compile(
    r"\bgeocode\w*\s*\(|\breverse_geocode\w*\s*\(|\bNominatim\s*\(|\bgooglemaps\.\w+"
    r"|\bgmaps\.\w+\s*\(|\bmapbox\b|\bplaces_nearby\s*\(|\bdirections\s*\(",
    re.IGNORECASE,
)
_PURPOSE_GEO_VIZ_RE = re.compile(
    r"\bfolium\.\w+|\bscatter_mapbox\s*\(|\bchoropleth\w*\s*\(|\bst\.map\s*\("
    r"|\bKeplerGl\s*\(|\bheatmap\w*\s*\(.*lat|\.explore\s*\(",
    re.IGNORECASE,
)
_PURPOSE_GEO_DATA_RE = re.compile(
    r"\bgpd\.read_file\s*\(|\bgeopandas\.read_file\s*\(|\bread_postgis\s*\("
    r"|\brasterio\.open\s*\(|\bfiona\.open\s*\(|\bosmnx\.\w+\s*\(|\box\.graph\w*\s*\(",
    re.IGNORECASE,
)
_PURPOSE_GEO_OPS_RE = re.compile(
    r"\bsjoin\w*\s*\(|\.buffer\s*\(|\.within\s*\(|\.intersects\s*\(|\.contains\s*\("
    r"|\bto_crs\s*\(|\bset_crs\s*\(|\btotal_bounds\b|\bunary_union\b"
    r"|\bshapely\.\w+|\bPoint\s*\(\s*[-\w]+\s*,|\bPolygon\s*\(|\bpyproj\.\w+"
    r"|\bTransformer\.from_crs\s*\(|\bbounding_box\w*|\bbbox\w*\s*=",
    re.IGNORECASE,
)
# Latitude AND longitude identifiers/columns both present in executable code.
_GEO_LAT_RE = re.compile(r"(?i)\blat(?:itude)?s?\b|[\"']lat(?:itude)?[\"']")
_GEO_LON_RE = re.compile(r"(?i)\blo?ng(?:itude)?s?\b|\blon\b|[\"']lo?n(?:gitude)?[\"']")

# ── Universal fallback executable signals (any language / any skill) ──────────
_PURPOSE_INPUT_VALIDATION_RE = re.compile(
    r"\bvalidate\w*\s*\(|\.is_valid\s*\(|\bjsonschema\b|\bmarshmallow\b"
    r"|\bcerberus\b|\bsanitiz\w+\s*\(|\bsafeParse\s*\(|\bzod\b|\byup\.\w+"
    r"|@validator\b|@field_validator\b",
    re.IGNORECASE,
)
_PURPOSE_NETWORK_CALL_RE = re.compile(
    r"\brequests\.(?:get|post|put|delete|patch|head|request)\s*\("
    r"|\bhttpx\.\w+\s*\(|\baiohttp\b|\burlopen\s*\(|\burllib\.request\b"
    r"|\bfetch\s*\(|\baxios\.\w+\s*\(|\baxios\s*\(",
    re.IGNORECASE,
)
_PURPOSE_FILE_IO_RE = re.compile(
    r"\bopen\s*\(\s*[\w\"'f]|\.read_text\s*\(|\.write_text\s*\(|\.read_bytes\s*\("
    r"|\.write_bytes\s*\(|\bshutil\.\w+\s*\(|\bos\.(?:remove|rename|makedirs|listdir)\s*\("
    r"|\breadFile\w*\s*\(|\bwriteFile\w*\s*\(",
)
_PURPOSE_LOGGING_RE = re.compile(
    r"\blogging\.getLogger\s*\(|\blogger\.(?:info|warning|error|debug|exception)\s*\("
    r"|\bstructlog\b|\bsentry_sdk\b|\bprometheus\w*\b|console\.(?:log|warn|error)\s*\(",
)
_PURPOSE_DATA_TRANSFORM_RE = re.compile(
    r"\.groupby\s*\(|\.merge\s*\(|\.pivot\w*\s*\(|\.melt\s*\(|\.assign\s*\("
    r"|\.astype\s*\(|\.dropna\s*\(|\.fillna\s*\(|\.apply\s*\(|\.resample\s*\("
    r"|\.sort_values\s*\(|\.value_counts\s*\("
    # Spark/batch ETL transforms and writers (camelCase DataFrame API).
    r"|\.withColumn\w*\s*\(|\.dropDuplicates\s*\(|\.repartition\s*\("
    r"|\.write\.(?:mode|parquet|csv|json|format|saveAsTable)\s*\(",
)
_PURPOSE_ERROR_HANDLING_RE = re.compile(
    r"\btry\s*:|\bexcept\s+\w|\braise\s+\w+|\btry\s*\{|\bcatch\s*\(",
)
# Executable statements inside a routed handler body (beyond the decorator line).
_HANDLER_BODY_RE = re.compile(r"\b(?:return|await|raise|if|for|while|with)\b")

# ── Frontend (TSX/JSX) structural signals ─────────────────────────────────────
# JS/TS comments are stripped before matching so a comment mentioning a form or
# chart is never a signal. Path shape refines identity (page/layout/ui-primitive);
# block-level code structure refines what THIS block does within the file.
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_JS_LINE_COMMENT_RE = re.compile(r"(?m)(?:^|(?<=\s))//.*$")

_FE_PATH_PAGE_RE = re.compile(r"(?:^|/)page\.(?:tsx|jsx)$|(?:^|/)pages/[^/]+\.(?:tsx|jsx)$")
_FE_PATH_LAYOUT_RE = re.compile(r"(?:^|/)layout\.(?:tsx|jsx)$")
_FE_PATH_UI_PRIMITIVE_RE = re.compile(r"(?:^|/)components/ui/[^/]+\.(?:tsx|jsx)$")
_FE_PATH_PROVIDER_RE = re.compile(r"provider[^/]*\.(?:tsx|jsx)$")
_FE_PATH_FORM_RE = re.compile(r"form[^/]*\.(?:tsx|jsx)$|[^/]*-form\.(?:tsx|jsx)$")
_FE_PATH_NAV_RE = re.compile(r"(?:nav|breadcrumb|sidebar|menu)[^/]*\.(?:tsx|jsx)$")
_FE_PATH_CHART_RE = re.compile(r"(?:chart|graph|plot|viz)[^/]*\.(?:tsx|jsx)$")
_FE_PATH_RESULTS_RE = re.compile(r"(?:result|panel|summary|output)[^/]*\.(?:tsx|jsx)$")
_FE_PATH_TABLE_RE = re.compile(r"(?:table|list|grid)[^/]*\.(?:tsx|jsx)$")
_FE_PATH_DIALOG_RE = re.compile(r"(?:dialog|modal|alert|toast|popover)[^/]*\.(?:tsx|jsx)$")

_FE_CODE_FORM_RE = re.compile(
    r"<form\b|onSubmit\s*=|handleSubmit\b|useForm\s*\(|<FormField\b|zodResolver\s*\(",
)
_FE_CODE_CHART_RE = re.compile(
    r"<(?:Line|Bar|Area|Pie|Scatter|Radar|Composed)Chart\b|<ResponsiveContainer\b"
    r"|\brecharts\b|\bchart\.js\b|\bd3\.\w+|\bplotly\b",
    re.IGNORECASE,
)
_FE_CODE_DIALOG_RE = re.compile(
    r"<(?:Alert)?Dialog\w*\b|<Modal\b|<Drawer\b|<Sheet\b|<Popover\b|<Alert\b|<Toast\b",
)
_FE_CODE_TABLE_RE = re.compile(r"<table\b|<Table\w*\b|<thead\b|<DataGrid\b|columns\s*=\s*[\[{]")
_FE_CODE_NAV_RE = re.compile(r"<nav\b|<Breadcrumb\w*\b|<NavigationMenu\b|<Sidebar\b")
_FE_CODE_PROVIDER_RE = re.compile(
    r"<\w*Provider\b|createContext\s*[(<]|\bThemeProvider\b",
)
_FE_CODE_API_CLIENT_RE = re.compile(
    r"\bfetch\s*\(|\baxios\.\w+\s*\(|\baxios\s*\(|\buseSWR\s*\(|\buseQuery\s*\(|\buseMutation\s*\(",
)
_FE_CODE_LOADING_ERROR_RE = re.compile(
    r"\bisLoading\b|\bisError\b|<Skeleton\b|<Spinner\b|\bloading\s*[?&]|\berror\s*&&",
)
_FE_CODE_STATE_RE = re.compile(r"\buseState\s*[(<]|\buseReducer\s*\(|\buseContext\s*\(")


def _executable_with_strings(text: str) -> str:
    """Strip comment / docstring PROSE but KEEP string literals.

    Some honest structural signals live inside quotes — ``df["latitude"]``
    column names, Dockerfile-ish strings — which the full
    :func:`_strip_comments_and_docstrings` pass would delete. This lighter
    variant removes triple-quoted blocks and ``#`` line comments only, so prose
    can still never match while quoted identifiers survive.
    """
    stripped = _TRIPLE_QUOTED_BLOCK_RE.sub("", text)
    return _LINE_COMMENT_RE.sub("", stripped)


def _geo_purpose_from_code(executable: str, raw_snippet: str) -> str | None:
    """The geospatial purpose of an EXECUTABLE body, or ``None``.

    Checked most-specific first (distance → geocoding → visualization → spatial
    data loading → spatial ops) with the lat/lon column check last — it needs
    BOTH a latitude and a longitude identifier/column in string-preserving,
    prose-stripped code, so a docstring mentioning "latitude" never matches.
    Import lines are stripped from the string-preserving text too, so a
    ``from utils import latitude, longitude`` line is never a signal.
    """
    if _PURPOSE_GEO_DISTANCE_RE.search(executable):
        return PURPOSE_GEO_DISTANCE_CALCULATION
    if _PURPOSE_GEO_GEOCODE_RE.search(executable):
        return PURPOSE_GEO_GEOCODING_API
    if _PURPOSE_GEO_VIZ_RE.search(executable):
        return PURPOSE_GEO_VISUALIZATION
    if _PURPOSE_GEO_DATA_RE.search(executable):
        return PURPOSE_GEO_DATA_LOADING
    if _PURPOSE_GEO_OPS_RE.search(executable):
        return PURPOSE_GEO_FEATURE_ENGINEERING
    with_strings = _strip_import_lines(_executable_with_strings(raw_snippet))
    if _GEO_LAT_RE.search(with_strings) and _GEO_LON_RE.search(with_strings):
        return PURPOSE_GEO_FEATURE_HANDLING
    return None


def _frontend_purpose(code_snippet: str | None, path: str) -> str:
    """The purpose of a TSX/JSX/frontend block from path shape + code structure.

    Never returns ``None`` — the generic ``frontend_ui_component`` is the
    fail-closed floor. Block-level code structure (a form, a chart, a dialog)
    outranks file identity so two blocks of the same ``page.tsx`` can honestly
    read as "React page / route component" and "Input form and form state
    handling" respectively; file identity (page/layout/ui-primitive/provider)
    decides when the block itself carries no more specific structure.

    Comments AND import lines are stripped before the code-structure checks, so
    ``import { LineChart } from "recharts"`` / ``import { useState } from
    "react"`` never reads as a chart / state-management block — only a real
    usage line (a rendered ``<LineChart>``, a ``useState(`` call) is a signal.
    """
    text = code_snippet or ""
    code = _strip_import_lines(_JS_LINE_COMMENT_RE.sub("", _JS_BLOCK_COMMENT_RE.sub("", text)))
    filename = path.rsplit("/", 1)[-1]
    if _FE_CODE_FORM_RE.search(code) or _FE_PATH_FORM_RE.search(filename):
        return PURPOSE_FRONTEND_FORM_COMPONENT
    if _FE_CODE_CHART_RE.search(code) or _FE_PATH_CHART_RE.search(filename):
        return PURPOSE_FRONTEND_CHART_COMPONENT
    if _FE_CODE_DIALOG_RE.search(code) or _FE_PATH_DIALOG_RE.search(filename):
        return PURPOSE_FRONTEND_DIALOG_ALERT
    if _FE_CODE_TABLE_RE.search(code) or _FE_PATH_TABLE_RE.search(filename):
        return PURPOSE_FRONTEND_TABLE_LIST
    if _FE_CODE_NAV_RE.search(code) or _FE_PATH_NAV_RE.search(filename):
        return PURPOSE_FRONTEND_NAVIGATION
    if _FE_CODE_PROVIDER_RE.search(code) or _FE_PATH_PROVIDER_RE.search(filename):
        return PURPOSE_FRONTEND_PROVIDER_THEME
    if _FE_PATH_PAGE_RE.search(path):
        return PURPOSE_FRONTEND_PAGE_COMPONENT
    if _FE_PATH_LAYOUT_RE.search(path):
        return PURPOSE_FRONTEND_LAYOUT_COMPONENT
    if _FE_PATH_UI_PRIMITIVE_RE.search(path):
        return PURPOSE_FRONTEND_UI_PRIMITIVE
    if _FE_PATH_RESULTS_RE.search(filename):
        return PURPOSE_FRONTEND_RESULTS_DISPLAY
    if _FE_CODE_API_CLIENT_RE.search(code):
        return PURPOSE_FRONTEND_API_CLIENT
    if _PURPOSE_INPUT_VALIDATION_RE.search(code):
        return PURPOSE_INPUT_VALIDATION
    if _FE_CODE_LOADING_ERROR_RE.search(code):
        return PURPOSE_FRONTEND_LOADING_ERROR
    if _FE_CODE_STATE_RE.search(code):
        return PURPOSE_FRONTEND_STATE_MANAGEMENT
    return PURPOSE_FRONTEND_UI_COMPONENT


# ── Dockerfile instruction classification ─────────────────────────────────────
_DOCKER_INSTRUCTION_RE = re.compile(
    r"(?im)^\s*(FROM|RUN|CMD|ENTRYPOINT|COPY|ADD|WORKDIR|ENV|ARG|EXPOSE|"
    r"HEALTHCHECK|LABEL|USER|VOLUME|SHELL|STOPSIGNAL|ONBUILD)\b"
)
_DOCKER_INSTALL_RE = re.compile(
    r"(?im)^\s*RUN\s+.*\b(?:pip3?|npm|yarn|pnpm|apt-get|apt|apk|poetry|conda|uv|gem|composer)\b"
    r".*\b(?:install|add|sync|ci)\b"
)
# Dockerfile executable build/run steps vs declarative-only configuration.
_DOCKER_EXEC_INSTRUCTIONS = frozenset(
    {"RUN", "CMD", "ENTRYPOINT", "COPY", "ADD", "HEALTHCHECK", "ONBUILD"}
)


def _dockerfile_instructions(snippet: str) -> list[str]:
    """Uppercased Dockerfile instruction words present in ``snippet``, in order."""
    return [m.group(1).upper() for m in _DOCKER_INSTRUCTION_RE.finditer(snippet)]


def _dockerfile_purpose(code_snippet: str | None) -> str:
    """The instruction-level purpose of a Dockerfile block (closed vocabulary).

    Priority: multi-stage build → dependency install → runtime command →
    health check → generic build step → files/workdir → exposed port →
    env/args → base image. A block spanning four or more distinct instruction
    kinds is effectively the whole build and keeps the generic
    ``containerization`` label; a block with no recognizable instruction fails
    closed to ``containerization`` too (it is still container packaging config).
    """
    text = code_snippet or ""
    instructions = _dockerfile_instructions(text)
    if not instructions:
        return PURPOSE_CONTAINERIZATION
    kinds = set(instructions)
    if instructions.count("FROM") >= 2:
        return PURPOSE_CONTAINER_MULTI_STAGE_BUILD
    if len(kinds) >= 4:
        return PURPOSE_CONTAINERIZATION
    if _DOCKER_INSTALL_RE.search(text):
        return PURPOSE_CONTAINER_DEPENDENCY_INSTALL
    if "CMD" in kinds or "ENTRYPOINT" in kinds:
        return PURPOSE_CONTAINER_RUNTIME_COMMAND
    if "HEALTHCHECK" in kinds:
        return PURPOSE_CONTAINER_HEALTHCHECK
    if "RUN" in kinds:
        return PURPOSE_CONTAINER_BUILD_STEP
    if "COPY" in kinds or "ADD" in kinds or "WORKDIR" in kinds:
        return PURPOSE_CONTAINER_FILES_SETUP
    if "EXPOSE" in kinds:
        return PURPOSE_CONTAINER_PORT_EXPOSURE
    if "ENV" in kinds or "ARG" in kinds:
        return PURPOSE_CONTAINER_ENV_CONFIG
    if "FROM" in kinds:
        return PURPOSE_CONTAINER_BASE_IMAGE
    return PURPOSE_CONTAINERIZATION


def _grade_dockerfile_snippet(snippet: str) -> str:
    """Deterministic grade for a line-level Dockerfile block.

    Comment-only blocks are documentation; executable build/run instructions
    (RUN/CMD/ENTRYPOINT/COPY/ADD/HEALTHCHECK) are a real implementation body of
    the container build; declarative-only instructions (FROM/ENV/ARG/EXPOSE/
    WORKDIR/LABEL/…) are configuration. No instruction at all fails closed to
    the repository-level fallback. The ML read-time gate is unaffected: a
    Dockerfile body carries no ML executable signal, so it can never survive as
    Machine Learning primary implementation.
    """
    non_blank = [ln.strip() for ln in snippet.splitlines() if ln.strip()]
    if not non_blank:
        return GRADE_REPO_LEVEL_FALLBACK
    if all(ln.startswith("#") for ln in non_blank):
        return GRADE_COMMENT_OR_DOCSTRING
    kinds = set(_dockerfile_instructions(snippet))
    if kinds & _DOCKER_EXEC_INSTRUCTIONS:
        return GRADE_IMPLEMENTATION_BODY
    if kinds:
        return GRADE_CONFIG_OR_CONSTANT
    return GRADE_REPO_LEVEL_FALLBACK


def describe_code_block_purpose(key: str | None) -> str:
    """Recruiter-readable label for a ``code_block_purpose_key`` (fail-closed)."""
    return CODE_BLOCK_PURPOSE_LABELS.get(
        key or "", CODE_BLOCK_PURPOSE_LABELS[PURPOSE_UNKNOWN_NEEDS_REVIEW]
    )


def code_block_purpose_summary(key: str | None) -> str:
    """One short, safe helper sentence for a purpose key (fail-closed)."""
    return _CODE_BLOCK_PURPOSE_SUMMARIES.get(
        key or "", _CODE_BLOCK_PURPOSE_SUMMARIES[PURPOSE_UNKNOWN_NEEDS_REVIEW]
    )


def _documentation_purpose(code_snippet: str | None) -> str:
    """Which closed documentation purpose a docstring/comment block is about.

    Reads the PROSE only to pick a static topic key (retraining pipeline →
    pipeline → usage → generic); nothing from the prose is ever echoed. The
    result is always in the ``comment_or_docstring`` purpose family, so a
    docstring that *mentions* ``model.fit(...)`` can only ever be documentation
    ABOUT training — never the "Model training" purpose itself.
    """
    text = (code_snippet or "").strip()
    if not text:
        return PURPOSE_DOCUMENTATION_OVERVIEW
    if _DOC_RETRAINING_RE.search(text):
        return PURPOSE_RETRAINING_DOCUMENTATION
    if _DOC_SERVING_RE.search(text):
        return PURPOSE_SERVING_DOCUMENTATION
    if _DOC_DEPLOYMENT_RE.search(text):
        return PURPOSE_DEPLOYMENT_DOCUMENTATION
    if _DOC_ARCHITECTURE_RE.search(text):
        return PURPOSE_ARCHITECTURE_DOCUMENTATION
    if _DOC_API_PROTOCOL_RE.search(text):
        return PURPOSE_API_PROTOCOL_DOCUMENTATION
    if _DOC_PIPELINE_RE.search(text):
        return PURPOSE_PIPELINE_DOCUMENTATION
    if _DOC_USAGE_RE.search(text):
        return PURPOSE_USAGE_INSTRUCTIONS
    return PURPOSE_DOCUMENTATION_OVERVIEW


def _semantic_purpose_from_code(code_snippet: str | None, file_path: str | None) -> str | None:
    """The purpose of an EXECUTABLE code body, or ``None``.

    A test-file path wins first (a test that calls ``.fit(`` is test code, not
    model-training implementation), then a frontend component extension. The
    executable checks run on comment/docstring-stripped AND import-stripped text
    in priority order (handler → training → evaluation → inference → features →
    data → model load/save → schema → route → cloud → deployment), so a training
    body that also computes a metric still reads as model training, while an
    import line naming a library (``nltk``, ``FAISS``, ``shapely``) is never
    itself an executable purpose signal.
    """
    path = str(file_path or "").strip().lower()
    if path and _TEST_PATH_RE.search(path):
        return PURPOSE_TEST_VALIDATION
    if path and _FRONTEND_PATH_RE.search(path):
        return _frontend_purpose(code_snippet, path)
    if path and _CI_CD_PATH_RE.search(path):
        return PURPOSE_CI_CD_WORKFLOW
    if path and _CONTAINER_PATH_RE.search(path):
        return _dockerfile_purpose(code_snippet)
    if not code_snippet or not code_snippet.strip():
        return None
    executable = _strip_import_lines(_strip_comments_and_docstrings(code_snippet))
    if not executable.strip():
        return None
    if _ROLE_ROUTE_RE.search(executable) and _ROLE_PREDICTION_RE.search(executable):
        return PURPOSE_API_PREDICTION_HANDLER
    # Tuning is checked BEFORE training: a ``GridSearchCV(...).fit(...)`` body is
    # hyperparameter search around training, and the search construct is the more
    # specific honest description of what the block does.
    if _PURPOSE_TUNING_RE.search(executable):
        return PURPOSE_HYPERPARAMETER_TUNING
    if _ROLE_MODEL_TRAINING_RE.search(executable):
        return PURPOSE_MODEL_TRAINING
    if _ROLE_EVALUATION_RE.search(executable):
        return PURPOSE_MODEL_EVALUATION
    if _ROLE_PREDICTION_RE.search(executable):
        return PURPOSE_PREDICTION_INFERENCE
    if _PURPOSE_LLM_RE.search(executable):
        return PURPOSE_LLM_CALL_WRAPPER
    if _PURPOSE_RAG_RE.search(executable):
        return PURPOSE_RAG_RETRIEVAL
    if _PURPOSE_EMBEDDING_RE.search(executable):
        return PURPOSE_EMBEDDING_GENERATION
    if _PURPOSE_NLP_RE.search(executable):
        return PURPOSE_TEXT_NLP_PROCESSING
    if _PURPOSE_CV_RE.search(executable):
        return PURPOSE_IMAGE_PROCESSING_CV
    geo = _geo_purpose_from_code(executable, code_snippet)
    if geo:
        return geo
    if _ROLE_FEATURE_RE.search(executable):
        return PURPOSE_PREPROCESSING_FEATURES
    if _ROLE_DATA_LOADING_RE.search(executable):
        return PURPOSE_DATA_LOADING
    if _PURPOSE_MODEL_LOADING_RE.search(executable):
        return PURPOSE_MODEL_LOADING
    if _PURPOSE_ARTIFACT_PERSISTENCE_RE.search(executable):
        return PURPOSE_ARTIFACT_PERSISTENCE
    if _PURPOSE_DATABASE_RE.search(executable):
        return PURPOSE_DATABASE_OPERATION
    if _PURPOSE_AUTH_RE.search(executable):
        return PURPOSE_AUTH_PERMISSION_CHECK
    if _PURPOSE_INPUT_VALIDATION_RE.search(executable):
        return PURPOSE_INPUT_VALIDATION
    if _PURPOSE_REQUEST_SCHEMA_RE.search(executable):
        return PURPOSE_API_REQUEST_SCHEMA
    if _ROLE_ROUTE_RE.search(executable):
        # A routed block whose body carries real executable statements is a full
        # request handler; a bare decorator (+ signature) stays a route shell.
        decorator_free = _ROLE_ROUTE_RE.sub("", executable)
        if _HANDLER_BODY_RE.search(decorator_free):
            return PURPOSE_API_REQUEST_HANDLER
        return PURPOSE_API_ROUTE_SHELL
    # Cloud URI schemes live inside string literals, so they are checked against
    # string-preserving text — but with comment/docstring prose and import lines
    # stripped, so a ``# see gs://bucket`` comment is never a cloud signal.
    if _PURPOSE_CLOUD_IO_RE.search(executable) or _CLOUD_URI_RE.search(
        _strip_import_lines(_executable_with_strings(code_snippet))
    ):
        return PURPOSE_CLOUD_STORAGE_IO
    if _PURPOSE_VISUALIZATION_RE.search(executable):
        return PURPOSE_DATA_VISUALIZATION
    if _ROLE_DEPLOYMENT_RE.search(executable):
        return PURPOSE_DEPLOYMENT_SERVING
    # Universal fallback purposes — generic code structure that still tells a
    # recruiter what the block does when no skill-specific family matched.
    if _PURPOSE_NETWORK_CALL_RE.search(executable):
        return PURPOSE_NETWORK_API_CALL
    if _PURPOSE_DATA_TRANSFORM_RE.search(executable):
        return PURPOSE_DATA_TRANSFORMATION
    if _PURPOSE_FILE_IO_RE.search(executable):
        return PURPOSE_FILE_IO
    if _PURPOSE_LOGGING_RE.search(executable):
        return PURPOSE_LOGGING_MONITORING
    if _PURPOSE_ERROR_HANDLING_RE.search(executable):
        return PURPOSE_ERROR_HANDLING
    return None


# ── Stage 1: block KIND classification (what the selected range IS) ───────────
#
# The purpose classifier is a STRICT TWO-STAGE pipeline. Stage 1 decides what the
# selected line range structurally IS — documentation, imports, config,
# executable code, a mix, or nothing trusted at all — from the VALIDATED grade
# plus the composition of the trusted snippet (never a stored reason). Stage 2
# (:func:`classify_code_block_purpose`) may only assign a purpose from the
# family Stage 1 allows: a documentation-only range can only ever be a
# documentation topic, an import-only range is always dependency setup, and a
# semantic executable purpose (training / inference / metrics / …) is reachable
# ONLY through the executable / mixed kinds. Skill words in prose or a library
# name on an import line can therefore never produce an executable purpose.

BLOCK_KIND_DOCUMENTATION_ONLY = "documentation_only"
BLOCK_KIND_IMPORT_ONLY = "import_only"
BLOCK_KIND_CONFIG_CONSTANTS_ONLY = "config_constants_only"
BLOCK_KIND_EXECUTABLE_CODE = "executable_code"
BLOCK_KIND_MIXED = "mixed_documentation_import_executable"
BLOCK_KIND_REPOSITORY_ONLY = "repository_only_no_trusted_source"
BLOCK_KIND_UNKNOWN = "unknown"

BLOCK_KINDS = (
    BLOCK_KIND_DOCUMENTATION_ONLY,
    BLOCK_KIND_IMPORT_ONLY,
    BLOCK_KIND_CONFIG_CONSTANTS_ONLY,
    BLOCK_KIND_EXECUTABLE_CODE,
    BLOCK_KIND_MIXED,
    BLOCK_KIND_REPOSITORY_ONLY,
    BLOCK_KIND_UNKNOWN,
)

# The three structural grades that already ARE a block kind. A bare route
# decorator is declaration-only plumbing, so it folds into the config kind (its
# purpose still refines to "API route shell" in Stage 2 via the grade).
_GRADE_BLOCK_KIND: dict[str, str] = {
    GRADE_COMMENT_OR_DOCSTRING: BLOCK_KIND_DOCUMENTATION_ONLY,
    GRADE_IMPORT_ONLY: BLOCK_KIND_IMPORT_ONLY,
    GRADE_CONFIG_OR_CONSTANT: BLOCK_KIND_CONFIG_CONSTANTS_ONLY,
    GRADE_ROUTE_DECORATOR_ONLY: BLOCK_KIND_CONFIG_CONSTANTS_ONLY,
}


def _range_composition(snippet: str) -> tuple[int, int, int]:
    """(prose_lines, import_lines, executable_lines) of ONE selected range.

    Counts only lines INSIDE the given snippet — code elsewhere in the file can
    never leak in, because only the persisted range excerpt is ever passed here.
    """
    non_blank = [ln for ln in snippet.splitlines() if ln.strip()]
    body_lines, _ = _strip_docstrings(non_blank)
    real = [ln for ln in body_lines if ln.strip() and _line_kind(ln) != "comment"]
    prose = len(non_blank) - len(real)
    import_flags = _import_line_flags(real)
    imports = sum(1 for f in import_flags if f)
    executable = len(real) - imports
    return prose, imports, executable


def classify_block_kind(
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
) -> str:
    """Stage 1 — what the selected line range structurally IS (fail closed).

    * The VALIDATED grade decides the weak structural kinds outright: a range
      graded ``comment_or_docstring`` IS documentation (the grader already
      applied prose/import dominance to the range), ``import_only`` IS imports,
      ``config_or_constant`` / ``route_decorator_only`` IS declarations only.
    * A range with real executable lines is ``executable_code`` — or ``mixed``
      when docstring/comment prose or import lines sit in the SAME selected
      range (top-of-file headers sliced together with a real body). Both kinds
      route Stage 2 to the executable classifiers, which strip the prose and
      import lines first, so the executable code decides the purpose.
    * A STRONG grade whose trusted body is not re-exposed at read time is still
      ``executable_code`` — the grade is the trusted structural verdict.
    * No trusted content and no strong grade → ``repository_only_no_trusted_source``
      (ungraded / repo fallback) or ``unknown`` for an unrecognized grade string.
    """
    g = str(grade or "").strip().lower()
    if g in _GRADE_BLOCK_KIND:
        return _GRADE_BLOCK_KIND[g]
    if code_snippet and code_snippet.strip():
        prose, imports, executable = _range_composition(code_snippet)
        if executable > 0:
            if prose > 0 or imports > 0:
                return BLOCK_KIND_MIXED
            return BLOCK_KIND_EXECUTABLE_CODE
    if is_strong_grade(g):
        return BLOCK_KIND_EXECUTABLE_CODE
    if g in ("", GRADE_REPO_LEVEL_FALLBACK):
        return BLOCK_KIND_REPOSITORY_ONLY
    if g in EVIDENCE_QUALITY_GRADES:
        return BLOCK_KIND_REPOSITORY_ONLY
    return BLOCK_KIND_UNKNOWN


def classify_code_block_purpose(
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
    selection_reason: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
) -> str:
    """Stage 2 — a conservative ``code_block_purpose_key`` for one focused block.

    This is a LABEL, never a strength verdict. It dispatches STRICTLY on the
    Stage-1 block kind (:func:`classify_block_kind`) and fails closed:

    1. ``documentation_only`` → a documentation topic (refined from its own
       prose, closed set); ``import_only`` → dependency setup; a config /
       declaration-only kind → config/paths (or its honest Dockerfile / route
       shell refinement). Skill words in docs and library names on import lines
       never create an executable purpose. A stale reason never changes this.
    2. ``executable_code`` / ``mixed`` → the EXECUTABLE lines inside the selected
       range decide the semantic purpose (training / evaluation / inference /
       handler / schema / cloud / …); prose and import lines are stripped first,
       so a mixed header + body range is classified by its real body.
    3. A STRONG grade with no trusted snippet/executable text is UNKNOWN —
       ``selection_reason`` is untrusted stored text and NEVER yields an
       executable purpose (Model training, Prediction / inference, …) on its
       own; only real source ever does.
    4. Anything else (repository-only / unknown kind) → repository context, with
       only safe path-shape refinements (a test / workflow / Dockerfile path).

    ``selection_reason`` is accepted only for signature stability with
    :func:`classify_code_role`; it is intentionally never consulted here.
    """
    g = str(grade or "").strip().lower()
    path = str(file_path or "").strip().lower()
    kind = classify_block_kind(grade=g, code_snippet=code_snippet)
    if kind == BLOCK_KIND_DOCUMENTATION_ONLY:
        return _documentation_purpose(code_snippet)
    if kind == BLOCK_KIND_IMPORT_ONLY:
        return PURPOSE_IMPORTS_DEPENDENCIES
    if kind == BLOCK_KIND_CONFIG_CONSTANTS_ONLY:
        if g == GRADE_ROUTE_DECORATOR_ONLY:
            return PURPOSE_API_ROUTE_SHELL
        # A declarative-only Dockerfile block (FROM/ENV/EXPOSE/WORKDIR) grades as
        # config; its honest purpose is still the specific container instruction.
        if path and _CONTAINER_PATH_RE.search(path):
            return _dockerfile_purpose(code_snippet)
        if code_snippet:
            # String-preserving but prose- and import-stripped, so a comment or
            # import mentioning cloud storage never refines a config block.
            config_text = _strip_import_lines(_executable_with_strings(code_snippet))
            if _CLOUD_URI_RE.search(config_text) or _PURPOSE_CLOUD_IO_RE.search(config_text):
                return PURPOSE_CLOUD_STORAGE_IO
        return PURPOSE_CONFIG_PATHS_ARTIFACTS
    # executable_code / mixed — and, for repository-only/unknown kinds, the same
    # call still yields ONLY safe path-shape purposes (test / workflow / container
    # paths); with no snippet and no such path it returns None and falls closed.
    purpose = _semantic_purpose_from_code(code_snippet, file_path)
    if purpose:
        return purpose
    if is_strong_grade(g):
        return PURPOSE_UNKNOWN_NEEDS_REVIEW
    return PURPOSE_REPOSITORY_CONTEXT


def effective_code_block_purpose(
    purpose_key: str | None,
    *,
    grade: str | None = None,
    code_snippet: str | None = None,
    selection_reason: str | None = None,
    file_path: str | None = None,
    function_name: str | None = None,
) -> str:
    """Read-time resolution of a block's purpose against its VALIDATED grade.

    Applied where a report row is projected (after ``effective_evidence_grade``),
    so an upstream/stale purpose can never contradict what the validated grade
    says the block IS:

    * a VALIDATED weak structural band keeps an upstream purpose ONLY when it is
      inside that band's honest family (so a snippet-refined "Documentation
      describing retraining pipeline" survives, but "Model training" riding on
      an import-only row is discarded and reclassified);
    * otherwise a recognized upstream purpose (server-derived, never user
      metadata) is kept as-is; and
    * a row with NO purpose is classified conservatively from the validated
      grade + whatever safe signals remain (fail closed to repository context).
    """
    g = str(grade or "").strip().lower()
    key = str(purpose_key or "").strip().lower()
    family = _GRADE_PURPOSE_FAMILY.get(g)
    if family is not None:
        if key in family:
            return key
        return classify_code_block_purpose(
            grade=g,
            code_snippet=code_snippet,
            selection_reason=selection_reason,
            file_path=file_path,
            function_name=function_name,
        )
    if key in CODE_BLOCK_PURPOSE_LABELS:
        return key
    return classify_code_block_purpose(
        grade=g,
        code_snippet=code_snippet,
        selection_reason=selection_reason,
        file_path=file_path,
        function_name=function_name,
    )


# ── Skill relevance (how a block relates to the SELECTED skill, NOT proof) ────
#
# ``skill_relevance_*`` answers the third recruiter question, distinct from both
# the purpose ("what does this block do?") and the grade ("how strong is the
# proof?"): **how does this block relate to the skill this report is about?** A
# frontend risk-input form is honest UI work — but for a *Machine Learning*
# report it is product context, never ML implementation; the same form IS direct
# evidence for a *React* report. Relevance is computed at read time from the
# already-resolved purpose × the selected skill's family × the VALIDATED grade,
# so it can never disagree with them — and, like the purpose, it is a closed
# vocabulary of static templates that NEVER upgrades proof strength: an
# in-family purpose on a non-strong grade only ever reads as a "needs review"
# candidate, and cross-family evidence never counts toward the selected skill.

RELEVANCE_DIRECT_IMPLEMENTATION = "direct_implementation"
RELEVANCE_DIRECT_CANDIDATE = "direct_candidate_needs_review"
RELEVANCE_SUPPORTING_IMPLEMENTATION = "supporting_implementation"
RELEVANCE_SUPPORTING_CONTEXT = "supporting_context"
RELEVANCE_PRODUCT_UI_CONTEXT = "product_ui_context"
RELEVANCE_DEPLOYMENT_CONTEXT = "deployment_context"
RELEVANCE_CROSS_SKILL_CONTEXT = "cross_skill_context"
RELEVANCE_DOCUMENTATION_CONTEXT = "documentation_context"
RELEVANCE_SETUP_CONTEXT = "setup_context"
RELEVANCE_TEST_CONTEXT = "test_context"
RELEVANCE_CONTEXT_ONLY = "context_only_needs_review"

# ``{skill}`` is replaced with the report's own canonical skill display name (a
# string the report already shows everywhere) — sanitized + length-capped, never
# metadata prose. Everything around it is a static template from this module.
SKILL_RELEVANCE_LABELS: dict[str, str] = {
    RELEVANCE_DIRECT_IMPLEMENTATION: "Direct {skill} implementation evidence",
    RELEVANCE_DIRECT_CANDIDATE: "Possible {skill} implementation — needs review",
    RELEVANCE_SUPPORTING_IMPLEMENTATION: "Supporting {skill} implementation evidence",
    RELEVANCE_SUPPORTING_CONTEXT: "Supporting context for {skill}",
    RELEVANCE_PRODUCT_UI_CONTEXT: "Product UI context, not {skill} implementation",
    RELEVANCE_DEPLOYMENT_CONTEXT: "Deployment context, not {skill} implementation",
    RELEVANCE_CROSS_SKILL_CONTEXT: "Adjacent code context, not direct {skill} evidence",
    RELEVANCE_DOCUMENTATION_CONTEXT: "Documentation context, not executable {skill} proof",
    RELEVANCE_SETUP_CONTEXT: "Setup context, not {skill} implementation proof",
    RELEVANCE_TEST_CONTEXT: "Test coverage context for {skill}",
    RELEVANCE_CONTEXT_ONLY: "Possible {skill} context — needs review",
}
SKILL_RELEVANCE_KEYS = tuple(SKILL_RELEVANCE_LABELS.keys())

_SKILL_RELEVANCE_SUMMARIES: dict[str, str] = {
    RELEVANCE_DIRECT_IMPLEMENTATION: (
        "This block's executable code directly implements {skill} work; the "
        "evidence grade still governs proof strength."
    ),
    RELEVANCE_DIRECT_CANDIDATE: (
        "This block appears related to {skill} implementation, but its proof "
        "strength has not been validated — treat as needs review."
    ),
    RELEVANCE_SUPPORTING_IMPLEMENTATION: (
        "This block's executable code supports the {skill} pipeline around the "
        "core implementation."
    ),
    RELEVANCE_SUPPORTING_CONTEXT: (
        "This block supports {skill} work as surrounding context; it is not "
        "standalone implementation proof."
    ),
    RELEVANCE_PRODUCT_UI_CONTEXT: (
        "This is frontend/product UI around the application — context for "
        "{skill}, not implementation proof."
    ),
    RELEVANCE_DEPLOYMENT_CONTEXT: (
        "This is deployment/infrastructure work around the project — context "
        "for {skill}, not implementation proof."
    ),
    RELEVANCE_CROSS_SKILL_CONTEXT: (
        "This block implements a different part of the project; it is not "
        "direct {skill} evidence."
    ),
    RELEVANCE_DOCUMENTATION_CONTEXT: (
        "This is documentation prose — context for {skill}, never executable proof."
    ),
    RELEVANCE_SETUP_CONTEXT: (
        "This is imports/configuration setup — context for {skill}, not "
        "implementation proof."
    ),
    RELEVANCE_TEST_CONTEXT: (
        "This is test code exercising the project; it supports {skill} claims "
        "without being the implementation itself."
    ),
    RELEVANCE_CONTEXT_ONLY: (
        "Repository-level context only; its relation to {skill} needs review."
    ),
}

# Skill FAMILY detection from the report's skill name — internal, regex-only
# (this module stays stdlib-only), checked most-specific first so "NLP" is not
# swallowed by the broader ML family and "Data Science" is ML, not data.
SKILL_FAMILY_ML = "ml"
SKILL_FAMILY_NLP = "nlp"
SKILL_FAMILY_CV = "cv"
SKILL_FAMILY_GENAI = "genai"
SKILL_FAMILY_GEO = "geospatial"
SKILL_FAMILY_DATA = "data"
SKILL_FAMILY_BACKEND = "backend"
SKILL_FAMILY_FRONTEND = "frontend"
SKILL_FAMILY_DEVOPS = "devops"
SKILL_FAMILY_SECURITY = "security"
SKILL_FAMILY_TESTING = "testing"
SKILL_FAMILY_LANGUAGE = "language"
SKILL_FAMILY_GENERAL = "general"

_SKILL_FAMILY_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bnlp\b|natural\s+language|text\s+(?:mining|classification|analytics)|sentiment", re.IGNORECASE),
     SKILL_FAMILY_NLP),
    (re.compile(r"computer\s+vision|image\s+(?:processing|recognition|classification)|\bopencv\b|object\s+detection", re.IGNORECASE),
     SKILL_FAMILY_CV),
    (re.compile(r"geo-?spatial|\bgis\b|geograph|spatial\s+(?:analysis|analytics|data|statistics)|remote\s+sensing|cartograph|geocod|\bgeomatics\b", re.IGNORECASE),
     SKILL_FAMILY_GEO),
    (re.compile(r"\bgen(?:erative)?\s*ai\b|\bllms?\b|large\s+language|prompt\s+engineer|\brag\b|retrieval[-\s]augmented|langchain|agentic|\bgpt\b", re.IGNORECASE),
     SKILL_FAMILY_GENAI),
    (re.compile(r"machine\s+learning|\bml\b|deep\s+learning|neural|data\s+scien|\bai\b|artificial\s+intelligence|predictive\s+model|reinforcement", re.IGNORECASE),
     SKILL_FAMILY_ML),
    (re.compile(r"devops|docker|kubernetes|\bci\s*/?\s*cd\b|terraform|\bcloud\b|\baws\b|\bgcp\b|\bazure\b|deployment|infrastructure|mlops|\bsre\b", re.IGNORECASE),
     SKILL_FAMILY_DEVOPS),
    (re.compile(r"security|cyber|\bauth(?:entication|orization)?\b|encryption|privacy|penetration", re.IGNORECASE),
     SKILL_FAMILY_SECURITY),
    (re.compile(r"\btest(?:ing)?\b|\bqa\b|quality\s+assurance|selenium|pytest|playwright", re.IGNORECASE),
     SKILL_FAMILY_TESTING),
    (re.compile(r"front[-\s]?end|react|next\.?js|\bvue\b|angular|svelte|\bui\b|user\s+interface|tailwind|\bcss\b|\bhtml\b", re.IGNORECASE),
     SKILL_FAMILY_FRONTEND),
    (re.compile(r"back[-\s]?end|\bapi\b|fastapi|\bflask\b|django|express|node\.?js|\brest\b|graphql|microservice|server[-\s]?side", re.IGNORECASE),
     SKILL_FAMILY_BACKEND),
    (re.compile(r"\bsql\b|database|\bdata\b|analytics|\betl\b|pandas|visuali[sz]ation|tableau|power\s*bi|\bspark\b"
                r"|postgres\w*|mysql|mariadb|sqlite|mongo\w*|\bredis\b|supabase|firebase|dynamodb|snowflake|bigquery",
                re.IGNORECASE),
     SKILL_FAMILY_DATA),
    (re.compile(r"python|javascript|typescript|\bjava\b|c\+\+|c#|golang|\bgo\b|\brust\b|kotlin|swift|\bphp\b|\bruby\b|\bbash\b|shell\s+script", re.IGNORECASE),
     SKILL_FAMILY_LANGUAGE),
)


def skill_family(skill: str | None) -> str:
    """Coarse family of a skill name ("Machine Learning" → ``ml``), fail-open to
    ``general`` — an unrecognized skill never gets a direct/supporting claim."""
    text = str(skill or "").strip()
    if not text:
        return SKILL_FAMILY_GENERAL
    for pattern, family in _SKILL_FAMILY_RES:
        if pattern.search(text):
            return family
    return SKILL_FAMILY_GENERAL


# For each purpose: the families it is DIRECT evidence for, and the families it
# SUPPORTS. Anything else is context (UI / deployment / cross-skill), decided in
# :func:`classify_skill_relevance`. The ML subfamilies (nlp / cv / genai) accept
# core ML-pipeline purposes as supporting evidence, and vice versa.
_ML_SUBFAMILIES = frozenset({SKILL_FAMILY_NLP, SKILL_FAMILY_CV, SKILL_FAMILY_GENAI})
_ML_AND_SUBS = frozenset({SKILL_FAMILY_ML}) | _ML_SUBFAMILIES

# The closed frontend purpose set — direct evidence only for a FRONTEND-family
# skill; product UI context for every other family (a React form is never ML).
_FRONTEND_PURPOSES = frozenset(
    {
        PURPOSE_FRONTEND_UI_COMPONENT,
        PURPOSE_FRONTEND_PAGE_COMPONENT,
        PURPOSE_FRONTEND_LAYOUT_COMPONENT,
        PURPOSE_FRONTEND_FORM_COMPONENT,
        PURPOSE_FRONTEND_STATE_MANAGEMENT,
        PURPOSE_FRONTEND_API_CLIENT,
        PURPOSE_FRONTEND_RESULTS_DISPLAY,
        PURPOSE_FRONTEND_CHART_COMPONENT,
        PURPOSE_FRONTEND_TABLE_LIST,
        PURPOSE_FRONTEND_DIALOG_ALERT,
        PURPOSE_FRONTEND_NAVIGATION,
        PURPOSE_FRONTEND_PROVIDER_THEME,
        PURPOSE_FRONTEND_LOADING_ERROR,
        PURPOSE_FRONTEND_UI_PRIMITIVE,
    }
)

_GEO_PURPOSES = frozenset(
    {
        PURPOSE_GEO_FEATURE_HANDLING,
        PURPOSE_GEO_FEATURE_ENGINEERING,
        PURPOSE_GEO_DISTANCE_CALCULATION,
        PURPOSE_GEO_GEOCODING_API,
        PURPOSE_GEO_DATA_LOADING,
        PURPOSE_GEO_VISUALIZATION,
    }
)

_CONTAINER_PURPOSES = frozenset(
    {
        PURPOSE_CONTAINERIZATION,
        PURPOSE_CONTAINER_BASE_IMAGE,
        PURPOSE_CONTAINER_DEPENDENCY_INSTALL,
        PURPOSE_CONTAINER_FILES_SETUP,
        PURPOSE_CONTAINER_ENV_CONFIG,
        PURPOSE_CONTAINER_PORT_EXPOSURE,
        PURPOSE_CONTAINER_RUNTIME_COMMAND,
        PURPOSE_CONTAINER_MULTI_STAGE_BUILD,
        PURPOSE_CONTAINER_BUILD_STEP,
        PURPOSE_CONTAINER_HEALTHCHECK,
    }
)

_PURPOSE_DIRECT_FAMILIES: dict[str, frozenset[str]] = {
    PURPOSE_MODEL_TRAINING: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_HYPERPARAMETER_TUNING: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_MODEL_EVALUATION: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_PREDICTION_INFERENCE: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_TEXT_NLP_PROCESSING: frozenset({SKILL_FAMILY_NLP}),
    PURPOSE_EMBEDDING_GENERATION: frozenset({SKILL_FAMILY_NLP, SKILL_FAMILY_GENAI}),
    PURPOSE_LLM_CALL_WRAPPER: frozenset({SKILL_FAMILY_GENAI}),
    PURPOSE_RAG_RETRIEVAL: frozenset({SKILL_FAMILY_GENAI}),
    PURPOSE_IMAGE_PROCESSING_CV: frozenset({SKILL_FAMILY_CV}),
    PURPOSE_API_PREDICTION_HANDLER: frozenset({SKILL_FAMILY_BACKEND}),
    PURPOSE_DATABASE_OPERATION: frozenset({SKILL_FAMILY_DATA, SKILL_FAMILY_BACKEND}),
    PURPOSE_AUTH_PERMISSION_CHECK: frozenset({SKILL_FAMILY_SECURITY}),
    PURPOSE_DEPLOYMENT_SERVING: frozenset({SKILL_FAMILY_DEVOPS}),
    PURPOSE_CLOUD_STORAGE_IO: frozenset({SKILL_FAMILY_DEVOPS}),
    PURPOSE_CI_CD_WORKFLOW: frozenset({SKILL_FAMILY_DEVOPS}),
    PURPOSE_CONTAINERIZATION: frozenset({SKILL_FAMILY_DEVOPS}),
    PURPOSE_DATA_VISUALIZATION: frozenset({SKILL_FAMILY_DATA}),
    PURPOSE_FRONTEND_UI_COMPONENT: frozenset({SKILL_FAMILY_FRONTEND}),
    PURPOSE_TEST_VALIDATION: frozenset({SKILL_FAMILY_TESTING}),
    PURPOSE_DATA_LOADING: frozenset({SKILL_FAMILY_DATA}),
    PURPOSE_PREPROCESSING_FEATURES: frozenset({SKILL_FAMILY_DATA}),
    # Frontend sub-purposes: direct evidence only for a frontend-family skill.
    **{p: frozenset({SKILL_FAMILY_FRONTEND}) for p in _FRONTEND_PURPOSES},
    # Geospatial purposes: direct evidence only for a geospatial-family skill.
    **{p: frozenset({SKILL_FAMILY_GEO}) for p in _GEO_PURPOSES},
    # Container/Dockerfile purposes: direct evidence only for DevOps/Docker.
    **{p: frozenset({SKILL_FAMILY_DEVOPS}) for p in _CONTAINER_PURPOSES},
    # Universal fallback purposes with an obvious owning family.
    PURPOSE_DATA_TRANSFORMATION: frozenset({SKILL_FAMILY_DATA}),
    PURPOSE_API_REQUEST_HANDLER: frozenset({SKILL_FAMILY_BACKEND}),
}

_PURPOSE_SUPPORTING_FAMILIES: dict[str, frozenset[str]] = {
    PURPOSE_MODEL_TRAINING: _ML_SUBFAMILIES | {SKILL_FAMILY_DATA},
    PURPOSE_HYPERPARAMETER_TUNING: _ML_SUBFAMILIES,
    PURPOSE_MODEL_EVALUATION: _ML_SUBFAMILIES | {SKILL_FAMILY_DATA},
    PURPOSE_PREDICTION_INFERENCE: _ML_SUBFAMILIES | {SKILL_FAMILY_BACKEND},
    PURPOSE_DATA_LOADING: _ML_AND_SUBS | {SKILL_FAMILY_BACKEND},
    PURPOSE_PREPROCESSING_FEATURES: _ML_AND_SUBS,
    PURPOSE_MODEL_LOADING: _ML_AND_SUBS | {SKILL_FAMILY_BACKEND, SKILL_FAMILY_DEVOPS},
    PURPOSE_ARTIFACT_PERSISTENCE: _ML_AND_SUBS | {SKILL_FAMILY_DATA, SKILL_FAMILY_DEVOPS},
    PURPOSE_TEXT_NLP_PROCESSING: frozenset({SKILL_FAMILY_ML, SKILL_FAMILY_GENAI}),
    PURPOSE_EMBEDDING_GENERATION: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_LLM_CALL_WRAPPER: frozenset({SKILL_FAMILY_NLP}),
    PURPOSE_RAG_RETRIEVAL: frozenset({SKILL_FAMILY_NLP, SKILL_FAMILY_DATA}),
    PURPOSE_IMAGE_PROCESSING_CV: frozenset({SKILL_FAMILY_ML}),
    PURPOSE_API_PREDICTION_HANDLER: _ML_AND_SUBS | {SKILL_FAMILY_DEVOPS},
    PURPOSE_API_REQUEST_SCHEMA: frozenset({SKILL_FAMILY_BACKEND}),
    PURPOSE_API_ROUTE_SHELL: frozenset({SKILL_FAMILY_BACKEND}),
    PURPOSE_DATABASE_OPERATION: frozenset({SKILL_FAMILY_DEVOPS}),
    PURPOSE_AUTH_PERMISSION_CHECK: frozenset({SKILL_FAMILY_BACKEND, SKILL_FAMILY_DEVOPS}),
    PURPOSE_DEPLOYMENT_SERVING: frozenset({SKILL_FAMILY_BACKEND}),
    PURPOSE_CLOUD_STORAGE_IO: frozenset({SKILL_FAMILY_DATA, SKILL_FAMILY_BACKEND}),
    PURPOSE_DATA_VISUALIZATION: _ML_AND_SUBS | {SKILL_FAMILY_GEO},
    # Geospatial work supports ML/data pipelines (feature engineering around a
    # model), but is never itself ML model implementation. For DevOps it stays
    # cross-skill context (deliberately absent here).
    PURPOSE_GEO_FEATURE_HANDLING: _ML_AND_SUBS | {SKILL_FAMILY_DATA},
    PURPOSE_GEO_FEATURE_ENGINEERING: _ML_AND_SUBS | {SKILL_FAMILY_DATA},
    PURPOSE_GEO_DISTANCE_CALCULATION: _ML_AND_SUBS | {SKILL_FAMILY_DATA},
    PURPOSE_GEO_GEOCODING_API: frozenset({SKILL_FAMILY_DATA, SKILL_FAMILY_BACKEND}),
    PURPOSE_GEO_DATA_LOADING: _ML_AND_SUBS | {SKILL_FAMILY_DATA},
    PURPOSE_GEO_VISUALIZATION: frozenset({SKILL_FAMILY_DATA}),
    # Universal fallback purposes: supporting at most, for families where the
    # construct is routine day-to-day work — never direct proof of anything.
    PURPOSE_INPUT_VALIDATION: frozenset(
        {SKILL_FAMILY_BACKEND, SKILL_FAMILY_SECURITY, SKILL_FAMILY_FRONTEND, SKILL_FAMILY_DATA}
    ),
    PURPOSE_FILE_IO: frozenset({SKILL_FAMILY_DATA, SKILL_FAMILY_BACKEND, SKILL_FAMILY_DEVOPS}),
    PURPOSE_NETWORK_API_CALL: frozenset({SKILL_FAMILY_BACKEND, SKILL_FAMILY_DEVOPS}),
    PURPOSE_ERROR_HANDLING: frozenset({SKILL_FAMILY_BACKEND}),
    PURPOSE_LOGGING_MONITORING: frozenset({SKILL_FAMILY_DEVOPS, SKILL_FAMILY_BACKEND}),
    PURPOSE_DATA_TRANSFORMATION: _ML_AND_SUBS,
    PURPOSE_API_REQUEST_HANDLER: frozenset({SKILL_FAMILY_DEVOPS}),
}

# Purposes that are infrastructure work: for a skill OUTSIDE their direct /
# supporting families they read as deployment context (not cross-skill code).
_INFRA_PURPOSES = (
    frozenset(
        {
            PURPOSE_DEPLOYMENT_SERVING,
            PURPOSE_CLOUD_STORAGE_IO,
            PURPOSE_CI_CD_WORKFLOW,
        }
    )
    | _CONTAINER_PURPOSES
)
_DOCUMENTATION_PURPOSES = frozenset(
    {
        PURPOSE_RETRAINING_DOCUMENTATION,
        PURPOSE_PIPELINE_DOCUMENTATION,
        PURPOSE_USAGE_INSTRUCTIONS,
        PURPOSE_DOCUMENTATION_OVERVIEW,
        PURPOSE_ARCHITECTURE_DOCUMENTATION,
        PURPOSE_API_PROTOCOL_DOCUMENTATION,
        PURPOSE_SERVING_DOCUMENTATION,
        PURPOSE_DEPLOYMENT_DOCUMENTATION,
    }
)
_SETUP_PURPOSES = frozenset({PURPOSE_IMPORTS_DEPENDENCIES, PURPOSE_CONFIG_PATHS_ARTIFACTS})


def _safe_skill_display(skill: str | None) -> str:
    """The skill display name as safely usable inside a relevance template.

    The canonical skill name is already shown throughout the report, so echoing
    it here adds no exposure — but it is still whitespace-collapsed and length-
    capped, failing back to the neutral "this skill"."""
    text = re.sub(r"\s+", " ", str(skill or "").strip())
    if not text or len(text) > 48:
        return "this skill"
    return text


def describe_skill_relevance(key: str | None, skill: str | None = None) -> str:
    """Recruiter-readable relevance label for a ``skill_relevance_key`` (fail-closed)."""
    template = SKILL_RELEVANCE_LABELS.get(key or "", SKILL_RELEVANCE_LABELS[RELEVANCE_CONTEXT_ONLY])
    return template.replace("{skill}", _safe_skill_display(skill))


def skill_relevance_summary(key: str | None, skill: str | None = None) -> str:
    """One short, safe helper sentence for a relevance key (fail-closed)."""
    template = _SKILL_RELEVANCE_SUMMARIES.get(
        key or "", _SKILL_RELEVANCE_SUMMARIES[RELEVANCE_CONTEXT_ONLY]
    )
    return template.replace("{skill}", _safe_skill_display(skill))


def classify_skill_relevance(
    purpose_key: str | None,
    *,
    skill: str | None = None,
    grade: str | None = None,
    ml_signal: bool | None = None,
) -> str:
    """How a block (already purpose-classified) relates to the SELECTED skill.

    Derived ONLY from the resolved purpose, the skill's coarse family, and the
    VALIDATED grade — never from stored reasons or raw text — so it can never
    disagree with the purpose or upgrade the grade:

    * documentation / imports / config purposes are always their own honest
      context ("Documentation context…", "Setup context…") — for EVERY skill;
    * an in-family executable purpose is direct evidence ONLY on a validated
      ``implementation_body`` grade; ``supporting_logic`` reads as supporting
      implementation (never "direct"); otherwise it is an explicit needs-review
      candidate;
    * a supporting-family purpose reads as supporting implementation (strong) or
      supporting context (weak);
    * UI for a non-frontend skill is product UI context; infrastructure work for
      a non-devops skill is deployment context; tests are test context;
    * everything else — including every purpose under an unrecognized skill
      family — fails closed to cross-skill / context-only. Cross-family evidence
      never counts toward the selected skill.

    ``ml_signal`` is the authoritative GRADE-TIME ML verdict for canonical rows
    whose trusted body was inspected server-side and then discarded (see
    :func:`ml_implementation_is_valid`). It is honoured in exactly ONE narrow
    case: an ``implementation_body`` whose purpose could not be resolved at read
    time (no re-exposed snippet → unknown/needs-review) but whose trusted body
    PROVED executable ML at grade time is direct evidence for an ML-family
    skill (supporting for the NLP/CV/GenAI subfamilies). It never upgrades any
    other purpose, grade, or skill family.
    """
    p = str(purpose_key or "").strip().lower()
    if p not in CODE_BLOCK_PURPOSE_LABELS:
        return RELEVANCE_CONTEXT_ONLY
    if p in _DOCUMENTATION_PURPOSES:
        return RELEVANCE_DOCUMENTATION_CONTEXT
    if p in _SETUP_PURPOSES:
        return RELEVANCE_SETUP_CONTEXT
    if p in (PURPOSE_REPOSITORY_CONTEXT, PURPOSE_UNKNOWN_NEEDS_REVIEW):
        if (
            p == PURPOSE_UNKNOWN_NEEDS_REVIEW
            and ml_signal is True
            and grade == GRADE_IMPLEMENTATION_BODY
        ):
            family = skill_family(skill)
            if family == SKILL_FAMILY_ML:
                return RELEVANCE_DIRECT_IMPLEMENTATION
            if family in _ML_SUBFAMILIES:
                return RELEVANCE_SUPPORTING_IMPLEMENTATION
        return RELEVANCE_CONTEXT_ONLY

    family = skill_family(skill)
    strong = is_strong_grade(grade)
    if family in _PURPOSE_DIRECT_FAMILIES.get(p, frozenset()):
        # Only a validated implementation BODY may claim "Direct … implementation
        # evidence". ``supporting_logic`` is real code around the implementation —
        # it stays a supporting claim; weaker/ungraded stays a needs-review
        # candidate. The relevance wording can never outrank the grade.
        if grade == GRADE_IMPLEMENTATION_BODY:
            return RELEVANCE_DIRECT_IMPLEMENTATION
        if grade == GRADE_SUPPORTING_LOGIC:
            return RELEVANCE_SUPPORTING_IMPLEMENTATION
        return RELEVANCE_DIRECT_CANDIDATE
    if family in _PURPOSE_SUPPORTING_FAMILIES.get(p, frozenset()):
        return (
            RELEVANCE_SUPPORTING_IMPLEMENTATION if strong else RELEVANCE_SUPPORTING_CONTEXT
        )
    if p == PURPOSE_TEST_VALIDATION:
        return RELEVANCE_TEST_CONTEXT
    if p in _FRONTEND_PURPOSES:
        return RELEVANCE_PRODUCT_UI_CONTEXT
    if p in _INFRA_PURPOSES:
        return RELEVANCE_DEPLOYMENT_CONTEXT
    if family == SKILL_FAMILY_LANGUAGE:
        # Any real executable purpose demonstrates work in the language; it is
        # supporting evidence for a language skill, never a "direct X" claim.
        return (
            RELEVANCE_SUPPORTING_IMPLEMENTATION if strong else RELEVANCE_SUPPORTING_CONTEXT
        )
    if family == SKILL_FAMILY_GENERAL:
        return RELEVANCE_SUPPORTING_CONTEXT if strong else RELEVANCE_CONTEXT_ONLY
    return RELEVANCE_CROSS_SKILL_CONTEXT


# Relevance keys that denote the SELECTED skill's own executable implementation
# work — direct in-family implementation, or supporting-family / language
# implementation validated on a strong grade. Every context key (cross-skill,
# product UI, deployment, documentation, setup, test, context-only) and the
# unvalidated needs-review candidate are excluded, so a block that merely
# SURROUNDS the skill can never gate primary status ("Demonstrated") or a
# primary synthesis statement.
_SKILL_IMPLEMENTATION_RELEVANCES = frozenset(
    {RELEVANCE_DIRECT_IMPLEMENTATION, RELEVANCE_SUPPORTING_IMPLEMENTATION}
)

# Relevance keys that POSITIVELY mark a block as another skill's code or
# non-code context for the selected skill. Such a row may never be presented
# as this skill's code evidence — not even as "supporting" — regardless of its
# grade. (Unknown / needs-review relevance is deliberately NOT here: it is not
# positively cross-skill, so the GRADE continues to govern its non-primary
# claims, while primary claims still require the strict allowlist above.)
_NON_SKILL_CODE_RELEVANCES = frozenset(
    {
        RELEVANCE_CROSS_SKILL_CONTEXT,
        RELEVANCE_PRODUCT_UI_CONTEXT,
        RELEVANCE_DEPLOYMENT_CONTEXT,
        RELEVANCE_DOCUMENTATION_CONTEXT,
        RELEVANCE_SETUP_CONTEXT,
    }
)


def is_skill_implementation_relevance(key: str | None) -> bool:
    """True when a relevance key marks the selected skill's OWN implementation.

    Used together with the VALIDATED ``implementation_body`` grade to gate
    "Demonstrated" status and primary synthesis statements: a
    ``cross_skill_context`` / ``product_ui_context`` / ``deployment_context``
    implementation row can never satisfy this, so a React form or a deployment
    script can never anchor a Machine Learning "Demonstrated". Fails closed on
    ``None`` / unknown keys.
    """
    return key in _SKILL_IMPLEMENTATION_RELEVANCES


def is_skill_code_relevance(key: str | None) -> bool:
    """False when a relevance key POSITIVELY marks a block as another skill's
    code or non-code context (cross-skill / product UI / deployment / docs /
    setup) — such a row is never this skill's code evidence, not even
    "supporting". True otherwise, including unknown/needs-review relevance,
    where the deterministic grade (never the relevance wording) continues to
    govern non-primary claims."""
    return key not in _NON_SKILL_CODE_RELEVANCES


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

_IMPORT_RE = re.compile(
    # Python: ``import x`` / ``from x import y`` / ``from . import y``.
    r"^\s*(?:import\s+\w|from\s+[\w.]+\s+import\b|from\s+\.+\s*import\b"
    # JS/TS: ``import { x } from``, ``import * as x``, ``import "side-effect"``,
    # ``import type { X }``, ``export { x } from`` / ``export * from``, and CJS
    # ``const x = require("y")`` — all dependency wiring, never implementation.
    r"|import\s+[{*\"']|import\s+type\s*[{\w]"
    r"|export\s+(?:\{[^}]*\}|\*)[^;]*\bfrom\b"
    r"|(?:const|let|var)\s+[\w$,{}\s]+=\s*require\s*\()"
)
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

    # MOSTLY-documentation block: when the range is dominated by docstring /
    # comment prose (≥3× the executable lines, and at most two executable lines
    # in total), the block IS documentation — a skill keyword inside the prose,
    # or a lone trailing statement, can never make it read as implementation.
    prose_lines = len(non_blank) - len(real)
    if len(real) <= 2 and prose_lines >= max(3 * len(real), 3):
        return GRADE_COMMENT_OR_DOCSTRING

    # Continuation lines of a multi-line import (``from x import (…)``) carry
    # bare library names; they are import text, never executable statements.
    real_kinds = [
        "import" if flagged else _line_kind(ln)
        for ln, flagged in zip(real, _import_line_flags(real))
    ]

    # All imports (with optional comments) → import-only.
    if all(k == "import" for k in real_kinds):
        return GRADE_IMPORT_ONLY

    # HEADER-dominated block: docstring/comment prose plus import lines dominate
    # (≥3× the executable lines, at most two executable lines in total) — the
    # range IS a module/file header. It grades by what dominates it (imports vs
    # prose), so a header with a lone trailing statement can never read as
    # implementation, even when nearby code elsewhere in the file would.
    exec_lines = [ln for ln, k in zip(real, real_kinds) if k != "import"]
    import_count = len(real) - len(exec_lines)
    header_lines = prose_lines + import_count
    if len(exec_lines) <= 2 and header_lines >= max(3 * len(exec_lines), 3):
        return GRADE_IMPORT_ONLY if import_count > prose_lines else GRADE_COMMENT_OR_DOCSTRING

    # Bare route decorator(s) + at most a signature/decorator/filler — no body.
    has_route = any(k == "route_decorator" for k in real_kinds)
    body_logic = [k for k in real_kinds if k in ("code",)]
    # Implementation signals are read from EXECUTABLE statements only: import
    # lines and inline ``#`` comments are excluded, so ``from sklearn.metrics
    # import accuracy_score`` or a trailing comment can never grade a block as
    # an implementation body.
    has_impl_signal = bool(
        _IMPL_SIGNAL_RE.search(_LINE_COMMENT_RE.sub("", "\n".join(exec_lines)))
    )
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
    # A line-level Dockerfile block has its own deterministic instruction
    # grading (executable build/run steps vs declarative-only config), so a
    # real Dockerfile can be Docker/DevOps implementation evidence while never
    # carrying an ML executable signal.
    if snippet.strip() and path and _CONTAINER_PATH_RE.search(path):
        return _grade_dockerfile_snippet(snippet)
    if snippet.strip() and (is_python or not path):
        return grade_python_snippet(snippet)

    # Non-Python snippet present: a light structural read (imports/comments only).
    if snippet.strip():
        non_blank = [ln for ln in snippet.splitlines() if ln.strip()]
        kinds = [
            "import" if flagged else _line_kind(ln)
            for ln, flagged in zip(non_blank, _import_line_flags(non_blank))
        ]
        real = [k for k in kinds if k != "comment"]
        if real and all(k == "import" for k in real):
            return GRADE_IMPORT_ONLY
        if non_blank and all(k == "comment" for k in kinds):
            return GRADE_COMMENT_OR_DOCSTRING
        # Implementation signals are read from executable text only: JS / hash
        # comments and import lines are stripped first, so a comment mentioning
        # ``model.fit(...)`` or an import naming a library never grades a
        # non-Python block as an implementation body.
        executable = _JS_LINE_COMMENT_RE.sub("", _JS_BLOCK_COMMENT_RE.sub("", snippet))
        executable = _strip_import_lines(_LINE_COMMENT_RE.sub("", executable))
        if _IMPL_SIGNAL_RE.search(executable):
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
