"""Video Proof Service — first-class uploaded/recorded demo video proof.

Students upload a project demonstration video (class demo, walkthrough,
presentation, screen demo, prototype demo, hackathon demo). This service:

  1. RETAINS the original via ``proof_artifact_service``
     (artifact_type ``video_proof_original`` — private storage, gated routes).
  2. Extracts a timestamped narration TRANSCRIPT via the provider-agnostic
     ``transcription_service`` (openai / local_whisper / none).
  3. Extracts evenly-spaced visual FRAMES via
     ``VideoKeyframeExtractorService`` (cv2 / ffmpeg / none) and retains each
     as a ``video_proof_frame`` artifact.
  4. Builds a DETERMINISTIC, conservative analysis object from the observed
     facts only.

Honesty rules (load-bearing — do not weaken):
  • Every stage that is unavailable records an explicit status
    (``not_configured`` / ``not_available`` / ``failed``) — results are never
    invented. OCR, object detection, UI-element detection and semantic video
    understanding are schema-ready but explicitly ``not_implemented`` in the
    analysis capabilities map until a real CV pipeline lands.
  • ``skills_supported`` only ever records a student-claimed skill whose name
    literally appears in the narration transcript, tagged
    ``mentioned_in_narration`` and ``verified: false``. Video NEVER verifies a
    skill by itself.
  • ``limitations`` always states what a demo video cannot prove (authorship,
    implementation, model training, security correctness, production
    readiness) and ``needs_review`` defaults true.

Dict-mode (hermetic tests): tables live as ``db["video_proofs"]`` etc., keyed
by id — same pattern as the rest of the backend.
"""

from __future__ import annotations

import logging

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from app.services import proof_artifact_service as artifacts
from app.services.transcription_service import (
    MEANINGFUL_WORD_THRESHOLD,
    TranscriptionUnavailableError,
    count_meaningful_words,
    is_low_quality_transcript,
    transcribe_audio,
)
from app.services.video_keyframe_extractor_service import (
    VIDEO_STATUS_ANALYZED,
    VIDEO_STATUS_NOT_AVAILABLE,
    VideoKeyframeExtractorService,
)

logger = logging.getLogger(__name__)

_PROOFS_TABLE = "video_proofs"
_SEGMENTS_TABLE = "video_proof_transcript_segments"
_FRAMES_TABLE = "video_proof_frames"

SOURCE_KINDS: frozenset[str] = frozenset(
    {
        "uploaded_demo",
        "class_demo",
        "project_walkthrough",
        "live_presentation",
        "screen_demo",
        "prototype_demo",
        "hackathon_demo",
    }
)

SOURCE_KIND_LABELS: dict[str, str] = {
    "uploaded_demo": "Uploaded demo video",
    "class_demo": "Class demo recording",
    "project_walkthrough": "Project walkthrough video",
    "live_presentation": "Live project presentation",
    "screen_demo": "Recorded screen demo",
    "prototype_demo": "Recorded prototype demo",
    "hackathon_demo": "Hackathon demo video",
}

_ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
_ALLOWED_MIME_PREFIX = "video/"

# What a demo video can NEVER prove on its own. Rendered verbatim — honest by
# construction.
VIDEO_PROOF_LIMITATIONS: list[str] = [
    "A demo video shows runtime behaviour and the candidate's explanation — it does not prove authorship of the code.",
    "Implementation details (code structure, model training, algorithms) are not verifiable from video alone.",
    "Security correctness and production readiness cannot be assessed from a recorded demo.",
    "Strongest when corroborated with GitHub code evidence, a live Website Proof, Document Proof, or a Project Defense.",
]

