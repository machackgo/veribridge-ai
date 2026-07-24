"""Public VBR report read access by public token (T7B).

T7B scope: read-only public access to a published ``vbr_reports`` row by its
``public_token``. ``public_token`` is minted only at publish time (T7A) and
cleared on unpublish, so this module never mints, rotates, or clears tokens.

This module does NOT call any LLM and never returns the public token itself,
storage paths, signed URLs, local/temp paths, full transcript text, raw
evidence metadata, or internal database identifiers.
"""

from __future__ import annotations

import logging

from typing import Any

from fastapi import HTTPException, status

from app.services.passport_visibility import owner_passport_is_public
from app.services.vbr_report_publish import _contains_unsafe_fields

logger = logging.getLogger(__name__)

_REPORTS_TABLE = "vbr_reports"

_VERIFICATION_NOTE = (
    "This report reflects evidence reviewed from the project's repository, a recorded "
    "walkthrough, transcript, and automated verification checks. It does not guarantee "
    "employment, skill mastery, or identity."
)

__all__ = ["get_public_report"]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_public_report_not_found",
            "message": "This report is not available.",
        },
    )


# ── Lookups ──────────────────────────────────────────────────────────────────


def _find_report_by_token(db: Any, public_token: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return next(
            (
                row
                for row in db.setdefault(_REPORTS_TABLE, {}).values()
                if row.get("public_token") == public_token
            ),
            None,
        )

    result = db.table(_REPORTS_TABLE).select("*").eq("public_token", public_token).limit(1).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _report_owner_id(db: Any, report: dict[str, Any]) -> str | None:
    """Owner ``user_id`` via the report's project row; None when unknown."""
    project_id = report.get("project_id")
    if not project_id:
        return None
    try:
        if isinstance(db, dict):
            row = db.setdefault("vbr_projects", {}).get(str(project_id))
        else:
            result = (
                db.table("vbr_projects")
                .select("user_id")
                .eq("id", str(project_id))
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - fail closed via missing owner
        return None
    if not isinstance(row, dict):
        return None
    user_id = row.get("user_id")
    return str(user_id) if user_id else None


# ── Response builder ────────────────────────────────────────────────────────


def _build_public_claims(body: dict[str, Any]) -> list[dict[str, Any]]:
    claims = body.get("claims") or []
    if not isinstance(claims, list):
        return []

    public_claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        public_claims.append(
            {
                "claim_text": claim.get("claim_text"),
                "judgment": claim.get("judgment"),
                "rationale": claim.get("rationale"),
                "evidence_count": len(claim.get("evidence_item_ids") or []),
            }
        )
    return public_claims


# ── Orchestration ────────────────────────────────────────────────────────────


_UNSAFE_PUBLIC_KEYS = {
    "storagepath",
    "storage_path",
    "mediastoragepath",
    "media_storage_path",
    "signedurl",
    "signed_url",
    "signedpath",
    "signed_path",
    "publictoken",
    "public_token",
    "localpath",
    "local_path",
    "temppath",
    "temp_path",
    "tmppath",
    "tmp_path",
    "raw",
    "rawmetadata",
    "raw_metadata",
    "metadata",
    "fulltext",
    "full_text",
    "fulltranscript",
    "full_transcript",
    "transcripttext",
    "transcript_text",
}

_UNSAFE_PUBLIC_VALUES = (
    "vbr/sessions/",
    "/tmp/",
    "supabase.co/storage",
    "/storage/v1/object",
    "signed_url",
    "signedurl",
    "signedUrl",
)


def _normalize_public_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum() or ch == "_")


def _contains_unsafe_public_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = _normalize_public_key(str(key))
            compact_key = normalized_key.replace("_", "")
            if normalized_key in _UNSAFE_PUBLIC_KEYS or compact_key in _UNSAFE_PUBLIC_KEYS:
                return True
            if _contains_unsafe_public_fields(nested):
                return True
        return False

    if isinstance(value, list):
        return any(_contains_unsafe_public_fields(item) for item in value)

    if isinstance(value, str):
        lowered = value.lower()
        return any(pattern.lower() in lowered for pattern in _UNSAFE_PUBLIC_VALUES)

    return False


def get_public_report(db: Any, public_token: str) -> dict[str, Any]:
    """Return a sanitized public projection of a published VBR report.

    Looks up ``vbr_reports`` by ``public_token``. Raises 404 unless a row is
    found, its ``status`` is ``published``, its ``public_token`` is still
    set, and its body passes the same unsafe-field scan enforced at publish
    time. The returned payload never contains the public token, storage
    paths, signed URLs, local/temp paths, full transcript text, raw evidence
    item IDs, or session/report identifiers.
    """
    if not public_token:
        raise _not_found()

    report = _find_report_by_token(db, public_token)
    if report is None:
        raise _not_found()

    if report.get("status") != "published" or not report.get("public_token"):
        raise _not_found()

    # Passport visibility is the master privacy switch: even a published legacy
    # report goes dark while the owner's Work Passport is Private. Nothing is
    # deleted, so making the Passport Public restores the link.
    owner_id = _report_owner_id(db, report)
    if not owner_passport_is_public(db, owner_id):
        raise _not_found()

    # Granular disclosure (migration 063): a legacy token honors the SAME
    # per-project policy as the canonical report — a hidden project or hidden
    # report is the same generic 404.
    from app.services.passport_disclosure import load_effective_disclosure

    disclosure = load_effective_disclosure(db, owner_id, passport_public=True)
    if not disclosure.report_visible(str(report.get("project_id") or "")):
        raise _not_found()

    body = report.get("body") or {}
    if not isinstance(body, dict) or not body:
        raise _not_found()

    if _contains_unsafe_public_fields(body):
        logger.warning("[VBR] Public report body failed the unsafe-field scan; refusing to serve.")
        raise _not_found()

    summary = body.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}

    return {
        "project_title": summary.get("project_title"),
        "repo_full_name": summary.get("repo_full_name"),
        "status": "published",
        "published_at": report.get("published_at"),
        "claim_count": summary.get("claim_count") or len(body.get("claims") or []),
        "evidence_count": summary.get("evidence_count"),
        "claims": _build_public_claims(body),
        "methodology": list(body.get("methodology") or []),
        "verification_note": _VERIFICATION_NOTE,
        # Migration path to the canonical renderer: when this legacy report's
        # project also has an ACTIVE new-style public report token, the client
        # redirects the recruiter to /vbr/report/{token}. Never a private
        # route; None when no published canonical report exists.
        "canonical_report_path": _canonical_report_path(db, report.get("project_id")),
    }


def _canonical_report_path(db: Any, project_id: Any) -> str | None:
    """``/vbr/report/{token}`` for this project's active canonical report.

    Best-effort: any lookup problem returns ``None`` so the legacy report
    still renders rather than breaking an old shared link.
    """
    if not project_id:
        return None
    try:
        if isinstance(db, dict):
            row = db.setdefault("vbr_projects", {}).get(str(project_id))
        else:
            result = (
                db.table("vbr_projects")
                .select("public_report_token")
                .eq("id", str(project_id))
                .limit(1)
                .execute()
            )
            rows = getattr(result, "data", []) or []
            row = rows[0] if rows else None
    except Exception:  # pragma: no cover - the redirect is optional
        return None
    if not isinstance(row, dict):
        return None
    token = row.get("public_report_token")
    if isinstance(token, str) and token.strip():
        return f"/vbr/report/{token.strip()}"
    return None
