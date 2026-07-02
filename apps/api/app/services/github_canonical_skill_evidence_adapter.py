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

from app.services.github_python_evidence_focus import (
    EVIDENCE_QUALITY_GRADES,
    GRADE_REPO_LEVEL_FALLBACK,
    ROLE_REPOSITORY_CONTEXT,
    TRUSTED_ANALYSIS_TABLE,
    classify_code_role,
    describe_code_role,
    grade_evidence,
    grade_rank,
    has_ml_executable_signal,
    is_strong_grade,
    is_weak_grade,
    trusted_provenance,
)
from app.services.github_skill_evidence_service import build_github_line_url, safe_commit_sha
from app.services.safe_public_url import is_safe_public_url, safe_repo_relative_path
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
    evidence_quality_grade: str = GRADE_REPO_LEVEL_FALLBACK
    # Conservative DESCRIPTIVE role for the code block (documentation_header /
    # imports_setup / config_constants / model_training / prediction_inference /
    # deployment_serving / repository_context …). Separate from the quality grade:
    # it says what the block *appears to be*, never how strong the proof is. A weak
    # row may carry a useful role label while remaining a needs-review signal.
    code_role_key: str = ROLE_REPOSITORY_CONTEXT
    public_safe: bool = False
    # Grade-time ML verdict from the TRUSTED provenance body (the raw snippet is
    # discarded rather than re-exposed). Tri-state: True = the trusted executable
    # body carried a real ML signal; False = it was inspected and carried none;
    # None = no trusted body was available to judge. Drives the read-time ML gate so
    # a deployment-only body can never present as ML primary implementation proof.
    ml_executable_signal: bool | None = None

    @property
    def skill_key(self) -> str:
        return _norm(self.skill_name)

    @property
    def code_role_label(self) -> str:
        """Human, recruiter-readable role label for :attr:`code_role_key`."""
        return describe_code_role(self.code_role_key)

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
            "evidence_quality_grade": self.evidence_quality_grade,
            "code_role_key": self.code_role_key,
            "code_role_label": self.code_role_label,
            "ml_executable_signal": self.ml_executable_signal,
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


