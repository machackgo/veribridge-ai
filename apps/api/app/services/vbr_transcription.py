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
_NO_SPEECH_MESSAGE = (
    "No useful speech was detected. Please retry with clearer audio or use the "
    "manual transcript fallback."
)
_LOW_QUALITY_MESSAGE = (
    "Transcript quality too low. Please re-record or use manual explanation."
)

__all__ = [
    "TranscriptResult",
    "get_session_transcript",
    "transcribe_session",
]

# Owner-only private preview cap. The private recorder/workspace page may show
# the student their own transcript, but we never render an unbounded blob — this
# keeps the payload small and predictable. This is the OWNER view only; the
# public report path sanitizes independently and never receives raw text.
_PREVIEW_CHAR_LIMIT = 4000


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


def _list_transcript_segments(db: Any, transcript_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
            if str(row.get("transcript_id")) == transcript_id
        ]
        return sorted(rows, key=lambda row: float(row.get("start_s") or 0.0))

    result = (
        db.table(_TRANSCRIPT_SEGMENTS_TABLE)
        .select("*")
        .eq("transcript_id", transcript_id)
        .order("start_s")
        .execute()
    )
    return getattr(result, "data", []) or []


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
        MEANINGFUL_WORD_THRESHOLD,
        TranscriptionUnavailableError,
        count_meaningful_words,
        is_low_quality_transcript,
        repeated_token_ratio,
        transcribe_audio,
    )

    # The processed full-session recording is a browser screen+mic capture
    # (VP8/VP9 video + Opus audio) uploaded as video/webm. Passing the content
    # type explicitly is what routes it through the shared provider's ffmpeg
    # audio-extraction path instead of being handed to Whisper as an
    # undecodable video container. Prefer a recorded content type from media
    # telemetry if present, else default to video/webm.
    full_video_content_type = full_video.get("content_type") or "video/webm"

    try:
        video_bytes = _download_full_video_bytes(db, storage_path)
        tx_result = transcribe_audio(
            video_bytes, "full.webm", content_type=full_video_content_type
        )
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
        # logger.exception captures the full traceback + provider error text for
        # local/server debugging. It contains no transcript text, storage paths,
        # or signed URLs — and the client still only receives the safe message
        # below, so raw internals are never exposed.
        logger.exception(
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

    # ── No-speech / punctuation-only guard ────────────────────────────────────
    # Whisper over a silent or near-silent recording does not error — it emits
    # punctuation-only segments (a run of "." tokens: "00:00 .", "00:07 .", …).
    # That is NOT a successful transcript: persisting it would show the student
    # "Transcript saved" over meaningless dots. We measure meaningful
    # (alphanumeric) words across the provider's full text AND its raw segment
    # texts; below the threshold we fail safely with a no_speech status so the UI
    # offers retry / manual fallback instead of a false success.
    # Take the max of the two sources rather than summing — a provider usually
    # returns the same content in both full_text and its segments, so summing
    # would double-count and inflate borderline low-word output past the gate.
    segment_source_text = " ".join(seg.text for seg in tx_result.transcript_segments)
    meaningful_word_count = max(
        count_meaningful_words(tx_result.transcript_text),
        count_meaningful_words(segment_source_text),
    )
    raw_segment_count = len(tx_result.transcript_segments)
    punctuation_only = meaningful_word_count < MEANINGFUL_WORD_THRESHOLD

    # Server-side diagnostics only — counts and a boolean, never transcript text,
    # storage paths, or provider traces.
    logger.info(
        "[VBR] Transcript speech check for session %s "
        "(meaningful_word_count=%d, segment_count=%d, punctuation_only=%s)",
        session_id,
        meaningful_word_count,
        raw_segment_count,
        punctuation_only,
    )

    if punctuation_only:
        _mark_session_transcript_status(db, session_id, "no_speech")
        return {
            "session_id": session_id,
            "status": "no_speech",
            "transcript_id": None,
            "segment_count": 0,
            "duration_s": None,
            "provider": tx_result.provider_used,
            "configured": True,
            "message": _NO_SPEECH_MESSAGE,
        }

    # ── Repeated-token hallucination guard ────────────────────────────────────
    # A weak/mis-configured model over degraded audio can emit a real-looking but
    # meaningless transcript that is one word repeated dozens of times ("… new
    # new new …"). That is NOT usable evidence: persisting it would show the
    # student "Transcript saved" over a hallucination and feed garbage into the
    # defense analysis. We measure repetitiveness over BOTH the provider's full
    # text and its joined segment texts (take the max so a clean full_text can't
    # mask degenerate segments) and fail safely with a low_quality status so the
    # UI offers re-record / manual fallback. Nothing is persisted.
    repeat_ratio = max(
        repeated_token_ratio(tx_result.transcript_text),
        repeated_token_ratio(segment_source_text),
    )
    low_quality = is_low_quality_transcript(tx_result.transcript_text) or is_low_quality_transcript(
        segment_source_text
    )

    # Server-side diagnostics only (local/dev debugging): repetitiveness score,
    # word/segment counts and the decision flag — never any transcript text.
    logger.info(
        "[VBR] Transcript quality check for session %s "
        "(meaningful_word_count=%d, segment_count=%d, repeated_token_ratio=%.2f, low_quality=%s)",
        session_id,
        meaningful_word_count,
        raw_segment_count,
        repeat_ratio,
        low_quality,
    )

    if low_quality:
        _mark_session_transcript_status(db, session_id, "low_quality")
        return {
            "session_id": session_id,
            "status": "low_quality",
            "transcript_id": None,
            "segment_count": 0,
            "duration_s": None,
            "provider": tx_result.provider_used,
            "configured": True,
            "message": _LOW_QUALITY_MESSAGE,
        }

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


def get_session_transcript(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Return the owner's private transcript preview for a session.

    Owner-scoped: ``get_owned_vbr_session_or_404`` enforces that only the
    student who owns the session can read it. This powers the private recorder /
    workspace page so the student can see and confirm their generated transcript
    (rule: the private owner page may show a transcript preview). The public
    recruiter report is served by a separate, sanitized code path and never uses
    this function — no raw transcript is ever exposed publicly here.

    Returns the persisted transcript text (capped at ``_PREVIEW_CHAR_LIMIT``)
    plus its timestamped segments. If no transcript has been generated yet, the
    status reflects telemetry (e.g. ``not_generated``/``failed``) and the
    ``segments``/``preview_text`` are empty rather than raising.
    """
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    telemetry = session.get("telemetry") or {}
    transcript_meta = telemetry.get("transcript") or {}
    status_value = transcript_meta.get("status") or "not_generated"

    transcript = _get_transcript_by_session(db, session_id)
    if transcript is None:
        return {
            "session_id": session_id,
            "status": status_value,
            "transcript_id": None,
            "provider": transcript_meta.get("provider"),
            "language": None,
            "segment_count": 0,
            "duration_s": transcript_meta.get("duration_s"),
            "preview_text": "",
            "truncated": False,
            "segments": [],
        }

    transcript_id = str(transcript["id"])
    segment_rows = _list_transcript_segments(db, transcript_id)
    segments = [
        {
            "start_s": float(row.get("start_s") or 0.0),
            "end_s": float(row.get("end_s") or 0.0),
            "text": row.get("text") or "",
        }
        for row in segment_rows
    ]

    full_text = transcript.get("full_text") or ""
    preview_text = full_text[:_PREVIEW_CHAR_LIMIT]
    truncated = len(full_text) > _PREVIEW_CHAR_LIMIT

    duration_s = transcript_meta.get("duration_s")
    if duration_s is None and segments:
        duration_s = max((segment["end_s"] for segment in segments), default=0.0)

    return {
        "session_id": session_id,
        "status": status_value,
        "transcript_id": transcript_id,
        "provider": transcript.get("provider") or transcript_meta.get("provider"),
        "language": transcript.get("language"),
        "segment_count": len(segments),
        "duration_s": duration_s,
        "preview_text": preview_text,
        "truncated": truncated,
        "segments": segments,
    }
