"""Student Proof Vault — a student-wide aggregator of ALL owned proof evidence.

The Verified Work Passport and the per-project VBR report used to read evidence
only from ``vbr_projects.metadata.attached_proofs`` — i.e. proofs the student had
*manually attached* to one Project Defense. But a student accumulates proof
evidence across many independent surfaces (a GitHub Proof page, a Document Proof
upload, a Website Proof recording, a Project Defense, a Skill Graph pipeline)
that may never have been attached to a single VBR project.

This service collects every **safe, student-owned** proof evidence item directly
from its source table — attached *or not* — and normalizes it into a single safe
"vault item" shape, grouped by skill. It powers:

* the **Private Work Passport** (owner-only) — every owned proof, grouped by
  skill, attached and unattached, with unattached proofs clearly labelled;
* the per-project report's **"Other student proofs for related skills"** section —
  vault items that match a report's claimed skills but are *not* attached to that
  project (so the report never pretends an unattached proof belongs to it).

Sources collected (5 proof types):

1. **GitHub Proof**  — ``github_proof_submissions`` (``detected_skills`` +
   ``analysis_snapshot.skill_code_evidence`` file/line/function locators).
2. **Document Proof** — ``optional_evidence_submissions`` (``evidence_objects``
   ``skill_name`` + page/section/snippet locators).
3. **Website Proof**  — ``workflow_analysis_results`` (``supported_skills`` +
   safe workflow/live-check summaries via ``website_proof_detail_service``).
4. **Project Defense / Video** — ``vbr_verification_sessions`` telemetry
   (``project_defense_analysis`` skills + ``video_evidence_chips``), always tied
   to the owning project.
5. **Skill Graph** — ``skill_evidence_pipelines`` (``skill_name`` +
   ``support_status``), from the pipeline DB.

Security invariants (mirror the report/passport scrubbers): a vault item NEVER
carries raw transcripts, raw document text, raw GitHub snapshots, raw DOM/OCR
dumps, provider payloads, storage paths, signed URLs, bucket paths, private file
ids, emails/auth ids, raw media paths, or numeric trust/ranking scores. Every
summary/snippet is bounded and score-scrubbed; only genuinely public URLs are
ever marked ``public_safe``. This module never calls an LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.github_canonical_skill_evidence_adapter import (
    CanonicalGitHubEvidence,
    collect_canonical_github_skill_evidence,
    repo_identity,
)
from app.services.github_python_evidence_focus import (
    GRADE_IMPLEMENTATION_BODY,
    GRADE_REPO_LEVEL_FALLBACK,
    PURPOSE_REPOSITORY_CONTEXT,
    RELEVANCE_CONTEXT_ONLY,
    ROLE_REPOSITORY_CONTEXT,
    classify_code_block_purpose,
    classify_code_role,
    classify_skill_relevance,
    code_block_purpose_summary,
    describe_code_block_purpose,
    describe_code_role,
    describe_skill_relevance,
    effective_code_block_purpose,
    effective_code_role,
    skill_relevance_summary,
    effective_evidence_grade,
    grade_rank,
    is_skill_implementation_relevance,
    is_strong_grade,
    safe_selection_reason,
)
from app.services.github_skill_evidence_service import (
    GitHubSkillEvidenceItem,
    GitHubSkillEvidenceResult,
    extract_github_skill_evidence,
    is_github_evidence_related_to_skill,
    is_ml_skill,
    skill_profile,
)
from app.services.safe_public_url import is_safe_public_url
from app.services.skill_normalization import canonical_skill, skill_category, skill_slug
from app.services.vbr_student_report import (
    _GITHUB_PROOFS_TABLE,
    _norm,
    _safe_domain,
    _scrub_score_fragments,
    _trace_text,
    _website_evidence_label,
)
from app.services.website_proof_detail_service import get_website_proof_detail

logger = logging.getLogger(__name__)

# Canonical proof-type labels — identical to the recruiter-facing evidence
# source badges used by the report/passport so a skill reads the same everywhere.
PROOF_GITHUB = "GitHub Proof"
PROOF_DOCUMENT = "Document Proof"
PROOF_WEBSITE = "Website Proof"
PROOF_DEFENSE = "Project Defense"
PROOF_VIDEO = "Video Evidence"
PROOF_SKILL_GRAPH = "Skill Graph"

_PROJECTS_TABLE = "vbr_projects"
_DOCUMENTS_TABLE = "optional_evidence_submissions"
_WORKFLOW_TABLE = "workflow_analysis_results"
_SESSIONS_TABLE = "vbr_verification_sessions"
_PIPELINES_TABLE = "skill_evidence_pipelines"
# Canonical, precise GitHub code evidence persisted by the older, stronger
# GitHub Portfolio & Proof engine (PortfolioScanner → skill_evidence rows).
_SKILL_EVIDENCE_TABLE = "skill_evidence"

# Qualitative Skill Graph support-status → label (never a numeric confidence).
_PIPELINE_STATUS_LABELS = {
    "strongly_supported": "Demonstrated",
    "partially_supported": "Partially demonstrated",
    "needs_review": "Needs review",
}

_GITHUB_LIMITATION = (
    "Repository evidence supports this skill but is not, by itself, proof the candidate "
    "personally authored every line."
)
_GITHUB_WEAK_ONLY_LIMITATION = (
    "Repository-level evidence only: the stored GitHub line evidence for this skill is imports, "
    "setup/metadata or notebook narrative — not strong line-level proof. Reanalysis is needed to "
    "surface stronger code-level evidence."
)
# Derived "this project has no GitHub code evidence for this skill" limitation.
# A shared constant so the per-chain generator and the same-title merge (which
# must drop it once chains with GitHub evidence are unioned in) stay in sync.
_NO_GITHUB_CODE_EVIDENCE_LIMITATION = "No GitHub code evidence in this project for this skill."
# Max precise (strong/medium) fallback code rows emitted per repo+skill from a
# ``github_proof_submissions`` snapshot. The canonical ranking (strong→medium,
# ML-pipeline relevance, line presence) is preserved by ``strong_for_skill``, so
# this only bounds how many of the strongest rows are surfaced per repo+skill.
_MAX_GITHUB_FALLBACK_ROWS_PER_SKILL = 5
_GITHUB_CANONICAL_LIMITATION = (
    "Precise code lines selected by the GitHub Portfolio & Proof scanner; locating skill-relevant "
    "code is strong evidence of the skill but is not, by itself, proof of sole authorship — combine "
    "with the Project Defense for ownership context."
)
_DOCUMENT_LIMITATION = (
    "Document evidence supports but does not independently prove implementation or authorship; "
    "only a safe summary is shown — never the raw file."
)
_WEBSITE_LIMITATION = (
    "Confirms observed behaviour at inspection time, not source-code authorship or ongoing uptime."
)
_DEFENSE_LIMITATION = "Self-explanation evidence; strongest when combined with artifact evidence."
_VIDEO_LIMITATION = (
    "A short timestamped moment; it corroborates the explanation but does not independently prove authorship."
)
_SKILL_GRAPH_LIMITATION = (
    "Aggregated Skill Graph evidence saved from the student's proofs; a private summary, not a numeric score."
)
_UNATTACHED_NOTE = "Not attached to a VBR project."

__all__ = [
    "PROOF_GITHUB",
    "PROOF_DOCUMENT",
    "PROOF_WEBSITE",
    "PROOF_DEFENSE",
    "PROOF_VIDEO",
    "PROOF_SKILL_GRAPH",
    "collect_vault_items",
    "group_vault_by_skill",
    "vault_items_for_skills",
    "collect_skill_summaries",
    "collect_skill_report",
    "collect_related_skill_proofs",
]


# ── Row listing (dict + Supabase) ────────────────────────────────────────────


def _rows_for_user(db: Any, table: str, user_id: str, *, user_key: str = "user_id") -> list[dict[str, Any]]:
    """List all rows in ``table`` owned by ``user_id`` (best-effort, never raises)."""
    try:
        if isinstance(db, dict):
            return [
                row
                for row in db.get(table, {}).values()
                if isinstance(row, dict) and str(row.get(user_key)) == str(user_id)
            ]
        resp = db.table(table).select("*").eq(user_key, user_id).execute()
        return [r for r in (getattr(resp, "data", []) or []) if isinstance(r, dict)]
    except Exception:  # pragma: no cover - listing is best-effort
        return []


# ── Attachment index ─────────────────────────────────────────────────────────


def _build_attachment_index(db: Any, user_id: str) -> dict[tuple[str, str], list[str]]:
    """Map ``(source_table, source_id)`` → ``[project_id, …]`` for attached proofs.

    Scans every owned ``vbr_projects`` row's ``metadata.attached_proofs`` so we
    can mark each vault item as attached (and to which project(s)). Project
    Defense sessions are attached directly via their ``project_id``; those are
    resolved at collection time, not here.
    """
    index: dict[tuple[str, str], list[str]] = {}

    def _add(table: str, source_id: Any, project_id: str) -> None:
        sid = str(source_id or "").strip()
        if not sid:
            return
        index.setdefault((table, sid), [])
        if project_id not in index[(table, sid)]:
            index[(table, sid)].append(project_id)

    for project in _rows_for_user(db, _PROJECTS_TABLE, user_id):
        project_id = str(project.get("id") or "")
        if not project_id:
            continue
        metadata = project.get("metadata") or {}
        attached = metadata.get("attached_proofs") if isinstance(metadata, dict) else None
        if not isinstance(attached, dict):
            continue

        github = attached.get("github_proof")
        if isinstance(github, dict):
            _add(_GITHUB_PROOFS_TABLE, github.get("github_proof_id") or github.get("id"), project_id)

        for doc in attached.get("documents") or []:
            if isinstance(doc, dict):
                _add(_DOCUMENTS_TABLE, doc.get("document_evidence_id"), project_id)

        for wp in attached.get("website_proofs") or []:
            if isinstance(wp, dict):
                _add(_WORKFLOW_TABLE, wp.get("proof_session_id"), project_id)

        for pid in attached.get("skill_pipeline_ids") or []:
            _add(_PIPELINES_TABLE, pid, project_id)

    return index


# Safe, structured per-source locator fields a vault item may carry IN ADDITION
# to its human ``safe_location`` label. These are populated cheaply at collection
# time (no hydration) so the Skill Report can render recruiter-verifiable proof
# (exact file/line/function/link, document page/citation, defense question, …).
# Every one is already safe (repo-relative path, line numbers, function name,
# public-only URL, deterministic question text, bounded answer excerpt).
_LOCATOR_KEYS = (
    "file_path",
    "line_start",
    "line_end",
    "function_name",
    "commit_sha",
    "public_url",
    "page_number",
    "section_label",
    "citation",
    # Safe document context: a figure/diagram/table reference label (never the
    # raw image/text) and whether the student explicitly allowed full-document
    # recruiter download. ``full_document_available`` is a plain bool — it never
    # carries a storage path or signed URL.
    "figure_reference",
    "full_document_available",
    "question_text",
    "answer_excerpt",
    "timestamp_label",
    # Explicit GitHub display-mode fields (single source of truth — the frontend
    # renders from these instead of re-inferring from file_path). Populated only
    # for GitHub items; ``None`` everywhere else.
    "display_mode",
    "evidence_strength",
    "evidence_quality_grade",
    # Conservative DESCRIPTIVE code role (documentation_header / imports_setup /
    # model_training / …). Says what the block appears to be — never proof
    # strength; the grade above still governs that.
    "code_role_key",
    "code_role_label",
    # Block-level PURPOSE (finer than the role): what THIS exact block appears
    # to do, as a closed safe key/label/summary ("Documentation describing
    # retraining pipeline", "Imports / dependency setup"). Never proof strength.
    "code_block_purpose_key",
    "code_block_purpose_label",
    "code_block_purpose_summary",
    # SKILL RELEVANCE relative to the skill the row is filed under (closed
    # template key/label/summary, recomputed at read time against the report's
    # selected skill). Never proof strength.
    "skill_relevance_key",
    "skill_relevance_label",
    "skill_relevance_summary",
    # Grade-time ML verdict from the trusted provenance body (tri-state bool / None).
    # Drives read-time ML semantic validation without ever re-exposing the snippet.
    "ml_executable_signal",
    "evidence_kind",
    "has_precise_line_evidence",
    "github_line_url",
    "repo_url",
    # Canonical (old Profile & Proof engine) GitHub fields — the precise
    # ``selection_reason`` ("API endpoint decorator") + optional subskill /
    # system-graph node that the PortfolioScanner stored on ``skill_evidence``.
    "selection_reason",
    "subskill_name",
    "skill_graph_node",
)


def _make_item(
    *,
    skill_name: str | None,
    proof_type: str,
    source_id: str,
    source_table: str,
    title: str,
    safe_summary: str,
    safe_location: str | None,
    public_safe: bool,
    limitation: str,
    attached_project_ids: list[str],
    safe_snippet: str | None = None,
    locators: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one proof into the safe vault-item shape (single source of truth).

    ``locators`` may carry any of ``_LOCATOR_KEYS`` (a whitelist) — only those
    keys are copied in, so a collector can never leak an unexpected raw field.
    """
    is_attached = bool(attached_project_ids)
    item = {
        "skill_name": skill_name,
        "proof_type": proof_type,
        "source_id": source_id,
        "source_table": source_table,
        # Primary attached project (first), if any — used for owner-only linking.
        "project_id": attached_project_ids[0] if attached_project_ids else None,
        "attached_project_ids": list(attached_project_ids),
        "title": title,
        "source_label": proof_type,
        "safe_summary": _trace_text(_scrub_score_fragments(safe_summary)),
        "safe_snippet": safe_snippet,
        "safe_location": safe_location,
        "public_safe": bool(public_safe),
        "visibility": "public" if public_safe else "private",
        "limitation": limitation if is_attached else f"{limitation} {_UNATTACHED_NOTE}".strip(),
        "is_attached_to_project": is_attached,
    }
    for key in _LOCATOR_KEYS:
        item[key] = (locators or {}).get(key)
    return item


