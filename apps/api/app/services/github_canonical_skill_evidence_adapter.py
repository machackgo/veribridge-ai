"""Canonical GitHub skill-evidence adapter (reads the OLD Profile & Proof engine).

The Verified Work Passport Skill Report and the VBR Project Report originally
derived their GitHub code evidence from a *parallel, weaker* path:
``github_proof_submissions.analysis_snapshot.skill_code_evidence`` (filtered by
:mod:`github_skill_evidence_service`). That path frequently degrades to
repo-level support because the analyzer pinned imports / setup / notebook prose.

But the student already has **precise, high-signal** GitHub code evidence stored
by the older, stronger *GitHub Portfolio & Proof* engine
(``github_portfolio_scanner.PortfolioScanner`` →
``github_portfolio_scan_service.import_selected_candidates`` →
``skill_evidence_service.create_skill_evidence``). Those rows live in the
canonical ``skill_evidence`` table with the exact fields the old Profile & Proof
UI renders:

* ``skill_name`` / ``repository_url`` / ``file_path`` / ``line_start`` /
  ``line_end`` / ``evidence_description``;
* ``metadata.github_highlight_url`` (the precise ``…#Lx-Ly`` highlight link),
  ``metadata.selection_reason`` (e.g. "API endpoint decorator"),
  ``metadata.evidence_title`` (project title), ``metadata.student_claim``.

This adapter is the single place that turns those *saved* canonical rows into a
safe, recruiter-verifiable :class:`CanonicalGitHubEvidence` for the Passport /
report consumers. It **never** calls the live scanner — it only reads what the
old engine already persisted — and it never exposes a private repo's link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.github_skill_evidence_service import build_github_line_url, safe_commit_sha
from app.services.safe_public_url import is_safe_public_url
from app.services.skill_normalization import canonical_skill

__all__ = [
    "CanonicalGitHubEvidence",
    "collect_canonical_github_skill_evidence",
    "repo_identity",
]

_EVIDENCE_TABLE = "skill_evidence"

# Repo ``owner/name`` from a github URL (https or ssh), tolerant of a trailing
# ``.git`` / slash. Used both to derive owner/name and to build a stable repo
# identity so a canonical row can be correlated to a VBR project / github proof
# that points at the same repository.
_REPO_RE = re.compile(r"github\.com[/:]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.IGNORECASE)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def repo_identity(url_or_full_name: str | None) -> str:
    """Normalized ``owner/name`` identity for a repo URL or ``owner/name`` string.

    Returns ``""`` when nothing repo-like can be parsed. Lower-cased so two refs
    to the same repository (``https://github.com/Octocat/Hello-World`` and
    ``octocat/hello-world``) collapse to one identity.
    """
    raw = str(url_or_full_name or "").strip()
    if not raw:
        return ""
    m = _REPO_RE.search(raw)
    if m:
        return f"{m.group(1).lower()}/{m.group(2).lower()}"
    # Bare ``owner/name`` (no host) — accept exactly two non-empty segments.
    cleaned = raw.rstrip("/").removesuffix(".git")
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) == 2 and "." not in parts[0]:
        return f"{parts[0].lower()}/{parts[1].lower()}"
    return ""


def _line(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        n = int(value)
        return n if n > 0 else None
    return None


@dataclass
class CanonicalGitHubEvidence:
    """One safe, precise GitHub skill-evidence item from the canonical table."""

    source: str = "skill_evidence"
    proof_type: str = "github"
    source_id: str = ""
    skill_name: str = ""
    canonical_skill_name: str = ""
    repo_owner: str | None = None
    repo_name: str | None = None
    repo_full_name: str | None = None
    repo_url: str | None = None  # public-safe only
    repo_id: str = ""  # normalized identity (owner/name) for correlation
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    github_line_url: str | None = None  # public-safe only
    selection_reason: str | None = None
    evidence_description: str | None = None
    project_title: str | None = None
    subskill_name: str | None = None
    skill_graph_node: str | None = None
    display_mode: str = "code_line"
    has_precise_line_evidence: bool = True
    evidence_kind: str = "portfolio_skill_evidence"
    evidence_strength: str = "strong"
    public_safe: bool = False

    @property
    def skill_key(self) -> str:
        return _norm(self.skill_name)

    @property
    def location_label(self) -> str:
        """Human "file · lines a-b" label."""
        fp = self.file_path or "repo-level"
        if self.line_start:
            suffix = f"-{self.line_end}" if self.line_end and self.line_end != self.line_start else ""
            return f"{fp} · lines {self.line_start}{suffix}"
        return fp

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "proof_type": self.proof_type,
            "source_id": self.source_id,
            "skill_name": self.skill_name,
            "canonical_skill_name": self.canonical_skill_name,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "repo_full_name": self.repo_full_name,
            "repo_url": self.repo_url if self.public_safe else None,
            "repo_id": self.repo_id,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "github_line_url": self.github_line_url,
            "selection_reason": self.selection_reason,
            "evidence_description": self.evidence_description,
            "project_title": self.project_title,
            "subskill_name": self.subskill_name,
            "skill_graph_node": self.skill_graph_node,
            "display_mode": self.display_mode,
            "has_precise_line_evidence": self.has_precise_line_evidence,
            "evidence_kind": self.evidence_kind,
            "evidence_strength": self.evidence_strength,
            "public_safe": self.public_safe,
        }


# Confidence label (old engine: "high"/"medium") → display strength.
_STRENGTH_BY_CONFIDENCE = {"high": "strong", "medium": "medium", "low": "medium"}


def _rows_for_user(db: Any, user_id: str) -> list[dict[str, Any]]:
    """List ``skill_evidence`` rows owned by ``user_id`` (best-effort, never raises)."""
    try:
        if isinstance(db, dict):
            return [
                row
                for row in db.get(_EVIDENCE_TABLE, {}).values()
                if isinstance(row, dict) and str(row.get("user_id")) == str(user_id)
            ]
        resp = db.table(_EVIDENCE_TABLE).select("*").eq("user_id", user_id).execute()
        return [r for r in (getattr(resp, "data", []) or []) if isinstance(r, dict)]
    except Exception:  # pragma: no cover - listing is best-effort
        return []


def _is_github_source_code_row(row: dict[str, Any]) -> bool:
    """True only for a precise GitHub *source-code* evidence row.

    Requires a ``file_path`` (precise line evidence is the whole point) AND a
    GitHub origin — either a ``github`` evidence_type (the portfolio scanner /
    Add-Repository proof writes ``"github repository"``) or a github.com
    repository URL. Extension-proof / document / manual rows are excluded.
    """
    if not str(row.get("file_path") or "").strip():
        return False
    evidence_type = _norm(row.get("evidence_type"))
    repo_url = _norm(row.get("repository_url") or row.get("repo_url"))
    return "github" in evidence_type or "github.com" in repo_url


def _build_item(row: dict[str, Any]) -> CanonicalGitHubEvidence | None:
    skill = str(row.get("skill_name") or "").strip()
    file_path = str(row.get("file_path") or "").strip().lstrip("/")
    if not skill or not file_path:
        return None
    # Reject traversal / absolute paths outright (mirrors the snapshot extractor).
    if "://" in file_path or ".." in file_path.split("/"):
        return None

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    repo_url = str(row.get("repository_url") or row.get("repo_url") or "").strip() or None
    repo_id = repo_identity(repo_url)
    owner, name = (repo_id.split("/", 1) + [""])[:2] if repo_id else ("", "")

    visibility = _norm(row.get("proof_visibility") or metadata.get("proof_visibility") or "public")
    public_safe = bool(
        visibility != "private"
        and repo_url
        and is_safe_public_url(repo_url)
        and "github.com" in repo_url.lower()
    )

    line_start = _line(row.get("line_start"))
    line_end = _line(row.get("line_end"))

    # Prefer the scanner's own precise highlight URL when it is a safe public
    # github link; else build one from the repo + path + lines. Never for a
    # private repo (public_safe gates both).
    github_line_url: str | None = None
    if public_safe:
        stored = str(metadata.get("github_highlight_url") or "").strip()
        if stored and is_safe_public_url(stored) and "github.com" in stored.lower():
            github_line_url = stored
        else:
            github_line_url = build_github_line_url(
                repo_url,
                commit_sha=safe_commit_sha(metadata.get("commit_sha")),
                branch=str(metadata.get("branch_ref") or "main"),
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                public_safe=public_safe,
            )

    selection_reason = str(metadata.get("selection_reason") or "").strip() or None
    evidence_description = str(row.get("evidence_description") or "").strip() or None
    project_title = str(metadata.get("evidence_title") or metadata.get("project_title") or "").strip() or None
    subskill = str(metadata.get("subskill") or metadata.get("subskill_name") or "").strip() or None
    graph_node = str(metadata.get("skill_graph_node") or metadata.get("system_graph_node") or "").strip() or None

    confidence = _norm(metadata.get("confidence_label") or row.get("confidence_label"))
    strength = _STRENGTH_BY_CONFIDENCE.get(confidence, "strong")

    return CanonicalGitHubEvidence(
        source_id=str(row.get("id") or ""),
        skill_name=skill,
        canonical_skill_name=canonical_skill(skill),
        repo_owner=owner or None,
        repo_name=name or None,
        repo_full_name=repo_id or None,
        repo_url=repo_url,
        repo_id=repo_id,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        github_line_url=github_line_url,
        selection_reason=selection_reason,
        evidence_description=evidence_description,
        project_title=project_title,
        subskill_name=subskill,
        skill_graph_node=graph_node,
        evidence_strength=strength,
        public_safe=public_safe,
    )


def collect_canonical_github_skill_evidence(
    db: Any,
    user_id: str,
    skill_name: str | None = None,
) -> list[CanonicalGitHubEvidence]:
    """Read canonical, precise GitHub skill evidence from ``skill_evidence``.

    Returns every safe GitHub source-code evidence row owned by ``user_id`` (the
    rows the old Profile & Proof engine persisted), each as a precise
    ``code_line`` :class:`CanonicalGitHubEvidence`. When ``skill_name`` is given,
    only rows matching that skill (by raw or canonical name) are returned.

    This NEVER triggers a live scan — it only consumes saved rows.
    """
    wanted = _norm(canonical_skill(skill_name)) if skill_name else None
    items: list[CanonicalGitHubEvidence] = []
    for row in _rows_for_user(db, user_id):
        if not _is_github_source_code_row(row):
            continue
        item = _build_item(row)
        if item is None:
            continue
        if wanted and _norm(item.canonical_skill_name) != wanted and item.skill_key != wanted:
            continue
        items.append(item)
    # Deterministic: precise (with lines) first, then by file path / line.
    items.sort(key=lambda i: (0 if i.line_start else 1, i.file_path or "", i.line_start or 0))
    return items
