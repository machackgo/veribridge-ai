"""Canonical GitHub skill-evidence extractor (single source of truth).

Both the **VBR Project Report** (``vbr_student_report``) and the **Work Passport
Skill Report** (``student_proof_vault_service``) used to filter the GitHub Proof
analyzer's stored ``analysis_snapshot.skill_code_evidence`` independently. The
Skill Report's copy did *no* weak-line filtering and accepted the first evidence
per skill, so it surfaced import-only snippets, ``sys.path`` setup, package /
README / metadata lines, and notebook markdown/prose as if they were strong
line-level skill proof.

This module is the one place that knows how to turn a stored
``github_proof_submissions`` row into safe, *strength-ranked* skill evidence:

* it extracts only the safe subset of each ``skill_code_evidence`` item
  (repo-relative path, integer line range, function/class/endpoint symbol, a
  bounded score-scrubbed snippet, a validated hex commit SHA);
* it classifies each item ``strong`` / ``medium`` / ``weak`` (imports, sys.path
  bootstrap, package/README/metadata, comment-only, notebook markdown/prose are
  ``weak`` and are NEVER shown as primary line proof);
* it ranks strong evidence above weak, and reports the skills whose ONLY stored
  line evidence is weak so callers can fall back to an honest repo-level card;
* it builds a safe GitHub line URL (preferring the pinned commit SHA, else the
  default branch) and never fabricates line numbers or links to random lines;
* it never exposes the raw ``analysis_snapshot`` or any private field.

It imports only ``safe_public_url`` + ``skill_normalization`` + stdlib, so the
report/vault services can both depend on it without a cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services.github_python_evidence_focus import (
    GRADE_REPO_LEVEL_FALLBACK,
    grade_evidence,
    grade_rank,
    is_strong_grade,
)
from app.services.safe_public_url import is_safe_public_url, safe_repo_relative_path
from app.services.skill_normalization import canonical_skill

__all__ = [
    "GitHubSkillEvidenceItem",
    "GitHubSkillEvidenceResult",
    "extract_github_skill_evidence",
    "classify_evidence_strength",
    "is_strong_code_snippet",
    "is_ml_skill",
    "is_github_evidence_related_to_skill",
    "ml_pipeline_rank",
    "implementation_quality_rank",
    "skill_profile",
    "focus_snippet_on_implementation",
    "evidence_quality_grade",
    "safe_code_snippet",
    "safe_commit_sha",
    "build_github_line_url",
]


def evidence_quality_grade(
    skill: str | None,
    file_path: str | None,
    code_snippet: str | None,
    symbol_name: str | None = None,
    evidence_kind: str | None = None,
    mapping_reason: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Deterministic ``evidence_quality_grade`` for one GitHub evidence row.

    Prefers the source snippet (graded structurally via the Python AST focus
    module); when no snippet is available it falls back to conservative metadata
    grading from the analyzer's reason / evidence kind — imports / docstrings /
    constants / bare route decorators are NEVER upgraded to an implementation
    body without a body to back them. See
    :mod:`app.services.github_python_evidence_focus`.
    """
    return grade_evidence(
        file_path=file_path,
        code_snippet=code_snippet,
        selection_reason=mapping_reason,
        evidence_kind=evidence_kind,
        line_start=line_start,
        line_end=line_end,
    )

GITHUB_PROOFS_TABLE = "github_proof_submissions"


# ── normalization ─────────────────────────────────────────────────────────────


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


# ── safe snippet / commit helpers ─────────────────────────────────────────────

_SCORE_PHRASE_RE = re.compile(r"\s+with\s+\d{1,3}\s*/\s*100\s+confidence\b", re.IGNORECASE)
_SCORE_FRAGMENT_RE = re.compile(r"\b\d{1,3}\s*/\s*100\b|\b\d{1,3}\s*%\b|\bconfidence\b", re.IGNORECASE)


def _scrub_score_fragments(value: str) -> str:
    """Remove score-like fragments from a snippet/summary."""
    scrubbed = _SCORE_PHRASE_RE.sub("", value or "")
    scrubbed = _SCORE_FRAGMENT_RE.sub("", scrubbed)
    scrubbed = re.sub(r"\s{2,}", " ", scrubbed)
    scrubbed = re.sub(r"\s+([.,;:])", r"\1", scrubbed)
    return scrubbed.strip()


def safe_code_snippet(value: str, limit: int = 280) -> str | None:
    """Bound + score-scrub a code snippet read from a public GitHub file.

    Code snippets are only ever produced for *public* repositories (the analyzer
    fetches file content through the public GitHub raw endpoint), so a snippet
    never exposes private source. We still bound and scrub it.
    """
    collapsed = (value or "").strip("\n")
    if not collapsed.strip():
        return None
    scrubbed = _scrub_score_fragments(collapsed)
    if len(scrubbed) <= limit:
        return scrubbed
    return scrubbed[: limit - 1].rstrip() + "…"


_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def safe_commit_sha(value: Any) -> str | None:
    """Return a bounded, hex-only commit SHA, or ``None``.

    A commit hash is a safe, recruiter-readable reference (no path/url/content),
    but we validate it is a plain hex SHA so no arbitrary string rides through.
    """
    sha = str(value or "").strip()
    if not sha or not _COMMIT_SHA_RE.match(sha):
        return None
    return sha.lower()


# ── strength classification ───────────────────────────────────────────────────
#
# The GitHub Proof analyzer sometimes pins ``skill_code_evidence`` to lines that
# are NOT meaningful skill proof — bare ``import`` lines, ``sys.path``/repo-root
# bootstrap, package/setup/README/metadata, comment-only blocks, or (for
# notebooks) raw markdown narrative cells. Surfacing those as "line-level skill
# proof" overstates the evidence. We classify each stored snippet and only
# promote genuinely strong/medium code to a line-level trace; weak snippets fall
# back to an honest repo-level card. We never invent line proof — this only
# filters/downgrades what the analyzer already stored.

