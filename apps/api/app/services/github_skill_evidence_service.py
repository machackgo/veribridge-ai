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

from app.services.safe_public_url import is_safe_public_url
from app.services.skill_normalization import canonical_skill

__all__ = [
    "GitHubSkillEvidenceItem",
    "GitHubSkillEvidenceResult",
    "extract_github_skill_evidence",
    "classify_evidence_strength",
    "is_strong_code_snippet",
    "safe_code_snippet",
    "safe_commit_sha",
    "build_github_line_url",
]

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
    clean_path = str(file_path or "").lstrip("/")
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
        return [
            i
            for i in self.strong_items
            if i.skill_key == key or _norm(i.canonical_skill_name) == ckey
        ]

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
            file_path = str(raw.get("file_path") or "").strip().lstrip("/")
            if not skill or not file_path:
                continue
            # Reject traversal / absolute paths outright.
            if "://" in file_path or ".." in file_path.split("/"):
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
                    line_start=line_start,
                    line_end=line_end,
                    public_safe=public_safe,
                )

            evidence_kind = _evidence_kind(
                file_path, raw_snippet, function_name, class_name, endpoint_path, line_start
            )

            mapping_reason = (
                f"Analyzer located {evidence_kind} evidence for {skill} in {file_path}"
                + (f" (lines {line_start}" + (f"-{line_end}" if line_end and line_end != line_start else "") + ")"
                   if line_start else "")
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
                    line_start=line_start,
                    line_end=line_end,
                    function_name=function_name,
                    class_name=class_name,
                    symbol_name=symbol_name,
                    endpoint_path=endpoint_path,
                    commit_sha=commit_sha,
                    branch=branch,
                    code_snippet=safe_code_snippet(raw_snippet) if (public_safe and strength != "weak") else None,
                    github_url=github_url,
                    evidence_kind=evidence_kind,
                    evidence_strength=strength,
                    mapping_reason=mapping_reason,
                    limitation=_STRONG_LIMITATION if strength != "weak" else _WEAK_LIMITATION,
                    public_safe=public_safe,
                )
            )
            if len(items) >= 60:
                break

    # Rank strong/medium above weak, then by line presence (deterministic).
    _rank = {"strong": 0, "medium": 1, "weak": 2}
    items.sort(key=lambda i: (_rank.get(i.evidence_strength, 9), 0 if i.line_start else 1))

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
