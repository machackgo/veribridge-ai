"""Public recruiter-safe VBR report link for a Project Defense project (v1).

This module turns the *student-owned* Final VBR Report preview
(``vbr_student_report.build_student_vbr_report``, built from a ``vbr_projects``
row + its Project Defense evidence) into a read-only, tokenized public
recruiter link.

Two surfaces live here:

* Owner-only operations — ``publish_project_report`` /
  ``unpublish_project_report`` / ``get_project_report_publish_status``. These
  mint / clear / report the project's ``public_report_token``. Ownership is
  always enforced via ``get_owned_vbr_project_or_404`` because ``get_db``
  returns the service-role client which bypasses RLS.
* Public read — ``build_public_project_report`` resolves a project by its
  active ``public_report_token`` (no auth) and returns a sanitized public
  projection of the report-safe summary.

The public projection re-uses the already-sanitized student report summaries
(qualitative evidence labels only — never numeric trust scores) and runs an
additional defence-in-depth scan so it never returns:

* raw transcript / document text, raw GitHub snapshots, full ``artifact_data``
* storage paths, signed/upload URLs, bucket names, local/temp paths
* any token other than the public token the recruiter already has
* internal IDs not needed publicly (project_id, session_id, question_id),
  the student's private email, or the auth user ID

This module never calls any LLM.
"""

from __future__ import annotations

import logging
import re
import secrets

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import get_owned_vbr_project_or_404
from app.services.safe_public_url import is_safe_public_url
from app.services.vbr_student_report import build_student_vbr_report

logger = logging.getLogger(__name__)

_PROJECTS_TABLE = "vbr_projects"
_USERS_TABLE = "users"
_PASSPORTS_TABLE = "vbr_work_passports"

_TOKEN_GENERATION_ATTEMPTS = 5

_REPORT_TITLE = "Verified Build Report"
_PUBLIC_PATH_PREFIX = "/vbr/report/"
_PASSPORT_PATH_PREFIX = "/p/"

_VERIFICATION_NOTE = (
    "This is an evidence-backed Verified Build Report shared by the candidate. "
    "Evidence is described as observed, supporting, or process evidence — never "
    "as a number, percentage, or ranking — and is not a guarantee of employment, "
    "skill mastery, or identity. Project Defense reflects the candidate's own "
    "explanation of their work, not independent proof of code authorship."
)