_IMPORT_LINE_RE = re.compile(r"^\s*(?:import\s+\w|from\s+[\w.]+\s+import\b)", re.IGNORECASE)
_COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//|/\*|\*|\"\"\"|''')")
# Repo-root / sys.path / environment bootstrap lines — plumbing, not skill proof.
_SETUP_LINE_RE = re.compile(
    r"sys\.path|__file__|os\.environ|load_dotenv|dotenv|PYTHONPATH|"
    r"repo[\s_-]*root|Path\(__file__\)",
    re.IGNORECASE,
)
# Package list / metadata / requirements — never line-level skill proof.
_METADATA_LINE_RE = re.compile(
    r"^\s*[\w\-]+\s*[=<>~!]{1,2}\s*[\d.]|"  # requirements.txt pin (foo==1.2)
    r"\b(?:install_requires|setup\(|name\s*=|version\s*=|author\s*=|description\s*=)",
    re.IGNORECASE,
)
# Substantive code signals: functions/classes/routes, ML fit/predict/train,
# model construction, SQL, and common JS/React handlers.
_STRONG_CODE_SIGNAL_RE = re.compile(
    r"\bdef\b|\bclass\b|\breturn\b|\bawait\b|\byield\b"
    r"|@(?:app|router|api|bp|blueprint)\b|@\w+\.(?:get|post|put|delete|patch|route)"
    r"|\.(?:fit|predict|predict_proba|transform|fit_transform|train|forward|score|"
    r"evaluate|compile|cluster|classify|detect|render|query|execute)\s*\("
    r"|\b(?:model|clf|net|pipeline|regressor|classifier|estimator|df|dataset)\s*="
    r"|\bSELECT\b|\bINSERT\s+INTO\b|\bUPDATE\b|\bCREATE\s+TABLE\b"
    r"|=>|\bfunction\b|\b(?:useState|useEffect|useMemo|useCallback|useRef)\b",
    re.IGNORECASE,
)
# Markdown / prose markers — a notebook markdown cell is narrative, not code.
_MARKDOWN_MARKER_RE = re.compile(r"\*\*|^#{1,6}\s|^\s*[-*]\s|https?://|\bcase studies\b", re.IGNORECASE)
# A bare line that "looks like code": has a call, an assignment, or ends a block.
_CODE_SHAPE_RE = re.compile(r"\w+\s*\(|[^=!<>]=[^=]|:\s*$|;\s*$|=>")

