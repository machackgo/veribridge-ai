"""Phase 1 — Individual Project Defense service.

Deterministic, non-LLM logic for:
  - creating a project-defense project identity (vbr_projects + metadata)
  - generating deterministic defense questions (vbr_session_questions)
  - saving manual/pasted defense answers as a transcript + segments
    (vbr_transcripts / vbr_transcript_segments)
  - running deterministic transcript analysis and storing the result in
    vbr_verification_sessions.telemetry.project_defense_analysis

Phase 1 is individual-student proof only. Team proof, live screen/camera
recording, speaker diarization, and final public report publishing are out
of scope.

``vbr_projects.repo_url`` is required by the existing schema (NOT NULL).
Phase 1 therefore requires a ``repo_url`` either directly or derived from an
attached GitHub proof — see ``_resolve_repo_url_and_proof``.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.schemas.vbr_project_defense import (
    ProjectDefenseCreateRequest,
    SubmitDefenseAnswersRequest,
)
from app.services.github_evidence_service import parse_github_repo_url
from app.services.github_proof_service import GitHubProofNotFoundError, GitHubProofService
from app.services.optional_evidence_service import OptionalEvidenceService
from app.services.safe_public_url import safe_repo_relative_path
from app.services.defense_answer_evidence_service import (
    build_defense_answer_evidence,
    explained_skills_from_answer_evidence,
)
from app.services.project_defense_analysis_service import analyze_defense_transcript
from app.services.project_defense_evidence_chips import build_evidence_chips
from app.services.website_proof_summary_service import get_website_proof_summary
from app.services.vbr_question_generation import (
    _create_session,
    _delete_session_questions,
    _insert_questions,
    get_active_session,
    list_session_questions,
)
from app.services.vbr_session_recording import update_session_telemetry

_PROJECTS_TABLE = "vbr_projects"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"
_QUESTIONS_TABLE = "vbr_session_questions"

_MAX_SKILL_QUESTIONS = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(text: str | None, max_len: int = 300) -> str:
    if not text:
        return ""
    return str(text)[:max_len]


# ── Safe display-value sanitizers (scrub values, not only keys) ───────────────
#
# Allowlisting *keys* is not enough — an approved field can still carry an
# unsafe *value*: a document "title" that is really a local/storage path
# (``/Users/alice/private/report.pdf``), a website "target_website" that is a
# signed URL with a token/signature query, a provider blob, or a raw storage
# path smuggled into a display string. These helpers scrub the *values* that
# surface in evidence labels, context DTOs, and generated questions so a private
# filesystem location, signed URL, or secret token can never leak through a
# display field.

# Fragments that mark a storage path, signed URL, provider blob, or secret token
# anywhere inside a value (case-insensitive).
_UNSAFE_VALUE_MARKERS = (
    "://",  # any scheme: file://, https://, s3://, gs://, supabase://, …
    "s3:",
    "gs:",
    "supabase",
    "/storage/v1/object",
    "/object/sign",
    "access_token",
    "token=",
    "signature=",
    "x-amz-",
    "x-goog-",
)

# A leading Windows drive letter (``C:\`` / ``C:/``) — unsafe as a display value.
_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def _looks_like_path_or_secret(text: str) -> bool:
    """Return ``True`` when ``text`` looks like a file/storage path or carries a
    signed-URL / token / provider-secret fragment — i.e. it must never surface
    as a display label.

    Deliberately conservative in the *other* direction too: an ordinary title
    that merely contains a colon (``Summary: Q3``) or a dot (``Final
    Report.pdf``) is NOT flagged, so legitimate document titles survive.
    """
    candidate = (text or "").strip()
    if not candidate:
        return False
    lowered = candidate.lower()
    # Absolute POSIX path, home-relative path, or UNC / backslash path.
    if candidate.startswith(("/", "~", "\\")):
        return True
    if _WINDOWS_DRIVE_RE.match(candidate):
        return True
    if any(marker in lowered for marker in _UNSAFE_VALUE_MARKERS):
        return True
    return False


def _safe_display_title(value: Any, fallback: str = "Document proof") -> str:
    """Scrub a display title so a raw file/storage path or signed URL can never
    surface. A path-/secret-looking value is replaced with ``fallback`` (never a
    ``lstrip('/')``-normalized fake path); an ordinary title is trimmed as
    before."""
    text = str(value or "").strip()
    if not text:
        return fallback
    if _looks_like_path_or_secret(text):
        return fallback
    return _truncate(text, 120)


def _safe_website_display(value: Any) -> str:
    """Safe display for a website target: ``scheme://host`` only, dropping any
    path / query / fragment / userinfo so a token or signature in a signed URL
    can never appear. Falls back to a bare hostname, else ``""``.

    A non-http(s) scheme (``s3://``, ``file://``, ``javascript:``) never has its
    scheme or path echoed — at most a bare host is surfaced.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text if "//" in text else "//" + text)
        host = (parts.hostname or "").strip().lower()
    except ValueError:
        return ""
    if not host:
        return ""
    scheme = (parts.scheme or "").lower()
    if scheme in ("http", "https"):
        return f"{scheme}://{host}"
    # No scheme (bare host) or a non-http scheme — surface only the safe host.
    return host


_SCORE_FRAGMENT_RE = re.compile(r"\s*\b\d+\s*/\s*\d+\b(?:\s*confidence)?", re.IGNORECASE)


def _strip_score_fragments(text: str) -> str:
    """Remove numeric score fragments (e.g. ``72/100 confidence``) from summary
    text so grounded questions never surface a raw score — the Final Report and
    public projections forbid ``/100`` style scores in traces."""
    return re.sub(r"\s{2,}", " ", _SCORE_FRAGMENT_RE.sub("", text)).strip()


