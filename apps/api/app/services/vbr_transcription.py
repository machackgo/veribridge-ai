"""VBR transcript generation (Phase 1).

Generates a timestamped transcript for a processed Project Defense /
Verified Build Report recording, using the provider-agnostic
``transcription_service``. Stores results as ``vbr_transcripts`` +
``vbr_transcript_segments`` rows linked to ``vbr_verification_sessions``.

If no transcription provider is configured, this returns a safe HTTP 200
response (``status="not_configured"``) so the frontend can show the manual
transcript fallback instead of failing. No raw video bytes, storage paths,
or full transcript text are ever included in log messages.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.vbr_session_recording import get_owned_vbr_session_or_404, get_session

logger = logging.getLogger(__name__)

_SESSIONS_TABLE = "vbr_verification_sessions"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"
_MEDIA_OBJECTS_TABLE = "_vbr_media_objects"

_NOT_CONFIGURED_MESSAGE = "Transcription provider is not configured. Use manual transcript fallback."
_TRANSCRIPTION_FAILED_MESSAGE = (
    "Transcription failed. Please try again later or use the manual transcript fallback."
)

__all__ = [
    "TranscriptResult",
    "transcribe_session",
]


@dataclass
class TranscriptResult:
    provider: str
    language: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    full_text: str = ""
    duration_s: float = 0.0


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


# ── Full video download (reads media-processing output) ─────────────────────


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
        logger.warning("[VBR] Full video download failed (stage=transcription_download)")
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


# ── Transcript persistence ──────────────────────────────────────────────────


def _get_transcript_by_session(db: Any, session_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        for row in db.setdefault(_TRANSCRIPTS_TABLE, {}).values():
            if row.get("session_id") == session_id:
                return row
        return None

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    return getattr(result, "data", None) if result is not None else None


def _insert_transcript(
    db: Any, session_id: str, provider: str, language: str, full_text: str, raw: dict[str, Any]
) -> dict[str, Any]:
    if isinstance(db, dict):
        row = {
            "id": str(uuid4()),
            "session_id": session_id,
            "provider": provider,
            "language": language,
            "full_text": full_text,
            "raw": raw,
            "created_at": _now(),
        }
        db.setdefault(_TRANSCRIPTS_TABLE, {})[row["id"]] = row
        return row

    result = (
        db.table(_TRANSCRIPTS_TABLE)
        .insert(
            {
                "session_id": session_id,
                "provider": provider,
                "language": language,
                "full_text": full_text,
                "raw": raw,
            }
        )
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _update_transcript(db: Any, transcript_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if isinstance(db, dict):
        for row in db.setdefault(_TRANSCRIPTS_TABLE, {}).values():
            if str(row.get("id")) == transcript_id:
                row.update(updates)
                return row
        return {}

    result = db.table(_TRANSCRIPTS_TABLE).update(updates).eq("id", transcript_id).execute()
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else {}


def _delete_transcript_segments(db: Any, transcript_id: str) -> None:
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {})
        for row_id in [k for k, row in store.items() if str(row.get("transcript_id")) == transcript_id]:
            del store[row_id]
        return

    db.table(_TRANSCRIPT_SEGMENTS_TABLE).delete().eq("transcript_id", transcript_id).execute()


def _insert_transcript_segments(
    db: Any, transcript_id: str, segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        store = db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {})
        rows = []
        for segment in segments:
            row = {
                "id": str(uuid4()),
                "transcript_id": transcript_id,
                "question_id": None,
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "text": segment["text"],
                "created_at": _now(),
            }
            store[row["id"]] = row
            rows.append(row)
        return rows

    payload = [
        {
            "transcript_id": transcript_id,
            "question_id": None,
            "start_s": segment["start_s"],
            "end_s": segment["end_s"],
            "text": segment["text"],
        }
        for segment in segments
    ]
    result = db.table(_TRANSCRIPT_SEGMENTS_TABLE).insert(payload).execute()
    return getattr(result, "data", []) or []


def _mark_session_transcribed(
    db: Any, session_id: str, transcript_id: str, result: TranscriptResult
) -> dict[str, Any]:
    session = get_session(db, session_id) or {}
    telemetry = dict(session.get("telemetry") or {})
    transcript_meta = dict(telemetry.get("transcript") or {})

    completed_at = _now()
    transcript_meta.update(
        {
            "status": "transcribed",
            "transcript_id": transcript_id,
            "provider": result.provider,
            "language": result.language,
            "segment_count": len(result.segments),
            "duration_s": result.duration_s,
            "completed_at": completed_at,
        }
    )
    telemetry["transcript"] = transcript_meta

    return _update_session(db, session_id, {"telemetry": telemetry, "updated_at": completed_at})


def _mark_session_transcript_status(db: Any, session_id: str, status_value: str) -> dict[str, Any]:
    session = get_session(db, session_id) or {}
    telemetry = dict(session.get("telemetry") or {})
    transcript_meta = dict(telemetry.get("transcript") or {})

    updated_at = _now()
    transcript_meta["status"] = status_value
    transcript_meta["updated_at"] = updated_at
    telemetry["transcript"] = transcript_meta

    return _update_session(db, session_id, {"telemetry": telemetry, "updated_at": updated_at})


# ── Orchestration ────────────────────────────────────────────────────────────


def transcribe_session(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Generate a timestamped transcript for a processed session.

    Validates ownership, that the session has been media-processed, and that
    a processed full-session video exists. Downloads the full video and runs
    it through the configured transcription provider, then stores the result
    as ``vbr_transcripts`` + ``vbr_transcript_segments`` rows. Idempotent:
    re-running replaces any existing transcript segments rather than
    duplicating the transcript row.

    If no transcription provider is configured, returns HTTP 200 with
    ``status="not_configured"`` so the frontend can show the manual
    transcript fallback. The response never includes storage paths or full
    transcript text.
    """
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to generate a transcript.",
            },
        )

    telemetry = session.get("telemetry") or {}
    media_processing = telemetry.get("media_processing") or {}
    full_video = media_processing.get("full_video") or {}
    storage_path = full_video.get("storage_path")
    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_full_video_missing",
                "message": "Processed full session video was not found for this session.",
            },
        )

    from app.services.transcription_service import (
        TranscriptionUnavailableError,
        transcribe_audio,
    )

    try:
        video_bytes = _download_full_video_bytes(db, storage_path)
        tx_result = transcribe_audio(video_bytes, "full.webm")
    except TranscriptionUnavailableError:
        _mark_session_transcript_status(db, session_id, "not_configured")
        return {
            "session_id": session_id,
            "status": "not_configured",
            "transcript_id": None,
            "segment_count": 0,
            "duration_s": None,
            "provider": None,
            "configured": False,
            "message": _NOT_CONFIGURED_MESSAGE,
        }
    except RuntimeError as exc:
        _mark_session_transcript_status(db, session_id, "failed")
        logger.warning(
            "[VBR] Transcription failed for session %s "
            "(stage=transcribe, provider=%s, exc_type=%s)",
            session_id,
            settings.transcription_provider,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "vbr_transcription_failed", "message": _TRANSCRIPTION_FAILED_MESSAGE},
        ) from exc

    language = tx_result.language or "en"
    segments = [
        {"start_s": float(seg.start_time), "end_s": float(seg.end_time), "text": seg.text}
        for seg in tx_result.transcript_segments
        if seg.text.strip()
    ]
    if not segments:
        fallback_duration = float(session.get("duration_s") or 0.0)
        segments = [{"start_s": 0.0, "end_s": fallback_duration, "text": tx_result.transcript_text}]

    duration_s = max((segment["end_s"] for segment in segments), default=0.0)

    existing = _get_transcript_by_session(db, session_id)
    if existing is not None:
        transcript_row = _update_transcript(
            db,
            str(existing["id"]),
            {
                "provider": tx_result.provider_used,
                "language": language,
                "full_text": tx_result.transcript_text,
                "raw": {},
            },
        )
        _delete_transcript_segments(db, str(existing["id"]))
    else:
        transcript_row = _insert_transcript(
            db, session_id, tx_result.provider_used, language, tx_result.transcript_text, {}
        )

    transcript_id = str(transcript_row["id"])
    saved_segments = _insert_transcript_segments(db, transcript_id, segments)

    result = TranscriptResult(
        provider=tx_result.provider_used,
        language=language,
        segments=segments,
        full_text=tx_result.transcript_text,
        duration_s=duration_s,
    )
    _mark_session_transcribed(db, session_id, transcript_id, result)

    logger.info(
        "[VBR] Transcript generated for session %s (provider=%s, segments=%d)",
        session_id,
        tx_result.provider_used,
        len(saved_segments),
    )

    return {
        "session_id": session_id,
        "status": "transcribed",
        "transcript_id": transcript_id,
        "segment_count": len(saved_segments),
        "duration_s": duration_s,
        "provider": tx_result.provider_used,
        "configured": True,
        "message": f"Transcript generated using {tx_result.provider_used}.",
    }