# Function/class/endpoint detectors (for evidence_kind + symbol extraction).
_DEF_RE = re.compile(r"\bdef\s+(\w+)\s*\(")
_CLASS_RE = re.compile(r"\bclass\s+(\w+)\b")
_ENDPOINT_DECORATOR_RE = re.compile(
    r"@(?:app|router|api|bp|blueprint)\.(?:get|post|put|delete|patch|route)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Config / deployment / test / notebook files: real code here is "medium" — a
# clear skill relation, but not the core function/endpoint/model implementation.
_MEDIUM_CONTEXT_RE = re.compile(
    r"(?:^|/)(?:test_|tests?/|conftest|"
    r"dockerfile|docker-compose|\.ya?ml$|\.tf$|\.toml$|\.cfg$|\.ini$|"
    r"deploy|ci|workflow|\.github/)",
    re.IGNORECASE,
)


def _looks_like_code_line(line: str) -> bool:
    return bool(_CODE_SHAPE_RE.search(line))


def is_strong_code_snippet(file_path: str, code_snippet: str, function_name: str | None) -> bool:
    """True only when a stored ``skill_code_evidence`` snippet is genuine,
    line-level skill proof (not imports/setup/comments/markdown narrative).

    The analyzer pinning an actual ``function_name`` is always treated as strong.
    (Identical to the original VBR report classifier — moved here as the shared
    source of truth so both surfaces downgrade weak evidence the same way.)
    """
    if function_name:
        return True
    snippet = (code_snippet or "").strip()
    if not snippet:
        return False

    is_notebook = file_path.lower().endswith(".ipynb")
    if is_notebook and _MARKDOWN_MARKER_RE.search(snippet):
        # Raw .ipynb markdown cell source — narrative, not executed code.
        return False

    lines = [ln.strip() for ln in snippet.splitlines() if ln.strip()]
    if not lines:
        return False

    # Strip imports, comments, bootstrap/setup plumbing, and package/metadata —
    # none of these are skill proof on their own.
    substantive = [
        ln
        for ln in lines
        if not _IMPORT_LINE_RE.match(ln)
        and not _COMMENT_LINE_RE.match(ln)
        and not _SETUP_LINE_RE.search(ln)
        and not _METADATA_LINE_RE.search(ln)
    ]
    if not substantive:
        return False

    full = "\n".join(lines)
    if _STRONG_CODE_SIGNAL_RE.search(full):
        return True

    # Otherwise require at least one substantive line that actually looks like
    # code (a call/assignment/block) rather than prose stripped from a notebook.
    return any(_looks_like_code_line(ln) for ln in substantive)


def classify_evidence_strength(
    file_path: str, code_snippet: str, function_name: str | None
) -> str:
    """Classify a stored snippet ``"strong"`` / ``"medium"`` / ``"weak"``.

    ``weak`` is exactly ``not is_strong_code_snippet(...)`` (so VBR's existing
    strong-vs-weak gate is preserved byte-for-byte). Among non-weak evidence,
    code that lives in a config/deployment/test/notebook file (a clear but
    supporting skill relation) is ``medium``; core function/class/endpoint/model
    code is ``strong``. Both ``strong`` and ``medium`` are displayable line
    proof; only ``weak`` is downgraded to a repo-level limitation.
    """
    if not is_strong_code_snippet(file_path, code_snippet, function_name):
        return "weak"
    lower_path = (file_path or "").lower()
    if lower_path.endswith(".ipynb") or _MEDIUM_CONTEXT_RE.search(lower_path):
        return "medium"
    return "strong"


# ── ML pipeline relevance (skill-aware ranking tie-breaker) ───────────────────
#
# For Machine-Learning-style skills the analyzer may pin several genuine code
# locations; not all are equally meaningful as ML proof. A line showing a real
# pipeline stage — training, preprocessing / feature engineering, model
# definition, prediction / inference, evaluation metrics, or dataset loading —
# is a far stronger ML signal than a generic helper line. We rank ML-pipeline
# code ABOVE generic lines *for ML skills only*; every non-ML skill returns the
# neutral rank ``0`` so the existing strong→weak ordering is preserved exactly.

_ML_SKILL_RE = re.compile(
    r"machine\s*learning|deep\s*learning|\bml\b|\bai\b|artificial\s*intelligence"
    r"|data\s*science|neural\s*network|\bnlp\b|natural\s*language|computer\s*vision"
    r"|tensorflow|pytorch|keras|scikit|sklearn",
    re.IGNORECASE,
)
_ML_PIPELINE_SIGNAL_RE = re.compile(
    # training pipeline
    r"\.fit(?:_transform)?\s*\(|model\.fit|\btrain(?:ing|_model|_loop)?\b|\bepochs?\b|\bbatch_size\b"
    # preprocessing / feature engineering
    r"|train_test_split|StandardScaler|MinMaxScaler|OneHotEncoder|LabelEncoder|fit_transform"
    r"|CountVectorizer|TfidfVectorizer|tokeniz|\bpreprocess|feature_|\.transform\s*\("
    # model definition
    r"|\bSequential\b|nn\.Module|\bkeras\b|\btorch\b|RandomForest|XGB|LogisticRegression|\bSVC\b"
    r"|GradientBoosting|DecisionTree|KMeans|build_model|def\s+build_model"
    # prediction / inference endpoint
    r"|\.predict(?:_proba)?\s*\(|def\s+predict|/predict|def\s+infer|\binference\b"
    # evaluation metrics
    r"|accuracy_score|f1_score|precision_score|recall_score|roc_auc|\bauc\b|confusion_matrix"
    r"|classification_report|mean_squared_error|r2_score|\.evaluate\s*\(|\.score\s*\("
    # dataset / data loading
    r"|read_csv|load_data|load_dataset|DataLoader|\bDataset\b|np\.load|\.npy\b",
    re.IGNORECASE,
)


def ml_pipeline_rank(
    skill: str, file_path: str | None, code_snippet: str | None, symbol_name: str | None
) -> int:
    """Skill-aware ML evidence ranking tie-breaker (lower = preferred).

    Returns ``0`` for any non-ML skill (neutral — other skills are unaffected).
    For an ML-style skill, returns ``0`` when the file/snippet/symbol shows a
    real ML pipeline stage (training, preprocessing, model definition, predict /
    inference, evaluation metrics, dataset loading) and ``1`` for a generic line,
    so meaningful ML code is preferred and weak generic helpers rank lower.
    """
    if not _ML_SKILL_RE.search(skill or ""):
        return 0
    haystack = " ".join(p for p in (file_path or "", code_snippet or "", symbol_name or "") if p)
    return 0 if _ML_PIPELINE_SIGNAL_RE.search(haystack) else 1


# ── deterministic implementation-quality scoring (all skills) ─────────────────
#
# ``ml_pipeline_rank`` only re-orders ML skills. The same recruiter-trust problem
# exists for EVERY skill: the analyzer can pin a row to a comment/constant/import/
# config/boilerplate line that merely *mentions* the skill rather than to the
# function/handler/component logic that actually demonstrates it. This layer is a
# generalized, deterministic (no-LLM) quality ranker. For each row it computes a
# band — lower = stronger — that the extractor uses as a tie-breaker AFTER the
# strong/medium/weak strength tier, so genuine implementation logic floats to the
# top and weak/boilerplate code sinks into the "+N more" overflow.
#
#   band 0  skill-profile "highest" implementation logic (e.g. ML train/predict,
#           an API route handler with a service/db call, React state/handler).
#   band 1  generic strong implementation logic — control flow / data ops / a db
#           query / an event handler — meaningful for any skill.
#   band 2  neutral code (a def/class without a notable logic signal).
#   band 3  skill-profile "lower" boilerplate (bare wrapper, static health route,
#           layout-only markup, config constant) OR an all-boilerplate snippet
#           (imports / constants / config / comments / logging only).

# Generic, skill-agnostic "real body logic" signals: control flow, data
# transforms, data-access calls, async/await, common mutation/query verbs.
_GENERAL_IMPL_SIGNAL_RE = re.compile(
    r"\bif\b|\belif\b|\belse\b|\bfor\b|\bwhile\b|\btry\b|\bexcept\b|\bcatch\b|\bmatch\b|\bswitch\b"
    r"|\breturn\s+\S|\braise\b|\bthrow\b|\bawait\b|\byield\b|\basync\b"
    r"|\.(?:map|filter|reduce|forEach|sort|append|extend|update|join|split|replace|format|"
    r"query|execute|fetchone|fetchall|fetch|save|create|delete|insert|commit|add|get|post|put)\s*\("
    r"|=>|\.then\s*\(|\bawait\b"
    r"|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\s+FROM\b|\bdb\.|\.objects\.|session\.",
    re.IGNORECASE,
)
# A line that is, on its own, only plumbing: import / constant / comment / type
# declaration / logging / a re-export. Used to detect all-boilerplate snippets.
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*(?:export\s+(?:const|default|\{)|module\.exports|const\s+\w+\s*=\s*require)"
    r"|^\s*[A-Z][A-Z0-9_]{2,}\s*[:=]"  # CONSTANT = ... / CONSTANT: ...
    r"|^\s*\w+\s*[:=]\s*(?:str|int|float|bool|bytes|number|string|boolean|"
    r"List|Dict|Tuple|Set|Optional|Any|Sequence|Mapping)\b\s*[#;]?\s*$"  # type-only decl
    r"|^\s*(?:logger|logging|console)\.\w+\s*\(",  # logging only
    re.IGNORECASE,
)


# Trailing ``# …`` / ``// …`` comment (whitespace-anchored so a ``//`` inside a
# URL like ``https://…`` is not mistaken for a comment).
_TRAILING_COMMENT_RE = re.compile(r"\s+(?:#|//).*$")


def _code_for_matching(code: str) -> str:
    """Strip whole comment lines and trailing comments so prose words inside a
    comment (``# loop for each model``) never trigger a code-logic signal."""
    out: list[str] = []
    for ln in (code or "").splitlines():
        if _COMMENT_LINE_RE.match(ln):
            continue
        out.append(_TRAILING_COMMENT_RE.sub("", ln))
    return "\n".join(out)


def _is_boilerplate_only(code: str) -> bool:
    """True when EVERY non-blank line of ``code`` is plumbing (import / constant /
    comment / setup / metadata / type-decl / logging) — i.e. nothing in the
    snippet is substantive implementation logic."""
    lines = [ln.strip() for ln in (code or "").splitlines() if ln.strip()]
    if not lines:
        return False
    for ln in lines:
        if (
            _IMPORT_LINE_RE.match(ln)
            or _COMMENT_LINE_RE.match(ln)
            or _SETUP_LINE_RE.search(ln)
            or _METADATA_LINE_RE.search(ln)
            or _BOILERPLATE_LINE_RE.search(ln)
        ):
            continue
        return False  # a substantive (non-boilerplate) line exists
    return True


# Machine-Learning Engineering — model serving / retraining / artifacts / feature
# pipelines / deployment tied to inference / monitoring / batch prediction.
_MLE_SKILL_RE = re.compile(
    r"machine[\s_-]*learning[\s_-]*engineer|\bmlops\b|\bml[\s_-]*ops\b|\bmle\b"
    r"|model[\s_-]*(?:serv|deploy|ops)",
    re.IGNORECASE,
)
_MLE_HIGH_RE = re.compile(
    r"model[\s_.]*(?:serv|deploy|load|save|registry|artifact|version)"
    r"|joblib\.(?:load|dump)|pickle\.(?:load|dump)|torch\.(?:load|save)|\.pkl\b|\.joblib\b|\.h5\b"
    r"|\bretrain\b|pipeline[\s_-]*retrain|feature[\s_-]*(?:store|pipeline)"
    r"|batch[\s_-]*(?:predict|inference)|\.predict(?:_proba)?\s*\(|\binference\b"
    r"|vertex|sagemaker|mlflow|bentoml|seldon|triton|\bserve\b|monitor",
    re.IGNORECASE,
)
_MLE_LOW_RE = re.compile(
    r"^\s*[A-Z_]+\s*[:=]|environment:|env:|\bversion:\s*[\d\"']|FROM\s+python|apt-get|pip\s+install",
    re.IGNORECASE,
)

# API Development — route handlers with validation / service / db / error / auth.
_API_SKILL_RE = re.compile(
    r"api[\s_-]*develop|backend|\brest\b|graphql|fastapi|flask|django|express|nestjs"
    r"|web[\s_-]*service|micro[\s_-]*service|server[\s_-]*side",
    re.IGNORECASE,
)
# A bare route decorator is NOT "highest" on its own (that is a "lower" signal —
# see ``_API_LOW_RE``); the request validation / service-or-db call / error
# handling / auth that lives in the handler body is what makes a route strong.
_API_HIGH_RE = re.compile(
    r"\.(?:query|execute|fetchone|fetchall|commit|filter|get_or_404|first|all|scalar)\s*\("
    r"|validate|serializ|pydantic|BaseModel|marshmallow|request\.(?:json|args|form|get_json)"
    r"|raise\s+HTTPException|abort\s*\(|status_code|JSONResponse|jsonify|res\.status"
    r"|current_user|require_auth|permission|authorize|Depends\s*\(",
    re.IGNORECASE,
)
_API_LOW_RE = re.compile(
    r"\b(?:Flask|FastAPI)\s*\(|create_app|add_middleware|register_blueprint|\.run\s*\("
    r"|if\s+__name__|app\.listen|/health|/ping|/healthz|healthcheck|def\s+health\b",
    re.IGNORECASE,
)

# React / frontend — state / effects / handlers / conditional render / data calls.
_REACT_SKILL_RE = re.compile(
    r"\breact\b|\bnext\.?js\b|front[\s_-]*end|\bvue\b|\bangular\b|\bsvelte\b|\bjsx\b|\btsx\b",
    re.IGNORECASE,
)
_REACT_HIGH_RE = re.compile(
    r"\buse(?:State|Effect|Memo|Callback|Ref|Reducer|Context)\b"
    r"|on(?:Click|Change|Submit|Input|Blur|KeyDown)\b|handle[A-Z]\w*|set[A-Z]\w*\s*\("
    r"|dispatch\s*\(|fetch\s*\(|axios|useQuery|useMutation|useSWR"
    r"|\?\s*\(?\s*<|&&\s*<|\.map\s*\(\s*\(?\w|\bprops\.",
    re.IGNORECASE,
)
_REACT_LOW_RE = re.compile(
    r"return\s*\(\s*<(?:div|section|footer|header|nav|main|span|p)\b[^>]*>\s*$"
    r"|^\s*<(?:div|section|footer|header|nav|main)\b|className\s*=\s*[\"'{]"
    r"|StyleSheet\.create|styled\.\w+|\.css\b|\.scss\b",
    re.IGNORECASE,
)

# Security / Auth — permission / RLS / token / access branching / consent / paths.
_SECURITY_SKILL_RE = re.compile(
    r"security|auth(?:enticat|oriz|n\b|z\b)|\brls\b|access[\s_-]*control|permission"
    r"|\boauth\b|\bjwt\b|encrypt|privacy|consent|\brbac\b",
    re.IGNORECASE,
)
_SECURITY_HIGH_RE = re.compile(
    r"permission|authoriz|authenticat|\brls\b|\bpolicy\b|verify[_\s]*token|decode.*(?:jwt|token)"
    r"|check[_\s]*(?:access|permission|auth)|require_\w+|\bconsent\b|sanitiz|is_safe|escape"
    r"|bcrypt|hashed?[_\s]*password|hmac|secrets\.compare|constant_time"
    r"|if\s+not\s+(?:user|current_user|token|authorized|allowed|request\.user)"
    r"|raise\s+(?:Permission|Forbidden|Unauthorized|HTTPException)",
    re.IGNORECASE,
)
_SECURITY_LOW_RE = re.compile(
    r"SECRET_KEY|ALGORITHM\s*[:=]|AUTH_\w+\s*[:=]|TOKEN_\w+\s*[:=]|os\.environ|getenv|settings\.",
    re.IGNORECASE,
)

# Cloud / DevOps — deployment / CI-CD steps / infra defs / container build/runtime.
_DEVOPS_SKILL_RE = re.compile(
    r"devops|cloud|ci[\s_/-]*cd|infrastructure|kubernetes|\bk8s\b|\bdocker\b|terraform"
    r"|deployment|\bsre\b|platform[\s_-]*engineer",
    re.IGNORECASE,
)
_DEVOPS_HIGH_RE = re.compile(
    r"^\s*(?:steps|jobs|stages):|runs-on:|\buses:|\brun:\s*\S|deploy\b|kubectl|\bhelm\b"
    r"|resource\s+\"|FROM\s+\w|RUN\s+\S|CMD\s+|ENTRYPOINT|docker\s+(?:build|run|push)"
    r"|gcloud\s+\w|aws\s+\w|\baz\s+\w|apiVersion:|kind:\s*(?:Deployment|Service|Job|CronJob)",
    re.IGNORECASE,
)
_DEVOPS_LOW_RE = re.compile(
    r"^\s*[A-Z_]{2,}\s*[:=]|environment:\s*$|^\s*env:\s*$|\bversion:\s*[\d\"']|tags:\s*$",
    re.IGNORECASE,
)

# Profile → (highest-signal regex, lower/boilerplate-signal regex). The ML profile
# reuses ``_ML_PIPELINE_SIGNAL_RE`` (training / preprocessing / model / inference /
# metrics / dataset) as its "highest" so ``ml_pipeline_rank`` and this layer agree.
_ML_LOW_RE = re.compile(
    r"upload_blob|download_blob|storage\.bucket|\bgcs\b|boto3|blob\.upload"
    r"|@(?:app|router)\.(?:get|post)\(\s*[\"']/(?:health|ping|status)"
    r"|^\s*[A-Z_]{2,}\s*[:=]",
    re.IGNORECASE,
)
_PROFILE_SIGNALS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "mle": (_MLE_HIGH_RE, _MLE_LOW_RE),
    "ml": (_ML_PIPELINE_SIGNAL_RE, _ML_LOW_RE),
    "security": (_SECURITY_HIGH_RE, _SECURITY_LOW_RE),
    "devops": (_DEVOPS_HIGH_RE, _DEVOPS_LOW_RE),
    "react": (_REACT_HIGH_RE, _REACT_LOW_RE),
    "api": (_API_HIGH_RE, _API_LOW_RE),
}