# A single ``owner``/``repo`` path segment on github.com: must start with an
# alphanumeric and contain only the characters GitHub itself allows in a
# namespace/repo name. Anything else (a query string, an ``@`` userinfo, a path
# traversal, a signed-URL blob) fails to match and is rejected.
_GITHUB_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_github_repo_display(repo_url: Any) -> tuple[str | None, str | None]:
    """Return a canonical, safe ``(label, url)`` for a GitHub repo, else
    ``(None, None)``.

    The stored ``repo_url`` is **never** echoed verbatim. Only a *normal*
    ``github.com/{owner}/{repo}`` repository is surfaced, and only its
    reconstructed ``owner/repo`` label and canonical
    ``https://github.com/{owner}/{repo}`` URL — any query string, fragment,
    userinfo, or extra path (``/tree/…``, ``/blob/…``) is dropped so a signed-URL
    token or signature can never ride along. A non-github.com host
    (``raw.githubusercontent.com`` / provider / signed storage / localhost),
    an ``s3://`` / ``file://`` URL, or a bare file path all yield
    ``(None, None)`` so the caller falls back to a neutral label.
    """
    text = str(repo_url or "").strip()
    if not text:
        return None, None
    try:
        parts = urlsplit(text if "//" in text else "https://" + text)
    except ValueError:
        return None, None
    host = (parts.hostname or "").strip().lower()
    if host not in ("github.com", "www.github.com"):
        return None, None
    segments = [seg for seg in parts.path.strip("/").split("/") if seg]
    if len(segments) < 2:
        return None, None
    owner, repo = segments[0], segments[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not (_GITHUB_SEGMENT_RE.match(owner) and _GITHUB_SEGMENT_RE.match(repo)):
        return None, None
    return f"{owner}/{repo}", f"https://github.com/{owner}/{repo}"


# Numeric evidence-score / confidence language that must never surface in a
# public summary. Covers the label-first, label-last, and bare-fraction forms:
# ``score: 0.91`` · ``confidence 87%`` · ``rating 8/10`` · ``72/100 confidence``
# · ``87% confidence`` · bare ``72/100``.
_SUMMARY_SCORE_RES = (
    re.compile(
        r"\b(?:score|confidence|rating|rated)\b\s*[:=]?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+|\s*%)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+(?:\.\d+)?(?:\s*/\s*\d+|\s*%)?\s*(?:confidence|score|rating|rated)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+\s*/\s*\d+\b", re.IGNORECASE),
)


# Standalone credential / private-identifier language that must never surface in
# a public summary, even when it is *not* embedded in a URL or query string (so
# the whitespace-token drop in :func:`_looks_like_path_or_secret` never sees it).
# Every match is replaced with ``[redacted]`` so neither the key label nor the
# secret/private value survives, while surrounding safe prose is preserved.
_REDACTED = "[redacted]"
_SECRET_RES = (
    # ``authorization: Bearer <token>`` / a bare ``Bearer <token>`` — matched
    # first (spans two whitespace tokens) so the token can never be re-exposed.
    re.compile(r"\b(?:authorization\s*[:=]\s*)?bearer\s+\S+", re.IGNORECASE),
    # ``key=value`` / ``key: value`` credential + private-identifier assignments.
    # The value (``\S+``) is redacted together with its key label.
    re.compile(
        r"\b(?:"
        r"api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"secret|token|password|passwd|pwd|"
        r"source[_-]?id|user[_-]?id|private[_-]?id|provider[_-]?id|account[_-]?id|client[_-]?id"
        r")\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    # Provider token/key formats that are unsafe even standing entirely alone:
    # GitHub PATs (``ghp_`` / ``github_pat_`` / ``gho_`` / ``ghu_`` / ``ghs_`` /
    # ``ghr_``), OpenAI-style ``sk-…`` keys, Slack ``xox…`` tokens, AWS access
    # key ids (``AKIA…``), and Google API keys (``AIza…``).
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+", re.IGNORECASE),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{3,}", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}"),
)


def _scrub_secrets(text: str) -> str:
    """Redact standalone credential / private-identifier language in ``text``.

    Runs on the whole string (not a whitespace-token split) so multi-token
    secrets — ``Authorization: Bearer ghp_…`` — are caught as one unit. Each
    unsafe phrase becomes ``[redacted]``; safe surrounding prose is untouched.
    """
    for pattern in _SECRET_RES:
        text = pattern.sub(_REDACTED, text)
    return text


def _safe_public_summary(value: Any, max_len: int = 300) -> str:
    """Sanitize a GitHub ``public_safe_summary`` *value* before it is exposed.

    Three scrubs run, so an approved key can never carry an unsafe value:

    * Standalone credential / private-identifier language — ``api_key=sk-…``,
      ``client_secret=…``, ``Authorization: Bearer …``, a bare ``ghp_…`` /
      ``github_pat_…`` / ``sk-…`` token, ``source_id=user_…`` — is redacted (see
      :func:`_scrub_secrets`). This runs on the full string first so a secret
      spanning two whitespace tokens (``Bearer <token>``) is caught.
    * Any remaining whitespace token that looks like a URL, storage path,
      signed-URL blob, or secret/token fragment (see
      :func:`_looks_like_path_or_secret`) is dropped — a signed link or
      ``token=…`` fragment can never appear.
    * Numeric evidence-score / confidence language (``72/100 confidence``,
      ``score: 0.91``, ``confidence 87%``, ``rating 8/10``) is removed.

    Ordinary safe prose about the evidence type, repo topics, files, commits, or
    implementation areas is kept.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = _scrub_secrets(text)
    kept = [tok for tok in text.split() if not _looks_like_path_or_secret(tok)]
    text = " ".join(kept)
    for pattern in _SUMMARY_SCORE_RES:
        text = pattern.sub("", text)
    return _truncate(re.sub(r"\s{2,}", " ", text).strip(" .,:;-"), max_len)


def _clean_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            out.append(text)
    return list(dict.fromkeys(out))


def _safe_evidence_file_paths(repo_metadata: Any) -> list[str]:
    """Safe, repo-relative evidence file paths the GitHub analyzer flagged.

    Read ONLY from ``repo_metadata.evidence_files`` (a list of repo-relative
    path strings) — never the rest of ``repo_metadata`` (which may hold raw
    analysis dumps / secrets). Entries that look like absolute URLs or that
    escape the repo root are dropped so the report can build file-level traces
    and public ``…/blob/<branch>/<path>`` links without ever leaking a raw
    snapshot, storage path, or external URL. Capped to keep the summary small.
    """
    if not isinstance(repo_metadata, dict):
        return []
    out: list[str] = []
    for raw in repo_metadata.get("evidence_files") or []:
        # Reject absolute / local / Windows / UNC / file:// paths outright —
        # never lstrip("/") them into a fake repo-relative path (would leak a
        # private filesystem location into public evidence traces).
        path = safe_repo_relative_path(raw)
        if not path:
            continue
        out.append(path)
    return list(dict.fromkeys(out))[:20]


# ── Project identity creation ────────────────────────────────────────────────


def _github_proof_summary(db: Any, user_id: str, github_proof_id: str) -> dict[str, Any]:
    """Build a safe summary for an owned GitHub proof.

    Raises ``ValueError("github_proof_not_found")`` if the proof is missing or
    owned by another user. Stores only safe, already-derived fields — never the
    raw ``repo_metadata`` payload.
    """
    try:
        proof = GitHubProofService(db).get_github_proof(user_id, github_proof_id)
    except GitHubProofNotFoundError as exc:
        raise ValueError("github_proof_not_found") from exc

    return {
        "github_proof_id": github_proof_id,
        "repo_url": proof.repo_url,
        "repo_owner": proof.repo_owner,
        "repo_name": proof.repo_name,
        "default_branch": (proof.default_branch or "").strip() or None,
        "status": proof.status,
        "detected_skills": _clean_list(proof.detected_skills),
        "public_safe_summary": _truncate(proof.public_safe_summary or "", 300),
        # Safe repo-relative file paths only (no raw repo_metadata) so the
        # report can build file-level GitHub traces instead of repo-level
        # cards. Empty ⇒ the report honestly falls back to repo-level.
        "evidence_files": _safe_evidence_file_paths(proof.repo_metadata),
    }


def _resolve_repo_url_and_proof(
    db: Any, user_id: str, body: ProjectDefenseCreateRequest
) -> tuple[str, dict[str, Any] | None]:
    """Resolve ``repo_url`` for the new project.

    Priority: explicit ``body.repo_url`` > repo_url from an attached GitHub
    proof > ``body.attached_proofs.repo_url`` fallback. Raises ``ValueError``
    with a known code if no repo_url can be resolved or the referenced GitHub
    proof is not owned by ``user_id``.
    """
    repo_url = (body.repo_url or "").strip()
    github_summary: dict[str, Any] | None = None

    github_proof_id = (body.attached_proofs.github_proof_id or "").strip() or None
    if github_proof_id:
        github_summary = _github_proof_summary(db, user_id, github_proof_id)
        if not repo_url:
            repo_url = (github_summary.get("repo_url") or "").strip()

    if not repo_url:
        repo_url = (body.attached_proofs.repo_url or "").strip()

    if not repo_url:
        raise ValueError("repo_url_required")

    return repo_url, github_summary


def _validate_skill_pipeline_ownership(pipeline_db: Any, user_id: str, skill_pipeline_ids: list[str]) -> None:
    """Validate that every ``skill_pipeline_ids`` entry belongs to ``user_id``.

    Raises ``ValueError("skill_pipeline_not_found")`` if any ID is missing or
    owned by another user.
    """
    from app.services.skill_evidence_pipeline_service import (
        PipelineNotFoundError,
        SkillEvidencePipelineService,
    )

    svc = SkillEvidencePipelineService(pipeline_db)
    for pipeline_id in skill_pipeline_ids:
        try:
            svc.get_pipeline(pipeline_id, user_id)
        except PipelineNotFoundError as exc:
            raise ValueError("skill_pipeline_not_found") from exc


def _safe_document_skills(row: dict[str, Any]) -> list[str]:
    """Safe, deduped skill names a document *explicitly* evidences.

    Read only from the analyzer's structured ``evidence_objects`` (skill names
    only — never raw snippets, page text, file paths, or numeric scores). When a
    document has no structured skill evidence this returns ``[]`` so the report
    treats it as project-level context rather than per-skill proof.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in row.get("evidence_objects") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("skill_name") or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _document_summaries(db: Any, user_id: str, document_evidence_ids: list[str]) -> list[dict[str, Any]]:
    """Return safe summaries for attached document proofs.

    Raises ``ValueError("document_evidence_not_found")`` if any ID is not
    owned by ``user_id``.
    """
    svc = OptionalEvidenceService(db)
    summaries: list[dict[str, Any]] = []
    for doc_id in document_evidence_ids:
        doc_id = str(doc_id).strip()
        if not doc_id:
            continue
        row = svc.get_by_id(user_id=user_id, evidence_id=doc_id)
        if row is None:
            raise ValueError("document_evidence_not_found")
        analysis_json = row.get("analysis_json") or {}
        # Safe title only: analyzer title > student-set title > generic fallback.
        # Never fall back to ``file_path`` — it may be a raw storage path and
        # must never surface as a public/owner-visible document title. The value
        # is additionally scrubbed so an analyzer/student title that is itself a
        # local/storage path or signed URL is replaced with a safe fallback.
        title = analysis_json.get("title") or row.get("title") or "Document"
        summaries.append(
            {
                "document_evidence_id": doc_id,
                "title": _safe_display_title(title, fallback="Document"),
                "source_type": row.get("source_type"),
                "status": row.get("status"),
                # Safe skill names the analyzer matched in this document. Used by
                # the report to map the document to ONLY these skills (never to
                # every claimed skill); empty ⇒ project-level evidence.
                "skills": _safe_document_skills(row),
            }
        )
    return summaries