_CORROBORATES_WITH: list[str] = ["github", "website", "document", "project_defense"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Generic table helpers (Supabase client or dict-mode) ──────────────────────


def _insert(db: Any, table: str, row: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(db, dict):
        db.setdefault(table, {})[row["id"]] = row
        return row
    try:
        resp = db.table(table).insert(row).execute()
        data = getattr(resp, "data", None)
        return data[0] if data else row
    except Exception as exc:
        logger.warning("[VideoProof] Insert into %s failed: %s", table, exc)
        return None


def _update(db: Any, table: str, row_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    patch = {**patch, "updated_at": _now()}
    if isinstance(db, dict):
        row = db.get(table, {}).get(row_id)
        if row is None:
            return None
        row.update(patch)
        return row
    try:
        resp = db.table(table).update(patch).eq("id", row_id).execute()
        data = getattr(resp, "data", None)
        return data[0] if data else None
    except Exception as exc:
        logger.warning("[VideoProof] Update of %s failed: %s", table, exc)
        return None


def _select_by(db: Any, table: str, field: str, value: Any, order_key: str | None = None) -> list[dict[str, Any]]:
    if isinstance(db, dict):
        rows = [r for r in db.get(table, {}).values() if r.get(field) == value]
    else:
        try:
            resp = db.table(table).select("*").eq(field, value).execute()
            rows = list(getattr(resp, "data", None) or [])
        except Exception as exc:
            logger.warning("[VideoProof] Select from %s failed: %s", table, exc)
            return []
    if order_key:
        rows.sort(key=lambda r: (r.get(order_key) is None, r.get(order_key)))
    return rows


def get_video_proof(db: Any, video_proof_id: str) -> dict[str, Any] | None:
    if isinstance(db, dict):
        return db.get(_PROOFS_TABLE, {}).get(video_proof_id)
    try:
        resp = db.table(_PROOFS_TABLE).select("*").eq("id", video_proof_id).maybe_single().execute()
        return getattr(resp, "data", None) if resp is not None else None
    except Exception as exc:
        logger.warning("[VideoProof] Lookup failed: %s", exc)
        return None


def list_video_proofs_for_user(db: Any, user_id: str) -> list[dict[str, Any]]:
    rows = _select_by(db, _PROOFS_TABLE, "user_id", user_id)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def list_video_proofs_for_project(db: Any, user_id: str, project_id: str) -> list[dict[str, Any]]:
    return [r for r in list_video_proofs_for_user(db, user_id) if r.get("project_id") == project_id]


def list_transcript_segments(db: Any, video_proof_id: str) -> list[dict[str, Any]]:
    return _select_by(db, _SEGMENTS_TABLE, "video_proof_id", video_proof_id, order_key="seq")


def list_frames(db: Any, video_proof_id: str) -> list[dict[str, Any]]:
    return _select_by(db, _FRAMES_TABLE, "video_proof_id", video_proof_id, order_key="timestamp_s")


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_upload(filename: str, mime_type: str | None, size_bytes: int, max_size_bytes: int) -> None:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_video_format",
                "message": "Upload an MP4, WebM, MOV, or M4V video file.",
            },
        )
    if mime_type and not mime_type.startswith(_ALLOWED_MIME_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_video_mime",
                "message": "The uploaded file does not look like a video.",
            },
        )
    if size_bytes > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "video_too_large",
                "message": f"Video exceeds the {max_size_bytes // (1024 * 1024)} MB limit.",
            },
        )


# ── Processing stages ──────────────────────────────────────────────────────────


def _run_transcription(db: Any, video_proof_id: str, data: bytes, filename: str, mime_type: str) -> tuple[str, int]:
    """Extract + persist narration transcript segments. Returns (status, segment_count)."""
    try:
        result = transcribe_audio(data, filename, mime_type)
    except TranscriptionUnavailableError:
        return "not_configured", 0
    except Exception as exc:
        logger.warning("[VideoProof] Transcription failed for %s: %s", video_proof_id, exc)
        return "failed", 0

    segments = [s for s in (result.transcript_segments or []) if (s.text or "").strip()]
    if not segments and not (result.transcript_text or "").strip():
        return "no_speech", 0

    # ── No-speech / low-quality guard (mirrors the VBR gates) ─────────────────
    # Whisper over silent/near-silent audio does not error — it emits
    # punctuation-only segments (a run of "." tokens), and degraded audio can
    # yield a single hallucinated token repeated dozens of times. Neither is a
    # real narration transcript and must never be persisted as ``completed``.
    # Measure meaningful words / repetitiveness across the provider's full text
    # AND its joined segment texts (max, same as ``vbr_transcription``). The
    # migration-057 status vocabulary has no ``low_quality``; a repeated-token
    # hallucination contains no usable narration speech, so both gates report
    # the honest ``no_speech`` and persist nothing.
    segment_source_text = " ".join(s.text.strip() for s in segments)
    meaningful_word_count = max(
        count_meaningful_words(result.transcript_text or ""),
        count_meaningful_words(segment_source_text),
    )
    if meaningful_word_count < MEANINGFUL_WORD_THRESHOLD:
        return "no_speech", 0
    if is_low_quality_transcript(result.transcript_text or "") or is_low_quality_transcript(
        segment_source_text
    ):
        return "no_speech", 0

    if not segments and result.transcript_text.strip():
        # Provider returned plain text without timing — keep it as one honest
        # untimed segment rather than inventing timestamps.
        row = {
            "id": str(uuid4()),
            "video_proof_id": video_proof_id,
            "seq": 0,
            "start_s": 0.0,
            "end_s": 0.0,
            "text": result.transcript_text.strip(),
            "speaker": None,
            "created_at": _now(),
        }
        _insert(db, _SEGMENTS_TABLE, row)
        return "completed", 1

    for i, seg in enumerate(segments):
        row = {
            "id": str(uuid4()),
            "video_proof_id": video_proof_id,
            "seq": i,
            "start_s": float(seg.start_time),
            "end_s": float(seg.end_time),
            "text": seg.text.strip(),
            "speaker": None,
            "created_at": _now(),
        }
        _insert(db, _SEGMENTS_TABLE, row)
    return "completed", len(segments)


