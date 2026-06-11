"""VBR keyframe-extraction skeleton (T5E).

T5E scope: extract a small, deterministic set of keyframe images from a
session's already-processed full session video (T5C), upload them to
private storage, and store ``vbr_keyframes`` rows. This module does NOT run
OCR, visual/vision analysis, or any LLM call — keyframes are stored as
private (P3) evidence only, for later analysis stages.

Extraction uses a safe ffmpeg argv-only command (no ``shell=True``) with a
bounded per-frame timeout. Tests monkeypatch ``run_ffmpeg_frame_extraction``
to write deterministic JPEG bytes when ffmpeg is unavailable.

TODO(T6): populate ``vision_summary`` with real OCR/vision analysis output.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.vbr_session_recording import get_owned_vbr_session_or_404, get_session

logger = logging.getLogger(__name__)

_SESSIONS_TABLE = "vbr_verification_sessions"
_KEYFRAMES_TABLE = "vbr_keyframes"

# Fake-DB only (dict-based test store): storage_path -> raw bytes. Shared
# with vbr_media_processing's full-video upload/download. Never used with a
# real Supabase client.
_MEDIA_OBJECTS_TABLE = "_vbr_media_objects"

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_WORK_DIR_ROOT = Path(tempfile.gettempdir()) / "veribridge_vbr_keyframes"

_MAX_KEYFRAMES = 8
_DEFAULT_DURATION_S = 40.0
_FFMPEG_FRAME_TIMEOUT_SECONDS = 15

_KEYFRAMES_FAILED_DETAIL = {
    "code": "vbr_keyframes_extraction_failed",
    "message": "Could not extract keyframes. Please try again.",
}

__all__ = [
    "build_keyframes_work_dir",
    "compute_keyframe_timestamps",
    "keyframe_storage_path",
    "ffmpeg_available",
    "build_safe_ffmpeg_frame_command",
    "run_ffmpeg_frame_extraction",
    "extract_keyframe_files",
    "upload_keyframe_image",
    "extract_keyframes_skeleton",
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


# ── Local workdir + timestamp planning ──────────────────────────────────────


def build_keyframes_work_dir(session_id: str) -> Path:
    """Return (and create) a controlled local temp directory for one session.

    ``session_id`` is already DB-resolved (via ``get_owned_vbr_session_or_404``)
    by the time this is called, but it is validated again here defensively
    since it becomes part of a filesystem path.
    """
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_keyframes_invalid_session_id",
                "message": "Session id is not safe for keyframe extraction.",
            },
        )

    work_dir = _WORK_DIR_ROOT / session_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def compute_keyframe_timestamps(
    duration_s: float | None, frame_count: int = _MAX_KEYFRAMES
) -> list[float]:
    """Return evenly-spaced timestamps (seconds) within ``duration_s``.

    Falls back to ``_DEFAULT_DURATION_S`` when the session has no recorded
    duration. Timestamps avoid 0 and the very end of the video to reduce the
    chance of seeking past EOF.
    """
    if frame_count <= 0:
        return []

    duration = float(duration_s) if duration_s and duration_s > 0 else _DEFAULT_DURATION_S
    step = duration / (frame_count + 1)
    return [round(step * (index + 1), 3) for index in range(frame_count)]


def keyframe_storage_path(session_id: str, frame_index: int) -> str:
    """Return the exact, server-controlled object path for one keyframe image."""
    return f"vbr/sessions/{session_id}/frames/{frame_index:03d}.jpg"


# ── ffmpeg frame extraction ─────────────────────────────────────────────────


def ffmpeg_available() -> bool:
    """Return True if an ``ffmpeg`` binary is on PATH."""
    return shutil.which("ffmpeg") is not None


def build_safe_ffmpeg_frame_command(input_path: Path, timestamp_s: float, output_path: Path) -> list[str]:
    """Return an argv list that extracts a single frame near ``timestamp_s``.

    This is a command builder only — callers must pass the result directly
    to ``subprocess.run`` (never ``shell=True``).
    """
    return [
        "ffmpeg",
        "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(input_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]


def run_ffmpeg_frame_extraction(input_path: Path, timestamp_s: float, output_path: Path) -> None:
    """Extract one frame near ``timestamp_s`` into ``output_path``.

    Uses ``subprocess.run`` with an argv list only (never ``shell=True``) and
    a bounded per-frame timeout. Raises a controlled ``HTTPException`` (500,
    ``vbr_keyframes_extraction_failed``) on any failure. Raw stderr is never
    included in the exception or logged.
    """
    if not ffmpeg_available():
        logger.warning("[VBR] ffmpeg keyframe extraction failed (stage=binary_missing)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        )

    command = build_safe_ffmpeg_frame_command(input_path, timestamp_s, output_path)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=_FFMPEG_FRAME_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("[VBR] ffmpeg keyframe extraction failed (stage=run, reason=%s)", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        ) from exc

    if result.returncode != 0:
        logger.warning("[VBR] ffmpeg keyframe extraction exited non-zero (stage=run)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        )

    if not output_path.is_file() or output_path.stat().st_size <= 0:
        logger.warning("[VBR] ffmpeg keyframe output missing or empty (stage=verify_output)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        )


def extract_keyframe_files(input_path: Path, work_dir: Path, timestamps: list[float]) -> list[Path]:
    """Extract one frame per timestamp into ``work_dir``, in order."""
    frame_paths: list[Path] = []
    for index, timestamp_s in enumerate(timestamps):
        output_path = work_dir / f"frame_{index:03d}.jpg"
        run_ffmpeg_frame_extraction(input_path, timestamp_s, output_path)
        frame_paths.append(output_path)
    return frame_paths


# ── Full video download (reads T5C output) ──────────────────────────────────


def _download_full_video_bytes(db: Any, storage_path: str) -> bytes:
    """Download the processed full-session video's raw bytes from private storage.

    Fake dict DBs read from ``_vbr_media_objects`` (populated by
    ``vbr_media_processing.upload_processed_full_video``). Real Supabase
    clients fail closed with a 503 if the media bucket is not configured or
    the storage client is unavailable.
    """
    if isinstance(db, dict):
        media_store = db.get(_MEDIA_OBJECTS_TABLE, {})
        data = media_store.get(storage_path)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "vbr_media_full_video_download_failed",
                    "message": "Processed full session video could not be loaded.",
                },
            )
        return bytes(data)

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
        logger.warning("[VBR] Full video download failed (stage=keyframes_download)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_full_video_download_failed",
                "message": "Processed full session video could not be loaded.",
            },
        ) from exc

    if not isinstance(data, (bytes, bytearray)):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "vbr_media_full_video_download_failed",
                "message": "Processed full session video could not be loaded.",
            },
        )

    return bytes(data)


# ── Keyframe image upload ────────────────────────────────────────────────────



def _best_effort_delete_storage_objects(db: Any, storage_paths: list[str]) -> None:
    """Best-effort cleanup for private frame objects after partial upload failure.

    This intentionally logs only counts/stage, not bucket names or object paths.
    """
    if not storage_paths:
        return

    if isinstance(db, dict):
        media_store = db.get("_vbr_media_objects", {})
        for storage_path in storage_paths:
            media_store.pop(storage_path, None)
        return

    bucket = settings.supabase_vbr_media_bucket
    if not bucket or not hasattr(db, "storage"):
        return

    try:
        db.storage.from_(bucket).remove(storage_paths)
    except Exception:
        logger.warning("[VBR] Keyframe cleanup failed (stage=cleanup count=%d)", len(storage_paths))


def upload_keyframe_image(db: Any, storage_path: str, data: bytes) -> None:
    """Upload one keyframe JPEG to private storage."""
    if isinstance(db, dict):
        db.setdefault(_MEDIA_OBJECTS_TABLE, {})[storage_path] = data
        return

    bucket = settings.supabase_vbr_media_bucket
    if not bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_media_bucket_not_configured",
                "message": "Recording upload storage is not configured.",
            },
        )

    if not hasattr(db, "storage"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "vbr_storage_client_unavailable",
                "message": "Recording upload storage is unavailable.",
            },
        )

    try:
        result = db.storage.from_(bucket).upload(
            storage_path,
            data,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )
    except Exception as exc:
        logger.warning("[VBR] Keyframe upload failed (stage=upload)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        ) from exc

    has_error = bool(getattr(result, "error", None))
    if isinstance(result, dict):
        has_error = has_error or bool(result.get("error"))

    if has_error:
        logger.warning("[VBR] Keyframe upload returned an error (stage=upload)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=dict(_KEYFRAMES_FAILED_DETAIL),
        )


# ── vbr_keyframes persistence ────────────────────────────────────────────────


def _delete_session_keyframes(db: Any, session_id: str) -> None:
    if isinstance(db, dict):
        store = db.setdefault(_KEYFRAMES_TABLE, {})
        for row_id in [k for k, row in store.items() if row.get("session_id") == session_id]:
            del store[row_id]
        return

    db.table(_KEYFRAMES_TABLE).delete().eq("session_id", session_id).execute()


def _insert_keyframes(db: Any, session_id: str, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_KEYFRAMES_TABLE, {})
        rows = []
        for frame in frames:
            row = {
                "id": str(uuid4()),
                "session_id": session_id,
                "ts_s": frame["ts_s"],
                "storage_path": frame["storage_path"],
                "phash": None,
                "near_question_id": None,
                "vision_summary": {"frame_index": frame["frame_index"], "strategy": "interval"},
                "created_at": _now(),
            }
            store[row["id"]] = row
            rows.append(row)
        return rows

    payload = [
        {
            "session_id": session_id,
            "ts_s": frame["ts_s"],
            "storage_path": frame["storage_path"],
            "phash": None,
            "near_question_id": None,
            "vision_summary": {"frame_index": frame["frame_index"], "strategy": "interval"},
        }
        for frame in frames
    ]
    result = db.table(_KEYFRAMES_TABLE).insert(payload).execute()
    return getattr(result, "data", []) or []


def _mark_session_keyframes_extracted(db: Any, session_id: str, frame_count: int) -> dict[str, Any]:
    session = get_session(db, session_id) or {}
    telemetry = dict(session.get("telemetry") or {})

    completed_at = _now()
    telemetry["keyframes"] = {
        "extracted": True,
        "frame_count": frame_count,
        "strategy": "interval",
        "completed_at": completed_at,
    }

    return _update_session(db, session_id, {"telemetry": telemetry, "updated_at": completed_at})


# ── Orchestration ────────────────────────────────────────────────────────────


def extract_keyframes_skeleton(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Extract a deterministic set of keyframes for a processed session.

    Validates ownership, that the session has been media-processed, and that
    a processed full-session video exists, then downloads the full video into
    a controlled temp directory, extracts up to ``_MAX_KEYFRAMES`` frames at
    evenly-spaced timestamps, uploads them to private storage, and stores
    ``vbr_keyframes`` rows. Idempotent: re-running replaces any existing
    keyframe rows for this session rather than duplicating them.

    No OCR, vision analysis, or LLM call happens here. The response never
    includes storage paths, signed URLs, local paths, or image bytes.
    """
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to extract keyframes.",
            },
        )

    telemetry = session.get("telemetry") or {}
    media_processing = telemetry.get("media_processing") or {}
    full_video = media_processing.get("full_video") or {}
    full_video_storage_path = full_video.get("storage_path")
    if not full_video_storage_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_full_video_missing",
                "message": "Processed full session video was not found for this session.",
            },
        )

    timestamps = compute_keyframe_timestamps(session.get("duration_s"))

    uploaded_frame_paths: list[str] = []
    work_dir = build_keyframes_work_dir(session_id)
    try:
        video_bytes = _download_full_video_bytes(db, full_video_storage_path)
        input_path = work_dir / "full.webm"
        input_path.write_bytes(video_bytes)

        frame_paths = extract_keyframe_files(input_path, work_dir, timestamps)

        frames: list[dict[str, Any]] = []
        for index, (timestamp_s, frame_path) in enumerate(zip(timestamps, frame_paths)):
            frame_storage_path = keyframe_storage_path(session_id, index)
            try:
                upload_keyframe_image(db, frame_storage_path, frame_path.read_bytes())
            except HTTPException:
                _best_effort_delete_storage_objects(db, uploaded_frame_paths)
                raise

            uploaded_frame_paths.append(frame_storage_path)
            frames.append({"ts_s": timestamp_s, "storage_path": frame_storage_path, "frame_index": index})
    except HTTPException:
        _best_effort_delete_storage_objects(db, uploaded_frame_paths)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    _delete_session_keyframes(db, session_id)
    _insert_keyframes(db, session_id, frames)
    updated_session = _mark_session_keyframes_extracted(db, session_id, len(frames))

    logger.info(
        "[VBR] Keyframes extracted for session %s (frame_count=%d)",
        session_id,
        len(frames),
    )

    return {
        "session_id": session_id,
        "frame_count": len(frames),
        "status": updated_session.get("status") or "processed",
        "message": "Keyframes extracted using a deterministic interval strategy. OCR/vision analysis is not yet implemented.",
    }