def _website_proof_summaries(db: Any, user_id: str, website_proof_session_ids: list[str]) -> list[dict[str, Any]]:
    """Return safe summaries for attached Website Proof sessions.

    Raises ``ValueError("website_proof_not_found")`` if any ID is not owned
    by ``user_id`` (or has no completed analysis).
    """
    summaries: list[dict[str, Any]] = []
    for proof_session_id in website_proof_session_ids:
        proof_session_id = str(proof_session_id).strip()
        if not proof_session_id:
            continue
        summary = get_website_proof_summary(db, user_id, proof_session_id)
        if summary is None:
            raise ValueError("website_proof_not_found")
        summaries.append(summary)
    return summaries


def create_project_defense(
    db: Any, pipeline_db: Any, user_id: str, body: ProjectDefenseCreateRequest
) -> dict[str, Any]:
    """Create a Phase 1 individual Project Defense project identity.

    Stores only IDs and safe summaries of attached proofs in
    ``vbr_projects.metadata.attached_proofs`` — never raw proof payloads.

    Raises ``ValueError("website_proof_not_found")`` if any
    ``website_proof_session_ids`` entry is not owned by ``user_id``, and
    ``ValueError("skill_pipeline_not_found")`` if any ``skill_pipeline_ids``
    entry is not owned by ``user_id``.
    """
    repo_url, github_summary = _resolve_repo_url_and_proof(db, user_id, body)

    repo_ref = parse_github_repo_url(repo_url)
    if repo_ref is None:
        raise ValueError("invalid_github_repo_url")
    repo_full_name = f"{repo_ref.owner}/{repo_ref.repo}"

    website_proof_session_ids = _clean_list(body.attached_proofs.website_proof_session_ids)
    website_proof_summaries = _website_proof_summaries(db, user_id, website_proof_session_ids)

    skill_pipeline_ids = _clean_list(body.attached_proofs.skill_pipeline_ids)
    if skill_pipeline_ids:
        _validate_skill_pipeline_ownership(pipeline_db, user_id, skill_pipeline_ids)

    document_summaries = _document_summaries(db, user_id, body.attached_proofs.document_evidence_ids)

    attached_proofs: dict[str, Any] = {}
    if github_summary:
        attached_proofs["github_proof"] = github_summary
    elif body.attached_proofs.github_proof_id:
        attached_proofs["github_proof_id"] = body.attached_proofs.github_proof_id

    if website_proof_summaries:
        attached_proofs["website_proofs"] = website_proof_summaries

    if document_summaries:
        attached_proofs["documents"] = document_summaries

    if skill_pipeline_ids:
        attached_proofs["skill_pipeline_ids"] = skill_pipeline_ids

    now = _now()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "user_id": user_id,
        "title": body.title.strip(),
        "repo_url": repo_url,
        "repo_full_name": repo_full_name,
        "deployed_url": None,
        "head_sha": None,
        "status": "draft",
        "metadata": {
            "description": body.description.strip(),
            "claimed_skills": _clean_list(body.claimed_skills),
            "student_role": body.student_role.strip(),
            "individual_project_only": True,
            "attached_proofs": attached_proofs,
            "phase": "project_defense_mvp_v1",
        },
        "created_at": now,
        "updated_at": now,
    }

    if isinstance(db, dict):
        db.setdefault(_PROJECTS_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_PROJECTS_TABLE).insert(row).execute()
    inserted = getattr(result, "data", []) or []
    if not inserted:
        raise RuntimeError("vbr_projects insert returned no data.")
    return inserted[0]


# ── Project-first defense flow (select an existing project to defend) ────────
#
# Project Defense is a defense layer on top of an existing project — not a
# fourth standalone proof form. These helpers power the "choose a project to
# defend" selection view and the selected-project workspace. They read ONLY the
# safe summaries already stored in ``vbr_projects.metadata`` (built by the
# attach/create paths above), so no raw proof payloads, storage paths, signed
# URLs, provider JSON, or numeric scores are ever re-derived here.


# ── Allowlisted safe projection of attached_proofs ───────────────────────────
#
# ``vbr_projects.metadata.attached_proofs`` is stored by the create/attach paths
# with safe summaries, but legacy rows may carry unsafe fields (raw provider
# JSON, storage paths, signed URLs, private proof IDs, raw document text, or
# numeric evidence scores). Anything read back for the workspace *context* view
# or for grounding defense questions goes through this allowlist first so those
# fields can never leak. Only the safe display fields survive.


