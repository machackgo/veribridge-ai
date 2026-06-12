"""VBR evidence-item builder (T6A).

T6A scope: build deterministic ``vbr_evidence_items`` rows from existing
processed artifacts — repo analysis facts, deployed URL checks, transcript
segments, keyframes, session questions, and media-processing telemetry. This
module does NOT call any LLM, judge claims, or generate reports.

Idempotent: rebuilding a session's evidence replaces only the T6A-owned
evidence items for that session (scoped via ``pointer.session_id``) rather
than duplicating rows.
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services.vbr_session_recording import get_owned_vbr_session_or_404

logger = logging.getLogger(__name__)

_EVIDENCE_TABLE = "vbr_evidence_items"
_REPO_ANALYSES_TABLE = "vbr_repo_analyses"
_URL_CHECKS_TABLE = "vbr_deployed_url_checks"
_TRANSCRIPTS_TABLE = "vbr_transcripts"
_TRANSCRIPT_SEGMENTS_TABLE = "vbr_transcript_segments"
_KEYFRAMES_TABLE = "vbr_keyframes"
_QUESTIONS_TABLE = "vbr_session_questions"

# Evidence types this builder owns. Used to scope idempotent delete/rebuild
# so report/judgment evidence created by later milestones is left untouched.
_T6A_EVIDENCE_TYPES = frozenset(
    {
        "repo_stat",
        "url_check",
        "transcript_segment",
        "keyframe",
        "session_telemetry",
    }
)

_EXCERPT_MAX_CHARS = 200

__all__ = ["build_session_evidence"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(text: str, max_chars: int = _EXCERPT_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# ── Artifact lookups ─────────────────────────────────────────────────────────


def _get_repo_analysis(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_REPO_ANALYSES_TABLE, {}).values()
            if row.get("project_id") == project_id
        ]
        return rows[0] if rows else None

    result = (
        db.table(_REPO_ANALYSES_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_latest_url_check(db: Any, project_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_URL_CHECKS_TABLE, {}).values()
            if row.get("project_id") == project_id
        ]
        rows.sort(key=lambda row: row.get("checked_at") or "", reverse=True)
        return rows[0] if rows else None

    result = (
        db.table(_URL_CHECKS_TABLE)
        .select("*")
        .eq("project_id", project_id)
        .order("checked_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", []) or []
    return rows[0] if rows else None


def _get_transcript(db: Any, session_id: str) -> dict[str, Any] | None:
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


def _list_transcript_segments(db: Any, transcript_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_TRANSCRIPT_SEGMENTS_TABLE, {}).values()
            if row.get("transcript_id") == transcript_id
        ]
        rows.sort(key=lambda row: row.get("start_s", 0))
        return rows

    result = (
        db.table(_TRANSCRIPT_SEGMENTS_TABLE)
        .select("*")
        .eq("transcript_id", transcript_id)
        .order("start_s")
        .execute()
    )
    return getattr(result, "data", []) or []


def _list_keyframes(db: Any, session_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_KEYFRAMES_TABLE, {}).values()
            if row.get("session_id") == session_id
        ]
        rows.sort(key=lambda row: row.get("ts_s", 0))
        return rows

    result = (
        db.table(_KEYFRAMES_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .order("ts_s")
        .execute()
    )
    return getattr(result, "data", []) or []


def _list_questions(db: Any, session_id: str) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [
            row
            for row in db.setdefault(_QUESTIONS_TABLE, {}).values()
            if row.get("session_id") == session_id
        ]
        rows.sort(key=lambda row: row.get("sort_order", 0))
        return rows

    result = (
        db.table(_QUESTIONS_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .order("sort_order")
        .execute()
    )
    return getattr(result, "data", []) or []


# ── vbr_evidence_items persistence ──────────────────────────────────────────


def _delete_session_evidence(db: Any, project_id: str, session_id: str) -> None:
    """Delete this session's T6A-owned evidence items (for idempotent rebuild).

    Scoped to ``project_id`` + T6A evidence types + ``pointer.session_id`` so
    evidence owned by later milestones (report/judgment) is left intact.
    """
    if isinstance(db, dict):
        store = db.setdefault(_EVIDENCE_TABLE, {})
        for evidence_id in [
            evidence_id
            for evidence_id, row in store.items()
            if row.get("project_id") == project_id
            and row.get("evidence_type") in _T6A_EVIDENCE_TYPES
            and (row.get("pointer") or {}).get("session_id") == session_id
        ]:
            del store[evidence_id]
        return

    (
        db.table(_EVIDENCE_TABLE)
        .delete()
        .eq("project_id", project_id)
        .in_("evidence_type", list(_T6A_EVIDENCE_TYPES))
        .filter("pointer->>session_id", "eq", session_id)
        .execute()
    )


def _insert_evidence_items(db: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    if isinstance(db, dict):
        store = db.setdefault(_EVIDENCE_TABLE, {})
        for row in rows:
            store[row["id"]] = row
        return rows

    result = db.table(_EVIDENCE_TABLE).insert(rows).execute()
    return getattr(result, "data", []) or []


# ── Evidence row builders ───────────────────────────────────────────────────


def _evidence_row(
    project_id: str,
    session_id: str,
    evidence_type: str,
    source: str,
    evidence_class: str,
    summary: str,
    pointer_extra: dict[str, Any],
    sensitivity: str = "normal",
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "project_id": project_id,
        "evidence_type": evidence_type,
        "source": source,
        "evidence_class": evidence_class,
        "interpretation": "deterministic",
        "visibility": "internal",
        "sensitivity": sensitivity,
        "pointer": {"session_id": session_id, **pointer_extra},
        "summary": summary,
        "created_at": _now(),
    }


def _build_repo_analysis_evidence(
    project_id: str, session_id: str, repo_analysis: dict[str, Any] | None
) -> dict[str, Any] | None:
    if repo_analysis is None:
        return None

    facts = repo_analysis.get("facts") or {}
    repo_full_name = facts.get("repo_full_name")
    languages = facts.get("languages")
    file_count = facts.get("file_count")
    commit_count = facts.get("commit_count")

    parts: list[str] = []
    if repo_full_name:
        parts.append(f"Repository {repo_full_name}")
    if languages:
        if isinstance(languages, dict):
            language_summary = ", ".join(sorted(languages.keys()))
        else:
            language_summary = ", ".join(str(language) for language in languages)
        if language_summary:
            parts.append(f"languages: {language_summary}")
    if file_count is not None:
        parts.append(f"{file_count} files")
    if commit_count is not None:
        parts.append(f"{commit_count} commits")

    summary = _truncate(", ".join(parts)) if parts else "Repository analysis facts recorded."

    pointer_extra = {
        "repo_analysis_id": str(repo_analysis["id"]),
        "repo_full_name": repo_full_name,
        "languages": languages,
        "file_count": file_count,
        "commit_count": commit_count,
    }

    return _evidence_row(
        project_id, session_id, "repo_stat", "vbr_repo_analyses", "artifact", summary, pointer_extra
    )


def _build_deployed_url_evidence(
    project_id: str, session_id: str, url_check: dict[str, Any] | None
) -> dict[str, Any] | None:
    if url_check is None:
        return None

    result = url_check.get("result") or "unknown"
    status_code = url_check.get("status_code")
    title = url_check.get("title")

    parts = [f"Deployed URL check: {result}"]
    if status_code is not None:
        parts.append(f"HTTP {status_code}")
    if title:
        parts.append(f"title: {title}")

    summary = _truncate(", ".join(parts))

    pointer_extra = {
        "url_check_id": str(url_check["id"]),
        "url": url_check.get("url"),
        "result": result,
        "status_code": status_code,
        "title": title,
    }

    return _evidence_row(
        project_id, session_id, "url_check", "vbr_deployed_url_checks", "artifact", summary, pointer_extra
    )


def _build_transcript_segment_evidence(
    project_id: str, session_id: str, transcript_id: str, segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in segments:
        summary = _truncate(segment.get("text") or "")
        pointer_extra = {
            "transcript_id": transcript_id,
            "segment_id": str(segment["id"]),
            "start_s": segment.get("start_s"),
            "end_s": segment.get("end_s"),
            "question_id": segment.get("question_id"),
        }
        rows.append(
            _evidence_row(
                project_id,
                session_id,
                "transcript_segment",
                "vbr_transcript_segments",
                "process",
                summary,
                pointer_extra,
                sensitivity="sensitive",
            )
        )
    return rows


def _build_keyframe_evidence(
    project_id: str, session_id: str, keyframes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for frame in keyframes:
        ts_s = frame.get("ts_s")
        vision_summary = frame.get("vision_summary") or {}
        frame_index = vision_summary.get("frame_index")

        parts = []
        if ts_s is not None:
            parts.append(f"Keyframe captured at {float(ts_s):.1f}s")
        else:
            parts.append("Keyframe captured")
        if frame_index is not None:
            parts.append(f"frame {frame_index}")

        summary = _truncate(", ".join(parts))

        # storage_path stays in the internal pointer only — never returned by
        # the build-evidence response.
        pointer_extra = {
            "keyframe_id": str(frame["id"]),
            "ts_s": ts_s,
            "frame_index": frame_index,
            "near_question_id": frame.get("near_question_id"),
            "storage_path": frame.get("storage_path"),
        }
        rows.append(
            _evidence_row(
                project_id,
                session_id,
                "keyframe",
                "vbr_keyframes",
                "process",
                summary,
                pointer_extra,
                sensitivity="sensitive",
            )
        )
    return rows


def _build_question_evidence(
    project_id: str, session_id: str, questions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for question in questions:
        sort_order = question.get("sort_order") or 0
        question_text = question.get("question_text") or ""
        summary = _truncate(f"Question {sort_order + 1}: {question_text}")

        pointer_extra = {
            "question_id": str(question["id"]),
            "sort_order": sort_order,
            "claim_ids": question.get("claim_ids") or [],
        }
        rows.append(
            _evidence_row(
                project_id,
                session_id,
                "session_telemetry",
                "vbr_session_questions",
                "process",
                summary,
                pointer_extra,
            )
        )
    return rows


def _build_media_processing_evidence(
    project_id: str, session_id: str, telemetry: dict[str, Any]
) -> dict[str, Any] | None:
    media_processing = telemetry.get("media_processing") or {}
    transcript_meta = telemetry.get("transcript") or {}
    keyframes_meta = telemetry.get("keyframes") or {}

    if not media_processing and not transcript_meta and not keyframes_meta:
        return None

    manifest_verified = bool(media_processing.get("manifest_verified"))
    full_video_created = bool(media_processing.get("full_video_created"))
    transcript_extracted = transcript_meta.get("status") == "transcribed"
    keyframes_extracted = bool(keyframes_meta.get("extracted"))

    parts: list[str] = []
    if manifest_verified:
        parts.append("manifest verified")
    if full_video_created:
        parts.append("full session video assembled")
    if transcript_extracted:
        segment_count = transcript_meta.get("segment_count")
        parts.append(
            f"transcript generated ({segment_count} segments)"
            if segment_count is not None
            else "transcript generated"
        )
    if keyframes_extracted:
        frame_count = keyframes_meta.get("frame_count")
        parts.append(
            f"keyframes extracted ({frame_count} frames)"
            if frame_count is not None
            else "keyframes extracted"
        )

    summary = _truncate("Media processing: " + ", ".join(parts)) if parts else "Media processing telemetry recorded."

    pointer_extra = {
        "manifest_verified": manifest_verified,
        "full_video_created": full_video_created,
        "chunk_count": media_processing.get("chunk_count"),
        "total_bytes": media_processing.get("total_bytes"),
        "transcript_extracted": transcript_extracted,
        "transcript_segment_count": transcript_meta.get("segment_count"),
        "keyframes_extracted": keyframes_extracted,
        "keyframe_count": keyframes_meta.get("frame_count"),
    }

    return _evidence_row(
        project_id,
        session_id,
        "session_telemetry",
        "vbr_verification_sessions.telemetry",
        "process",
        summary,
        pointer_extra,
    )


# ── Orchestration ────────────────────────────────────────────────────────────


def build_session_evidence(db: Any, session_id: str, user_id: str) -> dict[str, Any]:
    """Build deterministic vbr_evidence_items rows for a processed session.

    Validates ownership, that the session is ``processed``, and that a
    transcript and keyframes (or their telemetry) exist, then builds evidence
    items from repo analysis facts, deployed URL checks, transcript segments,
    keyframes, session questions, and media-processing telemetry. Idempotent:
    re-running replaces this session's T6A-owned evidence items rather than
    duplicating them.

    No LLM call happens here, no claims are judged, and no report is
    generated. The response never includes storage paths, signed URLs, local
    temp paths, or full transcript text.
    """
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_processed",
                "message": "Session must be in 'processed' status to build evidence.",
            },
        )

    telemetry = session.get("telemetry") or {}

    transcript_row = _get_transcript(db, session_id)
    if transcript_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_evidence_transcript_missing",
                "message": "Transcript artifacts are required before building evidence.",
            },
        )

    segments = _list_transcript_segments(db, str(transcript_row["id"]))
    if not segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_evidence_transcript_missing",
                "message": "Transcript segments are required before building evidence.",
            },
        )

    keyframe_rows = _list_keyframes(db, session_id)
    if not keyframe_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_evidence_keyframes_missing",
                "message": "Keyframe artifacts are required before building evidence.",
            },
        )

    project_id = str(project["id"])

    rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {
        "repo_analysis": 0,
        "deployed_url": 0,
        "transcript_segment": 0,
        "keyframe": 0,
        "question": 0,
        "media_processing": 0,
    }

    repo_evidence = _build_repo_analysis_evidence(project_id, session_id, _get_repo_analysis(db, project_id))
    if repo_evidence is not None:
        rows.append(repo_evidence)
        source_counts["repo_analysis"] = 1

    url_evidence = _build_deployed_url_evidence(project_id, session_id, _get_latest_url_check(db, project_id))
    if url_evidence is not None:
        rows.append(url_evidence)
        source_counts["deployed_url"] = 1

    segment_rows = _build_transcript_segment_evidence(project_id, session_id, str(transcript_row["id"]), segments)
    rows.extend(segment_rows)
    source_counts["transcript_segment"] = len(segment_rows)

    keyframe_evidence_rows = _build_keyframe_evidence(project_id, session_id, keyframe_rows)
    rows.extend(keyframe_evidence_rows)
    source_counts["keyframe"] = len(keyframe_evidence_rows)

    question_rows = _build_question_evidence(project_id, session_id, _list_questions(db, session_id))
    rows.extend(question_rows)
    source_counts["question"] = len(question_rows)

    media_processing_evidence = _build_media_processing_evidence(project_id, session_id, telemetry)
    if media_processing_evidence is not None:
        rows.append(media_processing_evidence)
        source_counts["media_processing"] = 1

    _delete_session_evidence(db, project_id, session_id)
    inserted = _insert_evidence_items(db, rows)

    logger.info("[VBR] Evidence built for session %s (count=%d)", session_id, len(inserted))

    return {
        "session_id": session_id,
        "evidence_count": len(inserted),
        "source_counts": source_counts,
        "status": session.get("status") or "processed",
        "message": "Evidence items built from processed session artifacts. Claim judgment and report generation are not yet implemented.",
    }
