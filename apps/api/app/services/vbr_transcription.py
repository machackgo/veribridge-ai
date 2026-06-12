"""VBR transcript-generation skeleton (T5D).

T5D scope: produce a deterministic transcript skeleton for a session whose
full video has already been processed (T5C), and store it as
``vbr_transcripts`` + ``vbr_transcript_segments`` rows. This module does NOT
download the full video, extract audio, run Whisper/AssemblyAI, or call any
external transcription provider.

TODO(T5E/T6): replace ``transcribe_full_video_skeleton`` with a real
transcription provider call after storage download/audio extraction is
finalized.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.vbr_session_recording import get_owned_vbr_session_or_404, get_session

logger = logging.getLogger(__name__)

_SESSIONS_TABLE = "vbr_verification_sessions"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"

_SKELETON_PROVIDER = "skeleton_fake"
_SKELETON_LANGUAGE = "en"

# Deterministic skeleton segments. TODO(T5E/T6): replace with real
# transcription provider output after storage download/audio extraction is
# finalized.
_SKELETON_SEGMENTS: list[dict[str, Any]] = [
    {"start_s": 0.0, "end_s": 8.0, "text": "Candidate introduced the project and repository."},
    {"start_s": 8.0, "end_s": 20.0, "text": "Candidate explained a key implementation decision."},
]

__all__ = [
    "TranscriptResult",
    "transcribe_full_video_skeleton",
    "transcribe_session_skeleton",
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


# ── Transcript provider skeleton ────────────────────────────────────────────


def transcribe_full_video_skeleton(db: Any, session: dict[str, Any]) -> TranscriptResult:
    """Return a deterministic transcript skeleton for a processed session.

    TODO(T5E/T6): replace skeleton with real transcription provider after
    storage download/audio extraction is finalized. Does not download the
    full video or call any external transcription API.
    """
    segments = [dict(segment) for segment in _SKELETON_SEGMENTS]
    full_text = " ".join(segment["text"] for segment in segments)
    duration_s = max((segment["end_s"] for segment in segments), default=0.0)

    return TranscriptResult(
        provider=_SKELETON_PROVIDER,
        language=_SKELETON_LANGUAGE,
        segments=segments,
        full_text=full_text,
        duration_s=duration_s,
    )


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


# ── Orchestration ────────────────────────────────────────────────────────────


def transcribe_session_skeleton(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Run the deterministic transcript-generation skeleton for a session.

    Validates ownership, that the session has been media-processed, and that
    a processed full-session video exists, then generates and stores a
    deterministic transcript skeleton. Idempotent: re-running replaces any
    existing transcript segments rather than duplicating the transcript row.

    No external transcription provider is called here. No raw video is
    downloaded. The response never includes storage paths or full transcript
    text.
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
    if not full_video.get("storage_path"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_full_video_missing",
                "message": "Processed full session video was not found for this session.",
            },
        )

    result = transcribe_full_video_skeleton(db, session)

    existing = _get_transcript_by_session(db, session_id)
    if existing is not None:
        transcript_row = _update_transcript(
            db,
            str(existing["id"]),
            {
                "provider": result.provider,
                "language": result.language,
                "full_text": result.full_text,
                "raw": {"skeleton": True},
            },
        )
        _delete_transcript_segments(db, str(existing["id"]))
    else:
        transcript_row = _insert_transcript(
            db, session_id, result.provider, result.language, result.full_text, {"skeleton": True}
        )

    transcript_id = str(transcript_row["id"])
    _insert_transcript_segments(db, transcript_id, result.segments)
    _mark_session_transcribed(db, session_id, transcript_id, result)

    logger.info(
        "[VBR] Transcript skeleton generated for session %s (segments=%d)",
        session_id,
        len(result.segments),
    )

    return {
        "session_id": session_id,
        "status": "transcribed",
        "transcript_id": transcript_id,
        "segment_count": len(result.segments),
        "duration_s": result.duration_s,
        "message": "Transcript generated using a deterministic skeleton. Real transcription provider integration is not yet implemented.",
    }