def _safe_github_proof_view(github: Any) -> dict[str, Any] | None:
    """Allowlisted GitHub proof summary (or None when there is no GitHub signal).

    Scrubs *values*, not only keys:

    * ``repo_url`` is never echoed verbatim. Only a canonical
      ``https://github.com/{owner}/{repo}`` — reconstructed from a value that
      clearly parses as a normal github.com repository — is surfaced; a signed
      URL, tokenized URL, raw/provider URL, non-GitHub storage URL, localhost
      URL, or file path yields ``None`` (callers fall back to a neutral label).
    * ``repo_owner`` / ``repo_name`` are re-derived from that same safe parse (or
      from clean owner/name fields), never trusted from raw input.
    * ``public_safe_summary`` is scrubbed of numeric evidence-score / confidence
      language and of any URL / signed-URL / token / secret fragment.
    """
    if not isinstance(github, dict):
        return None
    raw_owner = str(github.get("repo_owner") or "").strip()
    raw_name = str(github.get("repo_name") or "").strip()
    summary = _safe_public_summary(github.get("public_safe_summary"))

    label, safe_url = _safe_github_repo_display(github.get("repo_url"))
    # Fall back to owner/name fields only when they are clean GitHub segments —
    # never echo an owner/name that is itself a path or signed-URL fragment.
    if label is None and _GITHUB_SEGMENT_RE.match(raw_owner) and _GITHUB_SEGMENT_RE.match(raw_name):
        label = f"{raw_owner}/{raw_name}"
        safe_url = f"https://github.com/{raw_owner}/{raw_name}"

    # No GitHub signal at all (no raw repo_url, no owner/name, no summary) ⇒
    # nothing to display.
    if not (str(github.get("repo_url") or "").strip() or raw_owner or raw_name or summary):
        return None

    return {
        "repo_url": safe_url or "",
        "repo_owner": label.split("/", 1)[0] if label else None,
        "repo_name": label.split("/", 1)[1] if label else None,
        "status": (str(github.get("status")).strip() or None) if github.get("status") else None,
        "detected_skills": _clean_list(github.get("detected_skills")),
        "public_safe_summary": summary,
    }


def _safe_document_view(doc: Any) -> dict[str, Any] | None:
    """Allowlisted document summary — safe title/status/skills only.

    The title *value* is scrubbed (not just key-allowlisted): a legacy title
    that is really a local/storage path or signed URL is replaced with a safe
    fallback so it can never surface as a display label.
    """
    if not isinstance(doc, dict):
        return None
    return {
        "title": _safe_display_title(doc.get("title")),
        "source_type": (str(doc.get("source_type")).strip() or None) if doc.get("source_type") else None,
        "status": (str(doc.get("status")).strip() or None) if doc.get("status") else None,
        "skills": _clean_list(doc.get("skills")),
    }


def _safe_website_view(website: Any) -> dict[str, Any] | None:
    """Allowlisted website proof summary — safe target/confidence/skills only.

    The ``target_website`` *value* is scrubbed to ``scheme://host`` only, so a
    signed URL's token/signature query or a storage path can never surface.
    """
    if not isinstance(website, dict):
        return None
    return {
        "target_website": _safe_website_display(website.get("target_website")),
        "workflow_confidence": (
            str(website.get("workflow_confidence")).strip() or None
        )
        if website.get("workflow_confidence")
        else None,
        "supported_skills": _clean_list(website.get("supported_skills")),
    }


def sanitize_attached_proofs(attached: Any) -> dict[str, Any]:
    """Return an allowlisted copy of ``attached_proofs``.

    Drops any field that is not on the safe display allowlist — including raw
    provider JSON, storage paths, signed URLs, private proof/evidence IDs, raw
    document text, and numeric evidence scores.
    """
    if not isinstance(attached, dict):
        return {}
    out: dict[str, Any] = {}

    github = _safe_github_proof_view(attached.get("github_proof"))
    if github:
        out["github_proof"] = github

    documents = [view for d in (attached.get("documents") or []) if (view := _safe_document_view(d))]
    if documents:
        out["documents"] = documents

    websites = [view for w in (attached.get("website_proofs") or []) if (view := _safe_website_view(w))]
    if websites:
        out["website_proofs"] = websites

    return out


def safe_project_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted metadata projection for the selected-project context view."""
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "description": str(metadata.get("description") or ""),
        "claimed_skills": _clean_list(metadata.get("claimed_skills")),
        "student_role": str(metadata.get("student_role") or ""),
        "individual_project_only": bool(metadata.get("individual_project_only", True)),
        "attached_proofs": sanitize_attached_proofs(metadata.get("attached_proofs")),
        "phase": str(metadata.get("phase") or "project_defense_mvp_v1"),
    }


def _evidence_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build a safe per-type attached/missing evidence summary from metadata.

    Every label is built from the *sanitized* projection of ``attached_proofs``
    (see :func:`sanitize_attached_proofs`), so an evidence label can never leak
    a raw storage path, signed URL, provider blob, private id, or numeric score
    smuggled into a legacy field value.
    """
    attached = sanitize_attached_proofs(metadata.get("attached_proofs"))

    github = attached.get("github_proof")
    github_attached = isinstance(github, dict)
    github_label = ""
    if github_attached:
        # ``repo_owner`` / ``repo_name`` come from the sanitized projection
        # (canonical github.com parse), so ``owner/repo`` is safe to echo. When
        # the repo could not be safely parsed, fall back to a neutral label —
        # never echo the raw ``repo_url`` value.
        owner = github.get("repo_owner")
        name = github.get("repo_name")
        github_label = f"{owner}/{name}" if owner and name else "GitHub proof"

    documents = attached.get("documents")
    doc_titles = [
        _safe_display_title(d.get("title"))
        for d in (documents if isinstance(documents, list) else [])
        if isinstance(d, dict)
    ]

    websites = attached.get("website_proofs")
    web_labels = [
        (str(w.get("target_website") or "").strip() or "Website proof")
        for w in (websites if isinstance(websites, list) else [])
        if isinstance(w, dict)
    ]

    defense_completed = str(metadata.get("project_defense_status") or "") == "analyzed"

    return {
        "github_proof": {
            "attached": github_attached,
            "count": 1 if github_attached else 0,
            "label": github_label,
        },
        "documents": {
            "attached": len(doc_titles) > 0,
            "count": len(doc_titles),
            "label": ", ".join(doc_titles),
        },
        "website_proof": {
            "attached": len(web_labels) > 0,
            "count": len(web_labels),
            "label": ", ".join(web_labels),
        },
        "project_defense": {
            "attached": defense_completed,
            "count": 1 if defense_completed else 0,
            "label": "Completed" if defense_completed else "",
        },
    }


def _project_defense_status(db: Any, project: dict[str, Any]) -> str:
    """Deterministic defense status: not_started | in_progress | completed."""
    metadata = project.get("metadata") or {}
    if str(metadata.get("project_defense_status") or "") == "analyzed":
        return "completed"
    session = get_active_session(db, str(project["id"]))
    if session is not None and list_session_questions(db, str(session["id"])):
        return "in_progress"
    return "not_started"


def _report_ready(defense_status: str) -> bool:
    """Conservative report gating — a project report is only surfaced once the
    defense analysis has completed. Document-only / questions-only states are
    intentionally NOT report-ready."""
    return defense_status == "completed"


# ── Duplicate-project canonicalization + merge ───────────────────────────────
#
# A student can accumulate several ``vbr_projects`` rows for the SAME logical
# project — one per proof form they started from, plus historical drafts. The
# project-first Project Defense listing must collapse those into ONE canonical
# card per logical project (target model: one Project → GitHub / Document /
# Website / Defense), merging their evidence rather than showing many near-empty
# duplicates. These helpers implement a conservative dedupe: rows are grouped by
# a stable identity key (normalized project TITLE as the primary discriminator,
# strengthened by — never decided by — the repository) and their safe evidence
# summaries are merged. Repository is deliberately NOT sufficient on its own: a
# single monorepo can hold many distinct projects (e.g. a Billing Service and an
# Analytics Dashboard both in ``acme/mono``), and those must stay separate cards.

_WHITESPACE_RE = re.compile(r"\s+")

_DEFENSE_STATUS_RANK = {"not_started": 1, "in_progress": 2, "completed": 3}


def _normalize_text(value: Any) -> str:
    """Lowercase + whitespace-collapsed text for identity comparison."""
    return _WHITESPACE_RE.sub(" ", str(value or "").strip().lower())