def skill_profile(skill: str | None) -> str:
    """Map a skill name to one evidence-ranking profile, or ``""`` for none.

    Order is significant: the more specific Machine-Learning-Engineering profile
    is checked before plain Machine Learning, and Security/DevOps before the
    broader React/API families, so an overlapping name lands on its strongest
    profile. A skill with no profile is ranked purely on generic implementation
    signals (so it is never penalised for lacking a profile).
    """
    s = skill or ""
    if _MLE_SKILL_RE.search(s):
        return "mle"
    if _ML_SKILL_RE.search(s):
        return "ml"
    if _SECURITY_SKILL_RE.search(s):
        return "security"
    if _DEVOPS_SKILL_RE.search(s):
        return "devops"
    if _REACT_SKILL_RE.search(s):
        return "react"
    if _API_SKILL_RE.search(s):
        return "api"
    return ""


def implementation_quality_rank(
    skill: str,
    file_path: str | None,
    code_snippet: str | None,
    symbol_name: str | None,
    evidence_kind: str | None = None,
    mapping_reason: str | None = None,
) -> int:
    """Deterministic implementation-quality band (lower = stronger) for a row.

    Used by the extractor as a tie-breaker AFTER the strong/medium/weak strength
    tier, so meaningful implementation logic ranks above weak/boilerplate code for
    EVERY skill (not just ML). No LLM calls; purely regex/structural. See the
    band reference in the section header above.
    """
    code = code_snippet or ""

    # band 3 (short-circuit) — an all-boilerplate snippet (only imports / constants
    # / config / comments / logging) is never real implementation proof, even when
    # it name-drops a profile keyword (e.g. ``import torch`` or ``MODEL_PATH=…``).
    if code and _is_boilerplate_only(code):
        return 3

    # Match against the code with comments stripped (so prose words in a comment
    # never trigger a code-logic signal) plus the structured location/reason.
    match_code = _code_for_matching(code)
    location = " ".join(
        p for p in (file_path or "", symbol_name or "", evidence_kind or "", mapping_reason or "") if p
    )
    hay = f"{location}\n{match_code}"

    profile = skill_profile(skill)
    high, low = _PROFILE_SIGNALS.get(profile, (None, None))

    # band 0 — skill-profile "highest" implementation logic.
    if high is not None and high.search(hay):
        return 0
    # band 1 — generic strong implementation logic, good for any skill.
    if _GENERAL_IMPL_SIGNAL_RE.search(hay) or _STRONG_CODE_SIGNAL_RE.search(hay):
        return 1
    # band 3 — skill-profile "lower" boilerplate (bare wrapper / static health /
    # layout-only markup / config constant).
    if low is not None and low.search(hay):
        return 3
    # band 2 — neutral code (a def/class without a notable logic signal).
    return 2


