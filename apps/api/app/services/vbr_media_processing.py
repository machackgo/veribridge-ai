"""VBR uploaded-session media-processing skeleton (T5A).

T5A scope only: deterministic chunk-manifest validation and the controlled
session/project status transition that must happen before any real media
processing runs. This module does NOT run ffmpeg, Whisper, OCR, keyframe
extraction, or LLM calls, and never downloads media or mints/exposes signed
URLs.
"""

from __future__ import annotations

import re

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import _advance_project_status
from app.services.vbr_session_recording import (
    chunk_storage_path,
    get_owned_vbr_session_or_404,
    get_session,
)

_SESSIONS_TABLE = "vbr_verification_sessions"
_CHUNKS_TABLE = "vbr_video_chunks"

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_MAX_TOTAL_BYTES = int(1.5 * 1024 * 1024 * 1024)  # 1.5GB MVP cap

NEXT_STEPS: list[str] = ["concat_video", "transcribe_audio", "extract_keyframes"]

__all__ = [
    "list_session_chunks",
    "validate_chunk_manifest",
    "compute_manifest_summary",
    "mark_session_processing_started",
    "mark_session_media_processed",
    "process_uploaded_session_skeleton",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _update_session(db: Any, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        row = db.setdefault(_SESSIONS_TABLE, {}).get(session_id)
        if row is not None:
            row.update(updates)
        return row or {}

    result = db.table(_SESSIONS_TABLE).update(updates).eq("id", session_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


# ── Chunk manifest ───────────────────────────────────────────────────────────


def list_session_chunks(db: Any, session_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_CHUNKS_TABLE, {}).values()
            if row.get("session_id") == session_id
        ]
        return sorted(rows, key=lambda row: row.get("chunk_index", 0))

    result = (
        db.table(_CHUNKS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .order("chunk_index")
        .execute()
    )
    return getattr(result, "data", []) or []


def validate_chunk_manifest(session_id: str, chunks: list[dict[str, Any]]) -> None:
    """Validate a session's chunk manifest deterministically.

    Raises ``HTTPException`` (400) on the first violation found. Does not
    download media or inspect anything beyond the chunk metadata rows.
    """
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_manifest_empty",
                "message": "Session has no uploaded video chunks.",
            },
        )

    chunk_indexes: list[int] = []
    for chunk in chunks:
        chunk_index = chunk.get("chunk_index")
        if not isinstance(chunk_index, int) or chunk_index < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_manifest_invalid_chunk_index",
                    "message": "Chunk manifest contains an invalid chunk index.",
                },
            )
        chunk_indexes.append(chunk_index)

    if len(set(chunk_indexes)) != len(chunk_indexes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_manifest_duplicate_chunk_index",
                "message": "Chunk manifest contains duplicate chunk indexes.",
            },
        )

    if sorted(chunk_indexes) != list(range(len(chunks))):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_manifest_non_contiguous",
                "message": "Chunk indexes must be contiguous starting at 0.",
            },
        )

    total_bytes = 0
    for chunk in sorted(chunks, key=lambda chunk: chunk["chunk_index"]):
        chunk_index = chunk["chunk_index"]
        chunk_bytes = chunk.get("bytes")
        sha256 = chunk.get("sha256") or ""
        storage_path = chunk.get("storage_path") or ""

        if not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_manifest_invalid_bytes",
                    "message": f"Chunk {chunk_index} has an invalid byte count.",
                },
            )

        if not _SHA256_RE.fullmatch(sha256):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_manifest_invalid_sha256",
                    "message": f"Chunk {chunk_index} has an invalid sha256 digest.",
                },
            )

        expected_path = chunk_storage_path(session_id, chunk_index)
        if storage_path != expected_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_manifest_invalid_storage_path",
                    "message": f"Chunk {chunk_index} storage path does not match the expected path.",
                },
            )

        total_bytes += chunk_bytes

    if total_bytes > _MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_manifest_total_bytes_exceeded",
                "message": "Session media exceeds the maximum allowed size.",
            },
        )


def compute_manifest_summary(chunks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "chunk_count": len(chunks),
        "total_bytes": sum(int(chunk.get("bytes") or 0) for chunk in chunks),
    }


# ── Session/project state transitions ───────────────────────────────────────


def mark_session_processing_started(db: Any, session_id: str) -> dict[str, Any]:
    session = get_session(db, session_id) or {}
    telemetry = dict(session.get("telemetry") or {})
    media_processing = dict(telemetry.get("media_processing") or {})
    media_processing["started_at"] = _now()
    telemetry["media_processing"] = media_processing

    return _update_session(db, session_id, {"telemetry": telemetry, "updated_at": _now()})


def mark_session_media_processed(
    db: Any, session_id: str, manifest_summary: dict[str, int]
) -> dict[str, Any]:
    session = get_session(db, session_id) or {}
    telemetry = dict(session.get("telemetry") or {})
    media_processing = dict(telemetry.get("media_processing") or {})

    completed_at = _now()
    media_processing.setdefault("started_at", completed_at)
    media_processing.update(
        {
            "manifest_verified": True,
            "chunk_count": manifest_summary["chunk_count"],
            "total_bytes": manifest_summary["total_bytes"],
            "completed_at": completed_at,
            "next_steps": list(NEXT_STEPS),
        }
    )
    telemetry["media_processing"] = media_processing

    return _update_session(
        db,
        session_id,
        {"status": "processed", "telemetry": telemetry, "updated_at": completed_at},
    )


def process_uploaded_session_skeleton(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Run the deterministic media-processing skeleton for an uploaded session.

    Validates ownership, session status, and the chunk manifest, then
    transitions the session to ``processed`` and the parent project to
    ``media_processed``. No media is read or downloaded.
    """
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "uploaded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_uploaded",
                "message": "Session must be in 'uploaded' status to process media.",
            },
        )

    chunks = list_session_chunks(db, session_id)
    validate_chunk_manifest(session_id, chunks)
    summary = compute_manifest_summary(chunks)

    mark_session_processing_started(db, session_id)
    updated_session = mark_session_media_processed(db, session_id, summary)
    _advance_project_status(db, project, "media_processed")

    return {
        "session_id": session_id,
        "status": updated_session.get("status") or "processed",
        "chunk_count": summary["chunk_count"],
        "total_bytes": summary["total_bytes"],
        "next_steps": list(NEXT_STEPS),
        "message": "Media processing manifest verified. Transcription, keyframes, and judging are not yet implemented.",
    }
