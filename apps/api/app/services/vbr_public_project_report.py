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
from app.services.vbr_student_report import build_student_vbr_report

logger = logging.getLogger(__name__)

_PROJECTS_TABLE = "vbr_projects"
_USERS_TABLE = "users"

_TOKEN_GENERATION_ATTEMPTS = 5

_REPORT_TITLE = "Verified Build Report"
_PUBLIC_PATH_PREFIX = "/vbr/report/"

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


def _public_github_proof(github_proof: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(github_proof, dict):
        return None
    scrubbed = dict(github_proof)
    scrubbed["public_safe_summary"] = _scrub_numeric_scores(github_proof.get("public_safe_summary") or "")
    return scrubbed


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

    public = {
        "report_title": _REPORT_TITLE,
        "project_title": report.get("project_title") or "",
        "candidate_display_name": _lookup_display_name(db, owner_id),
        "project_summary": report.get("project_description") or "",
        "student_role": report.get("student_role") or "",
        "repo_full_name": report.get("repo_full_name"),
        "deployed_url": report.get("deployed_url") or None,
        "claimed_skills": list(report.get("claimed_skills") or []),
        "evidence_package": report.get("evidence_package") or {},
        "github_proof": _public_github_proof(report.get("github_proof")),
        "documents": list(report.get("documents") or []),
        "website_proofs": list(report.get("website_proofs") or []),
        "project_defense_analysis": report.get("project_defense_analysis"),
        "skill_evidence": list(report.get("skill_evidence") or []),
        "video_evidence_chips": _sanitize_video_chips(report.get("video_evidence_chips") or []),
        "limitations": _public_limitations(report.get("limitations") or []),
        "published_at": project.get("public_report_published_at"),
        "generated_at": report.get("generated_at"),
        "verification_note": _VERIFICATION_NOTE,
    }

    # Recursively scrub score-style fragments from every public string field
    # (must-fix: the scrubber is no longer limited to github_proof). Applied
    # after the projection is built and before the response is returned.
    public = _scrub_public_report(public)

    if _contains_unsafe_fields(public):
        logger.warning("[VBR] Public project report failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    return public