def _run_frame_extraction(
    db: Any,
    *,
    owner_user_id: str,
    video_proof_id: str,
    data: bytes,
    filename: str,
    mime_type: str,
) -> tuple[str, int, float | None]:
    """Extract frames, retain each as a gated artifact + row.

    Returns (status, frame_count, duration_seconds).
    """
    try:
        result = VideoKeyframeExtractorService().extract_keyframes(data, filename, mime_type)
    except Exception as exc:
        logger.warning("[VideoProof] Frame extraction crashed for %s: %s", video_proof_id, exc)
        return "failed", 0, None

    duration_s = (result.duration_ms / 1000.0) if result.duration_ms else None

    if result.video_analysis_status == VIDEO_STATUS_NOT_AVAILABLE:
        return "not_available", 0, duration_s
    if result.video_analysis_status != VIDEO_STATUS_ANALYZED:
        return "failed", 0, duration_s

    stored = 0
    for timestamp_ms, jpeg_bytes in result._extracted_frames:
        artifact = artifacts.register_artifact_with_bytes(
            db,
            owner_user_id=owner_user_id,
            proof_type="video",
            artifact_type="video_proof_frame",
            data=jpeg_bytes,
            file_name=f"frame_{timestamp_ms}ms.jpg",
            mime_type="image/jpeg",
            proof_id=video_proof_id,
        )
        frame_row = {
            "id": str(uuid4()),
            "video_proof_id": video_proof_id,
            "timestamp_s": timestamp_ms / 1000.0,
            "frame_artifact_id": artifact["id"] if artifact else None,
            # Populated ONLY by a real CV pipeline (future) — honest nulls today.
            "ocr_text": None,
            "detected_objects": None,
            "detected_ui_elements": None,
            "activity_summary": None,
            "relevance_to_skill": None,
            "created_at": _now(),
        }
        if artifact is not None:
            _insert(db, _FRAMES_TABLE, frame_row)
            stored += 1

    return ("completed" if stored else "failed"), stored, duration_s


def _duration_label(duration_s: float | None) -> str | None:
    if not duration_s or duration_s <= 0:
        return None
    total = int(duration_s)
    return f"{total // 60}m {total % 60:02d}s"