# ── Per-source collectors ────────────────────────────────────────────────────


def _github_location_label(ev: GitHubSkillEvidenceItem) -> str:
    """Human "file · function()/lines" label for a strong GitHub evidence item."""
    fp = ev.file_path or "repo-level"
    if ev.evidence_kind == "function" and ev.function_name:
        return f"{fp} · {ev.function_name}()"
    if ev.evidence_kind == "endpoint" and ev.endpoint_path:
        return f"{fp} · {ev.endpoint_path}"
    if ev.evidence_kind == "class" and ev.class_name:
        return f"{fp} · class {ev.class_name}"
    if ev.line_start:
        return f"{fp} · lines {ev.line_start}" + (
            f"-{ev.line_end}" if ev.line_end and ev.line_end != ev.line_start else ""
        )
    return fp


def _repo_pids_index(
    db: Any, user_id: str, gh_rows: list[dict[str, Any]], attach: dict[tuple[str, str], list[str]]
) -> dict[str, list[str]]:
    """Map a repo identity (``owner/name``) → the VBR project ids that point at it.

    A canonical ``skill_evidence`` GitHub row is correlated to a project chain by
    matching its repository to: (a) the project's own ``repo_url``/``repo_full_name``,
    and (b) any ``github_proof_submissions`` row attached to a project (so the
    precise canonical lines land in the SAME chain the weaker proof was in, and
    the fallback it supersedes is never orphaned from its project).
    """
    repo_pids: dict[str, list[str]] = {}

    def _add(rid: str, pid: str) -> None:
        if not rid or not pid:
            return
        repo_pids.setdefault(rid, [])
        if pid not in repo_pids[rid]:
            repo_pids[rid].append(pid)

    for pid, meta in _project_meta(db, user_id).items():
        _add(str(meta.get("repo_full") or ""), pid)

    for row in gh_rows:
        proof_id = str(row.get("id") or "")
        if not proof_id:
            continue
        rid = repo_identity(
            row.get("repo_url")
            or (f"{row.get('repo_owner')}/{row.get('repo_name')}" if row.get("repo_owner") else "")
        )
        for pid in attach.get((_GITHUB_PROOFS_TABLE, proof_id), []):
            _add(rid, pid)

    return repo_pids


