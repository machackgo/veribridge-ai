"""VBR report review/publish flow (T7A).

T7A scope: backend-only review/publish/unpublish/status flow for the private
``vbr_reports`` draft created in T6C. This module does NOT call any LLM,
build a public report page, or expose private evidence (storage paths,
signed URLs, local temp paths, full transcript text).

A ``public_token`` is created only at publish time. Unpublishing clears it so
old links stop resolving. All operations manually enforce ownership via
``get_owned_vbr_session_or_404`` since ``get_db`` returns the service-role
client which bypasses RLS.

TODO(admin-review): for MVP, the owning student can publish directly. Before
production this must be gated behind an admin/human-review step.
"""

from __future__ import annotations

import logging
import secrets

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import _advance_project_status
from app.services.vbr_session_recording import get_owned_vbr_session_or_404

logger = logging.getLogger(__name__)

_REPORTS_TABLE = "vbr_reports"
_REPORT_CLAIMS_TABLE = "vbr_report_claims"

_REVIEWABLE_STATUSES = {"draft", "in_review"}
_TOKEN_GENERATION_ATTEMPTS = 5

# Keys/value patterns that must never appear in a publishable report body.
_UNSAFE_BODY_KEYS = {
    "storage_path",
    "storagepath",
    "media_storage_path",
    "mediastoragepath",
    "signed_url",
    "signedurl",
    "signed_path",
    "signedpath",
    "local_path",
    "localpath",
    "temp_path",
    "temppath",
    "tmp_path",
    "tmppath",
    "public_token",
    "publictoken",
    "full_transcript",
    "fulltranscript",
    "transcript_text",
    "transcripttext",
    "full_text",
    "fulltext",
    "raw",
    "raw_metadata",
    "rawmetadata",
}

_UNSAFE_VALUE_PATTERNS = (
    "vbr/sessions/",
    "/tmp/",
    "signed_url",
    "signedurl",
    "signedUrl",
    "supabase.co/storage",
    "/storage/v1/object",
)

__all__ = [
    "submit_report_review",
    "publish_report",
    "unpublish_report",
    "get_report_status",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Lookups ──────────────────────────────────────────────────────────────────


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")


def _body_contains_unsafe_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = _normalize_key(str(key))
            compact_key = normalized_key.replace("_", "")
            if normalized_key in _UNSAFE_BODY_KEYS or compact_key in _UNSAFE_BODY_KEYS:
                return True
            if _body_contains_unsafe_fields(nested):
                return True
        return False

    if isinstance(value, list):
        return any(_body_contains_unsafe_fields(item) for item in value)

    if isinstance(value, str):
        lowered = value.lower()
        return any(pattern.lower() in lowered for pattern in _UNSAFE_VALUE_PATTERNS)

    return False


def _report_matches_session(report: dict[str, Any], session_id: str) -> bool:
    """Check that ``report`` belongs to ``session_id``.

    The ``session_id`` column is the primary association. ``body.summary.session_id``
    is checked as defense-in-depth when present: if it disagrees with the
    session_id column, the report is treated as not belonging to this session.
    """
    if str(report.get("session_id") or "") != str(session_id):
        return False

    body = report.get("body") or {}
    if isinstance(body, dict):
        summary = body.get("summary") or {}
        if isinstance(summary, dict) and summary.get("session_id") is not None:
            if str(summary.get("session_id")) != str(session_id):
                return False

    return True


def _require_session_report(report: dict[str, Any] | None, session_id: str) -> dict[str, Any]:
    if report is None or not _report_matches_session(report, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "vbr_report_not_found",
                "message": "No report draft was found for this verification session.",
            },
        )
    return report


def _get_report_by_session(db: Any, project_id: str, session_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_REPORTS_TABLE, {}).values()
            if row.get("project_id") == project_id and row.get("session_id") == session_id
        ]
        rows.sort(key=lambda row: row.get("version", 0), reverse=True)
        return rows[0] if rows else None

    result = (
        db.table(_REPORTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("session_id", session_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _count_report_claims(db: Any, report_id: str) -> int:
    if isinstance(db, dict):
        return sum(1 for row in db.setdefault(_REPORT_CLAIMS_TABLE, {}).values() if row.get("report_id") == report_id)

    result = db.table(_REPORT_CLAIMS_TABLE).select("id", count="exact").eq("report_id", report_id).execute()
    count = getattr(result, "count", None)
    if count is not None:
        return count
    rows = getattr(result, "data", []) or []
    return len(rows)


def _token_exists(db: Any, token: str) -> bool:
    if isinstance(db, dict):
        return any(row.get("public_token") == token for row in db.setdefault(_REPORTS_TABLE, {}).values())

    result = db.table(_REPORTS_TABLE).select("id").eq("public_token", token).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return bool(rows)


# ── Persistence ──────────────────────────────────────────────────────────────


def _update_report(db: Any, report_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_REPORTS_TABLE, {}).get(report_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_REPORTS_TABLE).update(updates).eq("id", report_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


# ── Safety ───────────────────────────────────────────────────────────────────


def _contains_unsafe_fields(value: Any) -> bool:
    """Recursively scan a report body for fields that must never be published.

    Blocks storage paths, signed URLs, local temp paths, and full transcript
    text from ever reaching a publishable report.
    """
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(key, str) and key.lower() in _UNSAFE_BODY_KEYS:
                return True
            if _contains_unsafe_fields(val):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_unsafe_fields(item) for item in value)
    if isinstance(value, str):
        return any(pattern in value for pattern in _UNSAFE_VALUE_PATTERNS)
    return False


def _generate_public_token(db: Any) -> str:
    for _ in range(_TOKEN_GENERATION_ATTEMPTS):
        token = secrets.token_urlsafe(24)
        if not _token_exists(db, token):
            return token

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "vbr_public_token_generation_failed",
            "message": "Could not generate a unique public token. Please try again.",
        },
    )


# ── Response builders ───────────────────────────────────────────────────────


def _review_response(session_id: str, report_id: str, report_status: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "report_id": report_id,
        "status": report_status,
        "message": "Report submitted for review. No public link has been created.",
    }


def _publish_response(session_id: str, report_id: str, report_status: str, public_token_created: bool) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "report_id": report_id,
        "status": report_status,
        "public_token_created": public_token_created,
        "message": "Report published.",
    }