def build_video_analysis(
    *,
    source_kind: str,
    claimed_skills: list[str],
    transcript_status: str,
    segment_texts: list[str],
    frames_status: str,
    frame_count: int,
    duration_seconds: float | None,
) -> dict[str, Any]:
    """Deterministic, conservative analysis built ONLY from observed facts.

    No LLM/vision inference happens here — the capabilities map says exactly
    which signals are real in this deployment and which are not implemented.
    """
    kind_label = SOURCE_KIND_LABELS.get(source_kind, "Demo video")

    facts: list[str] = [f"{kind_label} retained for recruiter review"]
    label = _duration_label(duration_seconds)
    if label:
        facts[0] += f" ({label})"
    if transcript_status == "completed":
        facts.append(f"narration transcript captured ({len(segment_texts)} segment{'s' if len(segment_texts) != 1 else ''})")
    elif transcript_status == "no_speech":
        facts.append("no usable narration speech was detected")
    elif transcript_status == "not_configured":
        facts.append("automatic transcription is not configured in this deployment")
    if frames_status == "completed":
        facts.append(f"{frame_count} visual frame{'s' if frame_count != 1 else ''} extracted for inspection")
    elif frames_status == "not_available":
        facts.append("frame extraction is not available in this deployment")
    demo_summary = ". ".join(s[0].upper() + s[1:] for s in facts) + "."

    # Conservative skill linkage: a claimed skill counts as "mentioned" only
    # when its name literally appears in the narration. Never verified.
    transcript_blob = " ".join(segment_texts).lower()
    skills_supported: list[dict[str, Any]] = []
    for skill in claimed_skills:
        name = (skill or "").strip()
        if not name:
            continue
        mentioned = bool(transcript_blob) and name.lower() in transcript_blob
        skills_supported.append(
            {
                "skill": name,
                "basis": "mentioned_in_narration" if mentioned else "claimed_only",
                "verified": False,
            }
        )

    return {
        "analysis_version": "deterministic-v1",
        "demo_summary": demo_summary,
        # Populated ONLY by a real semantic/CV pipeline (future) — empty, never guessed.
        "observed_workflow": [],
        "observed_inputs": [],
        "observed_outputs": [],
        "project_features_shown": [],
        "skills_supported": skills_supported,
        "proof_strength": "demo_evidence",
        "proof_strength_label": (
            "Demo / presentation evidence — shows runtime behaviour and the candidate's "
            "explanation; requires corroboration for implementation claims."
        ),
        "limitations": list(VIDEO_PROOF_LIMITATIONS),
        "corroborates_with": list(_CORROBORATES_WITH),
        "needs_review": True,
        "capabilities": {
            "transcript": transcript_status,
            "frames": frames_status,
            "ocr": "not_implemented",
            "object_detection": "not_implemented",
            "ui_element_detection": "not_implemented",
            "semantic_video_analysis": "not_implemented",
        },
    }


# ── Create + process ───────────────────────────────────────────────────────────


def create_video_proof(
    db: Any,
    *,
    user_id: str,
    data: bytes,
    filename: str,
    mime_type: str,
    title: str,
    description: str | None,
    source_kind: str,
    claimed_skills: list[str],
    project_id: str | None,
) -> dict[str, Any]:
    """Retain the original, run the honest analysis pipeline, persist the proof.

    Raises HTTPException 503 when artifact storage is not configured (a video
    proof without a retained original would be fake).
    """
    if source_kind not in SOURCE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_source_kind",
                "message": f"source_kind must be one of: {', '.join(sorted(SOURCE_KINDS))}.",
            },
        )
    if not artifacts.storage_available(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "artifact_storage_not_configured",
                "message": "Video proof storage is not configured on this server.",
            },
        )

    video_proof_id = str(uuid4())

    original = artifacts.register_artifact_with_bytes(
        db,
        owner_user_id=user_id,
        proof_type="video",
        artifact_type="video_proof_original",
        data=data,
        file_name=filename,
        mime_type=mime_type,
        proof_id=video_proof_id,
        project_id=project_id,
    )
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "video_retention_failed",
                "message": "The video could not be stored. Please try again.",
            },
        )

    row = {
        "id": video_proof_id,
        "user_id": user_id,
        "project_id": project_id,
        "title": title.strip() or artifacts.safe_filename(filename),
        "description": (description or "").strip() or None,
        "source_kind": source_kind,
        "status": "processing",
        "claimed_skills": [s.strip() for s in claimed_skills if s.strip()],
        "original_artifact_id": original["id"],
        "mime_type": mime_type,
        "file_name": artifacts.safe_filename(filename),
        "size_bytes": len(data),
        "duration_seconds": None,
        "transcript_status": "pending",
        "frames_status": "pending",
        "analysis_status": "pending",
        "analysis": None,
        "needs_review": True,
        "public_safe": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = _insert(db, _PROOFS_TABLE, row)
    if inserted is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "video_proof_persist_failed",
                "message": "The video proof could not be saved. Please try again.",
            },
        )

    # ── Honest processing pipeline (synchronous MVP) ──────────────────────────
    transcript_status, segment_count = _run_transcription(db, video_proof_id, data, filename, mime_type)
    frames_status, frame_count, duration_s = _run_frame_extraction(
        db,
        owner_user_id=user_id,
        video_proof_id=video_proof_id,
        data=data,
        filename=filename,
        mime_type=mime_type,
    )

    segment_texts = [str(s.get("text") or "") for s in list_transcript_segments(db, video_proof_id)]
    analysis = build_video_analysis(
        source_kind=source_kind,
        claimed_skills=row["claimed_skills"],
        transcript_status=transcript_status,
        segment_texts=segment_texts,
        frames_status=frames_status,
        frame_count=frame_count,
        duration_seconds=duration_s,
    )

    if duration_s is not None:
        artifacts.update_artifact(db, original["id"], {"duration_seconds": duration_s})

    updated = _update(
        db,
        _PROOFS_TABLE,
        video_proof_id,
        {
            "status": "analyzed",
            "duration_seconds": duration_s,
            "transcript_status": transcript_status,
            "frames_status": frames_status,
            "analysis_status": "completed",
            "analysis": analysis,
            "needs_review": True,
        },
    )
    return updated or get_video_proof(db, video_proof_id) or row