# ── snippet focusing: trim leading non-implementation lines ───────────────────
#
# A strong snippet sometimes leads with a comment/docstring/import/setup line
# before the real function body. Surfacing the comment first reads as weak proof.
# We trim ONLY the leading plumbing lines and advance ``line_start`` by exactly
# that many lines — never fabricating a line number (the new start stays inside
# the analyzer's stored range) and never touching trailing lines or the body.


def focus_snippet_on_implementation(
    snippet: str | None, line_start: int | None, line_end: int | None
) -> tuple[str | None, int | None]:
    """Drop leading comment/import/setup/metadata/blank lines from a strong
    snippet so it opens on real implementation code, advancing ``line_start`` to
    match. Returns the input unchanged when there is nothing safe to trim (no
    leading plumbing, the whole snippet is plumbing, or advancing would pass
    ``line_end``)."""
    if not snippet:
        return snippet, line_start
    raw_lines = snippet.splitlines()
    skip = 0
    for ln in raw_lines:
        s = ln.strip()
        if not s or (
            _IMPORT_LINE_RE.match(s)
            or _COMMENT_LINE_RE.match(s)
            or _SETUP_LINE_RE.search(s)
            or _METADATA_LINE_RE.search(s)
        ):
            skip += 1
            continue
        break
    if skip <= 0 or skip >= len(raw_lines):
        return snippet, line_start
    # Never advance past the stored end of the range — keep line numbers honest.
    if isinstance(line_start, int) and line_start > 0:
        if isinstance(line_end, int) and line_start + skip > line_end:
            return snippet, line_start
        new_start = line_start + skip
    else:
        new_start = line_start
    return "\n".join(raw_lines[skip:]), new_start


# ── conservative GitHub evidence skill-relation (connected reports only) ───────
#
# A connected Machine-Learning project's GitHub evidence is often spread across
# canonical rows the analyzer tagged with an *adjacent* skill — ``Python`` or
# ``Machine Learning Engineering`` — rather than ``Machine Learning`` exactly
# (e.g. ``src/model/train.py`` model instantiation, ``serving/main.py``
# prediction, ``scripts/pipeline_retrain.py`` training, tagged ``Python``). Exact
# canonical-skill matching drops those, so a connected ML report can show a single
# row even when the same repo holds many genuine ML-pipeline rows. This helper is
# a *narrow* relation gate: from the SAME confirmed owner/repo/project context, it
# admits an adjacent-tagged row into the ML report ONLY when the row carries
# ML-specific structured evidence — never a generic Python helper/import/setup
# line, and never any non-ML target skill (which always returns ``False``).