def _canonical_github_items(
    db: Any, user_id: str, repo_pids: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    """Build vault items from canonical ``skill_evidence`` GitHub rows.

    These are the precise, old-Profile-&-Proof code-line rows (exact file/line +
    ``github_highlight_url`` + ``selection_reason``). Each becomes a ``code_line``
    GitHub vault item, attached to the project chain whose repo matches (else
    standalone). Returns the items plus a ``{(repo_id, skill_key)}`` cover-set so
    the weaker ``github_proof_submissions`` fallback for the same repo+skill is
    suppressed — canonical evidence beats the fallback.
    """
    items: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    for ev in collect_canonical_github_skill_evidence(db, user_id):
        attached = repo_pids.get(ev.repo_id, []) if ev.repo_id else []
        # Only STRONG canonical evidence (implementation_body / supporting_logic)
        # is allowed to suppress the weaker github_proof_submissions fallback for
        # the same (repo, skill). A weak canonical row (import-only / docstring /
        # config / repo_level_fallback) is still surfaced as its own precise item,
        # but must NOT mark the pair fully covered — otherwise a stale/weak
        # canonical import row would hide a STRONGER snapshot/fallback proof for
        # the same repo+skill. Exact-duplicate rows are still collapsed later by
        # :func:`_dedupe_evidence`.
        if is_strong_grade(ev.evidence_quality_grade):
            covered.add((ev.repo_id, ev.skill_key))
        summary = (
            ev.evidence_description
            or ev.selection_reason
            or f"Precise code evidence for {ev.skill_name} located by the GitHub Portfolio & Proof scanner."
        )
        items.append(
            _make_item(
                skill_name=ev.skill_name,
                proof_type=PROOF_GITHUB,
                source_id=ev.source_id,
                source_table=_SKILL_EVIDENCE_TABLE,
                title=ev.project_title or ev.repo_full_name or "GitHub repository",
                safe_summary=summary,
                safe_location=ev.location_label,
                public_safe=ev.public_safe,
                limitation=_GITHUB_CANONICAL_LIMITATION,
                attached_project_ids=attached,
                locators={
                    "file_path": ev.file_path,
                    "line_start": ev.line_start,
                    "line_end": ev.line_end,
                    "public_url": ev.github_line_url or (ev.repo_url if ev.public_safe else None),
                    "display_mode": "code_line",
                    "has_precise_line_evidence": True,
                    "github_line_url": ev.github_line_url,
                    "repo_url": ev.repo_url if ev.public_safe else None,
                    "evidence_strength": ev.evidence_strength,
                    "evidence_quality_grade": ev.evidence_quality_grade,
                    "code_role_key": ev.code_role_key,
                    "code_role_label": ev.code_role_label,
                    "code_block_purpose_key": ev.code_block_purpose_key,
                    "code_block_purpose_label": ev.code_block_purpose_label,
                    "code_block_purpose_summary": ev.code_block_purpose_summary,
                    "skill_relevance_key": ev.skill_relevance_key,
                    "skill_relevance_label": ev.skill_relevance_label,
                    "skill_relevance_summary": ev.skill_relevance_summary,
                    "ml_executable_signal": ev.ml_executable_signal,
                    "evidence_kind": ev.evidence_kind,
                    "selection_reason": ev.selection_reason,
                    "subskill_name": ev.subskill_name,
                    "skill_graph_node": ev.skill_graph_node,
                },
            )
        )
    return items, covered


def _collect_github(db: Any, user_id: str, attach: dict[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
    """Collect safe GitHub skill evidence — canonical ``skill_evidence`` FIRST.

    The precise rows persisted by the older GitHub Portfolio & Proof engine
    (``skill_evidence``: exact file/line + ``github_highlight_url`` +
    ``selection_reason``) are read first and surfaced as ``code_line`` evidence.
    Only then are ``github_proof_submissions`` rows routed through the canonical
    :func:`extract_github_skill_evidence` (which downgrades imports / sys.path /
    metadata / notebook prose) — and any (repo, skill) already covered by a
    canonical ``skill_evidence`` row is SKIPPED so the weaker snapshot fallback
    never overrides the stronger precise evidence. The raw ``analysis_snapshot``
    is never read here.
    """
    gh_rows = _rows_for_user(db, _GITHUB_PROOFS_TABLE, user_id)
    repo_pids = _repo_pids_index(db, user_id, gh_rows, attach)

    # 1) Canonical precise GitHub evidence (the old Profile & Proof engine).
    items, covered = _canonical_github_items(db, user_id, repo_pids)

    # 2) github_proof_submissions fallback — only where canonical doesn't cover.
    for row in gh_rows:
        proof_id = str(row.get("id") or "")
        if not proof_id:
            continue
        row_repo_id = repo_identity(
            row.get("repo_url")
            or (f"{row.get('repo_owner')}/{row.get('repo_name')}" if row.get("repo_owner") else "")
        )
        attached = attach.get((_GITHUB_PROOFS_TABLE, proof_id), [])
        result: GitHubSkillEvidenceResult = extract_github_skill_evidence(row)
        repo_full = result.repo_full_name
        repo_url = result.repo_url or ""
        public_safe = result.public_safe
        summary = result.summary
        repo_public_url = repo_url if (public_safe and repo_url) else None
        repo_location = "repo-level" if not repo_url else (_safe_domain(repo_url) or "repo-level")

        # Union detected skills with any skill that appears only in code evidence.
        all_skill_keys: dict[str, str] = {_norm(s): s for s in result.detected_skills}
        for ev in result.items:
            if ev.skill_name.strip():
                all_skill_keys.setdefault(ev.skill_key, ev.skill_name)

        # Repo-level display fields shared by every honest "no precise line" card
        # (project-level repo, or a skill whose only stored line evidence is weak).
        repo_level_locators = {
            "public_url": repo_public_url,
            "repo_url": repo_public_url,
            "github_line_url": None,
            "display_mode": "repo_level",
            "has_precise_line_evidence": False,
            "evidence_kind": "repo_level_summary",
            "evidence_quality_grade": "repo_level_fallback",
            "code_role_key": ROLE_REPOSITORY_CONTEXT,
            "code_role_label": describe_code_role(ROLE_REPOSITORY_CONTEXT),
            "code_block_purpose_key": PURPOSE_REPOSITORY_CONTEXT,
            "code_block_purpose_label": describe_code_block_purpose(PURPOSE_REPOSITORY_CONTEXT),
            "code_block_purpose_summary": code_block_purpose_summary(PURPOSE_REPOSITORY_CONTEXT),
            # Repo-level context is context-only whatever the skill; the label is
            # re-resolved per selected skill at read time by ``_report_item``.
            "skill_relevance_key": RELEVANCE_CONTEXT_ONLY,
            "skill_relevance_label": describe_skill_relevance(RELEVANCE_CONTEXT_ONLY),
            "skill_relevance_summary": skill_relevance_summary(RELEVANCE_CONTEXT_ONLY),
        }

        if not all_skill_keys:
            # Repo with no detected skills — surface as project-level GitHub proof.
            items.append(
                _make_item(
                    skill_name=None,
                    proof_type=PROOF_GITHUB,
                    source_id=proof_id,
                    source_table=_GITHUB_PROOFS_TABLE,
                    title=str(repo_full),
                    safe_summary=summary,
                    safe_location=repo_location,
                    public_safe=public_safe,
                    limitation=_GITHUB_LIMITATION,
                    attached_project_ids=attached,
                    locators={**repo_level_locators, "evidence_strength": "repo_level"},
                )
            )
            continue

        # Skills whose only stored line evidence is weak (imports/setup/markdown).
        weak_only = {_norm(s) for s in result.weak_only_skill_names}

        for key, display in all_skill_keys.items():
            # Canonical skill_evidence (precise code lines) for this repo+skill
            # already covers it — never override it with the weaker snapshot.
            if (row_repo_id, key) in covered:
                continue
            # Emit EVERY distinct strong/medium precise row for this skill (already
            # ranked strong→medium, ML-pipeline relevance, then line presence by the
            # extractor), bounded per repo+skill — not just the single best row. A
            # one-row group made connected GitHub proof look weaker than standalone;
            # the bounded ranked list surfaces the same multi-row code evidence.
            strong_rows = result.strong_for_skill(display)[:_MAX_GITHUB_FALLBACK_ROWS_PER_SKILL]
            if strong_rows:
                for strong in strong_rows:
                    # Preserve the analyzer's mapping reason as the row's
                    # ``selection_reason`` (safely scrubbed) so connected rows carry
                    # the same "why this line" context as canonical precise rows.
                    selection_reason = (
                        _trace_text(_scrub_score_fragments(strong.mapping_reason))
                        if strong.mapping_reason
                        else None
                    )
                    # Conservative DESCRIPTIVE role for the focused block — computed
                    # here where the extractor's snippet is available, but it never
                    # promotes the grade (a docstring/import/config/route row keeps
                    # its honest grade-derived role whatever the reason claims).
                    code_role_key = classify_code_role(
                        grade=strong.evidence_quality_grade,
                        code_snippet=strong.code_snippet,
                        selection_reason=selection_reason,
                        file_path=strong.file_path,
                        function_name=strong.function_name,
                    )
                    # Block-level purpose, computed beside the role from the same
                    # safe signals. A label only — never promotes the grade.
                    purpose_key = classify_code_block_purpose(
                        grade=strong.evidence_quality_grade,
                        code_snippet=strong.code_snippet,
                        selection_reason=selection_reason,
                        file_path=strong.file_path,
                        function_name=strong.function_name,
                    )
                    # Relevance of this block to the skill it is filed under (a
                    # display default; recomputed per report skill at read time).
                    relevance_key = classify_skill_relevance(
                        purpose_key,
                        skill=display,
                        grade=strong.evidence_quality_grade,
                    )
                    items.append(
                        _make_item(
                            skill_name=display,
                            proof_type=PROOF_GITHUB,
                            source_id=proof_id,
                            source_table=_GITHUB_PROOFS_TABLE,
                            title=str(repo_full),
                            safe_summary=summary,
                            safe_location=_github_location_label(strong),
                            public_safe=public_safe,
                            limitation=_GITHUB_LIMITATION,
                            attached_project_ids=attached,
                            safe_snippet=strong.code_snippet,
                            locators={
                                "file_path": strong.file_path,
                                "line_start": strong.line_start,
                                "line_end": strong.line_end,
                                "function_name": strong.function_name,
                                "commit_sha": strong.commit_sha,
                                "public_url": strong.github_url or repo_public_url,
                                # Explicit precise-evidence display mode for the frontend.
                                "display_mode": "code_line",
                                "has_precise_line_evidence": True,
                                "github_line_url": strong.github_url,
                                "repo_url": repo_public_url,
                                "evidence_strength": strong.evidence_strength,
                                "evidence_quality_grade": strong.evidence_quality_grade,
                                "code_role_key": code_role_key,
                                "code_role_label": describe_code_role(code_role_key),
                                "code_block_purpose_key": purpose_key,
                                "code_block_purpose_label": describe_code_block_purpose(purpose_key),
                                "code_block_purpose_summary": code_block_purpose_summary(purpose_key),
                                "skill_relevance_key": relevance_key,
                                "skill_relevance_label": describe_skill_relevance(relevance_key, display),
                                "skill_relevance_summary": skill_relevance_summary(relevance_key, display),
                                "evidence_kind": strong.evidence_kind,
                                "selection_reason": selection_reason,
                            },
                        )
                    )
            else:
                # Weak-only (or no) line evidence → honest repo-level fallback. We
                # NEVER render the weak snippet or fabricate a line URL.
                strength = "weak" if key in weak_only else "repo_level"
                items.append(
                    _make_item(
                        skill_name=display,
                        proof_type=PROOF_GITHUB,
                        source_id=proof_id,
                        source_table=_GITHUB_PROOFS_TABLE,
                        title=str(repo_full),
                        safe_summary=summary,
                        safe_location=repo_location,
                        public_safe=public_safe,
                        limitation=_GITHUB_WEAK_ONLY_LIMITATION,
                        attached_project_ids=attached,
                        locators={**repo_level_locators, "evidence_strength": strength},
                    )
                )
    return items


# Dedicated, student-controlled full-document download opt-in fields. Consent is
# granted ONLY when one of these holds an actual boolean ``True`` (see the
# ``is True`` gate in ``_collect_documents``); the generic ``public_safe`` flag is
# deliberately excluded — "safe to summarize/cite" is not "safe to download".
_DOWNLOAD_CONSENT_FIELDS = (
    "recruiter_shareable",
    "allow_full_download",
    "allow_public_download",
    "public_download_enabled",
    "student_allowed_public_download",
    "recruiter_download_enabled",
    "explicit_download_consent",
)


def _collect_documents(db: Any, user_id: str, attach: dict[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in _rows_for_user(db, _DOCUMENTS_TABLE, user_id):
        doc_id = str(row.get("id") or "")
        if not doc_id:
            continue
        attached = attach.get((_DOCUMENTS_TABLE, doc_id), [])
        analysis_json = row.get("analysis_json") if isinstance(row.get("analysis_json"), dict) else {}
        title = str(analysis_json.get("title") or row.get("file_path") or "Document")
        status_label = str(row.get("status") or "analyzed")

        # Whether the student explicitly allowed full-document recruiter download.
        # Sourced ONLY from a dedicated student-controlled download opt-in on the
        # document's analysis_json (default closed). The generic ``public_safe``
        # flag is intentionally NOT consulted here: ``public_safe`` means a
        # document is safe to *summarize/cite* in a projection — it is NOT consent
        # to share the full document for download.
        #
        # Consent MUST be an actual Python boolean ``True`` on a dedicated opt-in
        # field. Truthy strings/numbers/containers ("true", "false", "yes", "no",
        # "1", "0", 1, 0, [], {}, any non-empty string) are NEVER consent — a
        # malformed/free-text value defaults to closed. A missing field is closed;
        # an explicit ``False`` disables. This is a plain bool — we NEVER surface a
        # storage path or signed URL from here; an "available" document still only
        # shows safe context, and any actual download is gated by its own endpoint.
        full_download_allowed = any(
            analysis_json.get(field) is True for field in _DOWNLOAD_CONSENT_FIELDS
        )

        evidence_objects = row.get("evidence_objects") if isinstance(row.get("evidence_objects"), list) else []
        seen_skills: set[str] = set()
        for obj in evidence_objects:
            if not isinstance(obj, dict):
                continue
            skill = str(obj.get("skill_name") or "").strip()
            key = _norm(skill)
            if not key or key in seen_skills:
                continue
            seen_skills.add(key)
            page = obj.get("page_number")
            section = _trace_text(str(obj.get("section_label") or ""), 80) or None
            snippet = _trace_text(_scrub_score_fragments(str(obj.get("snippet") or "")), 200) or None
            if isinstance(page, int) or (isinstance(page, str) and page.isdigit()):
                location = f"Page {page}" + (f" · {section}" if section else "")
            elif section:
                location = section
            else:
                location = "matched skill"
            page_int = page if isinstance(page, int) else (int(page) if isinstance(page, str) and page.isdigit() else None)
            reason = _trace_text(_scrub_score_fragments(str(obj.get("reason") or "")), 200) or None
            # Safe figure/diagram/table reference label (e.g. "Figure 3", "Table 2")
            # — only the analyzer's reference label, never the raw image/text.
            figure_reference = _trace_text(
                str(
                    obj.get("figure_reference")
                    or obj.get("figure")
                    or obj.get("table_reference")
                    or obj.get("diagram_reference")
                    or obj.get("exhibit")
                    or ""
                ),
                60,
            ) or None
            items.append(
                _make_item(
                    skill_name=skill,
                    proof_type=PROOF_DOCUMENT,
                    source_id=doc_id,
                    source_table=_DOCUMENTS_TABLE,
                    title=title,
                    safe_summary=(
                        reason
                        or f"{title} ({status_label}) — a supporting document the analyzer matched to {skill}."
                    ),
                    safe_location=location,
                    # Documents are never publicly linkable; only a safe summary shows.
                    public_safe=False,
                    limitation=_DOCUMENT_LIMITATION,
                    attached_project_ids=attached,
                    safe_snippet=snippet,
                    locators={
                        "page_number": page_int,
                        "section_label": section,
                        "citation": section,
                        "figure_reference": figure_reference,
                        "full_document_available": full_download_allowed,
                    },
                )
            )

        if not seen_skills:
            # Document with no analyzer-matched skill — project-level context only.
            items.append(
                _make_item(
                    skill_name=None,
                    proof_type=PROOF_DOCUMENT,
                    source_id=doc_id,
                    source_table=_DOCUMENTS_TABLE,
                    title=title,
                    safe_summary=f"{title} ({status_label}) — attached as context; not mapped to specific skills.",
                    safe_location="project context",
                    public_safe=False,
                    limitation=_DOCUMENT_LIMITATION,
                    attached_project_ids=attached,
                    locators={"full_document_available": full_download_allowed},
                )
            )
    return items


def _collect_website(db: Any, user_id: str, attach: dict[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    for row in _rows_for_user(db, _WORKFLOW_TABLE, user_id):
        session_id = str(row.get("proof_session_id") or "")
        if not session_id or session_id in seen_sessions:
            continue
        seen_sessions.add(session_id)
        attached = attach.get((_WORKFLOW_TABLE, session_id), [])
        target = str(row.get("target_website") or "")
        public_safe = is_safe_public_url(target)
        confidence = str(row.get("workflow_confidence") or "insufficient")
        strength = _website_evidence_label(int(row.get("evidence_strength_score") or 0))
        supported = [str(s) for s in (row.get("supported_skills") or []) if str(s).strip()]

        # PERFORMANCE: do NOT call get_website_proof_detail here — that runs once
        # per website proof (an N+1 hydration over potentially dozens of proofs)
        # and is far too heavy for the main Passport / vault-collection path. We
        # use only the bulk-safe summary columns already on this row. The deep
        # workflow/OCR/DOM/visual/live-check detail is hydrated lazily, for ONE
        # selected skill, inside ``collect_skill_report``.
        summary = (
            _trace_text(_scrub_score_fragments(str(row.get("workflow_summary") or row.get("recruiter_summary") or "")))
            or f"A working deployment was inspected ({strength}; workflow confidence: {confidence})."
        )
        location = _safe_domain(target) if public_safe else "deployment"
        title = target if public_safe else "Website Proof"

        if not supported:
            items.append(
                _make_item(
                    skill_name=None,
                    proof_type=PROOF_WEBSITE,
                    source_id=session_id,
                    source_table=_WORKFLOW_TABLE,
                    title=title,
                    safe_summary=summary,
                    safe_location=location,
                    public_safe=public_safe,
                    limitation=_WEBSITE_LIMITATION,
                    attached_project_ids=attached,
                )
            )
            continue

        for skill in supported:
            items.append(
                _make_item(
                    skill_name=skill,
                    proof_type=PROOF_WEBSITE,
                    source_id=session_id,
                    source_table=_WORKFLOW_TABLE,
                    title=title,
                    safe_summary=summary,
                    safe_location=location,
                    public_safe=public_safe,
                    limitation=_WEBSITE_LIMITATION,
                    attached_project_ids=attached,
                    locators={"public_url": target if public_safe else None},
                )
            )
    return items


def _collect_defense_video(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Defense / video evidence — always tied to its owning ``vbr_projects`` row.

    Reads each owned project's latest verification session telemetry
    (``project_defense_analysis`` skills + sanitized ``video_evidence_chips``).
    These are inherently attached to a project, so ``attached_project_ids`` is
    always the owning project.
    """
    items: list[dict[str, Any]] = []
    from app.services.vbr_question_generation import get_latest_session

    for project in _rows_for_user(db, _PROJECTS_TABLE, user_id):
        project_id = str(project.get("id") or "")
        if not project_id:
            continue
        session = get_latest_session(db, project_id)
        if not session:
            continue
        telemetry = session.get("telemetry") if isinstance(session.get("telemetry"), dict) else {}
        analysis = telemetry.get("project_defense_analysis")
        if isinstance(analysis, dict):
            explained = [str(s) for s in (analysis.get("skills_explained_well") or [])]
            mentioned = [str(s) for s in (analysis.get("skills_mentioned") or [])]
            summary = str(analysis.get("recruiter_summary") or analysis.get("transcript_summary") or "")
            seen: set[str] = set()
            for skill in explained + mentioned:
                key = _norm(skill)
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(
                    _make_item(
                        skill_name=skill,
                        proof_type=PROOF_DEFENSE,
                        source_id=str(session.get("id") or project_id),
                        source_table=_SESSIONS_TABLE,
                        title="Project Defense",
                        safe_summary=summary or "The candidate explained their own work during the Project Defense.",
                        safe_location="overall explanation",
                        public_safe=False,
                        limitation=_DEFENSE_LIMITATION,
                        attached_project_ids=[project_id],
                    )
                )

        for chip in telemetry.get("video_evidence_chips") or []:
            if not isinstance(chip, dict):
                continue
            related = str(chip.get("related_skill") or "").strip()
            label = str(chip.get("label") or "Video chip")
            timestamp_label = str(chip.get("timestamp") or chip.get("timestamp_label") or "").strip() or None
            items.append(
                _make_item(
                    skill_name=related or None,
                    proof_type=PROOF_VIDEO,
                    source_id=str(session.get("id") or project_id),
                    source_table=_SESSIONS_TABLE,
                    title=label,
                    safe_summary=str(chip.get("short_summary") or ""),
                    safe_location=label,
                    public_safe=False,
                    limitation=_VIDEO_LIMITATION,
                    attached_project_ids=[project_id],
                    locators={"timestamp_label": timestamp_label},
                )
            )
    return items


def _collect_skill_pipelines(
    pipeline_db: Any, user_id: str, attach: dict[tuple[str, str], list[str]]
) -> list[dict[str, Any]]:
    if pipeline_db is None:
        return []
    items: list[dict[str, Any]] = []
    for row in _rows_for_user(pipeline_db, _PIPELINES_TABLE, user_id, user_key="student_id"):
        pipeline_id = str(row.get("id") or "")
        skill = str(row.get("skill_name") or "").strip()
        if not pipeline_id or not skill:
            continue
        attached = attach.get((_PIPELINES_TABLE, pipeline_id), [])
        status = str(row.get("support_status") or "")
        label = _PIPELINE_STATUS_LABELS.get(status, "Supporting evidence")
        summary = (
            str(row.get("recruiter_summary") or row.get("student_summary") or "")
            or f"Skill Graph evidence for {skill} ({label.lower()})."
        )
        items.append(
            _make_item(
                skill_name=skill,
                proof_type=PROOF_SKILL_GRAPH,
                source_id=pipeline_id,
                source_table=_PIPELINES_TABLE,
                title=f"Skill Graph — {skill}",
                safe_summary=summary,
                safe_location=label,
                public_safe=False,
                limitation=_SKILL_GRAPH_LIMITATION,
                attached_project_ids=attached,
            )
        )
    return items


# ── Public API ───────────────────────────────────────────────────────────────


def collect_vault_items(db: Any, pipeline_db: Any, user_id: str) -> list[dict[str, Any]]:
    """Collect every safe, student-owned proof item across all proof sources.

    Reads each source table directly (attached *or not*), so the result is the
    student's whole proof vault — not just ``vbr_projects.metadata.attached_proofs``.
    """
    attach = _build_attachment_index(db, user_id)
    items: list[dict[str, Any]] = []
    items += _collect_github(db, user_id, attach)
    items += _collect_documents(db, user_id, attach)
    items += _collect_website(db, user_id, attach)
    items += _collect_defense_video(db, user_id)
    items += _collect_skill_pipelines(pipeline_db, user_id, attach)
    return items


def _group(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group skilled vault items by skill name (qualitative, recruiter-safe)."""
    by_skill: dict[str, dict[str, Any]] = {}
    for item in items:
        skill = item.get("skill_name")
        if not skill:
            continue
        key = _norm(str(skill))
        group = by_skill.get(key)
        if group is None:
            group = {
                "skill": str(skill),
                "proofs": [],
                "proof_types": [],
                "attached_count": 0,
                "unattached_count": 0,
                "has_unattached": False,
            }
            by_skill[key] = group
        group["proofs"].append(item)
        if item["proof_type"] not in group["proof_types"]:
            group["proof_types"].append(item["proof_type"])
        if item["is_attached_to_project"]:
            group["attached_count"] += 1
        else:
            group["unattached_count"] += 1
            group["has_unattached"] = True
    groups = list(by_skill.values())
    groups.sort(key=lambda g: g["skill"].lower())
    return groups


def group_vault_by_skill(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public: group all vault items by skill (for the Private Work Passport)."""
    return _group(items)


def vault_items_for_skills(
    items: list[dict[str, Any]],
    skills: list[str],
    *,
    exclude_project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Skill-grouped vault items matching ``skills``, optionally excluding any
    item already attached to ``exclude_project_id``.

    Powers a project report's "Other student proofs for related skills" section:
    pass the report's ``claimed_skills`` and the report's own ``project_id`` so a
    proof that *is* attached to this project is never duplicated as an "other"
    proof, and unattached / cross-project proofs surface honestly.
    """
    wanted = {_norm(s) for s in skills if str(s).strip()}
    if not wanted:
        return []
    filtered: list[dict[str, Any]] = []
    for item in items:
        skill = item.get("skill_name")
        if not skill or _norm(str(skill)) not in wanted:
            continue
        if exclude_project_id and exclude_project_id in (item.get("attached_project_ids") or []):
            continue
        filtered.append(item)
    return _group(filtered)


# ── Layer 1: compact skill summaries (main Passport — no website hydration) ────


def _project_titles(db: Any, user_id: str) -> dict[str, str]:
    """Map owned ``vbr_projects`` id → display title (for project usage labels)."""
    titles: dict[str, str] = {}
    for project in _rows_for_user(db, _PROJECTS_TABLE, user_id):
        pid = str(project.get("id") or "")
        if pid:
            titles[pid] = str(project.get("title") or "Untitled project")
    return titles


_REPO_IDENTITY_RE = re.compile(r"github\.com[/:]+([^/]+/[^/]+?)(?:\.git)?/?$", re.IGNORECASE)


def _project_meta(db: Any, user_id: str) -> dict[str, dict[str, Any]]:
    """Map owned ``vbr_projects`` id → safe matching metadata.

    Carries the display title plus normalized text tokens (title words + repo
    ``owner/name`` + repo name) used to correlate an *unattached* document to the
    project it most likely describes (by title/repo mention in the document's
    safe summary/snippet/title).
    """
    meta: dict[str, dict[str, Any]] = {}
    for project in _rows_for_user(db, _PROJECTS_TABLE, user_id):
        pid = str(project.get("id") or "")
        if not pid:
            continue
        title = str(project.get("title") or "Untitled project")
        repo_full = str(project.get("repo_full_name") or "").strip().lower()
        repo_url = str(project.get("repo_url") or "").strip().lower()
        if not repo_full and repo_url:
            m = _REPO_IDENTITY_RE.search(repo_url)
            repo_full = m.group(1) if m else ""
        repo_name = repo_full.split("/")[-1] if repo_full else ""
        meta[pid] = {
            "title": title,
            "title_norm": _norm(title),
            "repo_full": repo_full,
            "repo_name": repo_name,
        }
    return meta


# Order proof types are previewed in (most recruiter-verifiable first).
_PREVIEW_PRIORITY = {
    PROOF_GITHUB: 0,
    PROOF_WEBSITE: 1,
    PROOF_DOCUMENT: 2,
    PROOF_DEFENSE: 3,
    PROOF_VIDEO: 4,
    PROOF_SKILL_GRAPH: 5,
}
_MAX_PREVIEWS = 3


def _skill_status(
    proof_types: list[str],
    attached_count: int,
    *,
    skill: str | None = None,
    has_implementation_body: bool = False,
) -> str:
    """Qualitative skill label — never a numeric score.

    More distinct evidence sources (and any attached to a real project) ⇒ a
    stronger qualitative label. This is a grouping heuristic, not a trust score.

    For an IMPLEMENTATION-ORIENTED skill, "Demonstrated" additionally requires a
    real, SKILL-RELEVANT GitHub *implementation body*. A skill counts as
    implementation-oriented when it has a code profile (Machine Learning, API,
    React, Security, DevOps, MLOps …) OR when its evidence itself includes
    GitHub code proof — an unknown/unmapped IT skill claimed through code is
    still a code skill and must not escape the gate just because no profile
    regex knows its name. Weak GitHub (imports / docstrings / config / bare
    route decorator), cross-skill code, or an implementation body whose
    relevance never resolves past supporting/needs-review, plus a document and
    a defense, must NOT read as "Demonstrated" — that would contradict the
    honest "no primary implementation body was isolated" limitation. Such a
    skill is capped at "Evidence observed" until a skill-relevant primary
    implementation body exists. Skills with no code profile AND no GitHub
    evidence (e.g. Communication proven via documents + defense) are unaffected.
    """
    distinct = len({t for t in proof_types})
    if distinct >= 2 and attached_count:
        implementation_oriented = bool(skill) and (
            bool(skill_profile(skill)) or PROOF_GITHUB in proof_types
        )
        if implementation_oriented and not has_implementation_body:
            return "Evidence observed"
        return "Demonstrated"
    if distinct >= 2 or attached_count:
        return "Evidence observed"
    return "Supporting evidence"


def _effective_item_grade(item: dict[str, Any], skill: str | None) -> str | None:
    """Read-time VALIDATED grade for a vault item — the same ML semantic validation
    that :func:`collect_skill_report` applies when hydrating a card.

    A persisted GitHub ``implementation_body`` on an ML skill is only honoured when
    its trusted executable body actually carries an ML executable signal; a
    deployment-only / serving-only / route-only body (or one whose "ML" evidence is
    a stale reason / filename / function name) is DOWNGRADED here just as it is at
    hydration, so status evaluation never keys off a pre-validation grade.
    Non-GitHub items and non-ML skills are returned unchanged.
    """
    grade = item.get("evidence_quality_grade")
    if item.get("proof_type") != PROOF_GITHUB:
        return grade
    return effective_evidence_grade(
        grade,
        is_ml=is_ml_skill(skill) if skill else False,
        reason=item.get("selection_reason") or item.get("safe_summary"),
        code_snippet=item.get("safe_snippet"),
        file_path=item.get("file_path"),
        function_name=item.get("function_name"),
        ml_signal=item.get("ml_executable_signal"),
    )


def _item_is_skill_relevant_implementation(item: dict[str, Any], skill: str | None) -> bool:
    """True when a vault item is a validated GitHub implementation body whose
    SKILL RELEVANCE marks it as the selected skill's own implementation work.

    Both halves are recomputed at read time and fail closed:

    * the grade must survive :func:`_effective_item_grade` as
      ``implementation_body`` (an ML deployment-only body is downgraded), and
    * the block's resolved purpose × the selected skill's family must classify
      as direct/supporting implementation RELEVANCE — a ``cross_skill_context``
      implementation row (React UI code in a Machine Learning report, ML
      training code in a DevOps report), product UI context, deployment
      context, docs/setup/tests, or an unvalidated needs-review candidate can
      NEVER satisfy this, so it can never gate "Demonstrated".

    Skills with NO recognizable family (``general`` — an unknown/unmapped or
    future IT skill, or a niche name like "OAuth" the family regexes don't
    know) FAIL CLOSED like every other skill: :func:`classify_skill_relevance`
    resolves a ``general`` family to at most ``supporting_context`` /
    ``context_only_needs_review``, so an ``implementation_body`` grade ALONE can
    never satisfy this gate. Direct relevance requires a deterministic
    purpose × family mapping — an unmapped skill must first be added to the
    taxonomy (one place: the family regexes + purpose relevance maps in
    ``github_python_evidence_focus``) before its code can anchor "Demonstrated".
    """
    if item.get("proof_type") != PROOF_GITHUB:
        return False
    grade = _effective_item_grade(item, skill)
    if grade != GRADE_IMPLEMENTATION_BODY:
        return False
    purpose_key = effective_code_block_purpose(
        item.get("code_block_purpose_key"),
        grade=grade,
        code_snippet=item.get("safe_snippet"),
        selection_reason=item.get("selection_reason"),
        file_path=item.get("file_path"),
        function_name=item.get("function_name"),
    )
    return is_skill_implementation_relevance(
        classify_skill_relevance(
            purpose_key,
            skill=skill,
            grade=grade,
            ml_signal=item.get("ml_executable_signal"),
        )
    )


def _has_coherent_impl_chain(
    items: list[dict[str, Any]], *, skill: str | None = None
) -> bool:
    """True when a SINGLE attached project carries BOTH a skill-relevant GitHub
    implementation body AND independent corroboration (>= 2 distinct proof types),
    all attached to that same project.

    Skill status must be derived from the strongest COHERENT project chain, never
    from mixed global evidence: a standalone implementation body from project A plus
    weak attached evidence from a DIFFERENT project B must NOT read as
    "Demonstrated". Grouping by project identity keeps the implementation body and
    its corroboration inside the same chain, so an unrelated attached chain cannot
    be upgraded by a standalone implementation elsewhere.

    The implementation-body test uses
    :func:`_item_is_skill_relevant_implementation` — the read-time VALIDATED grade
    AND the read-time skill relevance, never the raw persisted
    ``evidence_quality_grade`` alone: an ML ``implementation_body`` row that is
    downgraded at read time (deployment-only body), or one whose relevance is
    ``cross_skill_context`` / product-UI / deployment context for THIS skill, must
    NOT count as coherent implementation evidence, so it can never combine with a
    defense / document to fabricate "Demonstrated".
    """
    by_project: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        if not it.get("is_attached_to_project"):
            continue
        for pid in it.get("attached_project_ids") or []:
            by_project.setdefault(pid, []).append(it)
    for chain_items in by_project.values():
        types = {i["proof_type"] for i in chain_items}
        has_impl = any(
            _item_is_skill_relevant_implementation(i, skill) for i in chain_items
        )
        if has_impl and len(types) >= 2:
            return True
    return False


def _preview_of(item: dict[str, Any]) -> dict[str, Any]:
    """A compact, safe preview of a vault item for the main Passport card."""
    return {
        "proof_type": item["proof_type"],
        "title": item.get("title") or "",
        "safe_location": item.get("safe_location"),
        "safe_summary": _trace_text(item.get("safe_summary") or "", 140),
        "is_attached_to_project": bool(item.get("is_attached_to_project")),
        "public_safe": bool(item.get("public_safe")),
    }


def collect_skill_summaries(
    db: Any, pipeline_db: Any, user_id: str, *, items: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Layer 1 — compact, recruiter-scannable skill summaries for the main Passport.

    Groups every safe vault proof by *canonical* skill name (aliases collapsed),
    and returns ONE compact card per skill: category, qualitative status, the
    projects it appears in, proof-source counts, attached/unattached counts, a
    short summary, and only the top few representative previews (with a
    ``more_count`` for the rest). It deliberately does NOT embed every proof card
    and does NOT hydrate website detail — that full evidence is loaded lazily by
    :func:`collect_skill_report` when the student opens one skill.

    ``items`` may be passed when the caller has already collected the vault (the
    Passport builder does, to avoid scanning the source tables twice).
    """
    if items is None:
        items = collect_vault_items(db, pipeline_db, user_id)
    titles = _project_titles(db, user_id)

    by_canon: dict[str, dict[str, Any]] = {}
    for item in items:
        raw = item.get("skill_name")
        if not raw:
            continue
        canon = canonical_skill(str(raw))
        key = _norm(canon)
        group = by_canon.get(key)
        if group is None:
            group = {
                "skill": canon,
                "category": skill_category(canon),
                "source_labels": [],
                "project_ids": [],
                "proof_source_counts": {},
                "_items": [],
                "attached_count": 0,
                "unattached_count": 0,
            }
            by_canon[key] = group
        group["_items"].append(item)
        if str(raw) not in group["source_labels"]:
            group["source_labels"].append(str(raw))
        group["proof_source_counts"][item["proof_type"]] = (
            group["proof_source_counts"].get(item["proof_type"], 0) + 1
        )
        for pid in item.get("attached_project_ids") or []:
            if pid not in group["project_ids"]:
                group["project_ids"].append(pid)
        if item.get("is_attached_to_project"):
            group["attached_count"] += 1
        else:
            group["unattached_count"] += 1

    summaries: list[dict[str, Any]] = []
    for group in by_canon.values():
        group_items = group.pop("_items")
        proof_types = list(group["proof_source_counts"].keys())
        # Coherent-chain gate (fix): a real implementation body counts toward
        # "Demonstrated" ONLY when it lives in the same attached project as its
        # corroboration — never a standalone body from an unrelated project.
        has_impl_body = _has_coherent_impl_chain(group_items, skill=group["skill"])
        ordered = sorted(
            group_items,
            key=lambda i: (
                0 if i.get("is_attached_to_project") else 1,
                _PREVIEW_PRIORITY.get(i["proof_type"], 9),
                0 if i.get("safe_location") else 1,
            ),
        )
        previews = [_preview_of(i) for i in ordered[:_MAX_PREVIEWS]]
        project_titles = [titles.get(pid, "Project") for pid in group["project_ids"]]
        unattached = group["unattached_count"]
        attached = group["attached_count"]
        total = attached + unattached
        limitations: list[str] = []
        if unattached:
            limitations.append(f"{unattached} proof(s) not attached to a VBR project.")
        if len(proof_types) == 1:
            limitations.append("Supported by a single evidence source — add another to strengthen it.")
        summaries.append(
            {
                "skill": group["skill"],
                "skill_slug": skill_slug(group["skill"]),
                "category": group["category"],
                "status": _skill_status(
                    proof_types, attached, skill=group["skill"], has_implementation_body=has_impl_body
                ),
                "source_labels": group["source_labels"],
                "project_ids": group["project_ids"],
                "project_titles": project_titles,
                "project_count": len(group["project_ids"]),
                "proof_source_counts": group["proof_source_counts"],
                "proof_count": total,
                "attached_count": attached,
                "unattached_count": unattached,
                "has_unattached": bool(unattached),
                "summary": (
                    f"{total} proof source(s) across {len(proof_types)} type(s) support this skill."
                ),
                "previews": previews,
                "more_count": max(0, total - len(previews)),
                "limitations": limitations,
            }
        )

    # Strongest first, then most-evidenced, then alphabetical.
    status_rank = {"Demonstrated": 0, "Evidence observed": 1, "Supporting evidence": 2}
    summaries.sort(
        key=lambda s: (status_rank.get(s["status"], 9), -int(s["proof_count"]), s["skill"].lower())
    )
    return summaries


# ── Layer 2: full Skill Report for ONE skill (hydrates website detail here) ────


def _report_item(
    item: dict[str, Any],
    titles: dict[str, str],
    *,
    hydrated: dict[str, Any] | None = None,
    skill: str | None = None,
) -> dict[str, Any]:
    """A rich, recruiter-verifiable evidence item for the Skill Report sections.

    ``skill`` (the report's canonical skill) drives read-time ML semantic validation
    of GitHub rows so a trusted deployment-only body stored as ``implementation_body``
    can never present as Machine Learning primary implementation proof.
    """
    row = {
        "proof_type": item["proof_type"],
        "source_id": item["source_id"],
        "title": item.get("title") or "",
        "safe_summary": item.get("safe_summary") or "",
        "safe_location": item.get("safe_location"),
        "safe_snippet": item.get("safe_snippet"),
        "public_safe": bool(item.get("public_safe")),
        "is_attached_to_project": bool(item.get("is_attached_to_project")),
        "attached_project_ids": list(item.get("attached_project_ids") or []),
        "project_titles": [titles.get(pid, "Project") for pid in (item.get("attached_project_ids") or [])],
        "limitation": item.get("limitation") or "",
        # Structured locators (already safe).
        "file_path": item.get("file_path"),
        "line_start": item.get("line_start"),
        "line_end": item.get("line_end"),
        "function_name": item.get("function_name"),
        "commit_sha": item.get("commit_sha"),
        "public_url": item.get("public_url"),
        # Explicit GitHub display-mode fields (frontend renders from these).
        "display_mode": item.get("display_mode"),
        "evidence_strength": item.get("evidence_strength"),
        "evidence_quality_grade": item.get("evidence_quality_grade"),
        "code_role_key": item.get("code_role_key"),
        "code_role_label": item.get("code_role_label"),
        "code_block_purpose_key": item.get("code_block_purpose_key"),
        "code_block_purpose_label": item.get("code_block_purpose_label"),
        "code_block_purpose_summary": item.get("code_block_purpose_summary"),
        "skill_relevance_key": item.get("skill_relevance_key"),
        "skill_relevance_label": item.get("skill_relevance_label"),
        "skill_relevance_summary": item.get("skill_relevance_summary"),
        "ml_executable_signal": item.get("ml_executable_signal"),
        "evidence_kind": item.get("evidence_kind"),
        "has_precise_line_evidence": item.get("has_precise_line_evidence"),
        "github_line_url": item.get("github_line_url"),
        "repo_url": item.get("repo_url"),
        # Canonical (old Profile & Proof) GitHub fields.
        "selection_reason": item.get("selection_reason"),
        "subskill_name": item.get("subskill_name"),
        "skill_graph_node": item.get("skill_graph_node"),
        "page_number": item.get("page_number"),
        "section_label": item.get("section_label"),
        "citation": item.get("citation"),
        "figure_reference": item.get("figure_reference"),
        "full_document_available": bool(item.get("full_document_available")),
        "question_text": item.get("question_text"),
        "answer_excerpt": item.get("answer_excerpt"),
        "timestamp_label": item.get("timestamp_label"),
        # Website-only hydrated fields (None for every other proof type).
        "workflow_summary": None,
        "workflow_steps": [],
        "dom_summary": None,
        "ocr_summary": None,
        "visual_summary": None,
        "live_check": None,
    }
    if item["proof_type"] == PROOF_GITHUB:
        # Read-time ML semantic validation FIRST: a trusted ``implementation_body``
        # that lacks actual ML executable signals (a deployment-only / serving-only /
        # cloud-only body) is downgraded to ``supporting_logic`` for an ML skill, so
        # it can never present as Machine Learning primary implementation proof. The
        # neutralisation below then keys off the VALIDATED grade.
        grade = effective_evidence_grade(
            item.get("evidence_quality_grade"),
            is_ml=is_ml_skill(skill),
            reason=item.get("selection_reason") or item.get("safe_summary"),
            code_snippet=item.get("safe_snippet"),
            file_path=item.get("file_path"),
            function_name=item.get("function_name"),
            ml_signal=item.get("ml_executable_signal"),
        )
        row["evidence_quality_grade"] = grade
        # Read-time code role, resolved against the VALIDATED grade. A weak /
        # fallback / ungraded row (including a stale legacy row with no role at
        # all) gets an honest grade-derived role — "Documentation / usage header",
        # "Imports / setup context", "Repository-level context" — never a role
        # inferred from a stale overclaiming ``selection_reason``. This is a LABEL
        # only; it never changes the grade above.
        role_key = effective_code_role(
            item.get("code_role_key"),
            grade=grade,
            code_snippet=item.get("safe_snippet"),
            selection_reason=item.get("selection_reason"),
            file_path=item.get("file_path"),
            function_name=item.get("function_name"),
        )
        row["code_role_key"] = role_key
        row["code_role_label"] = describe_code_role(role_key)
        # Read-time block purpose, resolved against the VALIDATED grade. A weak
        # structural band keeps an upstream purpose only when it is inside that
        # band's honest family (a snippet-refined documentation topic survives;
        # "Model training" riding on an import row is discarded), and a stale
        # legacy row with no purpose falls closed to repository-level context.
        # Label + summary come from the closed vocabulary — never stored text.
        purpose_key = effective_code_block_purpose(
            item.get("code_block_purpose_key"),
            grade=grade,
            code_snippet=item.get("safe_snippet"),
            selection_reason=item.get("selection_reason"),
            file_path=item.get("file_path"),
            function_name=item.get("function_name"),
        )
        row["code_block_purpose_key"] = purpose_key
        row["code_block_purpose_label"] = describe_code_block_purpose(purpose_key)
        row["code_block_purpose_summary"] = code_block_purpose_summary(purpose_key)
        # Read-time SKILL RELEVANCE, recomputed HERE against the report's selected
        # skill (never trusted from storage — a row filed under "Python" must not
        # carry a Python-relative relevance into a Machine Learning report). It is
        # derived only from the resolved purpose × skill family × the VALIDATED
        # grade, so cross-family evidence can never read as direct proof and a
        # weak row can never be promoted by its relevance wording.
        relevance_key = classify_skill_relevance(
            purpose_key,
            skill=skill,
            grade=grade,
            ml_signal=item.get("ml_executable_signal"),
        )
        row["skill_relevance_key"] = relevance_key
        row["skill_relevance_label"] = describe_skill_relevance(relevance_key, skill)
        row["skill_relevance_summary"] = skill_relevance_summary(relevance_key, skill)
        # Read-time neutralisation of a STALE persisted selection reason / summary. A
        # WEAK / fallback / ungraded GitHub row can never keep its stored reason —
        # even one that reads as technical ("model serving inference handler") — it is
        # replaced with an honest grade-derived / repository-level label. Only a
        # validated strong body (implementation_body / supporting_logic) keeps its
        # precise reason. Safe file path / line / function / "View code lines" links
        # are untouched; only the recruiter-facing reason/summary wording is corrected.
        if item.get("selection_reason"):
            row["selection_reason"] = safe_selection_reason(grade, item.get("selection_reason"))
        if not is_strong_grade(grade):
            row["safe_summary"] = safe_selection_reason(grade, row.get("safe_summary"))
    if hydrated:
        row["workflow_summary"] = hydrated.get("workflow_summary")
        row["workflow_steps"] = list(hydrated.get("workflow_steps") or [])
        row["dom_summary"] = hydrated.get("dom_summary")
        row["ocr_summary"] = hydrated.get("ocr_summary")
        row["visual_summary"] = hydrated.get("visual_summary")
        row["live_check"] = hydrated.get("live_check")
    return row


# ── Document correlation (proof-native: docs corroborate, never dump) ─────────
#
# A document is NEVER shown as a primary, standalone line-by-line dump. Instead
# each document evidence item is *correlated*: linked to the project (and the
# stronger artifact evidence) it most likely supports, and shown as a single
# "Document corroboration" card answering "what does this document corroborate?".

# Per-project document corroborations shown before "+N more". Standalone cap too.
_MAX_DOC_CORRELATIONS_PER_PROJECT = 3
_MAX_STANDALONE_DOC_CORRELATIONS = 5

_DOC_CORROBORATION_BASE_LIMITATION = (
    "Document supports the claim but does not independently prove implementation."
)
_DOC_PRIVATE_NOTE = "Private document; only a safe citation is shown."
_DOC_DOWNLOAD_GATED_NOTE = "Full document available only with candidate permission."


def _doc_corroborates_label(*, has_github: bool, has_website: bool, has_defense: bool) -> str:
    """What stronger evidence this document corroborates inside the chain."""
    if has_github:
        return "GitHub implementation"
    if has_website:
        return "Website workflow behavior"
    if has_defense:
        return "Skill explanation"
    return "Project architecture"


def _doc_correlation(
    item: dict[str, Any],
    *,
    corroborates: str,
    attached_to_project: bool,
    confidence: str | None = None,
) -> dict[str, Any]:
    """One safe "Document corroboration" card (never the raw document).

    ``confidence`` is the qualitative correlation confidence — "direct
    attachment", "title/project match", "skill-only match", or "weak/standalone"
    — so the UI can show how strongly the document is tied to the claim. A
    document is always *supporting* evidence, never primary proof of authorship.
    """
    limitations = [_DOC_CORROBORATION_BASE_LIMITATION, _DOC_PRIVATE_NOTE]
    if not attached_to_project:
        limitations.append(_UNATTACHED_NOTE)
    # Full-document download is gated on the student's explicit recruiter-share
    # opt-in. When not allowed, surface a safe permission note instead of any
    # path/URL (which are NEVER exposed here regardless of the flag).
    full_document_available = bool(item.get("full_document_available"))
    document_access_note = (
        "Full document shared by the candidate for recruiter review."
        if full_document_available
        else _DOC_DOWNLOAD_GATED_NOTE
    )
    return {
        "source_id": str(item["source_id"]),
        "document_title": item.get("title") or "Document",
        "page_number": item.get("page_number"),
        "section_label": item.get("section_label"),
        "citation": item.get("citation"),
        # Safe figure/diagram/table reference label (never the raw figure).
        "figure_reference": item.get("figure_reference"),
        "safe_snippet": item.get("safe_snippet"),
        "corroborates": corroborates,
        "correlation_confidence": confidence
        or ("direct attachment" if attached_to_project else "weak/standalone"),
        "reason": item.get("safe_summary") or "",
        # Why this page/section supports the skill — the analyzer's safe reason,
        # falling back to a deterministic "supports {corroborates}" sentence.
        "why_supported": (
            item.get("safe_summary")
            or f"This document section supports {corroborates.lower()} for this skill."
        ),
        # Documents corroborate; they are supporting evidence, never "Demonstrated".
        "support_label": "Supporting evidence",
        # Recruiter-safe download gating (no signed URL / storage path ever).
        "full_document_available": full_document_available,
        "document_access_note": document_access_note,
        "limitation": " ".join(limitations),
    }


def _dedupe_doc_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate document evidence by (title, page, snippet) — kills repeats."""
    seen: set[tuple[str, Any, str]] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = (
            str(it.get("title") or "").strip().lower(),
            it.get("page_number"),
            str(it.get("safe_snippet") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _evidence_item_key(e: dict[str, Any]) -> tuple:
    """Stable identity for a GitHub/Website/Defense/Video evidence item.

    Used to de-dupe evidence after several same-title project chains are merged.
    Covers GitHub line items (source + file/line/function + display_mode),
    repo-level GitHub (source + repo_url + display_mode), Website (source + url +
    workflow), and Defense/Video (source + question/timestamp/summary).
    """
    return (
        str(e.get("proof_type") or ""),
        str(e.get("source_id") or ""),
        str(e.get("file_path") or ""),
        e.get("line_start"),
        e.get("line_end"),
        str(e.get("function_name") or ""),
        str(e.get("display_mode") or ""),
        str(e.get("repo_url") or e.get("public_url") or ""),
        str(e.get("workflow_summary") or ""),
        str(e.get("question_text") or ""),
        str(e.get("timestamp_label") or ""),
        str(e.get("safe_summary") or ""),
    )


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for e in items:
        key = _evidence_item_key(e)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


# Compact code-location rows shown per repository BEFORE the "+N more" toggle.
_MAX_STANDALONE_GITHUB_ROWS_PER_REPO = 6
# Hard upper bound on rows carried per repository group. Rows beyond the visible
# window (above) are still included in the payload so the frontend can expand
# "+N more code locations" inline, but the total is bounded so a pathological repo
# never bloats the report. Strong implementation rows are ordered first, so any
# rows dropped past this cap are always the weakest/repo-level fallbacks.
_MAX_GITHUB_GROUP_ROWS_HARD_CAP = 18


def _github_row_label(e: dict[str, Any]) -> str:
    """Compact "file · function()/lines" label for one standalone GitHub row."""
    fp = str(e.get("file_path") or "").strip()
    if not fp:
        return str(e.get("title") or "Repository-level evidence")
    if e.get("function_name"):
        return f"{fp} · {e['function_name']}()"
    line_start = e.get("line_start")
    if line_start:
        line_end = e.get("line_end")
        rng = f"lines {line_start}" + (
            f"-{line_end}" if line_end and line_end != line_start else ""
        )
        return f"{fp} · {rng}"
    return fp


def _github_row_tier(row: dict[str, Any]) -> int:
    """Precise-vs-repo-level tier for a row. ``0`` = precise code line, ``1`` =
    other, ``2`` = repo-level fallback. Used as a SECONDARY key after the quality
    grade so precise code rows still sort above repo-level cards within a grade."""
    has_line = bool(row.get("file_path")) and row.get("line_start") is not None
    display_mode = str(row.get("display_mode") or "")
    if display_mode == "code_line" or has_line:
        return 0
    if display_mode == "repo_level":
        return 2
    return 1


def _github_row_rank(row: dict[str, Any]) -> tuple[int, int]:
    """Sort key ordering STRONG implementation rows above weak/repo-level rows.

    The PRIMARY key is the deterministic ``evidence_quality_grade`` band (so an
    ``implementation_body`` / ``supporting_logic`` row outranks a
    ``route_decorator_only`` / docstring / import / config / repo-level fallback
    row for the same repo). The SECONDARY key is the precise-vs-repo-level tier so
    a precise code line still sorts above an honest repo-level card within the same
    grade. Neither key is the file path: the sort is stable, so the upstream
    ML-pipeline relevance order (training / preprocessing / model / inference /
    metrics ahead of generic helpers) is preserved among equal-rank rows.
    """
    return (grade_rank(row.get("evidence_quality_grade")), _github_row_tier(row))


def _group_github_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group GitHub evidence by repository into compact row groups.

    Several code lines from the SAME repository are collapsed into one repository
    group with compact ``rows`` (a safe "file · lines" label + public ``…#L``
    link) instead of one full evidence card per line. Repositories are grouped
    ONLY by their canonical ``owner/name`` identity (an exact-owner match that
    must contain a ``/`` — never a bare repo name), so two different owners'
    same-named repos never merge. Evidence with NO canonical owner/repo identity
    (a legacy/ownerless row) is ambiguous: grouping it by title alone would
    wrongly merge two unrelated "shared-app" rows, so we fail closed and keep each
    such row as its own group, keyed by stable *internal* evidence identity
    (source_id / file / line range / display mode via :func:`_evidence_item_key`).
    That identity is only ever a grouping key — it is never exposed in the
    projected rows. ``repo_url`` is only carried when the repo is public-safe.
    Rows are de-duplicated, ordered precise-line-first, and capped per repo (the
    remainder is reported as ``row_more_count``). Returns ``[]`` for an empty
    list. Used for BOTH the standalone GitHub projection and each connected proof
    chain's "Code implementation" section so they render the same grouped model.
    """
    groups: list[dict[str, Any]] = []
    index: dict[Any, dict[str, Any]] = {}
    seen_rows: dict[Any, set[tuple]] = {}
    for e in items:
        repo_full, _name = _github_repo_identity(e)
        # Group ONLY by a confidently-known canonical ``owner/repo`` (must contain
        # a ``/``). A missing/ownerless identity falls back to stable evidence
        # identity — NEVER the title — so ambiguous legacy rows stay separate.
        if "/" in repo_full:
            key: Any = ("repo", repo_full)
        else:
            key = ("evidence", _evidence_item_key(e))
        group = index.get(key)
        if group is None:
            # ``repo_url`` is set on the item ONLY when the repo is public-safe
            # (see ``_collect_github``), so its presence is the public signal.
            repo_url = e.get("repo_url") or None
            group = {
                "repo_label": str(e.get("title") or "") or (repo_full or "GitHub repository"),
                "repo_url": repo_url,
                "repo_is_public": bool(repo_url),
                "rows": [],
                "row_more_count": 0,
            }
            index[key] = group
            seen_rows[key] = set()
            groups.append(group)
        elif not group["repo_url"] and e.get("repo_url"):
            # A later row for the same repo carried the public URL — promote it.
            group["repo_url"] = e["repo_url"]
            group["repo_is_public"] = True

        row_key = _evidence_item_key(e)
        if row_key in seen_rows[key]:
            continue
        seen_rows[key].add(row_key)
        group["rows"].append(
            {
                "source_id": str(e.get("source_id") or ""),
                "label": _github_row_label(e),
                "file_path": e.get("file_path"),
                "line_start": e.get("line_start"),
                "line_end": e.get("line_end"),
                "function_name": e.get("function_name"),
                "display_mode": e.get("display_mode"),
                # Deterministic quality band so the frontend ranks/excludes weak
                # rows (route_decorator_only / docstring / import / config /
                # repo-level fallback) instead of rendering them like real code.
                "evidence_quality_grade": e.get("evidence_quality_grade"),
                # Conservative DESCRIPTIVE role (already resolved against the
                # validated grade by ``_report_item``). Weak rows render this
                # instead of a stale/overclaiming ``selection_reason``.
                "code_role_key": e.get("code_role_key"),
                "code_role_label": e.get("code_role_label"),
                # Block-level purpose (already resolved against the validated
                # grade by ``_report_item``): what this exact block appears to
                # do, plus one short safe helper sentence. Labels only.
                "code_block_purpose_key": e.get("code_block_purpose_key"),
                "code_block_purpose_label": e.get("code_block_purpose_label"),
                "code_block_purpose_summary": e.get("code_block_purpose_summary"),
                # Skill relevance (already recomputed against the report's
                # selected skill by ``_report_item``). Labels only.
                "skill_relevance_key": e.get("skill_relevance_key"),
                "skill_relevance_label": e.get("skill_relevance_label"),
                "skill_relevance_summary": e.get("skill_relevance_summary"),
                "selection_reason": e.get("selection_reason"),
                "github_line_url": e.get("github_line_url"),
                "public_url": e.get("public_url"),
            }
        )
    # Order STRONG implementation rows above weak/repo-level rows by quality grade,
    # THEN bound (so a strong precise row is never demoted into "+N more" by mere
    # input order). Rows beyond the visible window are KEPT in the payload (up to
    # the hard cap) so "+N more code locations" can expand inline; ``row_more_count``
    # reports how many are initially collapsed.
    #
    # When a group has ANY strong (implementation_body / supporting_logic) row, the
    # visible window holds ONLY strong rows — every weak row (route_decorator_only /
    # docstring / import / config / repo-level fallback) is pushed into the
    # collapsed "+N more" remainder so it never appears as visible top evidence
    # beside real implementation code. When a group has no strong row, the least-bad
    # safe fallback is shown normally (the strongest weak rows fill the window).
    for group in groups:
        group["rows"].sort(key=_github_row_rank)
        rows = group["rows"][:_MAX_GITHUB_GROUP_ROWS_HARD_CAP]
        group["rows"] = rows
        strong_count = sum(1 for r in rows if is_strong_grade(r.get("evidence_quality_grade")))
        if strong_count:
            # Only strong rows are visible; weak rows collapse into "+N more".
            visible = min(strong_count, _MAX_STANDALONE_GITHUB_ROWS_PER_REPO)
        else:
            visible = min(len(rows), _MAX_STANDALONE_GITHUB_ROWS_PER_REPO)
        group["row_more_count"] = max(0, len(rows) - visible)
    return groups


def _doc_corr_key(c: dict[str, Any]) -> tuple:
    """Stable identity for a Document corroboration card (title/page/snippet)."""
    return (
        str(c.get("document_title") or "").strip().lower(),
        c.get("page_number"),
        str(c.get("safe_snippet") or "").strip().lower(),
    )


def _dedupe_doc_correlations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for c in items:
        key = _doc_corr_key(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _group_defense_evidence(
    defense: list[dict[str, Any]], video: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Collapse a chain's Project Defense + Video evidence into ONE grouped section.

    Repeated defense attempts produce many near-identical "the candidate explained
    their work" cards. This groups them into a single section: one concise
    explanation (the defense recruiter summary), the combined *cited moments*
    (video chips / timestamped or question-anchored defense moments, de-duplicated),
    a single merged limitation, and the count of grouped evidence items. No
    evidence is lost — the raw ``defense_evidence`` / ``video_evidence`` lists stay
    on the chain. Returns ``None`` when there is no defense/video evidence. Never
    exposes raw transcript text — only the already-safe summaries/labels.
    """
    combined = list(defense or []) + list(video or [])
    if not combined:
        return None

    # Concise explanation: the first non-empty Project Defense explanation, else
    # the first non-empty summary across the grouped evidence.
    explanation = ""
    for e in defense or []:
        s = str(e.get("safe_summary") or "").strip()
        if s:
            explanation = s
            break
    if not explanation:
        for e in combined:
            s = str(e.get("safe_summary") or "").strip()
            if s:
                explanation = s
                break

    # Cited moments: only items anchored to a concrete moment (a video timestamp
    # or a defense question) — the generic "overall explanation" defense cards are
    # folded into ``explanation`` above, never repeated as a moment. De-duplicated.
    moments: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for e in combined:
        ts = e.get("timestamp_label")
        q = e.get("question_text")
        if not ts and not q:
            continue
        label = str(e.get("title") or "").strip() or "Defense moment"
        summ = str(e.get("safe_summary") or "").strip()
        key = (label.lower(), str(ts or ""), str(q or ""), summ.lower())
        if key in seen:
            continue
        seen.add(key)
        moments.append(
            {
                "label": label,
                "timestamp_label": str(ts).strip() if ts else None,
                "question_text": str(q).strip() if q else None,
                "short_summary": summ,
                "source_id": str(e.get("source_id") or ""),
            }
        )

    limitations: list[str] = []
    for e in combined:
        lim = str(e.get("limitation") or "").strip()
        if lim and lim not in limitations:
            limitations.append(lim)

    return {
        "explanation": explanation,
        "moments": moments,
        "grouped_count": len(combined),
        "limitation": " ".join(limitations),
        "source_ids": [str(e.get("source_id") or "") for e in combined if e.get("source_id")],
    }


def _match_document_to_project(
    item: dict[str, Any], meta: dict[str, dict[str, Any]]
) -> str | None:
    """Best-effort link an UNATTACHED document to a project by title/repo mention.

    Scans the document's safe title + summary + snippet + location for a project
    title or repo name. Returns the matched ``project_id`` or ``None``.
    """
    haystack = _norm(
        " ".join(
            str(item.get(k) or "")
            for k in ("title", "safe_summary", "safe_snippet", "safe_location")
        )
    )
    if not haystack:
        return None
    for pid, m in meta.items():
        title_norm = str(m.get("title_norm") or "")
        repo_name = str(m.get("repo_name") or "")
        repo_full = str(m.get("repo_full") or "")
        if title_norm and len(title_norm) >= 4 and title_norm in haystack:
            return pid
        if repo_full and repo_full in haystack:
            return pid
        if repo_name and len(repo_name) >= 4 and repo_name in haystack:
            return pid
    return None


def _github_repo_identity(item: dict[str, Any]) -> tuple[str, str]:
    """Normalized ``(owner/name, name)`` repo identity for a GitHub evidence item."""
    repo_url = str(item.get("repo_url") or item.get("public_url") or "").strip().lower()
    if not repo_url:
        return "", ""
    m = _REPO_IDENTITY_RE.search(repo_url)
    repo_full = (m.group(1) if m else repo_url.rstrip("/")).lower()
    repo_name = repo_full.split("/")[-1] if repo_full else ""
    return repo_full, repo_name


def _match_github_to_project(
    item: dict[str, Any], meta: dict[str, dict[str, Any]]
) -> str | None:
    """Best-effort link an UNATTACHED GitHub proof to the project it belongs to.

    A GitHub proof carries its own authoritative repository identity, so it is
    folded into a project's main proof chain ONLY when it is the *exact same
    repository* — a canonical ``owner/name`` identity match. Matching by repo
    name alone is unsafe: ``bob/shared-app`` must never fold into a project built
    on ``alice/shared-app`` just because both end in ``shared-app``. So when the
    owner is missing or ambiguous on either side we fail closed and keep the proof
    genuinely standalone. URLs are normalized (``https://github.com/alice/x`` and
    ``git@github.com:alice/x.git`` both canonicalize to ``alice/x``) but the
    comparison is always owner+repo, case-normalized — never the bare name. A
    proof for a different repo is never folded in. The selected skill is constant
    across the report, so an exact-repo match here is a same-repo + same-skill +
    same-project-context match. Returns the matched ``project_id`` or ``None``.
    """
    repo_full, _repo_name = _github_repo_identity(item)
    # Require a canonical ``owner/name`` identity. A bare repo name (no owner, no
    # ``/``) is ambiguous, so we fail closed and leave the proof standalone.
    if "/" not in repo_full:
        return None
    for pid, m in meta.items():
        m_repo_full = str(m.get("repo_full") or "")
        if "/" in m_repo_full and m_repo_full == repo_full:
            return pid
    return None


def _related_github_items(
    items: list[dict[str, Any]], matched: list[dict[str, Any]], canon: str
) -> list[dict[str, Any]]:
    """Adjacent-tagged GitHub rows to relate into an ML skill's report (narrow).

    Returns the extra GitHub vault items (beyond exact-skill ``matched``) that
    belong to the SAME confirmed owner/repo, ``github_proof_submissions`` source,
    or attached project as an exact ML match, carry precise (strong/medium) line
    evidence, and are ML-specific per
    :func:`is_github_evidence_related_to_skill`. Returns ``[]`` for any non-ML
    skill (no broadening) or when there is no confirmed GitHub context — so exact
    owner/repo routing is never weakened and unrelated repos are never folded in.
    """
    if not is_ml_skill(canon):
        return []

    # Confirmed context: every repo / proof source / project that ALREADY has an
    # exact ML match. A candidate row must share one of these to be related in.
    confirmed_repos: set[str] = set()
    confirmed_sources: set[str] = set()
    confirmed_projects: set[str] = set()
    for i in matched:
        if i["proof_type"] != PROOF_GITHUB:
            continue
        repo_full, _name = _github_repo_identity(i)
        if "/" in repo_full:
            confirmed_repos.add(repo_full)
        if i.get("source_id"):
            confirmed_sources.add(str(i["source_id"]))
        for pid in i.get("attached_project_ids") or []:
            confirmed_projects.add(pid)
    if not (confirmed_repos or confirmed_sources or confirmed_projects):
        return []

    matched_obj_ids = {id(i) for i in matched}
    related: list[dict[str, Any]] = []
    for i in items:
        if id(i) in matched_obj_ids or i["proof_type"] != PROOF_GITHUB:
            continue
        # Only precise (strong/medium) line evidence is related in — never a
        # weak/repo-level row (those keep their own honest repo-level fallback).
        if not i.get("has_precise_line_evidence"):
            continue
        repo_full, _name = _github_repo_identity(i)
        same_context = (
            ("/" in repo_full and repo_full in confirmed_repos)
            or (bool(i.get("source_id")) and str(i["source_id"]) in confirmed_sources)
            or any(pid in confirmed_projects for pid in (i.get("attached_project_ids") or []))
        )
        if not same_context:
            continue
        if not is_github_evidence_related_to_skill(
            canon,
            evidence_skill=str(i.get("skill_name") or ""),
            file_path=i.get("file_path"),
            code_snippet=i.get("safe_snippet"),
            symbol_name=i.get("function_name"),
            mapping_reason=i.get("selection_reason") or i.get("safe_summary"),
            evidence_kind=i.get("evidence_kind"),
        ):
            continue
        related.append(i)
    return related


def _chain_summary(
    skill: str,
    project_title: str,
    gh: list,
    web: list,
    dfn: list,
    vid: list,
    docs: list,
) -> str:
    """One safe sentence describing how a project's proofs corroborate the skill."""
    parts: list[str] = []
    if gh:
        parts.append("GitHub code")
    if web:
        parts.append("a live website workflow")
    if dfn:
        parts.append("the Project Defense explanation")
    if vid:
        parts.append("video evidence")
    if docs:
        parts.append("document corroboration")
    if not parts:
        return f"{skill} appears in {project_title}."
    if len(parts) == 1:
        joined = parts[0]
    else:
        joined = ", ".join(parts[:-1]) + " and " + parts[-1]
    return (
        f"In {project_title}, {skill} is supported by {joined} — these sources corroborate the "
        "same skill claim."
    )


def _chain_proof_signature(chain: dict[str, Any]) -> tuple:
    """A stable proof-package key for a project chain (for duplicate collapse).

    Two chains are duplicates when they share the same normalized project title
    AND the same set of underlying proof source ids (GitHub / Website / Defense /
    Video / Document). The selected skill is constant across the whole report, so
    it is not part of the key. This collapses repeated VBR project rows that point
    at the same proofs without deleting any underlying data.
    """

    def _ids(items: list[dict[str, Any]]) -> tuple:
        return tuple(sorted({str(e.get("source_id") or "") for e in items if e.get("source_id")}))

    return (
        _norm(str(chain.get("project_title") or "")),
        _ids(chain.get("github_evidence") or []),
        _ids(chain.get("website_evidence") or []),
        _ids(chain.get("defense_evidence") or []),
        _ids(chain.get("video_evidence") or []),
        _ids(chain.get("document_correlations") or []),
    )


def _collapse_duplicate_chains(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate project chains that share the same proof package.

    Keeps ONE representative chain per ``(_chain_proof_signature)`` group, merges
    the collapsed project ids/count and de-dupes/unions limitations. Underlying
    proof data is never deleted — only the duplicate *report output* is collapsed.
    """
    by_sig: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for chain in projects:
        sig = _chain_proof_signature(chain)
        rep = by_sig.get(sig)
        if rep is None:
            by_sig[sig] = chain
            order.append(sig)
            continue
        # Merge this duplicate into the representative.
        for pid in chain.get("collapsed_project_ids") or []:
            if pid and pid not in rep["collapsed_project_ids"]:
                rep["collapsed_project_ids"].append(pid)
        rep["collapsed_project_count"] = len(rep["collapsed_project_ids"])
        for lim in chain.get("limitations") or []:
            if lim not in rep["limitations"]:
                rep["limitations"].append(lim)

    collapsed = [by_sig[sig] for sig in order]
    for rep in collapsed:
        if rep.get("collapsed_project_count", 1) > 1:
            note = (
                f"Repeated project attempts collapsed: {rep['collapsed_project_count']} VBR project rows "
                "share this same proof package; one representative chain is shown."
            )
            if note not in rep["limitations"]:
                rep["limitations"].insert(0, note)
    return collapsed


def _group_chains_by_title(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display-level grouping of project chains by normalized project title.

    Runs AFTER exact proof-package collapse. Local Boston-style data has many VBR
    attempts for the *same* project with *different* proof combinations (GitHub +
    Document, GitHub + Document + Defense, Document-only, …) — exact collapse keeps
    each as its own chain, so the Skill Report still shows many chains for one
    project. This step merges every same-title chain (the selected skill is
    constant across the whole report) into ONE display chain: it unions + de-dupes
    all GitHub / Website / Defense / Video evidence and Document corroborations,
    combines source badges, merges limitations, preserves "attached" if any
    grouped chain was attached, and records ``grouped_attempt_count`` /
    ``grouped_project_ids`` plus a "N related project attempts grouped" note. No
    underlying proof data is deleted — only the duplicate *display* chains merge.
    """
    by_title: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for chain in chains:
        key = _norm(str(chain.get("project_title") or ""))
        if key not in by_title:
            by_title[key] = []
            order.append(key)
        by_title[key].append(chain)

    grouped: list[dict[str, Any]] = []
    for key in order:
        group = by_title[key]
        rep = group[0]
        if len(group) == 1:
            grouped.append(rep)
            continue

        rep["github_evidence"] = _dedupe_evidence(
            [e for c in group for e in (c.get("github_evidence") or [])]
        )
        rep["website_evidence"] = _dedupe_evidence(
            [e for c in group for e in (c.get("website_evidence") or [])]
        )
        rep["defense_evidence"] = _dedupe_evidence(
            [e for c in group for e in (c.get("defense_evidence") or [])]
        )
        rep["video_evidence"] = _dedupe_evidence(
            [e for c in group for e in (c.get("video_evidence") or [])]
        )
        rep["document_correlations"] = _dedupe_doc_correlations(
            [d for c in group for d in (c.get("document_correlations") or [])]
        )

        sources: set[str] = set()
        for c in group:
            sources.update(c.get("sources") or [])
        rep["sources"] = sorted(sources)

        limitations: list[str] = []
        for c in group:
            for lim in c.get("limitations") or []:
                if lim not in limitations:
                    limitations.append(lim)
        # A same-title merge unions GitHub evidence across attempts: one attempt may
        # have had no GitHub proof (so it carried the derived "No GitHub code
        # evidence…" limitation) while another supplied it. After the union, that
        # derived limitation would contradict the now-nonempty merged evidence, so
        # recompute it: drop it when merged GitHub evidence exists. Genuine repo /
        # authorship limitations on the evidence items themselves are untouched.
        if rep.get("github_evidence"):
            limitations = [
                lim for lim in limitations if lim != _NO_GITHUB_CODE_EVIDENCE_LIMITATION
            ]

        grouped_count = sum(int(c.get("collapsed_project_count", 1) or 1) for c in group)
        grouped_ids: list[str] = []
        for c in group:
            ids = c.get("collapsed_project_ids") or (
                [c.get("project_id")] if c.get("project_id") else []
            )
            for pid in ids:
                if pid and pid not in grouped_ids:
                    grouped_ids.append(pid)

        rep["grouped_attempt_count"] = grouped_count
        rep["grouped_project_ids"] = grouped_ids
        rep["attached"] = any(c.get("attached") for c in group)

        note = f"{grouped_count} related project attempts grouped."
        if note not in limitations:
            limitations.insert(0, note)
        rep["limitations"] = limitations

        grouped.append(rep)
    return grouped


def collect_skill_report(
    db: Any, pipeline_db: Any, user_id: str, skill_name: str, *, synthesize: bool = True
) -> dict[str, Any]:
    """Layer 2 — the FULL, recruiter-verifiable evidence for ONE skill.

    Returns all of this student's safe proof evidence for ``skill_name``
    (canonicalised), grouped by proof source, with the concrete stored fields a
    recruiter can verify: GitHub file/line/function/snippet/link, Website
    workflow/OCR/DOM/visual/live-check summaries (hydrated HERE, only for this
    skill's website proofs), Document page/section/snippet/citation, and
    Defense/Video timestamp chips. Includes per-project usage and honest gaps.

    ``synthesize`` (default ``True``) embeds the Proof Synthesis Agent fields,
    which run the Step-4 LLM Synthesis Layer (so the configured provider is
    resolved). Callers that only need the deterministic per-source evidence — and
    must NOT trigger any LLM provider — pass ``synthesize=False`` to get the raw,
    synthesis-free report; the explicit Step-6 reanalysis gate does exactly this.
    """
    requested = str(skill_name)
    requested_slug = skill_slug(requested)
    items = collect_vault_items(db, pipeline_db, user_id)

    # Match by slug so a URL slug ("machine-learning") and any stored alias
    # ("ml", "Machine Learning") all resolve to the same skill.
    def _matches(raw: str) -> bool:
        return skill_slug(raw) == requested_slug or _norm(canonical_skill(raw)) == _norm(
            canonical_skill(requested)
        )

    matched = [i for i in items if i.get("skill_name") and _matches(str(i["skill_name"]))]

    # Canonical display name: prefer a real matched proof's canonical (so an
    # unknown-but-real skill keeps its stored casing); else fall back to request.
    canon = canonical_skill(str(matched[0]["skill_name"])) if matched else canonical_skill(requested)
    titles = _project_titles(db, user_id)
    meta = _project_meta(db, user_id)

    # ── Conservative GitHub evidence skill relation (ML connected reports) ─────
    # An ML report's exact canonical matching above drops genuine ML-pipeline
    # GitHub rows the analyzer tagged with an adjacent skill (Python / Machine
    # Learning Engineering) — so a connected ML project can show a single row even
    # when the SAME owner/repo holds many real ML rows (model instantiation,
    # prediction, training, evaluation). Relate those in HERE, narrowly: only for
    # an ML target skill, only precise (strong/medium) rows, only from a repo /
    # source / project ALREADY confirmed by an exact ML match (exact owner/repo
    # routing is never weakened), and only when the row is ML-specific (never a
    # generic Python helper/import/setup line — see ``is_github_evidence_related_to_skill``).
    matched += _related_github_items(items, matched, canon)

    github = [_report_item(i, titles, skill=canon) for i in matched if i["proof_type"] == PROOF_GITHUB]
    documents = [_report_item(i, titles) for i in matched if i["proof_type"] == PROOF_DOCUMENT]
    defense = [_report_item(i, titles) for i in matched if i["proof_type"] == PROOF_DEFENSE]
    video = [_report_item(i, titles) for i in matched if i["proof_type"] == PROOF_VIDEO]
    skill_graph = [_report_item(i, titles) for i in matched if i["proof_type"] == PROOF_SKILL_GRAPH]

    # Website: hydrate the deep safe detail HERE — and only for this skill's
    # website proofs (dedupe by session so a session isn't hydrated twice).
    website: list[dict[str, Any]] = []
    hydrated_cache: dict[str, dict[str, Any] | None] = {}
    for i in matched:
        if i["proof_type"] != PROOF_WEBSITE:
            continue
        sid = str(i["source_id"])
        if sid not in hydrated_cache:
            hydrated_cache[sid] = get_website_proof_detail(db, str(user_id), sid)
        website.append(_report_item(i, titles, hydrated=hydrated_cache[sid]))

    # De-duplicate document evidence up front (kills repeated identical snippets).
    documents = _dedupe_doc_items(documents)

    # ── Connected proof chains: documents corroborate, never dump ─────────────
    # Every project that has any artifact/defense evidence (or an attached doc).
    project_ids: list[str] = []
    for ev in github + website + defense + video + documents:
        for pid in ev.get("attached_project_ids") or []:
            if pid not in project_ids:
                project_ids.append(pid)

    # Route each document to the project it corroborates (attached → its project;
    # unattached → title/repo mention match), else to the standalone bucket. The
    # correlation confidence is held in a side-map keyed by the doc's identity so
    # we never pollute the (extra-forbidding) report item dicts themselves.
    project_docs: dict[str, list[dict[str, Any]]] = {pid: [] for pid in project_ids}
    standalone_docs: list[dict[str, Any]] = []
    doc_confidence: dict[int, str] = {}
    for doc in documents:
        attached_pids = [pid for pid in (doc.get("attached_project_ids") or []) if pid in project_docs]
        if attached_pids:
            doc_confidence[id(doc)] = "direct attachment"
            for pid in attached_pids:
                project_docs[pid].append(doc)
            continue
        matched_pid = _match_document_to_project(doc, meta)
        if matched_pid and matched_pid in project_docs:
            doc_confidence[id(doc)] = "title/project match"
            project_docs[matched_pid].append(doc)
        else:
            doc_confidence[id(doc)] = "weak/standalone"
            standalone_docs.append(doc)

    # Integrate UNATTACHED GitHub proofs that belong to a project that already
    # has a chain (same repo / project title) INTO that main chain, instead of
    # leaving them as duplicate "standalone supporting proofs" at the bottom. The
    # proof is never duplicated — a routed item is removed from the standalone
    # bucket. GitHub proofs that match no existing chain stay genuinely standalone.
    routed_github: dict[str, list[dict[str, Any]]] = {pid: [] for pid in project_ids}
    integrated_github_ids: set[int] = set()
    for e in github:
        if e.get("attached_project_ids"):
            continue
        matched_pid = _match_github_to_project(e, meta)
        if matched_pid and matched_pid in routed_github:
            routed_github[matched_pid].append(e)
            integrated_github_ids.add(id(e))

    projects: list[dict[str, Any]] = []
    for pid in project_ids:
        gh = _dedupe_evidence(
            [e for e in github if pid in (e.get("attached_project_ids") or [])]
            + routed_github.get(pid, [])
        )
        web = [e for e in website if pid in (e.get("attached_project_ids") or [])]
        dfn = [e for e in defense if pid in (e.get("attached_project_ids") or [])]
        vid = [e for e in video if pid in (e.get("attached_project_ids") or [])]
        docs_here = _dedupe_doc_items(project_docs.get(pid, []))
        corro_label = _doc_corroborates_label(
            has_github=bool(gh), has_website=bool(web), has_defense=bool(dfn or vid)
        )
        doc_corr_all = [
            _doc_correlation(
                d,
                corroborates=corro_label,
                attached_to_project=bool(d.get("attached_project_ids")),
                confidence=doc_confidence.get(id(d)),
            )
            for d in docs_here
        ]
        # Keep the FULL (per-project deduped) corroboration list on the chain; the
        # cap is applied ONCE at the very end, AFTER same-title chains are grouped,
        # so a grouped chain never repeats the same document across attempts.
        sources = sorted(
            {e["proof_type"] for e in gh + web + dfn + vid}
            | ({PROOF_DOCUMENT} if doc_corr_all else set())
        )
        limitations: list[str] = []
        if not gh:
            limitations.append(_NO_GITHUB_CODE_EVIDENCE_LIMITATION)
        if not web:
            limitations.append("No Website Proof in this project for this skill.")
        projects.append(
            {
                "project_id": pid,
                "project_title": titles.get(pid, "Project"),
                "attached": True,
                "attached_status": "Attached to a VBR project",
                "sources": sources,
                "evidence_chain_summary": _chain_summary(
                    canon, titles.get(pid, "Project"), gh, web, dfn, vid, doc_corr_all
                ),
                "github_evidence": gh,
                "website_evidence": web,
                "document_correlations": doc_corr_all,
                "document_more_count": 0,
                "defense_evidence": dfn,
                "video_evidence": vid,
                "limitations": limitations,
                "collapsed_project_count": 1,
                "collapsed_project_ids": [pid],
                "grouped_attempt_count": 1,
                "grouped_project_ids": [pid],
            }
        )

    # Local DBs often hold several VBR project rows with the SAME title and the
    # SAME attached proof package (repeated "Boston" defense attempts). First
    # collapse exact-duplicate proof packages, then group every remaining
    # same-title chain (different proof combinations of the same project) into ONE
    # display chain so the Skill Report doesn't render many chains for one project.
    projects = _collapse_duplicate_chains(projects)
    projects = _group_chains_by_title(projects)

    # Cap document corroborations PER (possibly grouped) chain — applied here, once,
    # so the cap counts deduped documents across all grouped attempts.
    for chain in projects:
        full = _dedupe_doc_correlations(chain.get("document_correlations") or [])
        chain["document_correlations"] = full[:_MAX_DOC_CORRELATIONS_PER_PROJECT]
        chain["document_more_count"] = max(0, len(full) - _MAX_DOC_CORRELATIONS_PER_PROJECT)

    # ── Standalone bucket (proofs not attached to any VBR project) ────────────
    # GitHub proofs already integrated into a project chain (same repo/title) are
    # excluded here so they are never shown twice (chain + standalone).
    standalone_github = _dedupe_evidence(
        [
            e
            for e in github
            if not e.get("attached_project_ids") and id(e) not in integrated_github_ids
        ]
    )
    standalone_website = [e for e in website if not e.get("attached_project_ids")]
    standalone_defense = [e for e in defense if not e.get("attached_project_ids")]
    standalone_video = [e for e in video if not e.get("attached_project_ids")]
    standalone_docs = _dedupe_doc_items(standalone_docs)
    standalone_corr_label = _doc_corroborates_label(
        has_github=bool(standalone_github),
        has_website=bool(standalone_website),
        has_defense=bool(standalone_defense or standalone_video),
    )
    standalone_doc_corr_all = [
        _doc_correlation(
            d,
            corroborates=standalone_corr_label,
            attached_to_project=False,
            confidence=doc_confidence.get(id(d)) or "weak/standalone",
        )
        for d in standalone_docs
    ]
    standalone_doc_corr = standalone_doc_corr_all[:_MAX_STANDALONE_DOC_CORRELATIONS]
    standalone_doc_more = max(0, len(standalone_doc_corr_all) - len(standalone_doc_corr))

    standalone_evidence = {
        "github": standalone_github,
        # Repository-grouped, de-duplicated projection of the standalone GitHub
        # evidence above — compact rows per repo (the UI renders this, never one
        # full card per code line). ``github`` stays for back-compat.
        "github_groups": _group_github_evidence(standalone_github),
        "website": standalone_website,
        "documents": standalone_doc_corr,
        "document_more_count": standalone_doc_more,
        "defense": standalone_defense,
        "video": standalone_video,
        "skill_graph": skill_graph,
    }

    has_standalone = bool(
        standalone_github
        or standalone_website
        or standalone_defense
        or standalone_video
        or skill_graph
        or standalone_doc_corr
    )
    if has_standalone:
        projects.append(
            {
                "project_id": None,
                "project_title": "Student Proof Vault (not attached to a VBR project)",
                "attached": False,
                "attached_status": _UNATTACHED_NOTE,
                "sources": sorted(
                    {
                        e["proof_type"]
                        for e in standalone_github
                        + standalone_website
                        + standalone_defense
                        + standalone_video
                        + skill_graph
                    }
                    | ({PROOF_DOCUMENT} if standalone_doc_corr else set())
                ),
                "evidence_chain_summary": (
                    "Standalone proofs that support this skill but are not attached to a VBR project."
                ),
                "github_evidence": standalone_github,
                "website_evidence": standalone_website,
                "document_correlations": standalone_doc_corr,
                "document_more_count": standalone_doc_more,
                "defense_evidence": standalone_defense,
                "video_evidence": standalone_video,
                "limitations": [_UNATTACHED_NOTE],
            }
        )

    # Collapse each chain's Project Defense + Video evidence into ONE grouped
    # section so a chain never renders many repeated "the candidate explained
    # their work" cards (the raw lists are kept intact — no evidence is lost).
    # Also project each chain's GitHub implementation evidence through the SAME
    # repository-grouped model used for standalone GitHub (compact "file · lines"
    # rows grouped per canonical owner/repo) so connected "Code implementation"
    # reads as one grouped block per repo instead of a weaker single card. The
    # flat ``github_evidence`` stays for back-compat; ``github_groups`` is the
    # primary projection the UI renders.
    for chain in projects:
        chain["defense_group"] = _group_defense_evidence(
            chain.get("defense_evidence") or [], chain.get("video_evidence") or []
        )
        chain["github_groups"] = _group_github_evidence(chain.get("github_evidence") or [])

    # ── Overview + gaps ──────────────────────────────────────────────────────
    proof_source_counts: dict[str, int] = {}
    for i in matched:
        proof_source_counts[i["proof_type"]] = proof_source_counts.get(i["proof_type"], 0) + 1
    attached_count = sum(1 for i in matched if i.get("is_attached_to_project"))
    unattached_count = len(matched) - attached_count
    proof_types = list(proof_source_counts.keys())
    attached_project_count = sum(1 for p in projects if p.get("attached"))

    gaps: list[str] = []
    if unattached_count:
        gaps.append(f"{unattached_count} proof(s) for this skill are not attached to a VBR project.")
    if not github:
        gaps.append("No GitHub repository evidence for this skill — code authorship is unverified here.")
    elif all(not g.get("file_path") for g in github):
        gaps.append(
            "GitHub evidence is repo-level only (no file/line-level code located) — reanalysis "
            "could surface stronger line-level proof."
        )
    if not website:
        gaps.append("No Website Proof maps to this skill — a working deployment was not demonstrated.")
    if not documents:
        gaps.append("No document evidence cites this skill.")
    if not (defense or video):
        gaps.append("No Project Defense or video evidence covers this skill.")

    summary = (
        f"{len(matched)} safe proof source(s) across {len(proof_types)} type(s) support {canon}."
    )
    # A real GitHub implementation body is required before an implementation-oriented
    # skill reads as "Demonstrated" (see :func:`_skill_status`) — and it must live in
    # a COHERENT attached project chain (implementation body + corroboration in the
    # SAME project), never a standalone body from an unrelated project.
    has_impl_body = _has_coherent_impl_chain(matched, skill=canon)
    status = _skill_status(
        proof_types, attached_count, skill=canon, has_implementation_body=has_impl_body
    )

    report = {
        "skill": canon,
        "skill_slug": skill_slug(canon),
        "requested_skill": requested,
        "category": skill_category(canon),
        "status": status,
        "summary": summary,
        "source_counts": proof_source_counts,
        "overview": {
            "skill": canon,
            "category": skill_category(canon),
            "status": status,
            "proof_source_counts": proof_source_counts,
            "proof_count": len(matched),
            "attached_count": attached_count,
            "unattached_count": unattached_count,
            "project_count": attached_project_count,
            "why_supported": summary,
            "gaps": gaps,
        },
        "projects": projects,
        "standalone_evidence": standalone_evidence,
        "github": github,
        "website": website,
        "documents": documents,
        "defense": defense,
        "video": video,
        "skill_graph": skill_graph,
        "gaps": gaps,
        "generated_at": "",
    }

    # Proof Synthesis Agent — connect the per-source evidence above into
    # recruiter-verifiable proof chains (confidence tier, evidence-cited synthesis
    # statements, why-linked) and a capped "unlinked supporting evidence" bucket.
    # This runs the Step-4 LLM Synthesis Layer, so it is skipped entirely when a
    # caller asks for the synthesis-free report (``synthesize=False``) — that path
    # never resolves or calls an LLM provider.
    if synthesize:
        from app.services.proof_synthesis_agent_service import synthesize_skill_report

        report.update(synthesize_skill_report(report))
    return report


def collect_related_skill_proofs(
    db: Any,
    pipeline_db: Any,
    user_id: str,
    project_id: str | None,
    skill_names: list[str],
) -> list[dict[str, Any]]:
    """Summary-only vault matches for a project report's "Other student proofs"
    section: this student's other safe proofs that match ``skill_names`` but are
    NOT attached to ``project_id``. Grouped by skill, never a full raw dump.
    """
    items = collect_vault_items(db, pipeline_db, user_id)
    return vault_items_for_skills(items, skill_names, exclude_project_id=project_id)
