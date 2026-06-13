"""Session recording/upload foundation for VBR verification sessions (T4A/T4D).

T4D adds real chunk upload targets: ``create_chunk_upload_target`` mints a
short-lived Supabase Storage signed upload URL (when
``SUPABASE_VBR_MEDIA_BUCKET`` is configured) for a server-computed
``storage_path``. The browser uploads chunk bytes directly to that URL, then
calls the existing chunk metadata endpoint, which validates the path matches
exactly.
"""
from __future__ import annotations

import logging
import re

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSIONS_TABLE = "vbr_verification_sessions"
_CHUNKS_TABLE = "vbr_video_chunks"
_CONSENT_TABLE = "consent_records"

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_MAX_CHUNK_BYTES = 25 * 1024 * 1024  # 25MB

__all__ = [
    "get_session",
    "get_owned_vbr_session_or_404",
    "has_recording_consent",
    "create_recording_consent",
    "validate_chunk_payload",
    "upsert_video_chunk",
    "count_chunks",
    "start_session",
    "update_session_telemetry",
    "finalize_session",
    "chunk_storage_path",
    "create_chunk_upload_target",
    "check_recording_storage_readiness",
    "check_session_recording_readiness",
    "cancel_recording_session",
]

_RETRYABLE_RECORDING_STATUSES = {"created", "recording"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Session lookup ───────────────────────────────────────────────────────────


def get_session(db: Any, session_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.setdefault(_SESSIONS_TABLE, {}).get(session_id)

    result = (
        db.table(_SESSIONS_TABLE)
        .select("*")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    return getattr(result, "data", None) if result is not None else None


def _session_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "vbr_session_not_found",
            "message": "Verification session not found.",
            "session_id": session_id,
        },
    )


def get_owned_vbr_session_or_404(
    db: Any, session_id: str, user_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return owned session + project or a generic session-not-found error.

    Important: for cross-user access, do not leak the parent project_id.
    """
    from app.api.v1.endpoints.vbr_projects import get_owned_vbr_project_or_404

    session = get_session(db, session_id)
    if session is None:
        raise _session_not_found(session_id)

    try:
        project = get_owned_vbr_project_or_404(db, str(session["project_id"]), user_id)
    except HTTPException:
        raise _session_not_found(session_id) from None

    return session, project

def _update_session(db: Any, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_SESSIONS_TABLE, {}).get(session_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_SESSIONS_TABLE).update(updates).eq("id", session_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


# ── Consent ──────────────────────────────────────────────────────────────────


def has_recording_consent(db: Any, user_id: str) -> bool:
    if isinstance(db, dict):
        return any(
            row.get("user_id") == user_id and row.get("kind") == "recording" and row.get("granted")
            for row in db.setdefault(_CONSENT_TABLE, {}).values()
        )

    result = (
        db.table(_CONSENT_TABLE)
        .select("id")
        .eq("user_id", user_id)
        .eq("kind", "recording")
        .eq("granted", True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return bool(rows)


def create_recording_consent(
    db: Any,
    user_id: str,
    text_version: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "kind": "recording",
        "granted": True,
        "text_version": text_version or "recording_v1",
        "metadata": metadata or {},
        "created_at": _now(),
    }

    if isinstance(db, dict):
        db.setdefault(_CONSENT_TABLE, {})[row["id"]] = row
        return row

    result = db.table(_CONSENT_TABLE).insert(row).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else row


# ── Video chunks ─────────────────────────────────────────────────────────────


def chunk_storage_path(session_id: str, chunk_index: int) -> str:
    """Return the exact, server-controlled object path for a session chunk.

    Clients never choose this path — both the upload-url endpoint and the
    chunk metadata endpoint derive it from ``session_id``/``chunk_index`` and
    require an exact match.
    """
    return f"vbr/sessions/{session_id}/chunks/{chunk_index:03d}.webm"


def _validate_chunk_basics(chunk_index: int, chunk_bytes: int, sha256: str) -> None:
    if chunk_index < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_index",
                "message": "chunk_index must be greater than or equal to 0.",
            },
        )

    if chunk_bytes <= 0 or chunk_bytes > _MAX_CHUNK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_size",
                "message": f"bytes must be greater than 0 and at most {_MAX_CHUNK_BYTES}.",
            },
        )

    if not _SHA256_RE.fullmatch(sha256 or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_sha256",
                "message": "sha256 must be a 64-character hex digest.",
            },
        )


def validate_chunk_payload(
    session_id: str,
    chunk_index: int,
    storage_path: str,
    chunk_bytes: int,
    sha256: str,
) -> None:
    _validate_chunk_basics(chunk_index, chunk_bytes, sha256)

    expected_path = chunk_storage_path(session_id, chunk_index)
    if storage_path != expected_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_storage_path",
                "message": f"storage_path must equal '{expected_path}'.",
            },
        )


def create_chunk_upload_target(
    db: Any,
    session_id: str,
    chunk_index: int,
    chunk_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    """Validate a proposed chunk and return a short-lived upload target.

    The returned ``storage_path`` is always the server-computed exact path —
    the client cannot influence it. ``upload_url`` is a real Supabase Storage
    signed upload URL when ``SUPABASE_VBR_MEDIA_BUCKET`` is configured and a
    real Supabase client is in use; otherwise it is a clearly-marked
    placeholder (see ``_create_signed_upload_url``).
    """
    _validate_chunk_basics(chunk_index, chunk_bytes, sha256)

    storage_path = chunk_storage_path(session_id, chunk_index)
    upload_url = _create_signed_upload_url(db, storage_path)

    return {
        "upload_url": upload_url,
        "storage_path": storage_path,
        "chunk_index": chunk_index,
        "expires_in": None,
    }


def check_recording_storage_readiness(db: Any) -> dict[str, Any]:
    """Check whether recording-chunk upload storage is ready to use.

    Returns a small, safe-to-render dict — ``ready``, ``code``, and
    ``message`` only. Never includes bucket names, storage paths, signed
    URLs, or other configuration details.
    """
    if isinstance(db, dict):
        return {"ready": True, "code": None, "message": "Recording upload storage is ready."}

    if not settings.supabase_vbr_media_bucket:
        return {
            "ready": False,
            "code": "vbr_media_bucket_not_configured",
            "message": "Recording upload storage is not configured.",
        }

    if not hasattr(db, "storage"):
        return {
            "ready": False,
            "code": "vbr_storage_client_unavailable",
            "message": "Recording upload storage is unavailable.",
        }

    return {"ready": True, "code": None, "message": "Recording upload storage is ready."}


def check_session_recording_readiness(db: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Check whether ``session`` is currently usable for browser recording.

    Combines the session-status check with ``check_recording_storage_readiness``
    so the frontend can run a single preflight call before requesting any
    media permissions.
    """
    if session.get("status") not in _RETRYABLE_RECORDING_STATUSES:
        return {
            "ready": False,
            "code": "vbr_session_not_retryable",
            "message": "This session can no longer be used for recording.",
        }

    return check_recording_storage_readiness(db)


def cancel_recording_session(db: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Reset a stuck, zero-chunk 'recording' session back to 'created'.

    Callers must already have verified the session is owned by the current
    user, in 'recording' status, and has zero uploaded chunks.
    """
    now = _now()
    return _update_session(
        db,
        str(session["id"]),
        {"status": "created", "started_at": None, "updated_at": now},
    )


def _create_signed_upload_url(db: Any, storage_path: str) -> str:
    """Create a real signed upload URL for a private VBR media object.

    Test fake DBs may return a deterministic fake URL. Real service clients must
    fail closed if storage is not configured or the signed URL response is invalid.
    """
    if isinstance(db, dict):
        return f"unconfigured://test-vbr-media-bucket/{storage_path}"

    readiness = check_recording_storage_readiness(db)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": readiness["code"], "message": readiness["message"]},
        )

    bucket = settings.supabase_vbr_media_bucket

    try:
        signed = db.storage.from_(bucket).create_signed_upload_url(storage_path)
    except Exception as exc:
        logger.warning("[VBR] Failed to create signed upload URL for %s: %s", storage_path, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_chunk_upload_url_unavailable",
                "message": "Could not create an upload target. Please try again.",
            },
        ) from exc

    upload_url = signed.get("signed_url") or signed.get("signedUrl")
    if not upload_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_chunk_upload_url_unavailable",
                "message": "Could not create an upload target. Please try again.",
            },
        )

    return upload_url

def upsert_video_chunk(
    db: Any,
    session_id: str,
    chunk_index: int,
    storage_path: str,
    chunk_bytes: int,
    sha256: str | None,
) -> dict[str, Any]:
    now = _now()

    if isinstance(db, dict):
        store = db.setdefault(_CHUNKS_TABLE, {})
        existing = next(
            (
                row
                for row in store.values()
                if row.get("session_id") == session_id and row.get("chunk_index") == chunk_index
            ),
            None,
        )
        if existing is not None:
            existing.update(
                {
                    "storage_path": storage_path,
                    "bytes": chunk_bytes,
                    "sha256": sha256,
                    "received_at": now,
                }
            )
            return existing

        row = {
            "id": str(uuid4()),
            "session_id": session_id,
            "chunk_index": chunk_index,
            "storage_path": storage_path,
            "bytes": chunk_bytes,
            "sha256": sha256,
            "received_at": now,
        }
        store[row["id"]] = row
        return row

    result = (
        db.table(_CHUNKS_TABLE)
        .upsert(
            {
                "session_id": session_id,
                "chunk_index": chunk_index,
                "storage_path": storage_path,
                "bytes": chunk_bytes,
                "sha256": sha256,
                "received_at": now,
            },
            on_conflict="session_id,chunk_index",
        )
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def count_chunks(db: Any, session_id: str) -> int:
    if isinstance(db, dict):
        return sum(1 for row in db.setdefault(_CHUNKS_TABLE, {}).values() if row.get("session_id") == session_id)

    result = db.table(_CHUNKS_TABLE).select("id", count="exact").eq("session_id", session_id).execute()
    count = getattr(result, "count", None)
    if count is not None:
        return count
    rows = getattr(result, "data", []) or []
    return len(rows)


# ── Session state transitions ───────────────────────────────────────────────


def start_session(db: Any, session: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    return _update_session(db, str(session["id"]), {"status": "recording", "started_at": now, "updated_at": now})


def update_session_telemetry(db: Any, session: dict[str, Any], telemetry: dict[str, Any], merge: bool = True) -> dict[str, Any]:
    if merge:
        merged = {**(session.get("telemetry") or {}), **telemetry}
    else:
        merged = telemetry

    return _update_session(db, str(session["id"]), {"telemetry": merged, "updated_at": _now()})


def finalize_session(db: Any, session: dict[str, Any], duration_s: int | None) -> dict[str, Any]:
    now = _now()
    updates: dict[str, Any] = {"status": "uploaded", "ended_at": now, "updated_at": now}
    if duration_s is not None:
        updates["duration_s"] = duration_s

    return _update_session(db, str(session["id"]), updates)