# ── Sharing gate ───────────────────────────────────────────────────────────────


def set_video_proof_visibility(db: Any, *, user_id: str, video_proof_id: str, public_safe: bool) -> dict[str, Any]:
    """Owner toggles recruiter access. Propagates to every retained artifact."""
    proof = get_video_proof(db, video_proof_id)
    if proof is None or proof.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "video_proof_not_found", "message": "Video proof not found."},
        )

    updated = _update(db, _PROOFS_TABLE, video_proof_id, {"public_safe": bool(public_safe)})

    # The toggle's consented scope is RECRUITERS — retained bytes (original
    # video / frames / transcript artifacts) go recruiter_safe, never
    # public_safe, so anonymous callers can never stream them. The artifact
    # ``public_safe`` column stays a mirror of (access_policy = 'public_safe').
    # Pre-fix rows: see docs/data-repairs/2026-08-recruiter-share-access-policy.md.
    policy = "recruiter_safe" if public_safe else "owner_only"
    for artifact in artifacts.list_artifacts_for_proof(db, proof_type="video", proof_id=video_proof_id):
        artifacts.update_artifact(
            db, str(artifact["id"]), {"access_policy": policy, "public_safe": policy == "public_safe"}
        )
    return updated or proof


# ── Safe projection ────────────────────────────────────────────────────────────


def safe_video_proof_dto(db: Any, proof: dict[str, Any], *, include_private_detail: bool) -> dict[str, Any]:
    """Allowlist DTO — never storage paths/buckets. ``include_private_detail``
    is the owner surface flag; a shared (public_safe) proof exposes the same
    safe fields to non-owners."""
    segments = list_transcript_segments(db, str(proof["id"]))
    frames = list_frames(db, str(proof["id"]))
    return {
        "id": proof.get("id"),
        "title": proof.get("title") or "",
        "description": proof.get("description"),
        "source_kind": proof.get("source_kind"),
        "source_kind_label": SOURCE_KIND_LABELS.get(str(proof.get("source_kind")), "Demo video"),
        "status": proof.get("status"),
        "project_id": proof.get("project_id"),
        "claimed_skills": list(proof.get("claimed_skills") or []),
        "mime_type": proof.get("mime_type"),
        "file_name": proof.get("file_name"),
        "size_bytes": proof.get("size_bytes"),
        "duration_seconds": proof.get("duration_seconds"),
        "duration_label": _duration_label(proof.get("duration_seconds")),
        "transcript_status": proof.get("transcript_status"),
        "frames_status": proof.get("frames_status"),
        "analysis_status": proof.get("analysis_status"),
        "analysis": proof.get("analysis"),
        "needs_review": bool(proof.get("needs_review", True)),
        "public_safe": bool(proof.get("public_safe", False)),
        "original_artifact_id": proof.get("original_artifact_id"),
        "segment_count": len(segments),
        "frame_count": len(frames),
        "created_at": proof.get("created_at"),
    }