def _normalized_repo_identity(project: dict[str, Any]) -> str:
    """Canonical ``owner/repo`` (lowercased) for a project, or ``""``.

    Prefers the stored ``repo_full_name``; falls back to parsing ``repo_url``.
    Every project row carries a repo (``vbr_projects.repo_url`` is NOT NULL), so
    this is a strong *strengthening* signal for the canonical key — but it is
    NOT sufficient on its own to merge two rows, because a single monorepo can
    hold many distinct projects (see :func:`_canonical_project_key`).
    """
    full_name = str(project.get("repo_full_name") or "").strip().lower()
    if full_name:
        return full_name.strip("/")
    ref = parse_github_repo_url(str(project.get("repo_url") or "").strip())
    if ref is not None:
        return f"{ref.owner}/{ref.repo}".lower()
    return ""


def _canonical_project_key(project: dict[str, Any]) -> tuple:
    """Conservative identity key used to group duplicate project rows.

    The normalized project TITLE is the primary discriminator. A shared
    repository can *strengthen* a match but must never merge two different
    project titles on its own — a single monorepo can hold many distinct
    projects (a Billing Service and an Analytics Dashboard both in ``acme/mono``
    must stay separate). Two rows therefore collapse only when their normalized
    titles AND repository identities agree.

    An untitled row falls back to repo + description prefix + claimed-skill set
    so it still groups with its own duplicates without repo alone being enough.
    """
    metadata = project.get("metadata") or {}
    title = _normalize_text(project.get("title"))
    repo = _normalized_repo_identity(project)
    if title:
        return ("title_repo", title, repo)
    description_prefix = _normalize_text(metadata.get("description"))[:120]
    skills = tuple(sorted({s.lower() for s in _clean_list(metadata.get("claimed_skills"))}))
    return ("repo_desc", repo, description_prefix, skills)