def _trusted_provenance_by_evidence(db: Any, user_id: str) -> dict[str, dict[str, Any]]:
    """Map ``skill_evidence_id -> validated provenance`` from the protected table.

    Reads :data:`TRUSTED_ANALYSIS_TABLE` — a SERVICE-ROLE-ONLY table that
    authenticated users can neither write nor read — and keeps only records that
    pass :func:`trusted_provenance` (our analyzer name + a recognized version). The
    read path uses the service-role client (``get_db``), so this is the single
    place a *trusted* grade / focused excerpt enters render time. A missing table
    or any error yields an empty map, so every row FAILS CLOSED to source-backed /
    weak grading rather than trusting anything user-editable.

    ``skill_evidence.metadata`` is never consulted here — a hostile owner editing
    their own metadata directly via Supabase cannot reach this map.
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        if isinstance(db, dict):
            table = db.get(TRUSTED_ANALYSIS_TABLE, {})
            records = list(table.values()) if isinstance(table, dict) else list(table or [])
        else:
            resp = db.table(TRUSTED_ANALYSIS_TABLE).select("*").eq("user_id", user_id).execute()
            records = [r for r in (getattr(resp, "data", []) or []) if isinstance(r, dict)]
    except Exception:  # pragma: no cover - provenance read is best-effort, fail closed
        return out
    for rec in records:
        if not isinstance(rec, dict):
            continue
        eid = str(rec.get("skill_evidence_id") or "")
        if not eid:
            continue
        # Defense in depth for the dict-backed store: never cross user boundaries.
        rec_user = rec.get("user_id")
        if rec_user is not None and str(rec_user) != str(user_id):
            continue
        validated = trusted_provenance(rec)
        if validated is not None:
            out[eid] = validated
    return out


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


def _trusted_persisted_grade(
    row: dict[str, Any],
    metadata: dict[str, Any],
    provenance: dict[str, Any] | None,
) -> str | None:
    """A previously-persisted ``evidence_quality_grade``, if it is trustworthy.

    A recognized grade *string* in user-controlled metadata is NOT enough — a
    hostile owner can UPDATE their own ``skill_evidence.metadata`` directly via
    Supabase (the row's RLS is "own row ALL") and assert ``implementation_body``
    with no real source behind it. Provenance from the SERVICE-ROLE-ONLY protected
    table gates what we trust:

    * A grade carried by a trusted protected-table ``provenance`` record (our
      analyzer name + a recognized version, stamped only by the offline scanner
      through the service role) is trusted as-is. Authenticated users cannot write
      that table, so this can never be forged.
    * Otherwise only a **weak** flat grade in metadata is honored (a weak band can
      never promote a row to top evidence, so keeping weak rows weak is harmless).
      Any **strong** flat grade without protected provenance FAILS CLOSED.

    Returns ``None`` when there is no trustworthy persisted grade, so the caller
    then tries source-backed AST validation, else caps the row to
    ``repo_level_fallback``.
    """
    if provenance is not None:
        grade = str(provenance.get("evidence_quality_grade") or "").strip().lower()
        return grade if grade in EVIDENCE_QUALITY_GRADES else None
    # No trusted protected provenance: a forged analyzer marker / grade in flat
    # metadata can never be trusted. Honor only a weak flat grade (cannot promote);
    # fail closed on any strong claim.
    raw = metadata.get("evidence_quality_grade") if isinstance(metadata, dict) else None
    if raw is None:
        raw = row.get("evidence_quality_grade")
    grade = str(raw or "").strip().lower()
    if grade in EVIDENCE_QUALITY_GRADES and is_weak_grade(grade):
        return grade
    return None


def _build_item(
    row: dict[str, Any], provenance: dict[str, Any] | None = None
) -> CanonicalGitHubEvidence | None:
    skill = str(row.get("skill_name") or "").strip()
    # Reject absolute / local / Windows / UNC / file:// / traversal paths
    # outright — never lstrip("/") an absolute path into a fake repo-relative
    # one that would leak a private filesystem location into a public link.
    file_path = safe_repo_relative_path(row.get("file_path"))
    if not skill or not file_path:
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

    # Deterministic evidence_quality_grade. A canonical row rarely carries its
    # source body, so grading FAILS CLOSED unless implementation quality can be
    # proven from real source — descriptive metadata alone must never establish
    # precise implementation evidence:
    #
    # * a SERVER-trusted source excerpt (the scanner persists the focused excerpt,
    #   redacted, into the SERVICE-ROLE-ONLY protected table) → regrade
    #   structurally via AST/body logic; this is the ONLY snippet path that may
    #   yield a strong implementation_body / supporting_logic grade. A user-forged
    #   ``code_snippet`` in metadata is NOT read here — it cannot validate source.
    # * else a trusted persisted ``evidence_quality_grade`` (one the scanner
    #   computed from real source at scan time, carried by the protected table, or
    #   a weak flat metadata grade) → honored.
    # * else (no trusted body, no trusted grade) → grade conservatively from the
    #   selection_reason / file kind but CAP the result to a weak band: any strong
    #   metadata read fails closed to ``repo_level_fallback``. So a stale
    #   import-only / docstring / config / decorator-only canonical row (e.g. an
    #   import-only ``api.py:19-23``), or a hostile forged payload, can never
    #   become visible top evidence on the strength of its description.
    #
    # ``provenance`` is supplied by the caller from the protected table only;
    # ``skill_evidence.metadata`` is never trusted for provenance. selection_reason
    # still helps identify relevance (and is preserved safely below), but never
    # upgrades a weak canonical row.
    trusted_snippet = (
        str(provenance.get("safe_excerpt") or "").strip() or None if provenance else None
    )
    # Grade-time ML verdict: inspect the TRUSTED provenance body for a real ML
    # executable signal here, where the snippet is available, then carry only the
    # boolean forward (the raw snippet is never re-exposed at read time). When no
    # trusted body exists the verdict is None (unknown) and the read-time gate fails
    # closed — a stale reason / filename / function name can never stand in for it.
    ml_executable_signal = (
        has_ml_executable_signal(trusted_snippet) if trusted_snippet else None
    )
    if trusted_snippet:
        quality_grade = grade_evidence(
            file_path=file_path,
            code_snippet=trusted_snippet,
            selection_reason=selection_reason or evidence_description,
            evidence_kind=None,
            line_start=line_start,
            line_end=line_end,
        )
    else:
        trusted_grade = _trusted_persisted_grade(row, metadata, provenance)
        if trusted_grade is not None:
            quality_grade = trusted_grade
        else:
            metadata_grade = grade_evidence(
                file_path=file_path,
                code_snippet=None,
                selection_reason=selection_reason or evidence_description,
                evidence_kind=None,
                line_start=line_start,
                line_end=line_end,
            )
            # Fail closed: metadata may only establish a WEAK band. Any strong read
            # (supporting_logic / implementation_body) without a body or trusted
            # grade collapses to repo_level_fallback and is flagged for re-scan.
            quality_grade = (
                metadata_grade if is_weak_grade(metadata_grade) else GRADE_REPO_LEVEL_FALLBACK
            )
    # A canonical row whose grade collapses to a weak band is no longer "strong"
    # precise proof — surface it as medium so the consumer ranks it below genuine
    # implementation bodies (it is still precise line evidence, just weaker).
    if not is_strong_grade(quality_grade) and strength == "strong":
        strength = "medium"

    # Conservative DESCRIPTIVE role label. Computed here where the TRUSTED executable
    # excerpt is available (so a real training / inference / evaluation body reads
    # accurately), but it NEVER promotes the grade above: a docstring/import/config/
    # route row keeps its honest grade-derived role even if a stale reason overclaims.
    code_role_key = classify_code_role(
        grade=quality_grade,
        code_snippet=trusted_snippet,
        selection_reason=selection_reason or evidence_description,
        file_path=file_path,
    )

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
        evidence_quality_grade=quality_grade,
        code_role_key=code_role_key,
        ml_executable_signal=ml_executable_signal,
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
    # Trusted provenance comes ONLY from the service-role-only protected table,
    # keyed by skill_evidence id — never from the user-editable row metadata.
    provenance_by_eid = _trusted_provenance_by_evidence(db, user_id)
    items: list[CanonicalGitHubEvidence] = []
    for row in _rows_for_user(db, user_id):
        if not _is_github_source_code_row(row):
            continue
        provenance = provenance_by_eid.get(str(row.get("id") or ""))
        item = _build_item(row, provenance)
        if item is None:
            continue
        if wanted and _norm(item.canonical_skill_name) != wanted and item.skill_key != wanted:
            continue
        items.append(item)
    # Deterministic: strong implementation/supporting grades first (so a stale
    # docstring/import/constant canonical row sinks below genuine implementation
    # bodies), then precise (with lines) first, then by file path / line.
    items.sort(
        key=lambda i: (
            grade_rank(i.evidence_quality_grade),
            0 if i.line_start else 1,
            i.file_path or "",
            i.line_start or 0,
        )
    )
    return items
