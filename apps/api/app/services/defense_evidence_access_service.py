"""Project Defense — private, authorized evidence access helpers.

The inspection layer (:mod:`project_defense_inspection_service`) is pure and
carries no DB access. This module supplies the two *authorized, owner-only*
pieces of evidence that need the database, so the inspection builder can stay
pure and the public projection can stay fail-closed:

1. :func:`build_safe_answer_excerpts` — a bounded, sanitized excerpt of the
   student's *own* spoken answer for each defended question, recovered from the
   ``vbr_transcript_segments`` rows. Never the full transcript, never the raw
   segment array — just a length-capped, storage/URL/token-scrubbed snippet plus
   safe ``mm:ss`` start/end labels.

2. :func:`build_recording_playback` — an *authorized* playback handle for the
   owner's own processed defense recording. It mints a short-lived signed URL
   for the private full-session video (owner request, owner bearer token) — it
   never returns the raw storage path, and it fails closed to
   ``{"available": …, "playback_url": None}`` whenever storage is not configured
   or the signed URL cannot be created.

Both are consumed ONLY on the private owner report/vault path. The public
recruiter projection (:func:`public_report_safety_service`) re-derives its cards
from the fixed taxonomy and drops the playback URL and excerpt unless the card
is explicitly public-safe.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.services.project_defense_evidence_chips import (
    _format_timestamp,
    _sanitize_transcript_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_safe_answer_excerpts",
    "build_recording_playback",
    "TRANSCRIPT_EXCERPT_MAX_CHARS",
]

_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"

# Upper bound on a per-question transcript excerpt. Bounded on purpose: the owner
# report shows a short excerpt around the cited moment, never a full transcript
# dump. Kept in the 500–800 char band the product asks for.
TRANSCRIPT_EXCERPT_MAX_CHARS = 600

# Signed playback URL lifetime (seconds). Short enough to bound exposure, long
# enough for a single viewing session of the owner's own recording.
_PLAYBACK_URL_TTL_SECONDS = 60 * 30


def _cap(text: str, max_chars: int = TRANSCRIPT_EXCERPT_MAX_CHARS) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "…"


def build_safe_answer_excerpts(db: Any, session_id: str) -> dict[str, dict[str, Any]]:
    """Map ``question_id`` → a bounded, sanitized excerpt of the student's answer.

    Reads the session's ``vbr_transcript_segments`` (each carrying the answering
    ``question_id``, the answer ``text``, and ``start_s`` / ``end_s``), then for
    each question concatenates its segment text in time order, sanitizes it
    (storage paths / signed URLs / tokens / local paths redacted), caps the
    length, and derives ``mm:ss`` start/end labels.

    Returns ``{}`` on any lookup problem (honest fallback to "no excerpt"). The
    raw segment array is never returned — only the derived, capped fields.
    """
    if not session_id:
        return {}
    try:
        if isinstance(db, dict):
            transcript_ids = {
                str(r["id"])
                for r in db.get(_TRANSCRIPTS_TABLE, {}).values()
                if str(r.get("session_id")) == session_id and r.get("id")
            }
            segments = [
                r
                for r in db.get(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
                if str(r.get("transcript_id")) in transcript_ids
            ]
        else:
            tx = db.table(_TRANSCRIPTS_TABLE).select("id").eq("session_id", session_id).execute()
            transcript_ids = [str(r["id"]) for r in (getattr(tx, "data", []) or []) if r.get("id")]
            segments = []
            for tid in transcript_ids:
                seg = (
                    db.table(_TRANSCRIPT_SEGMENTS_TABLE)
                    .select("question_id,text,start_s,end_s")
                    .eq("transcript_id", tid)
                    .execute()
                )
                segments.extend(getattr(seg, "data", []) or [])
    except Exception:  # pragma: no cover - excerpts are best-effort
        return {}

    # Group segments by answering question, in time order.
    by_question: dict[str, list[dict[str, Any]]] = {}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        qid = seg.get("question_id")
        if not qid:
            continue
        by_question.setdefault(str(qid), []).append(seg)

    out: dict[str, dict[str, Any]] = {}
    for qid, segs in by_question.items():
        try:
            segs.sort(key=lambda s: float(s.get("start_s") or 0.0))
        except Exception:  # pragma: no cover - defensive
            pass
        raw = " ".join(str(s.get("text") or "").strip() for s in segs if s.get("text"))
        excerpt = _cap(_sanitize_transcript_text(raw))
        if not excerpt:
            continue
        starts = [float(s["start_s"]) for s in segs if s.get("start_s") is not None]
        ends = [float(s["end_s"]) for s in segs if s.get("end_s") is not None]
        out[qid] = {
            "safe_transcript_excerpt": excerpt,
            "transcript_excerpt_start_label": _format_timestamp(min(starts)) if starts else None,
            "transcript_excerpt_end_label": _format_timestamp(max(ends)) if ends else None,
        }
    return out


def _full_video_storage_path(session: dict[str, Any]) -> str | None:
    """Return the processed full-session video storage path, if one exists."""
    telemetry = session.get("telemetry") if isinstance(session, dict) else None
    if not isinstance(telemetry, dict):
        return None
    media = telemetry.get("media_processing")
    if not isinstance(media, dict):
        return None
    full_video = media.get("full_video")
    if not isinstance(full_video, dict):
        return None
    path = full_video.get("storage_path")
    return str(path) if path else None


def build_recording_playback(db: Any, session: dict[str, Any] | None) -> dict[str, Any]:
    """Authorized owner playback handle for the session's own defense recording.

    ``session`` must already be verified as owned by the requesting user. When a
    processed full-session video exists we report ``available: True`` and try to
    mint a short-lived signed URL for it; on any storage error (or a dict test
    DB) we fail closed to ``playback_url: None`` while still reporting that the
    recording exists, so the UI can show the "recording exists but no safe
    playback link from this view yet" note. The raw storage path is never
    returned.
    """
    result: dict[str, Any] = {"available": False, "playback_url": None}
    if not isinstance(session, dict):
        return result

    storage_path = _full_video_storage_path(session)
    if not storage_path:
        return result
    result["available"] = True

    # Test/dict DBs and unconfigured storage: recording exists but no live signed
    # URL — fail closed to a null playback URL.
    if isinstance(db, dict):
        return result

    bucket = settings.supabase_vbr_media_bucket
    try:
        signed = db.storage.from_(bucket).create_signed_url(
            storage_path, _PLAYBACK_URL_TTL_SECONDS
        )
    except Exception as exc:  # pragma: no cover - depends on live storage
        logger.warning("[VBR] Failed to create signed playback URL: %s", exc)
        return result

    url = None
    if isinstance(signed, dict):
        url = signed.get("signedURL") or signed.get("signed_url") or signed.get("signedUrl")
    if url:
        result["playback_url"] = str(url)
    return result