# Natural-language ML-pipeline reasons (canonical ``selection_reason`` text such
# as "model instantiation", "evaluation metrics", "prediction/inference",
# "pipeline retrain") plus ML library / file markers. Complements the code-token
# ``_ML_PIPELINE_SIGNAL_RE`` above which matches actual code lines.
_ML_EVIDENCE_REASON_RE = re.compile(
    r"train(?:ing|ed|_model|_loop|s)?\b|preprocess|feature[\s_-]*(?:engineer|extract|select)"
    r"|model[\s_-]*(?:defin|instanti|construct|architect|build|train|deploy|serv|inference)"
    r"|\bpredict\b|prediction|\binfer(?:ence|ring)?\b|evaluat|\bmetric|accuracy|\bf1\b|precision"
    r"|recall|\bauc\b|\broc\b|confusion[\s_-]*matrix|classif|regress|cluster|\bdataset\b"
    r"|data[\s_-]*load|pipeline[\s_-]*retrain|\bretrain|hyperparameter|cross[\s_-]*validat"
    r"|\bepoch|loss[\s_-]*function|vertex[\s_-]*deploy|model[\s_-]*serving|model[\s_-]*deployment"
    r"|\bsklearn\b|scikit|tensorflow|pytorch|keras|\bxgboost\b|\bneural\b|embedding|inference",
    re.IGNORECASE,
)
# Generic plumbing markers — an import/setup/config/helper/logging/constant line
# is NEVER ML proof on its own, even if it lives near ML code.
_GENERIC_EVIDENCE_RE = re.compile(
    r"\bimport\b|^\s*from\s+[\w.]+\s+import\b|sys\.path|\bsetup\b|\bconfig\b|\bsettings\b"
    r"|\bhelper\b|\butil(?:s|ity|ities)?\b|logging|\blogger\b|\bconstant|boilerplate|scaffold"
    r"|\breadme\b|requirement|dependenc|\binstall|getting[\s_-]*started|environment[\s_-]*variable"
    r"|\bgetenv\b|os\.environ",
    re.IGNORECASE,
)


def is_ml_skill(skill: str | None) -> bool:
    """True for an ML-style skill name (Machine Learning, ML, AI, NLP, CV, …).

    The connected GitHub evidence relation layer only ever broadens ML skills, so
    callers gate on this before relating adjacent-tagged rows into a report.
    """
    return bool(_ML_SKILL_RE.search(skill or ""))


def is_github_evidence_related_to_skill(
    target_skill: str,
    *,
    evidence_skill: str,
    file_path: str | None = None,
    code_snippet: str | None = None,
    symbol_name: str | None = None,
    mapping_reason: str | None = None,
    evidence_kind: str | None = None,
) -> bool:
    """Conservative "should this GitHub row count for ``target_skill``?" gate.

    The caller has ALREADY confirmed the row shares the same canonical
    owner/repo/project context as a genuine ``target_skill`` match (so exact
    owner/repo routing is never weakened here). This only decides whether an
    *adjacent-tagged* row is ML-specific enough to be admitted:

    * returns ``False`` for any non-ML ``target_skill`` (no broadening at all);
    * returns ``True`` when the row's own skill is in the ML family (Machine
      Learning OR Machine Learning Engineering / Deep Learning / NLP / …);
    * otherwise (e.g. a ``Python``-tagged row) returns ``True`` ONLY when the
      file/symbol/reason/snippet shows a real ML-pipeline stage (training,
      preprocessing, model definition/instantiation, prediction/inference,
      evaluation/metrics, dataset loading, pipeline retrain, model serving) AND
      the row is not generic plumbing (import/setup/config/helper/logging/
      constant) — unless the code itself contains a genuine ML-pipeline call.
    """
    if not is_ml_skill(target_skill):
        return False
    # Same ML family (Machine Learning, Machine Learning Engineering, Deep
    # Learning, NLP, Computer Vision, …) — a clear, in-family relation.
    if is_ml_skill(evidence_skill):
        return True

    location = " ".join(p for p in (file_path or "", symbol_name or "", evidence_kind or "") if p)
    reason = mapping_reason or ""
    code = code_snippet or ""
    ml_signal = bool(_ML_PIPELINE_SIGNAL_RE.search(f"{location} {code}")) or bool(
        _ML_EVIDENCE_REASON_RE.search(f"{reason} {location}")
    )
    if not ml_signal:
        return False
    # Reject generic plumbing (import/setup/helper/logging/config) unless the code
    # snippet itself is an unambiguous ML-pipeline call (``.fit(``/``.predict(``…).
    if _GENERIC_EVIDENCE_RE.search(f"{location} {reason}") and not _ML_PIPELINE_SIGNAL_RE.search(code):
        return False
    return True


def _evidence_kind(
    file_path: str,
    snippet: str,
    function_name: str | None,
    class_name: str | None,
    endpoint_path: str | None,
    line_start: int | None,
) -> str:
    if endpoint_path:
        return "endpoint"
    if function_name:
        return "function"
    if class_name:
        return "class"
    if line_start:
        return "lines"
    if file_path:
        return "file"
    return "repo"


# ── safe GitHub URL builder ───────────────────────────────────────────────────


def build_github_line_url(
    repo_url: str | None,
    *,
    commit_sha: str | None,
    branch: str | None,
    file_path: str,
    line_start: int | None,
    line_end: int | None,
    public_safe: bool,
) -> str | None:
    """Build ``…/blob/{commit_or_branch}/{file_path}#L{a}-L{b}`` for a public repo.

    Prefers the pinned commit SHA (most precise), else the default branch. Returns
    ``None`` unless the repo URL is a safe public github.com target, so a private
    repo file is never advertised as openable. A ``#L`` anchor is appended ONLY
    when ``line_start`` is a valid positive integer — never a random/invalid line.
    """
    base = str(repo_url or "").rstrip("/")
    if not public_safe or not base or not is_safe_public_url(base) or "github.com" not in base:
        return None
    # Defense-in-depth: never build a blob link from an absolute / local /
    # Windows / file:// path — reject it instead of lstrip("/")-ing it into a
    # fake repo-relative one (callers already sanitize, but this is the gate
    # that actually emits the public URL).
    clean_path = safe_repo_relative_path(file_path)
    if not clean_path:
        return None
    ref = commit_sha or (str(branch or "").strip() or "HEAD")
    url = f"{base}/blob/{ref}/{clean_path}"
    if isinstance(line_start, int) and line_start > 0:
        url += f"#L{line_start}"
        if isinstance(line_end, int) and line_end > line_start:
            url += f"-L{line_end}"
    return url


