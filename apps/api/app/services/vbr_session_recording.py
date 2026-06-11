"""Session recording/upload foundation for VBR verification sessions (T4A skeleton).


MVP scope only: backend metadata endpoints for starting a recording session,
recording chunk metadata, merging telemetry, and finalizing a session. No
real Supabase signed upload URLs are minted here.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath


from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

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
    "chunk_storage_prefix",
]


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


def chunk_storage_prefix(session_id: str) -> str:
    return f"vbr/sessions/{session_id}/chunks/"


def validate_chunk_payload(
    session_id: str,
    chunk_index: int,
    storage_path: str,
    chunk_bytes: int,
    sha256: str | None = None,
) -> None:
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

    expected_prefix = chunk_storage_prefix(session_id)

    if "\\" in storage_path or storage_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_storage_path",
                "message": "storage_path must be a safe relative object path.",
            },
        )

    path = PurePosixPath(storage_path)
    if ".." in path.parts or "." in path.parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_storage_path",
                "message": "storage_path cannot contain traversal segments.",
            },
        )

    if not storage_path.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_storage_path",
                "message": f"storage_path must start with '{expected_prefix}'.",
            },
        )

    if sha256 is not None and not _SHA256_RE.fullmatch(sha256):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_invalid_chunk_sha256",
                "message": "sha256 must be a 64-character hex digest.",
            },
        )

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