def group_duplicate_projects(projects: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group project rows by canonical identity, preserving first-seen order."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    order: list[tuple] = []
    for project in projects:
        key = _canonical_project_key(project)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(project)
    return [groups[key] for key in order]


def _group_defense_status(db: Any, group: list[dict[str, Any]]) -> str:
    """Strongest defense status across a duplicate group.

    completed > in_progress > not_started — so a card never regresses to a
    weaker duplicate's status.
    """
    best = 1
    for project in group:
        best = max(best, _DEFENSE_STATUS_RANK.get(_project_defense_status(db, project), 1))
    for status, rank in _DEFENSE_STATUS_RANK.items():
        if rank == best:
            return status
    return "not_started"


def _pick_canonical_project(db: Any, group: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the strongest project row to own the canonical id.

    Priority: strongest defense status (so its real session / analysis is the
    one resumed) → has an attached GitHub proof → most recently updated. The
    winner's id is what the frontend uses for context / question generation, so
    it must be the row that actually holds the strongest defense state.
    """

    def sort_key(project: dict[str, Any]) -> tuple:
        status_rank = _DEFENSE_STATUS_RANK.get(_project_defense_status(db, project), 1)
        metadata = project.get("metadata") or {}
        attached = metadata.get("attached_proofs") or {}
        github = attached.get("github_proof") if isinstance(attached, dict) else None
        has_github = 1 if (isinstance(github, dict) and github.get("repo_url")) else 0
        return (status_rank, has_github, str(project.get("updated_at") or ""))

    return max(group, key=sort_key)


def _merge_group_metadata(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge the safe metadata of a duplicate group into one canonical view.

    Only already-safe summary fields are combined (no raw payloads are touched):
      - description: prefer the most complete (longest) one
      - claimed_skills: union, deduped, order-preserving
      - student_role: first non-empty
      - GitHub proof: the first duplicate that carries an attached proof summary
        (so the card shows Attached when ANY duplicate has GitHub, never Missing
        merely because the strongest row lacked its own GitHub metadata)
      - documents / website proofs: unioned + de-duplicated by stable id
      - project_defense_status: analyzed if ANY duplicate has completed analysis
    """
    descriptions = [
        str((p.get("metadata") or {}).get("description") or "").strip() for p in group
    ]
    best_description = max(descriptions, key=len) if descriptions else ""

    claimed: list[str] = []
    student_role = ""
    for project in group:
        metadata = project.get("metadata") or {}
        claimed.extend(_clean_list(metadata.get("claimed_skills")))
        if not student_role:
            student_role = str(metadata.get("student_role") or "").strip()
    claimed_skills = list(dict.fromkeys(claimed))

    merged_github: dict[str, Any] | None = None
    merged_documents: list[dict[str, Any]] = []
    merged_websites: list[dict[str, Any]] = []
    skill_pipeline_ids: list[str] = []
    analyzed = False

    for project in group:
        metadata = project.get("metadata") or {}
        if str(metadata.get("project_defense_status") or "") == "analyzed":
            analyzed = True
        attached = metadata.get("attached_proofs") or {}
        if not isinstance(attached, dict):
            continue

        github = attached.get("github_proof")
        if merged_github is None and isinstance(github, dict) and github.get("repo_url"):
            merged_github = github

        documents = attached.get("documents")
        if isinstance(documents, list):
            merged_documents = _merge_summaries_by_key(
                merged_documents,
                [d for d in documents if isinstance(d, dict)],
                "document_evidence_id",
            )

        websites = attached.get("website_proofs")
        if isinstance(websites, list):
            merged_websites = _merge_summaries_by_key(
                merged_websites,
                [w for w in websites if isinstance(w, dict)],
                "proof_session_id",
            )

        pipeline_ids = attached.get("skill_pipeline_ids")
        if isinstance(pipeline_ids, list):
            skill_pipeline_ids = list(dict.fromkeys([*skill_pipeline_ids, *_clean_list(pipeline_ids)]))

    attached_proofs: dict[str, Any] = {}
    if merged_github:
        attached_proofs["github_proof"] = merged_github
    if merged_documents:
        attached_proofs["documents"] = merged_documents
    if merged_websites:
        attached_proofs["website_proofs"] = merged_websites
    if skill_pipeline_ids:
        attached_proofs["skill_pipeline_ids"] = skill_pipeline_ids

    merged: dict[str, Any] = {
        "description": best_description,
        "claimed_skills": claimed_skills,
        "student_role": student_role,
        "individual_project_only": True,
        "attached_proofs": attached_proofs,
        "phase": "project_defense_mvp_v1",
    }
    if analyzed:
        merged["project_defense_status"] = "analyzed"
    return merged


def build_merged_project(db: Any, group: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a synthetic canonical project (best row's id + merged metadata)."""
    canonical = _pick_canonical_project(db, group)
    return {**canonical, "metadata": _merge_group_metadata(group)}


def _find_project_group(db: Any, user_id: str, project_id: str) -> list[dict[str, Any]]:
    """All project rows sharing the canonical identity of ``project_id``.

    Returns a single-element group when the project stands alone. Owner-scoped
    via ``list_eligible_projects``; the caller has already enforced ownership of
    ``project_id`` itself.
    """
    projects = list_eligible_projects(db, user_id)
    target = next((p for p in projects if str(p["id"]) == str(project_id)), None)
    if target is None:
        return []
    key = _canonical_project_key(target)
    return [p for p in projects if _canonical_project_key(p) == key]


def merge_owned_project(db: Any, user_id: str, project: dict[str, Any]) -> dict[str, Any]:
    """Return ``project`` with metadata merged across its duplicate group.

    The returned dict keeps the requested project's id (so defense sessions bind
    consistently) but exposes the merged, strongest evidence package — never a
    weaker duplicate that happens to be missing GitHub.
    """
    group = _find_project_group(db, user_id, str(project["id"])) or [project]
    return {**project, "metadata": _merge_group_metadata(group)}


def list_eligible_projects(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Return the current user's projects, most recent first. Owner-scoped."""
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_PROJECTS_TABLE, {}).values()
            if str(row.get("user_id")) == str(user_id)
        ]
        rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return rows

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return getattr(result, "data", []) or []


def build_eligible_project_summary(db: Any, project: dict[str, Any]) -> dict[str, Any]:
    """Safe selection-card summary for one project (no raw proof payloads)."""
    metadata = project.get("metadata") or {}
    defense_status = _project_defense_status(db, project)
    return {
        "id": str(project["id"]),
        "title": project.get("title") or "",
        "description": str(metadata.get("description") or ""),
        "claimed_skills": _clean_list(metadata.get("claimed_skills") or []),
        "repo_full_name": project.get("repo_full_name"),
        "defense_status": defense_status,
        "report_ready": _report_ready(defense_status),
        "evidence": _evidence_summary(metadata),
        "created_at": str(project.get("created_at") or ""),
        "updated_at": str(project.get("updated_at") or ""),
    }


def build_merged_eligible_summary(db: Any, group: list[dict[str, Any]]) -> dict[str, Any]:
    """Safe selection-card summary for one *logical* project (a duplicate group).

    The card exposes the strongest defense status, merged evidence, and the
    canonical project id — so clicking "Defend" opens the best row's workspace
    with the combined evidence rather than a near-empty duplicate.
    """
    canonical = _pick_canonical_project(db, group)
    merged_metadata = _merge_group_metadata(group)
    defense_status = _group_defense_status(db, group)
    return {
        "id": str(canonical["id"]),
        "title": canonical.get("title") or "",
        "description": str(merged_metadata.get("description") or ""),
        "claimed_skills": _clean_list(merged_metadata.get("claimed_skills") or []),
        "repo_full_name": canonical.get("repo_full_name"),
        "defense_status": defense_status,
        "report_ready": _report_ready(defense_status),
        "evidence": _evidence_summary(merged_metadata),
        "created_at": str(canonical.get("created_at") or ""),
        "updated_at": str(canonical.get("updated_at") or ""),
    }


def list_deduped_eligible_summaries(db: Any, user_id: str) -> list[dict[str, Any]]:
    """One canonical, evidence-merged selection card per logical project.

    Collapses duplicate/historical ``vbr_projects`` rows (see
    :func:`group_duplicate_projects`) so the project-first listing shows the
    target model — one Project card with its merged GitHub / Document / Website /
    Defense evidence — instead of many partial duplicates.
    """
    projects = list_eligible_projects(db, user_id)
    return [build_merged_eligible_summary(db, group) for group in group_duplicate_projects(projects)]


def build_project_defense_context(db: Any, project: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    """Full workspace context for a selected project.

    Includes the *merged* safe evidence summary (combined across any duplicate
    project rows for the same logical project), the strongest deterministic
    defense status, and — when a defense session already exists — its id and
    generated questions so the workspace can resume rather than force a fresh
    start. When ``user_id`` is provided the evidence is merged across the whole
    duplicate group so the selected workspace never regresses to a weaker
    duplicate that is missing GitHub.
    """
    if user_id is not None:
        group = _find_project_group(db, user_id, str(project["id"])) or [project]
    else:
        group = [project]

    metadata = _merge_group_metadata(group)
    defense_status = _group_defense_status(db, group)

    session = get_active_session(db, str(project["id"]))
    session_id = str(session["id"]) if session is not None else None
    questions = list_session_questions(db, session_id) if session_id else []

    return {
        "evidence": _evidence_summary(metadata),
        "safe_metadata": safe_project_metadata(metadata),
        "defense_status": defense_status,
        "report_ready": _report_ready(defense_status),
        "session_id": session_id,
        "questions": questions,
    }


def _merge_summaries_by_key(
    existing: Any, new_items: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """Merge two lists of safe summaries, de-duplicating by ``key`` (new wins)."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in (existing if isinstance(existing, list) else []) + new_items:
        if not isinstance(item, dict):
            continue
        item_key = str(item.get(key) or id(item))
        if item_key not in merged:
            order.append(item_key)
        merged[item_key] = item
    return [merged[k] for k in order]


def attach_proofs_to_project(
    db: Any, pipeline_db: Any, user_id: str, project: dict[str, Any], attached: Any
) -> dict[str, Any]:
    """Attach existing owned proofs to an existing owned project.

    Only IDs are accepted; the backend re-derives safe summaries and merges them
    into ``vbr_projects.metadata.attached_proofs`` (never raw payloads). Ownership
    of every referenced proof is enforced by the summary builders, which raise a
    known ``ValueError`` code when a proof is missing or owned by another user.

    Returns the same safe projection the context endpoint uses — a sanitized
    ``evidence`` summary and an allowlisted ``safe_metadata`` — so the attach
    response never echoes raw ``metadata.attached_proofs``, storage paths, signed
    URLs, private ids, provider JSON, raw text, or numeric scores, even when the
    project already carried unsafe legacy metadata.
    """
    metadata = project.get("metadata") or {}
    existing = metadata.get("attached_proofs") or {}
    existing = dict(existing) if isinstance(existing, dict) else {}

    github_proof_id = (getattr(attached, "github_proof_id", None) or "").strip() or None
    if github_proof_id:
        existing["github_proof"] = _github_proof_summary(db, user_id, github_proof_id)

    website_ids = _clean_list(getattr(attached, "website_proof_session_ids", None))
    if website_ids:
        new_web = _website_proof_summaries(db, user_id, website_ids)
        existing["website_proofs"] = _merge_summaries_by_key(
            existing.get("website_proofs"), new_web, "proof_session_id"
        )

    document_ids = getattr(attached, "document_evidence_ids", None) or []
    new_docs = _document_summaries(db, user_id, document_ids)
    if new_docs:
        existing["documents"] = _merge_summaries_by_key(
            existing.get("documents"), new_docs, "document_evidence_id"
        )

    skill_pipeline_ids = _clean_list(getattr(attached, "skill_pipeline_ids", None))
    if skill_pipeline_ids:
        _validate_skill_pipeline_ownership(pipeline_db, user_id, skill_pipeline_ids)
        prev = existing.get("skill_pipeline_ids") or []
        existing["skill_pipeline_ids"] = list(dict.fromkeys([*prev, *skill_pipeline_ids]))

    _update_project_metadata(db, project, {"attached_proofs": existing})
    metadata = project.get("metadata") or {}
    return {
        "evidence": _evidence_summary(metadata),
        "safe_metadata": safe_project_metadata(metadata),
    }


# ── Deterministic defense question generation ───────────────────────────────


def build_defense_question_specs(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Build deterministic project-defense question specs grounded in context.

    Questions are grounded in the selected project's own description and the
    *safe* summaries of its attached proofs (GitHub public-safe summary, document
    titles/skills, website target). Every proof field read here is first passed
    through :func:`sanitize_attached_proofs`, so no raw provider JSON, storage
    path, signed URL, private ID, raw document text, or numeric score can ever
    surface inside a generated question.
    """
    metadata = project.get("metadata") or {}
    title = project.get("title") or "this project"
    description = _truncate(str(metadata.get("description") or "").strip(), 400)
    claimed_skills = _clean_list(metadata.get("claimed_skills") or [])
    student_role = str(metadata.get("student_role") or "").strip()

    attached = sanitize_attached_proofs(metadata.get("attached_proofs"))
    github_proof = attached.get("github_proof")
    repo_url = str(github_proof.get("repo_url") or "").strip() if isinstance(github_proof, dict) else ""
    github_summary = (
        _strip_score_fragments(_truncate(str(github_proof.get("public_safe_summary") or "").strip(), 240))
        if isinstance(github_proof, dict)
        else ""
    )
    documents = attached.get("documents") or []
    website_proofs = attached.get("website_proofs") or []

    specs: list[dict[str, Any]] = []

    # Architecture — grounded in the project's own description when available.
    if description:
        architecture_text = (
            f'Your project "{title}" is described as: "{description}". '
            "Walk through its main architecture — how a request or workflow moves through the major "
            "components — and explain why you designed it this way."
        )
    else:
        architecture_text = f'Explain the main architecture of "{title}" and why you designed it this way.'
    specs.append(
        {
            "question_text": architecture_text,
            "target_ref": {"type": "project_defense", "kind": "architecture"},
        }
    )

    if student_role:
        specs.append(
            {
                "question_text": (
                    f'You described your role as: "{_truncate(student_role, 200)}". '
                    f'Walk through the part of "{title}" you personally built and explain how it reflects this role.'
                ),
                "target_ref": {"type": "project_defense", "kind": "contribution"},
            }
        )
    else:
        specs.append(
            {
                "question_text": f'Walk through the part of "{title}" you personally built and explain your specific contribution.',
                "target_ref": {"type": "project_defense", "kind": "contribution"},
            }
        )

    for skill in claimed_skills[:_MAX_SKILL_QUESTIONS]:
        if repo_url and github_summary:
            specs.append(
                {
                    "question_text": (
                        f'Your GitHub proof for "{title}" summarises it as: "{github_summary}". '
                        f"Point to where in the repository ({repo_url}) you demonstrate your claimed skill "
                        f"in {skill}, and walk through that code."
                    ),
                    "target_ref": {"type": "project_defense", "kind": "skill_repo_link", "skill": skill},
                }
            )
        elif repo_url:
            specs.append(
                {
                    "question_text": (
                        f"Explain how this GitHub repository ({repo_url}) "
                        f"supports your claimed skill in {skill}."
                    ),
                    "target_ref": {"type": "project_defense", "kind": "skill_repo_link", "skill": skill},
                }
            )
        else:
            specs.append(
                {
                    "question_text": f'Explain how "{title}" demonstrates your claimed skill in {skill}.',
                    "target_ref": {"type": "project_defense", "kind": "skill_link", "skill": skill},
                }
            )

    if website_proofs:
        first_site = website_proofs[0]
        target = str(first_site.get("target_website") or "").strip()
        if target:
            live_demo_text = (
                f"Walk through how the live demo at {target} maps to the implementation of "
                f'"{title}" — which parts of the code produce what the reviewer sees.'
            )
        else:
            live_demo_text = "Show or describe how the live/demo proof for this project connects to your implementation."
        specs.append(
            {
                "question_text": live_demo_text,
                "target_ref": {"type": "project_defense", "kind": "live_demo_link"},
            }
        )

    if documents:
        first_doc = documents[0]
        doc_title = str(first_doc.get("title") or "your submitted document")
        doc_skills = _clean_list(first_doc.get("skills"))
        if doc_skills:
            document_text = (
                f'Your document "{doc_title}" is linked to {", ".join(doc_skills)}. '
                f'Explain how it substantiates that work in "{title}".'
            )
        else:
            document_text = f'Explain how the document "{doc_title}" relates to "{title}" and what it demonstrates.'
        specs.append(
            {
                "question_text": document_text,
                "target_ref": {"type": "project_defense", "kind": "document_link"},
            }
        )

    # Missing-evidence context — ask the student to account for the gaps so the
    # question plan reflects what is (and is not) actually attached.
    missing: list[str] = []
    if not repo_url:
        missing.append("a GitHub repository proof")
    if not documents:
        missing.append("a supporting document")
    if not website_proofs:
        missing.append("a live/website demo")
    if missing:
        specs.append(
            {
                "question_text": (
                    f'You have not attached {" or ".join(missing)} for "{title}". '
                    "Explain how you evidence your claimed skills without it, or what you would add to strengthen the proof."
                ),
                "target_ref": {"type": "project_defense", "kind": "missing_evidence"},
            }
        )

    specs.append(
        {
            "question_text": "Explain one technical challenge you faced while building this project and how you solved it.",
            "target_ref": {"type": "project_defense", "kind": "challenge"},
        }
    )

    specs.append(
        {
            "question_text": "What would you improve next if you continued working on this project?",
            "target_ref": {"type": "project_defense", "kind": "improvement"},
        }
    )

    return specs


def generate_defense_questions(db: Any, project: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Create/reuse a verification session and save deterministic defense questions.

    Raises ``ValueError("active_session_already_started")`` if the project's
    active session has already progressed beyond ``created`` (e.g. a
    walkthrough recording is in progress).
    """
    project_id = str(project["id"])

    session = get_active_session(db, project_id)
    if session is not None and session.get("status") != "created":
        raise ValueError("active_session_already_started")
    if session is None:
        session = _create_session(db, project_id)

    _delete_session_questions(db, session["id"])

    specs = build_defense_question_specs(project)
    now = _now()
    rows = [
        {
            "id": str(uuid4()),
            "session_id": session["id"],
            "sort_order": sort_order,
            "question_text": spec["question_text"],
            "target_ref": spec["target_ref"],
            "claim_ids": [],
            "asked_at_s": None,
            "answered": False,
            "created_at": now,
        }
        for sort_order, spec in enumerate(specs)
    ]

    inserted = _insert_questions(db, rows)
    return str(session["id"]), inserted


# ── Manual transcript + analysis ─────────────────────────────────────────────


def _upsert_transcript(db: Any, session_id: str, full_text: str) -> dict[str, Any]:
    now = _now()
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPTS_TABLE, {})
        existing = next((r for r in store.values() if str(r.get("session_id")) == session_id), None)
        if existing is not None:
            existing["full_text"] = full_text
            existing["provider"] = "manual"
            existing["language"] = "en"
            existing["raw"] = {}
            return existing
        row = {
            "id": str(uuid4()),
            "session_id": session_id,
            "provider": "manual",
            "language": "en",
            "full_text": full_text,
            "raw": {},
            "created_at": now,
        }
        store[row["id"]] = row
        return row

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .upsert(
            {
                "session_id": session_id,
                "provider": "manual",
                "language": "en",
                "full_text": full_text,
                "raw": {},
            },
            on_conflict="session_id",
        )
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _replace_transcript_segments(db: Any, transcript_id: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {})
        for key in [k for k, row in store.items() if str(row.get("transcript_id")) == transcript_id]:
            del store[key]
        now = _now()
        rows: list[dict[str, Any]] = []
        for seg in segments:
            row = {"id": str(uuid4()), "transcript_id": transcript_id, "created_at": now, **seg}
            store[row["id"]] = row
            rows.append(row)
        return rows

    db.table(_TRANSCRIPT_SEGMENTS_TABLE).delete().eq("transcript_id", transcript_id).execute()
    if not segments:
        return []
    rows_to_insert = [{"transcript_id": transcript_id, **seg} for seg in segments]
    result = db.table(_TRANSCRIPT_SEGMENTS_TABLE).insert(rows_to_insert).execute()
    return getattr(result, "data", []) or []


def _update_project_metadata(db: Any, project: dict[str, Any], patch: dict[str, Any]) -> None:
    """Merge ``patch`` into ``vbr_projects.metadata`` for ``project`` and persist it."""
    metadata = {**(project.get("metadata") or {}), **patch}
    now = _now()
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(str(project["id"]))
        if row is not None:
            row["metadata"] = metadata
            row["updated_at"] = now
    else:
        db.table(_PROJECTS_TABLE).update({"metadata": metadata, "updated_at": now}).eq(
            "id", project["id"]
        ).execute()
    project["metadata"] = metadata


_AUTO_TRANSCRIPT_PROVIDERS = {"openai", "local_whisper"}


def _get_auto_generated_transcript(
    db: Any, session_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Return an existing auto-generated transcript (and its segments) for ``session_id``.

    Only matches transcripts produced by ``vbr_transcription.transcribe_session``
    (``provider`` in ``_AUTO_TRANSCRIPT_PROVIDERS``) — never a manually pasted
    transcript (``provider == "manual"``).
    """
    if isinstance(db, dict):
        transcript = next(
            (
                row
                for row in db.setdefault(_TRANSCRIPTS_TABLE, {}).values()
                if str(row.get("session_id")) == session_id
                and row.get("provider") in _AUTO_TRANSCRIPT_PROVIDERS
            ),
            None,
        )
        if transcript is None or not (transcript.get("full_text") or "").strip():
            return None
        transcript_id = str(transcript["id"])
        segments = [
            row
            for row in db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
            if str(row.get("transcript_id")) == transcript_id
        ]
        return transcript, segments

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    transcript = getattr(result, "data", None) if result is not None else None
    if not transcript or transcript.get("provider") not in _AUTO_TRANSCRIPT_PROVIDERS:
        return None
    if not (transcript.get("full_text") or "").strip():
        return None

    seg_result = (
        db.table(_TRANSCRIPT_SEGMENTS_TABLE)
        .select("*")
        .eq("transcript_id", transcript["id"])
        .execute()
    )
    segments = getattr(seg_result, "data", []) or []
    return transcript, segments


def _mark_questions_answered(db: Any, question_ids: set[str]) -> None:
    ids = [qid for qid in question_ids if qid]
    if not ids:
        return
    if isinstance(db, dict):
        store = db.setdefault(_QUESTIONS_TABLE, {})
        for qid in ids:
            row = store.get(qid)
            if row is not None:
                row["answered"] = True
        return
    db.table(_QUESTIONS_TABLE).update({"answered": True}).in_("id", ids).execute()


def submit_defense_answers(
    db: Any, session: dict[str, Any], project: dict[str, Any], body: SubmitDefenseAnswersRequest
) -> dict[str, Any]:
    """Save pasted/manual defense answers as a transcript + segments and analyze.

    If neither ``body.answers`` nor ``body.combined_text`` contains any
    non-empty text, falls back to an existing auto-generated transcript (from
    ``vbr_transcription.transcribe_session``) as the analysis source, if one
    exists. Raises ``ValueError("no_answers_provided")`` if neither manual
    text nor an auto-generated transcript is available.
    """
    session_id = str(session["id"])
    questions = list_session_questions(db, session_id)
    questions_by_id = {str(q["id"]): q for q in questions}

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    answered_question_ids: set[str] = set()

    for item in body.answers:
        answer_text = (item.answer_text or "").strip()
        if not answer_text:
            continue
        question = questions_by_id.get(str(item.question_id)) if item.question_id else None
        question_text = question.get("question_text") if question else None
        if question_text:
            text_parts.append(f"Q: {question_text}\nA: {answer_text}")
        else:
            text_parts.append(answer_text)

        idx = len(segments)
        segments.append(
            {
                "question_id": str(question["id"]) if question else None,
                "start_s": float(idx),
                "end_s": float(idx + 1),
                "text": answer_text,
            }
        )
        if question is not None:
            answered_question_ids.add(str(question["id"]))

    combined_text = (body.combined_text or "").strip()
    if combined_text:
        text_parts.append(combined_text)
        idx = len(segments)
        segments.append(
            {
                "question_id": None,
                "start_s": float(idx),
                "end_s": float(idx + 1),
                "text": combined_text,
            }
        )

    # Independent of which transcript source feeds the textual analysis
    # below, video evidence chips are always built from the real,
    # auto-generated video transcript (with meaningful timestamps) if one
    # exists — manual-answer segments use synthetic start_s/end_s indices.
    auto_video_transcript = _get_auto_generated_transcript(db, session_id)

    if segments:
        full_text = "\n\n".join(text_parts)
        transcript = _upsert_transcript(db, session_id, full_text)
        transcript_id = str(transcript["id"])
        saved_segments = _replace_transcript_segments(db, transcript_id, segments)
        _mark_questions_answered(db, answered_question_ids)
    else:
        if auto_video_transcript is None:
            raise ValueError("no_answers_provided")
        auto_transcript, saved_segments = auto_video_transcript
        transcript_id = str(auto_transcript["id"])
        full_text = auto_transcript.get("full_text") or ""

    metadata = project.get("metadata") or {}
    claimed_skills = _clean_list(metadata.get("claimed_skills") or [])
    attached = metadata.get("attached_proofs") or {}
    if not isinstance(attached, dict):
        attached = {}
    github_proof = attached.get("github_proof")
    github_summary = ""
    if isinstance(github_proof, dict):
        github_summary = str(github_proof.get("public_safe_summary") or "")

    # ── Claim-level Defense Answer Evidence (question_id / target_ref grounded) ──
    # Built from the SAME segments that were persisted: manual answers carry
    # their answering question_id (targeted evidence); an auto video transcript
    # has no question_id, so its text honestly stays untargeted/generic and can
    # never promote a skill.
    evidence_segments = segments if segments else list(saved_segments)
    answer_evidence = build_defense_answer_evidence(
        questions=questions,
        segments=evidence_segments,
        claimed_skills=claimed_skills,
        attached_proofs=attached,
        project_title=str(project.get("title") or ""),
    )

    # Question-grounded skill mapping replaces the keyword heuristic whenever
    # at least one answer was tied to a question; a purely untargeted
    # submission (combined text / auto transcript only) passes None and keeps
    # the conservative transcript-only fallback.
    grounded_explained = (
        explained_skills_from_answer_evidence(answer_evidence)
        if answered_question_ids
        else None
    )

    analysis_result = analyze_defense_transcript(
        transcript_text=full_text,
        claimed_skills=claimed_skills,
        github_summary=github_summary,
        question_grounded_explained_skills=grounded_explained,
    )
    analysis_dict = asdict(analysis_result)

    # Stamp the transcript privacy verdict onto every answer evidence object so
    # the public projection can fail closed per item.
    privacy_status = str(analysis_result.privacy_scan_status or "").strip().lower() or "unknown"
    for item in answer_evidence:
        item["privacy_status"] = privacy_status
        item["public_shareable"] = privacy_status == "clean" and not item.get("contradiction_flag")

    telemetry_update: dict[str, Any] = {
        "project_defense_analysis": analysis_dict,
        "defense_answer_evidence": answer_evidence,
    }
    if auto_video_transcript is not None:
        # A real video transcript is available — (re)compute chips from it.
        # Note: if this run also persists manual answers (below),
        # _upsert_transcript may overwrite this transcript's row in place
        # (same session_id, single transcript per session), so the segments
        # captured here must be used now rather than re-fetched later.
        video_evidence_chips = build_evidence_chips(auto_video_transcript[1], claimed_skills, questions)
        telemetry_update["video_evidence_chips"] = video_evidence_chips
    else:
        # No (current) auto-generated video transcript — preserve any
        # previously computed chips rather than erasing them.
        video_evidence_chips = list((session.get("telemetry") or {}).get("video_evidence_chips") or [])

    update_session_telemetry(db, session, telemetry_update, merge=True)
    _update_project_metadata(db, project, {"project_defense_status": "analyzed"})

    return {
        "transcript_id": transcript_id,
        "segment_count": len(saved_segments),
        "answered_question_count": len(answered_question_ids),
        "analysis": analysis_dict,
        "video_evidence_chips": video_evidence_chips,
        "defense_answer_evidence": answer_evidence,
    }