# ── canonical item / result ───────────────────────────────────────────────────


@dataclass
class GitHubSkillEvidenceItem:
    """One safe, strength-ranked GitHub skill-evidence item."""

    proof_type: str = "github"
    source_id: str = ""
    repo_owner: str | None = None
    repo_name: str | None = None
    repo_url: str | None = None
    project_id: str | None = None
    project_title: str | None = None
    skill_name: str = ""
    canonical_skill_name: str = ""
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    function_name: str | None = None
    class_name: str | None = None
    symbol_name: str | None = None
    endpoint_path: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    code_snippet: str | None = None
    github_url: str | None = None
    evidence_kind: str = "repo"
    evidence_strength: str = "weak"
    evidence_quality_grade: str = GRADE_REPO_LEVEL_FALLBACK
    mapping_reason: str = ""
    limitation: str = ""
    is_attached_to_project: bool = False
    public_safe: bool = False

    @property
    def skill_key(self) -> str:
        return _norm(self.skill_name)

    @property
    def is_line_level(self) -> bool:
        """A displayable (strong/medium) item with a concrete file location."""
        return self.evidence_strength in ("strong", "medium") and bool(self.file_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_type": self.proof_type,
            "source_id": self.source_id,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url if self.public_safe else None,
            "project_id": self.project_id,
            "project_title": self.project_title,
            "skill_name": self.skill_name,
            "canonical_skill_name": self.canonical_skill_name,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "function_name": self.function_name,
            "class_name": self.class_name,
            "symbol_name": self.symbol_name,
            "endpoint_path": self.endpoint_path,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "code_snippet": self.code_snippet,
            "github_url": self.github_url,
            "evidence_kind": self.evidence_kind,
            "evidence_strength": self.evidence_strength,
            "evidence_quality_grade": self.evidence_quality_grade,
            "mapping_reason": self.mapping_reason,
            "limitation": self.limitation,
            "is_attached_to_project": self.is_attached_to_project,
            "public_safe": self.public_safe,
        }


_STRONG_LIMITATION = (
    "Pinpoints skill-relevant code, but matching code at a location is not the same as proving "
    "sole authorship; combine with the Project Defense for ownership context."
)
_WEAK_LIMITATION = (
    "Stored GitHub line evidence for this skill is only imports/setup/metadata or notebook "
    "narrative — not strong line-level proof; shown as repo-level support pending reanalysis."
)
_REPO_LIMITATION = (
    "Repository-level evidence supports this skill but is not, by itself, line-level proof that "
    "the candidate personally authored every part."
)


@dataclass
class GitHubSkillEvidenceResult:
    """The canonical, strength-ranked GitHub evidence for one proof row."""

    source_id: str = ""
    repo_owner: str | None = None
    repo_name: str | None = None
    repo_url: str | None = None
    branch: str | None = None
    public_safe: bool = False
    summary: str = ""
    detected_skills: list[str] = field(default_factory=list)
    # Every extracted item (strong, medium AND weak), ranked strong→weak.
    items: list[GitHubSkillEvidenceItem] = field(default_factory=list)

    @property
    def repo_full_name(self) -> str:
        if self.repo_owner and self.repo_name:
            return f"{self.repo_owner}/{self.repo_name}"
        return self.repo_url or "GitHub repository"

    @property
    def strong_items(self) -> list[GitHubSkillEvidenceItem]:
        """Displayable (strong/medium) line/function/endpoint items."""
        return [i for i in self.items if i.evidence_strength != "weak"]

    @property
    def weak_items(self) -> list[GitHubSkillEvidenceItem]:
        return [i for i in self.items if i.evidence_strength == "weak"]

    def strong_for_skill(self, skill: str) -> list[GitHubSkillEvidenceItem]:
        key = _norm(skill)
        ckey = _norm(canonical_skill(skill))
        matches = [
            i
            for i in self.strong_items
            if i.skill_key == key or _norm(i.canonical_skill_name) == ckey
        ]
        # When a real implementation body / supporting-logic row exists for this
        # skill, drop weak-grade rows (a docstring / import / constant / bare route
        # decorator the analyzer pinned) so they are never shown as TOP evidence —
        # they may only resurface as repo-level support when nothing stronger
        # exists. Already ordered strongest-first by the extractor's sort.
        if any(is_strong_grade(i.evidence_quality_grade) for i in matches):
            return [i for i in matches if is_strong_grade(i.evidence_quality_grade)]
        return matches

    def best_strong_for_skill(self, skill: str) -> GitHubSkillEvidenceItem | None:
        matches = self.strong_for_skill(skill)
        return matches[0] if matches else None

    @property
    def strong_skill_keys(self) -> set[str]:
        return {i.skill_key for i in self.strong_items}

    @property
    def weak_only_skill_names(self) -> list[str]:
        """Skills whose ONLY stored line evidence is weak (deduped, ordered)."""
        strong = self.strong_skill_keys
        seen: set[str] = set()
        out: list[str] = []
        for i in self.weak_items:
            if i.skill_key in strong or i.skill_key in seen or not i.skill_name.strip():
                continue
            seen.add(i.skill_key)
            out.append(i.skill_name)
        return out


