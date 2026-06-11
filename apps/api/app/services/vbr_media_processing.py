"""VBR uploaded-session media-processing skeleton (T5A + T5B).

T5A scope: deterministic chunk-manifest validation and the controlled
session/project status transition that must happen before any real media
processing runs.

T5B scope: download the validated chunks from private storage into a
controlled local temp directory, verify each downloaded file against its
recorded size/sha256, and prepare an ffmpeg concat manifest. This module
still does NOT run ffmpeg, Whisper, OCR, keyframe extraction, or LLM calls,
and never mints/exposes signed URLs or local temp paths to clients.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import tempfile

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.api.v1.endpoints.vbr_projects import _advance_project_status
from app.core.config import settings
from app.services.vbr_session_recording import (
    chunk_storage_path,
    get_owned_vbr_session_or_404,
    get_session,
)

logger = logging.getLogger(__name__)

_SESSIONS_TABLE = "vbr_verification_sessions"
_CHUNKS_TABLE = "vbr_video_chunks"

# Fake-DB only (dict-based test store): storage_path -> raw bytes, used to
# simulate non-default downloaded content for a chunk. Never used with a
# real Supabase client.
_CHUNK_BLOBS_TABLE = "vbr_video_chunk_blobs"

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_TOTAL_BYTES = int(1.5 * 1024 * 1024 * 1024)  # 1.5GB MVP cap

_WORK_DIR_ROOT = Path(tempfile.gettempdir()) / "veribridge_vbr_processing"

NEXT_STEPS: list[str] = ["concat_video", "transcribe_audio", "extract_keyframes"]

__all__ = [
    "list_session_chunks",
    "validate_chunk_manifest",
    "compute_manifest_summary",
    "mark_session_processing_started",
    "mark_session_media_processed",
    "build_processing_work_dir",
    "build_chunk_local_path",
    "download_session_chunks_to_workdir",
    "verify_downloaded_chunk_files",
    "build_ffmpeg_concat_manifest",
    "build_safe_ffmpeg_concat_command",
    "fake_chunk_bytes",
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
            "chunks_downloaded": True,
            "download_verified": True,
            "concat_manifest_created": True,
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


# ── Local workdir + storage download (T5B) ──────────────────────────────────


def build_processing_work_dir(session_id: str) -> Path:
    """Return (and create) a controlled local temp directory for one session.

    ``session_id`` is already DB-resolved (via ``get_owned_vbr_session_or_404``)
    by the time this is called, but it is validated again here defensively
    since it becomes part of a filesystem path.
    """
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_invalid_session_id",
                "message": "Session id is not safe for media processing.",
            },
        )

    work_dir = _WORK_DIR_ROOT / session_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def build_chunk_local_path(work_dir: Path, chunk_index: int) -> Path:
    """Return the local path for one chunk's downloaded bytes.

    Filenames are derived solely from ``chunk_index`` — never from any
    user-controlled string.
    """
    if chunk_index < 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_invalid_chunk_index",
                "message": "Chunk index is not safe for media processing.",
            },
        )

    return work_dir / f"chunk_{chunk_index:03d}.webm"


def fake_chunk_bytes(session_id: str, chunk_index: int, size: int) -> bytes:
    """Deterministic fake chunk content for the in-memory test database.

    Real Supabase Storage downloads never use this — see
    ``_download_chunk_bytes``. Exposed for tests so they can compute a
    matching sha256 for a given (session_id, chunk_index, size).
    """
    if size <= 0:
        return b""

    seed = f"vbr-fake-chunk:{session_id}:{chunk_index:03d}".encode("utf-8")
    repeats = (size // len(seed)) + 1
    return (seed * repeats)[:size]


def _download_chunk_bytes(
    db: Any, session_id: str, chunk_index: int, storage_path: str, expected_bytes: int
) -> bytes:
    """Download one chunk's raw bytes from the configured private bucket.

    Fake dict DBs simulate downloaded content (see ``fake_chunk_bytes`` and
    ``_CHUNK_BLOBS_TABLE``). Real Supabase clients fail closed with a 503 if
    the media bucket is not configured or the storage client is unavailable.
    """
    if isinstance(db, dict):
        blobs = db.setdefault(_CHUNK_BLOBS_TABLE, {})
        blob = blobs.get(storage_path)
        if blob is not None:
            return bytes(blob)
        return fake_chunk_bytes(session_id, chunk_index, expected_bytes)

    bucket = settings.supabase_vbr_media_bucket
    if not bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_media_bucket_not_configured",
                "message": "Recording media storage is not configured.",
            },
        )

    if not hasattr(db, "storage"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_storage_client_unavailable",
                "message": "Recording media storage is unavailable.",
            },
        )

    try:
        data = db.storage.from_(bucket).download(storage_path)
    except Exception as exc:
        logger.warning(
            "[VBR] Chunk download failed for session %s chunk %d: %s", session_id, chunk_index, exc
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_chunk_download_failed",
                "message": f"Failed to download chunk {chunk_index}.",
            },
        ) from exc

    if not isinstance(data, (bytes, bytearray)):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_chunk_download_failed",
                "message": f"Failed to download chunk {chunk_index}.",
            },
        )

    return bytes(data)


def download_session_chunks_to_workdir(
    db: Any, session_id: str, chunks: list[dict[str, Any]]
) -> list[Path]:
    """Download each chunk in order into a controlled local temp directory.

    Returns the local paths in chunk-index order. Raises ``HTTPException``
    if the storage backend is unavailable/misconfigured or a download fails.
    """
    work_dir = build_processing_work_dir(session_id)

    local_paths: list[Path] = []
    for chunk in sorted(chunks, key=lambda chunk: chunk["chunk_index"]):
        chunk_index = chunk["chunk_index"]
        storage_path = chunk["storage_path"]
        expected_bytes = int(chunk.get("bytes") or 0)

        data = _download_chunk_bytes(db, session_id, chunk_index, storage_path, expected_bytes)
        local_path = build_chunk_local_path(work_dir, chunk_index)

        try:
            local_path.write_bytes(data)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "vbr_media_chunk_download_failed",
                    "message": f"Failed to store chunk {chunk_index} for processing.",
                },
            ) from exc

        local_paths.append(local_path)

    return local_paths


def verify_downloaded_chunk_files(
    local_paths: list[Path], expected_chunks: list[dict[str, Any]]
) -> None:
    """Verify each downloaded file's size and sha256 against the manifest.

    Raises ``HTTPException`` (400) on the first mismatch found, or 500 if a
    file is missing entirely.
    """
    ordered_chunks = sorted(expected_chunks, key=lambda chunk: chunk["chunk_index"])

    for local_path, chunk in zip(local_paths, ordered_chunks):
        chunk_index = chunk["chunk_index"]

        if not local_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "vbr_media_chunk_download_failed",
                    "message": f"Chunk {chunk_index} was not downloaded.",
                },
            )

        expected_bytes = int(chunk.get("bytes") or 0)
        actual_bytes = local_path.stat().st_size
        if actual_bytes != expected_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_media_chunk_size_mismatch",
                    "message": f"Chunk {chunk_index} downloaded size does not match the recorded size.",
                },
            )

        digest = hashlib.sha256()
        with local_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)

        expected_sha256 = (chunk.get("sha256") or "").lower()
        if digest.hexdigest() != expected_sha256:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "vbr_media_chunk_hash_mismatch",
                    "message": f"Chunk {chunk_index} downloaded content does not match the recorded sha256.",
                },
            )


def build_ffmpeg_concat_manifest(local_paths: list[Path], work_dir: Path) -> Path:
    """Write an ffmpeg concat-demuxer manifest listing chunks in order.

    The manifest references only local paths produced by
    ``build_chunk_local_path`` under ``work_dir`` — never user input.
    """
    manifest_path = work_dir / "concat_manifest.txt"

    lines: list[str] = []
    for path in local_paths:
        # ffmpeg concat demuxer: wrap in single quotes, escape embedded quotes.
        escaped = path.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")

    content = "\n".join(lines)
    if content:
        content += "\n"
    manifest_path.write_text(content, encoding="utf-8")
    return manifest_path


def build_safe_ffmpeg_concat_command(manifest_path: Path, output_path: Path) -> list[str]:
    """Return an argv list for an ffmpeg concat command.

    This is a command builder only — callers must pass the result directly
    to ``subprocess.run`` (never ``shell=True``). Not executed by T5B.
    """
    return [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(manifest_path),
        "-c", "copy",
        str(output_path),
    ]


def process_uploaded_session_skeleton(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Run the media-processing pipeline foundation for an uploaded session.

    Validates ownership, session status, and the chunk manifest, then
    downloads each chunk to a controlled local temp directory, verifies the
    downloaded bytes against the recorded size/sha256, and prepares an
    ffmpeg concat manifest. Finally transitions the session to ``processed``
    and the parent project to ``media_processed``.

    No video is concatenated, transcribed, or analyzed by an LLM here.
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

    work_dir = build_processing_work_dir(session_id)
    try:
        local_paths = download_session_chunks_to_workdir(db, session_id, chunks)
        verify_downloaded_chunk_files(local_paths, chunks)
        build_ffmpeg_concat_manifest(local_paths, work_dir)
    finally:
        # TODO(T5C): a future concat/transcription step will need these
        # files again — until then, do not leave downloaded media on disk.
        shutil.rmtree(work_dir, ignore_errors=True)

    updated_session = mark_session_media_processed(db, session_id, summary)
    _advance_project_status(db, project, "media_processed")

    return {
        "session_id": session_id,
        "status": updated_session.get("status") or "processed",
        "chunk_count": summary["chunk_count"],
        "total_bytes": summary["total_bytes"],
        "next_steps": list(NEXT_STEPS),
        "message": "Media downloaded, verified, and concat manifest prepared. Transcription, keyframes, and judging are not yet implemented.",
    }