def _unpublish_response(session_id: str, report_id: str, report_status: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "report_id": report_id,
        "status": report_status,
        "message": "Report unpublished. The previous public link no longer resolves.",
    }


# ── Orchestration ────────────────────────────────────────────────────────────


def submit_report_review(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Move a private draft report to ``in_review``.

    Requires ownership, a ``processed`` session, and an existing report draft
    in ``draft`` status. Idempotent if the report is already ``in_review``.
    Never creates a public token.
    """
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to submit a report for review.",
            },
        )

    project_id = str(project["id"])
    report = _require_session_report(_get_report_by_session(db, project_id, session_id), session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_not_found",
                "message": "A report draft must exist before submitting for review.",
            },
        )

    report_id = str(report["id"])
    published_report = _get_published_report(db, project_id)
    if published_report is not None and str(published_report.get("id")) != report_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_already_published",
                "message": "A published report already exists for this project.",
            },
        )

    current_status = report.get("status") or "draft"

    if current_status == "in_review":
        return _review_response(session_id, report_id, current_status)

    if current_status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_not_draft",
                "message": "Report must be in 'draft' status to submit for review.",
            },
        )

    updated = _update_report(db, report_id, {"status": "in_review", "updated_at": _now()})
    _advance_project_status(db, project, "in_review")

    logger.info("[VBR] Report submitted for review for session %s (report=%s)", session_id, report_id)

    return _review_response(session_id, report_id, updated.get("status") or "in_review")


def _get_published_report(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_REPORTS_TABLE, {}).values()
                if row.get("project_id") == project_id and row.get("status") == "published"
            ),
            None,
        )

    result = (
        db.table(_REPORTS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .eq("status", "published")
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def publish_report(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Publish a private report, minting a public token for the first time.

    Requires ownership, an existing report in ``draft``/``in_review`` status
    with a non-empty body and at least one report claim, and a body that
    contains no unsafe fields (storage paths, signed URLs, local temp paths,
    full transcript text). Idempotent if already published: returns the
    existing status without regenerating the token.
    """
    _session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    project_id = str(project["id"])
    report = _require_session_report(_get_report_by_session(db, project_id, session_id), session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_not_found",
                "message": "A report must exist before it can be published.",
            },
        )

    report_id = str(report["id"])
    current_status = report.get("status") or "draft"

    if current_status == "published":
        return _publish_response(session_id, report_id, current_status, bool(report.get("public_token")))

    if current_status not in _REVIEWABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_not_publishable",
                "message": "Report must be in 'draft' or 'in_review' status to publish.",
            },
        )

    published_report = _get_published_report(db, project_id)
    if published_report is not None and str(published_report.get("id")) != report_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_already_published",
                "message": "A published report already exists for this project.",
            },
        )

    body = report.get("body") or {}
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_body_missing",
                "message": "Report body is required before publishing.",
            },
        )

    if _body_contains_unsafe_fields(body):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_unsafe_body",
                "message": "Report body contains fields that cannot be published.",
            },
        )

    if _count_report_claims(db, report_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_claims_missing",
                "message": "Report claims are required before publishing.",
            },
        )

    public_token = _generate_public_token(db)
    now = _now()
    updated = _update_report(
        db,
        report_id,
        {
            "status": "published",
            "public_token": public_token,
            "published_at": now,
            "updated_at": now,
        },
    )

    _advance_project_status(db, project, "published")

    logger.info("[VBR] Report published for session %s (report=%s)", session_id, report_id)

    return _publish_response(session_id, report_id, updated.get("status") or "published", True)


def unpublish_report(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Unpublish a report, clearing its public token.

    Requires ownership and a published report. Idempotent if already
    unpublished. Does not delete the report body.
    """
    _session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    project_id = str(project["id"])
    report = _require_session_report(_get_report_by_session(db, project_id, session_id), session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_report_not_found",
                "message": "No report exists for this session.",
            },
        )

    report_id = str(report["id"])
    current_status = report.get("status") or "draft"

    if current_status == "unpublished":
        return _unpublish_response(session_id, report_id, current_status)

    if current_status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_report_not_published",
                "message": "Report must be 'published' to unpublish.",
            },
        )

    updated = _update_report(
        db,
        report_id,
        {
            "status": "unpublished",
            "public_token": None,
            "updated_at": _now(),
        },
    )

    logger.info("[VBR] Report unpublished for session %s (report=%s)", session_id, report_id)

    return _unpublish_response(session_id, report_id, updated.get("status") or "unpublished")


def get_report_status(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Return a private status summary for this session's report.

    Never includes the public token itself or the report body.
    """
    _session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    project_id = str(project["id"])
    report = _require_session_report(_get_report_by_session(db, project_id, session_id), session_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "vbr_report_not_found",
                "message": "No report exists for this session yet.",
            },
        )

    report_id = str(report["id"])

    return {
        "session_id": session_id,
        "report_id": report_id,
        "status": report.get("status") or "draft",
        "has_public_token": bool(report.get("public_token")),
        "claim_count": _count_report_claims(db, report_id),
        "updated_at": str(report.get("updated_at") or ""),
        "published_at": report.get("published_at"),
    }