def _line(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        n = int(value)
        return n if n > 0 else None
    return None


def extract_github_skill_evidence(
    github_row: Mapping[str, Any] | None,
    *,
    requested_skill: str | None = None,
) -> GitHubSkillEvidenceResult:
    """Turn a ``github_proof_submissions`` row into safe, strength-ranked evidence.

    ``requested_skill`` is optional; when supplied it only refines the per-item
    ``mapping_reason`` text. The result always carries *all* extracted items
    (callers filter by skill via :meth:`strong_for_skill` / inspect
    :attr:`weak_only_skill_names`). The raw ``analysis_snapshot`` is never echoed.
    """
    if not isinstance(github_row, Mapping):
        return GitHubSkillEvidenceResult()

    source_id = str(github_row.get("id") or "")
    owner = github_row.get("repo_owner")
    name = github_row.get("repo_name")
    repo_url = str(github_row.get("repo_url") or "") or None
    branch = str(github_row.get("default_branch") or "main")
    is_public = _norm(str(github_row.get("visibility") or "")) == "public"
    public_safe = bool(is_public and repo_url and is_safe_public_url(repo_url))
    summary = _scrub_score_fragments(str(github_row.get("public_safe_summary") or "")) or (
        "Repository analyzed; VeriBridge detected the skills below from its files and structure."
    )
    detected = [str(s) for s in (github_row.get("detected_skills") or []) if str(s).strip()]

    snapshot = github_row.get("analysis_snapshot")
    raw_items = snapshot.get("skill_code_evidence") if isinstance(snapshot, dict) else None
    requested_key = _norm(canonical_skill(requested_skill)) if requested_skill else None

    items: list[GitHubSkillEvidenceItem] = []
    seen: set[tuple[str, str, Any, Any]] = set()
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            skill = str(raw.get("skill") or "").strip()
            # Reject absolute / local / Windows / UNC / file:// / traversal
            # paths outright — never lstrip("/") an absolute path into a fake
            # repo-relative one (would leak a private filesystem location).
            file_path = safe_repo_relative_path(raw.get("file_path"))
            if not skill or not file_path:
                continue

            line_start = _line(raw.get("line_start"))
            line_end = _line(raw.get("line_end"))
            function_name = str(raw.get("function_name") or "").strip() or None
            raw_snippet = str(raw.get("code_snippet") or "")

            key = (_norm(skill), file_path, line_start, line_end)
            if key in seen:
                continue
            seen.add(key)

            strength = classify_evidence_strength(file_path, raw_snippet, function_name)
            commit_sha = safe_commit_sha(raw.get("commit_sha"))

            # Derive function/class/endpoint symbols from the snippet (never guessed
            # beyond what the analyzer actually stored as code).
            class_name = None
            endpoint_path = None
            if strength != "weak":
                if not function_name:
                    m = _DEF_RE.search(raw_snippet)
                    if m:
                        function_name = m.group(1)
                cm = _CLASS_RE.search(raw_snippet)
                if cm:
                    class_name = cm.group(1)
                em = _ENDPOINT_DECORATOR_RE.search(raw_snippet)
                if em:
                    endpoint_path = em.group(1)
            symbol_name = function_name or class_name or endpoint_path

            # Focus a displayable snippet onto its real implementation body: drop
            # leading comment/import/setup lines and advance line_start to match,
            # so the row opens on actual code, not a docstring/import. Weak rows
            # are never displayed, so only strong/medium snippets are focused; the
            # advanced start stays inside the analyzer's stored range (never faked).
            display_snippet = raw_snippet
            display_line_start = line_start
            if strength != "weak":
                display_snippet, display_line_start = focus_snippet_on_implementation(
                    raw_snippet, line_start, line_end
                )

            # A line URL is only ever built for displayable (strong/medium)
            # evidence — never for a weak import/setup/markdown line, which would
            # link a recruiter to a meaningless line. Prefer the analyzer's own
            # ``…#L`` link when it is a safe public github.com URL; else build one
            # (commit SHA preferred).
            stored_url = str(raw.get("github_url") or "").strip() or None
            if stored_url and (not is_safe_public_url(stored_url) or "github.com" not in stored_url):
                stored_url = None
            github_url = stored_url if (public_safe and strength != "weak") else None
            if public_safe and strength != "weak" and not github_url:
                github_url = build_github_line_url(
                    repo_url,
                    commit_sha=commit_sha,
                    branch=branch,
                    file_path=file_path,
                    line_start=display_line_start,
                    line_end=line_end,
                    public_safe=public_safe,
                )

            evidence_kind = _evidence_kind(
                file_path, raw_snippet, function_name, class_name, endpoint_path, display_line_start
            )

            # Deterministic implementation-quality grade. Computed from the focused
            # display snippet when one exists (the most honest structural signal),
            # else conservatively from evidence kind / location. Grading reads the
            # snippet structurally only — it never exposes snippet content.
            quality_grade = grade_evidence(
                file_path=file_path,
                code_snippet=display_snippet if display_snippet.strip() else raw_snippet,
                selection_reason=None,
                evidence_kind=evidence_kind,
                line_start=display_line_start,
                line_end=line_end,
            )

            mapping_reason = (
                f"Analyzer located {evidence_kind} evidence for {skill} in {file_path}"
                + (f" (lines {display_line_start}"
                   + (f"-{line_end}" if line_end and line_end != display_line_start else "") + ")"
                   if display_line_start else "")
                + "."
            )
            if requested_key and _norm(canonical_skill(skill)) == requested_key:
                mapping_reason = f"Matches requested skill. {mapping_reason}"

            items.append(
                GitHubSkillEvidenceItem(
                    source_id=source_id,
                    repo_owner=str(owner) if owner else None,
                    repo_name=str(name) if name else None,
                    repo_url=repo_url,
                    skill_name=skill,
                    canonical_skill_name=canonical_skill(skill),
                    file_path=file_path,
                    line_start=display_line_start,
                    line_end=line_end,
                    function_name=function_name,
                    class_name=class_name,
                    symbol_name=symbol_name,
                    endpoint_path=endpoint_path,
                    commit_sha=commit_sha,
                    branch=branch,
                    code_snippet=safe_code_snippet(display_snippet) if (public_safe and strength != "weak") else None,
                    github_url=github_url,
                    evidence_kind=evidence_kind,
                    evidence_strength=strength,
                    evidence_quality_grade=quality_grade,
                    mapping_reason=mapping_reason,
                    limitation=_STRONG_LIMITATION if strength != "weak" else _WEAK_LIMITATION,
                    public_safe=public_safe,
                )
            )
            if len(items) >= 60:
                break

    # Rank strong/medium above weak; then by the deterministic
    # ``evidence_quality_grade`` band (implementation_body → supporting_logic →
    # config/constant → route_decorator_only → comment/docstring → import_only →
    # repo fallback) so an exact implementation body always outranks a docstring /
    # import / bare route decorator; then by the skill-profile implementation-
    # quality tie-breaker; finally prefer rows that carry a concrete line.
    _rank = {"strong": 0, "medium": 1, "weak": 2}
    items.sort(
        key=lambda i: (
            _rank.get(i.evidence_strength, 9),
            grade_rank(i.evidence_quality_grade),
            implementation_quality_rank(
                i.skill_name, i.file_path, i.code_snippet, i.symbol_name, i.evidence_kind, i.mapping_reason
            ),
            0 if i.line_start else 1,
        )
    )

    return GitHubSkillEvidenceResult(
        source_id=source_id,
        repo_owner=str(owner) if owner else None,
        repo_name=str(name) if name else None,
        repo_url=repo_url,
        branch=branch,
        public_safe=public_safe,
        summary=summary,
        detected_skills=detected,
        items=items,
    )