__all__ = [
    "publish_project_report",
    "unpublish_project_report",
    "get_project_report_publish_status",
    "build_public_project_report",
    "_scrub_public_report",
    "_scrub_text",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Unsafe-field scan (defence in depth) ─────────────────────────────────────

_UNSAFE_KEYS = {
    "storagepath",
    "storage_path",
    "mediastoragepath",
    "media_storage_path",
    "videopath",
    "video_path",
    "signedurl",
    "signed_url",
    "signedpath",
    "signed_path",
    "uploadurl",
    "upload_url",
    "bucket",
    "bucketname",
    "bucket_name",
    "publictoken",
    "public_token",
    "publicreporttoken",
    "public_report_token",
    "accesstoken",
    "access_token",
    "localpath",
    "local_path",
    "temppath",
    "temp_path",
    "tmppath",
    "tmp_path",
    "raw",
    "rawmetadata",
    "raw_metadata",
    "artifactdata",
    "artifact_data",
    "fulltext",
    "full_text",
    "fulltranscript",
    "full_transcript",
    "transcripttext",
    "transcript_text",
    "email",
    "useremail",
    "user_email",
    "userid",
    "user_id",
    "authuserid",
    "auth_user_id",
}

_UNSAFE_VALUE_PATTERNS = (
    "vbr/sessions/",
    "/tmp/",
    "supabase.co/storage",
    "/storage/v1/object",
    "signed_url",
    "signedurl",
    "signedurl",
    "bearer ",
)


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")


def _contains_unsafe_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalize_key(str(key))
            compact = normalized.replace("_", "")
            if normalized in _UNSAFE_KEYS or compact in _UNSAFE_KEYS:
                return True
            if _contains_unsafe_fields(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_unsafe_fields(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(pattern in lowered for pattern in _UNSAFE_VALUE_PATTERNS)
    return False


# ── Lookups / persistence ────────────────────────────────────────────────────


def _find_project_by_token(db: Any, token: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_PROJECTS_TABLE, {}).values()
                if row.get("public_report_token") == token
            ),
            None,
        )

    result = (
        db.table(_PROJECTS_TABLE)
        .select("*")
        .eq("public_report_token", token)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _token_exists(db: Any, token: str) -> bool:
    if isinstance(db, dict):
        return any(
            row.get("public_report_token") == token
            for row in db.setdefault(_PROJECTS_TABLE, {}).values()
        )

    result = db.table(_PROJECTS_TABLE).select("id").eq("public_report_token", token).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return bool(rows)


def _update_project(db: Any, project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_PROJECTS_TABLE, {}).get(project_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_PROJECTS_TABLE).update(updates).eq("id", project_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _generate_token(db: Any) -> str:
    for _ in range(_TOKEN_GENERATION_ATTEMPTS):
        token = secrets.token_urlsafe(24)
        if not _token_exists(db, token):
            return token
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "vbr_public_report_token_generation_failed",
            "message": "Could not generate a unique public link. Please try again.",
        },
    )


def _lookup_public_passport_path(db: Any, user_id: str) -> str | None:
    """Best-effort recruiter-safe link back to the owner's *published* passport.

    Returns ``/p/{slug}`` only when the owner has an actively published Work
    Passport with a slug; any uncertainty (no passport, unpublished, missing
    slug, lookup error) returns ``None`` so a private passport is never linked.
    Kept inline (rather than importing the passport service) to avoid a circular
    import — ``vbr_work_passport_service`` already imports from this module.
    """
    if not user_id:
        return None
    try:
        if isinstance(db, dict):
            row = next(
                (
                    r
                    for r in db.setdefault(_PASSPORTS_TABLE, {}).values()
                    if str(r.get("user_id")) == str(user_id)
                ),
                None,
            )
        else:
            result = (
                db.table(_PASSPORTS_TABLE)
                .select("public_slug,is_published")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - passport backlink is optional
        return None

    if not isinstance(row, dict) or not row.get("is_published"):
        return None
    slug = row.get("public_slug")
    if isinstance(slug, str) and slug.strip():
        return f"{_PASSPORT_PATH_PREFIX}{slug.strip()}"
    return None


def _lookup_display_name(db: Any, user_id: str) -> str | None:
    """Best-effort safe candidate display name; omitted (None) on any issue.

    Only ``full_name`` is read — never the student's email or auth ID.
    """
    try:
        if isinstance(db, dict):
            row = db.setdefault(_USERS_TABLE, {}).get(user_id)
        else:
            result = (
                db.table(_USERS_TABLE).select("full_name").eq("id", user_id).limit(1).execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - display name is optional
        return None

    if not isinstance(row, dict):
        return None
    name = row.get("full_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


# ── Response builders ────────────────────────────────────────────────────────


def _public_path(token: str) -> str:
    return f"{_PUBLIC_PATH_PREFIX}{token}"


def _status_response(project: dict[str, Any]) -> dict[str, Any]:
    token = project.get("public_report_token")
    is_public = bool(token)
    return {
        "project_id": str(project["id"]),
        "is_public": is_public,
        "public_token": token,
        "public_path": _public_path(token) if is_public else None,
        "published_at": project.get("public_report_published_at"),
    }


# ── Owner-only operations ────────────────────────────────────────────────────


def publish_project_report(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Publish a recruiter-safe public link for the project's VBR report.

    Idempotent: if the project already has an active public token it is
    returned unchanged (the link is stable and not rotated). Ownership is
    enforced; other users' projects 404.
    """
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    existing = project.get("public_report_token")
    if existing:
        return _status_response(project)

    token = _generate_token(db)
    now = _now()
    updated = _update_project(
        db,
        str(project["id"]),
        {"public_report_token": token, "public_report_published_at": now, "updated_at": now},
    )
    # Keep the in-memory project dict in sync for the response.
    project.update(updated or {"public_report_token": token, "public_report_published_at": now})

    logger.info("[VBR] Public report link published for project %s", project_id)
    return _status_response(project)


def unpublish_project_report(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Revoke the public link, clearing the token so old links stop resolving.

    Idempotent: a project with no active token is returned unchanged.
    """
    project = get_owned_vbr_project_or_404(db, project_id, user_id)

    if not project.get("public_report_token"):
        return _status_response(project)

    now = _now()
    updated = _update_project(
        db,
        str(project["id"]),
        {"public_report_token": None, "public_report_published_at": None, "updated_at": now},
    )
    project.update(updated or {})
    project["public_report_token"] = None
    project["public_report_published_at"] = None

    logger.info("[VBR] Public report link revoked for project %s", project_id)
    return _status_response(project)


def get_project_report_publish_status(db: Any, project_id: str, user_id: str) -> dict[str, Any]:
    """Return the project's publish status, including the owner's own token."""
    project = get_owned_vbr_project_or_404(db, project_id, user_id)
    return _status_response(project)


# ── Public read ──────────────────────────────────────────────────────────────


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_public_report_not_found",
            "message": "This report is not available.",
        },
    )


def _sanitize_video_chips(chips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop internal references (``question_id``) from video evidence chips."""
    sanitized: list[dict[str, Any]] = []
    for chip in chips:
        if not isinstance(chip, dict):
            continue
        sanitized.append(
            {
                "label": chip.get("label"),
                "timestamp_start_s": chip.get("timestamp_start_s"),
                "timestamp_end_s": chip.get("timestamp_end_s"),
                "short_summary": chip.get("short_summary"),
                "related_skill": chip.get("related_skill"),
                "source": chip.get("source") or "project_defense_video",
                "source_type": chip.get("source_type") or "video_transcript",
            }
        )
    return sanitized


# Numeric / score-style fragments must never reach the public recruiter report
# (product rule: no /100 bars, percentages-as-scores, "trust score" wording,
# ranking fragments, or "fully verified"). Upstream summaries (GitHub Proof,
# defense recruiter summaries, document/website text, skill notes, etc.) are
# free text and may embed any of these, so we redact them from *every* public
# string field — recursively — leaving the qualitative wording intact.
#
# Order matters: composite patterns (fraction, percent, "trust score", "score
# 91") run before the bare "score" word so numbers are stripped alongside it.
_SCORE_FRACTION_RE = re.compile(r"\b\d{1,3}\s*/\s*100\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_TRUST_SCORE_RE = re.compile(r"\btrust[\s_-]*scores?\b", re.IGNORECASE)
_FULLY_VERIFIED_RE = re.compile(r"\bfully[\s_-]+verified\b", re.IGNORECASE)
_SCORE_WITH_NUMBER_RE = re.compile(r"\bscor(?:e|es|ed|ing)\s*:?\s*\d{1,3}\b", re.IGNORECASE)
_NUMBER_WITH_SCORE_RE = re.compile(r"\b\d{1,3}\s*(?:/\s*\d{1,3}\s*)?scor(?:e|es|ed|ing)\b", re.IGNORECASE)
_RANK_RE = re.compile(r"\branke(?:d|ing)?\s*#?\s*\d+\b", re.IGNORECASE)
_RANK_HASH_RE = re.compile(r"#\s*\d+\b")
# Covers score / scores / scored / scoring so no "score" substring survives.
_SCORE_WORD_RE = re.compile(r"\bscor(?:e|es|ed|ing)\b", re.IGNORECASE)

# Filler words that become dangling after a fragment is stripped (e.g.
# "scored 91/100 confidence" → "confidence"). Removed only when adjacent to a
# now-empty fragment via the whitespace collapse below; kept simple on purpose.
_CONNECTOR_RE = re.compile(r"\b(?:with|at|of)\s+(?=[.,;:]|$)", re.IGNORECASE)


def _scrub_text(text: str) -> str:
    out = _SCORE_FRACTION_RE.sub(" ", text)
    out = _PERCENT_RE.sub(" ", out)
    out = _TRUST_SCORE_RE.sub(" ", out)
    out = _FULLY_VERIFIED_RE.sub("verified", out)
    out = _SCORE_WITH_NUMBER_RE.sub(" ", out)
    out = _NUMBER_WITH_SCORE_RE.sub(" ", out)
    out = _RANK_RE.sub(" ", out)
    out = _RANK_HASH_RE.sub(" ", out)
    out = _SCORE_WORD_RE.sub(" ", out)
    out = _CONNECTOR_RE.sub("", out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out.strip()


def _scrub_numeric_scores(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    return _scrub_text(text)


def _scrub_public_report(value: Any) -> Any:
    """Recursively redact score-style fragments from every public string value.

    Walks the fully-built public projection (dicts, lists, strings) and scrubs
    each string in place. Keys are never altered, so the defence-in-depth
    unsafe-key scan still operates on the original structure.
    """
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {key: _scrub_public_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_public_report(item) for item in value]
    return value


# Generic, non-leaking limitation appended when a direct verification link was
# dropped because its target was not safely public (never reveals the raw URL).
_OMITTED_LINK_LIMITATION = (
    "One or more direct verification links were private or internal and have been "
    "omitted from this public report."
)


def _public_github_proof(github_proof: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(github_proof, dict):
        return None
    scrubbed = dict(github_proof)
    scrubbed["public_safe_summary"] = _scrub_numeric_scores(github_proof.get("public_safe_summary") or "")
    # A repo URL is only kept (and only advertised as directly linkable) when it
    # is a public-safe http(s) target — never echo a private/internal raw URL.
    repo_url = github_proof.get("repo_url")
    repo_url_is_safe = is_safe_public_url(repo_url)
    scrubbed["repo_url"] = repo_url if repo_url_is_safe else None
    scrubbed["repo_is_public"] = bool(github_proof.get("repo_is_public")) and repo_url_is_safe
    return scrubbed


def _public_website_proofs(proofs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Project website proofs, blanking any non-public ``target_website``.

    Returns the safe proofs plus a flag indicating whether at least one target
    URL was omitted, so limitations can honestly reflect the omission. The
    qualitative evidence (strength, confidence, skills) is always preserved —
    only the raw direct link is dropped when it is not public-safe.
    """
    safe: list[dict[str, Any]] = []
    omitted = False
    for proof in proofs:
        if not isinstance(proof, dict):
            continue
        row = dict(proof)
        target = row.get("target_website") or ""
        if target and not is_safe_public_url(target):
            row["target_website"] = ""  # never echo a raw private/internal URL
            omitted = True
        safe.append(row)
    return safe, omitted


def _public_evidence_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-gate each evidence trace's direct link before it reaches recruiters.

    The student-report builder already drops non-public links, but the public
    surface re-verifies every ``public_url`` through the safe-public-url helper
    (defence in depth) so an unsafe link can never be advertised as openable.
    """
    safe: list[dict[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        row = dict(trace)
        if not is_safe_public_url(row.get("public_url")):
            row["public_url"] = None
            row["public_url_label"] = None
            row["is_publicly_openable"] = False
            if not row.get("private_evidence_note"):
                row["private_evidence_note"] = "A direct link was omitted because it was private or internal."
        # Never echo a raw private/internal URL in the human-readable title.
        title = str(row.get("source_title") or "")
        if "://" in title and not is_safe_public_url(title):
            row["source_title"] = str(row.get("source_type") or "Evidence source")
        # Strip the safe-but-detailed proof excerpts that are only meant for the
        # private student preview. The human-readable ``location_label`` (e.g.
        # "Q3", "Live URL", "repo-level") and the deterministic ``question_text``
        # stay — they carry the recruiter-facing reference without exposing raw
        # answers, document passages, or internal paths.
        row["snippet"] = None
        row["answer_excerpt"] = None
        # GitHub code snippet is dropped on the public surface — the public
        # ``…#L`` blob link is the recruiter-facing proof of the exact lines.
        row["code_snippet"] = None
        if row.get("source_type") == "Document Proof" and row.get("location_detail"):
            row["location_detail"] = (
                "The matched passage is retained privately; only the document reference is shown."
            )
        safe.append(row)
    return safe


def _public_limitations(limitations: list[str]) -> list[str]:
    """Keep honest empty-state / disclaimer lines, drop preview-only wording."""
    return [
        line
        for line in limitations
        if isinstance(line, str) and "private student preview" not in line.lower()
    ]


def build_public_project_report(db: Any, pipeline_db: Any, token: str) -> dict[str, Any]:
    """Resolve a published project by ``token`` and return its public report.

    Raises 404 unless a project with this exact active ``public_report_token``
    exists. The report is built from the same report-safe summaries the student
    preview uses, then projected to public fields and scanned for unsafe
    content as defence in depth.
    """
    if not token:
        raise _not_found()

    project = _find_project_by_token(db, token)
    if project is None or not project.get("public_report_token"):
        raise _not_found()

    owner_id = str(project.get("user_id") or "")
    report = build_student_vbr_report(db, pipeline_db, project, owner_id)

    # ── Direct verification links: public-safe gate (must-fix) ───────────────
    # Only genuinely public http(s) targets may be linked from an anonymous
    # recruiter view. Unsafe targets (localhost, private/internal hosts, private
    # IPs, file/data/blob/javascript, storage/signed URLs) are dropped here so
    # the raw URL never reaches the response JSON.
    raw_deployed_url = report.get("deployed_url") or None
    deployed_url = raw_deployed_url if is_safe_public_url(raw_deployed_url) else None
    website_proofs, website_link_omitted = _public_website_proofs(report.get("website_proofs") or [])
    deployed_link_omitted = bool(raw_deployed_url) and deployed_url is None

    limitations = _public_limitations(report.get("limitations") or [])
    if (deployed_link_omitted or website_link_omitted) and _OMITTED_LINK_LIMITATION not in limitations:
        limitations.append(_OMITTED_LINK_LIMITATION)

    public = {
        "report_title": _REPORT_TITLE,
        "project_title": report.get("project_title") or "",
        "candidate_display_name": _lookup_display_name(db, owner_id),
        "project_summary": report.get("project_description") or "",
        "student_role": report.get("student_role") or "",
        "repo_full_name": report.get("repo_full_name"),
        "deployed_url": deployed_url,
        "claimed_skills": list(report.get("claimed_skills") or []),
        "evidence_package": report.get("evidence_package") or {},
        "github_proof": _public_github_proof(report.get("github_proof")),
        "documents": list(report.get("documents") or []),
        "website_proofs": website_proofs,
        "project_defense_analysis": report.get("project_defense_analysis"),
        "skill_evidence": list(report.get("skill_evidence") or []),
        "evidence_traces": _public_evidence_traces(report.get("evidence_traces") or []),
        "video_evidence_chips": _sanitize_video_chips(report.get("video_evidence_chips") or []),
        "limitations": limitations,
        "published_at": project.get("public_report_published_at"),
        "generated_at": report.get("generated_at"),
        "public_passport_path": _lookup_public_passport_path(db, owner_id),
        "verification_note": _VERIFICATION_NOTE,
    }

    # Recursively scrub score-style fragments from every public string field
    # (must-fix: the scrubber is no longer limited to github_proof). Applied
    # after the projection is built and before the response is returned.
    public = _scrub_public_report(public)

    # Step 7: route the final gate through the centralized Public Safety layer —
    # a strict superset of the inline scan that also strengthens scrubbing
    # (rank/rating/percentile + emails) and rejects private source_id / metadata /
    # raw-payload / provider-config keys, ``/Users/…`` & ``file://`` paths, and raw
    # emails. Lazily imported because the safety service imports this module's
    # low-level primitives (``_scrub_text`` / ``_contains_unsafe_fields``).
    from app.services.public_report_safety_service import (
        PublicReportUnsafeError,
        enforce_public_safe,
    )

    try:
        public = enforce_public_safe(public)
    except PublicReportUnsafeError:
        logger.warning("[VBR] Public project report failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    return public
