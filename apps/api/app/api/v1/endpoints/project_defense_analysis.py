"""Project Defense Transcript Analysis endpoints.

POST /{session_id}/analyze/project-defense           — run the transcript analysis
GET  /{session_id}/analysis/project-defense          — fetch the stored result
POST /{session_id}/defense/upload-media              — register uploaded media file
PATCH /{session_id}/defense/transcript               — update transcript + reviewed flag
POST /{session_id}/defense/transcribe                — transcribe registered media
POST /{session_id}/defense/refine-transcript         — (re-)run NLP refinement
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_current_user_id, get_db
from app.core.config import settings
from app.schemas.project_defense_analysis import (
    ALLOWED_MEDIA_EXTENSIONS,
    MAX_MEDIA_SIZE_BYTES,
    ProjectDefenseAnalyzeRequest,
    ProjectDefenseAnalysisResponse,
    ProjectDefenseMediaUploadResponse,
    ProjectDefenseRefineTranscriptRequest,
    ProjectDefenseRefineTranscriptResponse,
    ProjectDefenseTranscribeResponse,
    ProjectDefenseUpdateTranscriptRequest,
)
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services.project_defense_analysis_service import (
    ProjectDefenseAnalysisService,
    analyze_defense_transcript,
    coherent_overall_defense_score,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Bounded streaming chunk size — same OOM-safe pattern as the workflow-video
# upload (workflow_visual_frames.py): never whole-body read before the size gate.
_UPLOAD_CHUNK_BYTES = 1024 * 1024

# Storage bucket name — read from pydantic-settings (which loads .env).
# Do NOT use os.environ.get() here: pydantic-settings does not write back to
# os.environ, so os.environ.get() always returns "" for values only in .env.
_MEDIA_BUCKET = settings.supabase_defense_media_bucket

# Safe startup diagnostic — confirms the env var reached the Python process.
# Logs bucket name (not a secret) and presence of credentials (not their values).
logger.info(
    "Project Defense storage: bucket=%r  supabase_url_present=%s  service_key_present=%s",
    _MEDIA_BUCKET or "(not configured)",
    bool(settings.supabase_url),
    bool(settings.supabase_service_role_key.get_secret_value()),
)
_tx_provider = settings.transcription_provider.strip().lower()
logger.info(
    "Transcription: provider=%r  enabled=%s  local_whisper_model=%r  device=%r",
    _tx_provider or "none",
    _tx_provider not in ("none", ""),
    settings.local_whisper_model_size,
    settings.local_whisper_device,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _verify_session(user_id: str, session_id: str, db: Any) -> None:
    """Raise 404 if the session doesn't belong to this user."""
    try:
        ExtensionProofSessionService(db)._get_row(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": session_id,
            },
        ) from exc


def _row_to_response(
    row: dict[str, Any],
    user_id: str,
    session_id: str,
    transcript_text: str | None = None,
) -> ProjectDefenseAnalysisResponse:
    """Convert a DB row dict into a response model."""
    return ProjectDefenseAnalysisResponse(
        id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or user_id),
        proof_session_id=str(row.get("proof_session_id") or session_id),
        video_url=row.get("video_url"),
        media_url=row.get("media_url"),
        media_type=row.get("media_type"),
        media_filename=row.get("media_filename"),
        media_storage_path=row.get("media_storage_path"),
        transcription_status=str(row.get("transcription_status") or "not_started"),
        transcript_reviewed=bool(row.get("transcript_reviewed", False)),
        transcript_text=transcript_text if transcript_text is not None else str(row.get("transcript_text") or ""),
        # Refinement fields
        raw_transcript=row.get("raw_transcript"),
        refined_transcript=row.get("refined_transcript"),
        transcript_correction_summary=row.get("transcript_correction_summary") or [],
        transcript_glossary_matches=row.get("transcript_glossary_matches") or [],
        transcript_refinement_status=str(row.get("transcript_refinement_status") or "not_started"),
        transcript_needs_review=bool(row.get("transcript_needs_review", False)),
        # Analysis outputs
        transcript_summary=str(row.get("transcript_summary") or ""),
        skills_mentioned=row.get("skills_mentioned") or [],
        skills_explained_well=row.get("skills_explained_well") or [],
        skills_missing_from_explanation=row.get("skills_missing_from_explanation") or [],
        consistency_with_evidence_score=int(row.get("consistency_with_evidence_score") or 0),
        explanation_clarity_score=int(row.get("explanation_clarity_score") or 0),
        ownership_signal_score=int(row.get("ownership_signal_score") or 0),
        technical_depth_score=int(row.get("technical_depth_score") or 0),
        # Coherence: a legacy stored overall may exceed what its component
        # scores support (pre-proportional-rubric rows). Serve the derived
        # coherent value instead — stored rows are never mutated.
        overall_defense_score=coherent_overall_defense_score(row),
        risk_flags=row.get("risk_flags") or [],
        recruiter_summary=str(row.get("recruiter_summary") or ""),
        recommended_improvements=row.get("recommended_improvements") or [],
        privacy_scan_status=str(row.get("privacy_scan_status") or "clean"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


# ── POST /analyze/project-defense ─────────────────────────────────────────────

@router.post(
    "/{session_id}/analyze/project-defense",
    response_model=ProjectDefenseAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a project defense transcript for a proof session",
)
def analyze_project_defense(
    session_id: str,
    body: ProjectDefenseAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseAnalysisResponse:
    """
    Analyse a student's project defense transcript and store the result.

    The transcript is scanned for sensitive data before storage.  If sensitive
    data is detected the privacy_scan_status is set to 'flagged' and the result
    is hidden from recruiter view until reviewed.

    Transcript analysis is project-agnostic — it works for frontend apps,
    full-stack projects, ML models, dashboards, local-only apps, portfolios,
    and future non-CS fields.

    IMPORTANT: This endpoint never sets final_verification_status to "complete".
    Final Verification completion requires a separate VeriBridge reviewer step.
    """
    _verify_session(user_id, session_id, db)

    # ── Run analysis ───────────────────────────────────────────────────────────
    result = analyze_defense_transcript(
        transcript_text=body.transcript_text,
        claimed_skills=body.claimed_skills,
        proof_objective=body.proof_objective,
        workflow_summary=body.workflow_summary,
        github_summary=body.github_summary,
        live_check_summary=body.live_check_summary,
    )

    # ── Retrieve any previously registered media metadata ─────────────────────
    service = ProjectDefenseAnalysisService(db)
    existing = service.get_analysis(user_id, session_id) or {}

    # ── Persist ────────────────────────────────────────────────────────────────
    stored = service.store_analysis(
        user_id=user_id,
        proof_session_id=session_id,
        video_url=body.video_url,
        transcript_text=body.transcript_text,
        result=result,
        media_type=existing.get("media_type"),
        media_filename=existing.get("media_filename"),
        media_storage_path=existing.get("media_storage_path"),
        media_url=existing.get("media_url"),
        transcript_reviewed=True,   # analysed → treat as reviewed
    )

    return _row_to_response(stored, user_id, session_id, transcript_text=body.transcript_text)


# ── GET /analysis/project-defense ─────────────────────────────────────────────

@router.get(
    "/{session_id}/analysis/project-defense",
    response_model=ProjectDefenseAnalysisResponse,
    summary="Get the stored project defense analysis for a proof session",
)
def get_project_defense_analysis(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseAnalysisResponse:
    """
    Retrieve the most recently stored project defense analysis result.
    Returns 404 if no analysis has been run yet for this session.
    """
    _verify_session(user_id, session_id, db)

    service = ProjectDefenseAnalysisService(db)
    row = service.get_analysis(user_id, session_id)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "project_defense_not_found",
                "message": "No project defense analysis found for this session.",
                "session_id": session_id,
            },
        )

    return _row_to_response(row, user_id, session_id)


# ── POST /defense/upload-media ─────────────────────────────────────────────────

@router.post(
    "/{session_id}/defense/upload-media",
    response_model=ProjectDefenseMediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload or register a project defense media file",
)
async def upload_project_defense_media(
    session_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseMediaUploadResponse:
    """
    Accept a defense audio/video file, validate it, optionally store it in
    Supabase Storage (if SUPABASE_DEFENSE_MEDIA_BUCKET env var is set), and
    register the media metadata in the project_defense_analysis_results table.

    Allowed formats: mp4, mov, webm, mp3, wav, m4a (max 200 MB).

    Media is kept private by default — it is not exposed in recruiter or
    public view unless explicitly allowed.

    If storage is not configured the metadata is still stored and the student
    can paste/edit the transcript in the next step.
    """
    _verify_session(user_id, session_id, db)

    # ── Validate file extension ────────────────────────────────────────────────
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_MEDIA_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_media_type",
                "message": (
                    f"File type '.{ext}' is not supported. "
                    f"Allowed: {', '.join(sorted(ALLOWED_MEDIA_EXTENSIONS))}."
                ),
            },
        )

    # ── Stream file in bounded chunks and validate size ────────────────────────
    # A bare ``await file.read()`` would materialize an oversized body in
    # memory BEFORE the size check (the workflow-video OOM failure mode); the
    # 413 fires as soon as the limit is crossed instead.
    buffer = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > MAX_MEDIA_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "media_too_large",
                    "message": (
                        f"File size {len(buffer) / (1024 * 1024):.1f} MB exceeds the "
                        "200 MB limit."
                    ),
                },
            )
    content = bytes(buffer)
    size_bytes = len(content)

    # ── Supabase Storage upload ────────────────────────────────────────────────
    # When a bucket is configured, the file MUST be stored — failure is not
    # gracefully swallowed, because a missing file breaks transcription later.
    storage_path: str | None = None
    media_url: str | None = None
    bucket_configured = bool(_MEDIA_BUCKET)

    logger.info(
        "upload-media: session=%s filename=%r size=%d bucket=%r is_real_db=%s",
        session_id, filename, size_bytes,
        _MEDIA_BUCKET or "(not configured)",
        not isinstance(db, dict),
    )

    if bucket_configured and not isinstance(db, dict):
        # Include a server-side timestamp to avoid path collisions on re-upload
        ts = int(time.time())
        storage_path = f"{user_id}/{session_id}/{ts}_{filename}"

        try:
            db.storage.from_(_MEDIA_BUCKET).upload(
                storage_path,
                content,
                file_options={"content-type": file.content_type or "application/octet-stream"},
            )
        except Exception as exc:
            logger.error(
                "Supabase Storage upload failed for session %s (bucket=%s path=%s): %s",
                session_id, _MEDIA_BUCKET, storage_path, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "storage_upload_failed",
                    "message": (
                        "Could not store the media file. "
                        "Check Supabase Storage configuration and bucket permissions, "
                        "then try again."
                    ),
                },
            )

        logger.info(
            "upload-media: storage upload succeeded path=%r", storage_path
        )

        # Retrieve the public URL — non-fatal if it fails (we have storage_path)
        try:
            url_result = db.storage.from_(_MEDIA_BUCKET).get_public_url(storage_path)
            media_url = url_result if isinstance(url_result, str) else None
        except Exception as exc:
            logger.warning(
                "Could not retrieve public URL for %s: %s", storage_path, exc
            )

    # ── Register metadata in DB ────────────────────────────────────────────────
    service = ProjectDefenseAnalysisService(db)
    service.register_media(
        user_id=user_id,
        proof_session_id=session_id,
        media_filename=filename,
        media_type=ext,
        media_size_bytes=size_bytes,
        media_url=media_url,
        media_storage_path=storage_path,
    )

    # Only report "uploaded and stored" when a file is actually in storage.
    # When no bucket is configured, be honest: the file is registered but
    # auto-transcription requires a configured storage bucket.
    if storage_path:
        msg = "Media uploaded and stored."
    else:
        msg = (
            "Media registered. No storage bucket is configured, so automatic "
            "transcription is unavailable — paste or edit your transcript below, "
            "then click Analyze Project Defense."
        )

    return ProjectDefenseMediaUploadResponse(
        proof_session_id=session_id,
        media_filename=filename,
        media_type=ext,
        media_size_bytes=size_bytes,
        media_url=media_url,
        media_storage_path=storage_path,
        transcription_status="uploaded",
        storage_configured=bucket_configured,
        message=msg,
    )


# ── PATCH /defense/transcript ──────────────────────────────────────────────────

@router.patch(
    "/{session_id}/defense/transcript",
    response_model=ProjectDefenseAnalysisResponse,
    summary="Update the defense transcript text and reviewed flag",
)
def update_defense_transcript(
    session_id: str,
    body: ProjectDefenseUpdateTranscriptRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseAnalysisResponse:
    """
    Update the stored transcript text for a defense session.

    Use this to save the student's reviewed/edited transcript before running
    analysis.  Sets transcription_status to 'transcript_ready' when
    transcript_reviewed is True.

    Returns 404 if no media has been registered yet for this session.
    """
    _verify_session(user_id, session_id, db)

    service = ProjectDefenseAnalysisService(db)
    row = service.update_transcript(
        user_id=user_id,
        proof_session_id=session_id,
        transcript_text=body.transcript_text,
        transcript_reviewed=body.transcript_reviewed,
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "project_defense_not_found",
                "message": (
                    "No project defense record found for this session. "
                    "Upload a media file or submit a transcript first."
                ),
                "session_id": session_id,
            },
        )

    return _row_to_response(row, user_id, session_id)


# ── POST /defense/transcribe ───────────────────────────────────────────────────

@router.post(
    "/{session_id}/defense/transcribe",
    response_model=ProjectDefenseTranscribeResponse,
    summary="Transcribe the registered defense media file to text",
)
async def transcribe_defense_media(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseTranscribeResponse:
    """
    Transcribe the audio/video file registered for this proof session.

    Flow
    ----
    1. Verify the session belongs to this user.
    2. Load stored media_storage_path / media_url from DB.
    3. Download file bytes from Supabase Storage (or media_url as fallback).
    4. Call the configured transcription provider (none | openai).
    5. Run privacy scan on the generated transcript text.
    6. Save transcript_text; set transcription_status = 'transcript_ready'.
    7. Return transcript_text for the student to review/edit before analysis.

    Graceful fallback
    -----------------
    If TRANSCRIPTION_PROVIDER=none or OPENAI_API_KEY is missing, returns
    HTTP 200 with ``configured=False`` and an instructional message — the
    frontend shows the manual-paste fallback.  No 5xx in this case.

    Final Verification is NEVER set to 'complete' from this endpoint.
    """
    from app.services.transcription_service import (
        MEANINGFUL_WORD_THRESHOLD,
        TranscriptionUnavailableError,
        count_meaningful_words,
        is_low_quality_transcript,
        transcribe_audio,
    )
    from app.services.workflow_privacy_scan_service import scan_proof_data

    _verify_session(user_id, session_id, db)

    service = ProjectDefenseAnalysisService(db)
    row = service.get_analysis(user_id, session_id)

    # A media row exists if media_filename was set by register_media.
    # storage_path/url may be absent in storage-less deployments and tests.
    if row is None or not row.get("media_filename"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "media_not_found",
                "message": (
                    "No media file is registered for this session. "
                    "Upload or record a video/audio file first."
                ),
                "session_id": session_id,
            },
        )

    # ── Fetch file bytes ───────────────────────────────────────────────────────
    filename: str = row.get("media_filename") or "defense.webm"
    content_type: str | None = None
    file_bytes: bytes | None = None

    storage_path: str | None = row.get("media_storage_path")
    media_url: str | None = row.get("media_url")

    # Try Supabase Storage first
    if storage_path and _MEDIA_BUCKET and not isinstance(db, dict):
        try:
            file_bytes = db.storage.from_(_MEDIA_BUCKET).download(storage_path)
        except Exception as exc:
            logger.warning(
                "Storage download failed for %s (%s): %s", session_id, storage_path, exc
            )

    # Fallback: fetch from media_url
    if file_bytes is None and media_url:
        try:
            import httpx
            with httpx.Client(timeout=60.0) as http:
                resp = http.get(media_url)
                resp.raise_for_status()
                file_bytes = resp.content
                content_type = resp.headers.get("content-type")
        except Exception as exc:
            logger.warning(
                "URL download failed for %s (%s): %s", session_id, media_url, exc
            )

    # In-memory store (tests): use empty bytes so transcription service is reached
    if file_bytes is None and isinstance(db, dict):
        file_bytes = b""

    if file_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "media_download_failed",
                "message": (
                    "Could not retrieve the media file for transcription. "
                    "Check that the file was uploaded successfully, then retry."
                ),
            },
        )

    # ── Transcribe ─────────────────────────────────────────────────────────────
    try:
        tx_result = transcribe_audio(file_bytes, filename, content_type)
    except TranscriptionUnavailableError:
        # Graceful 200: not configured — frontend shows manual paste fallback.
        return ProjectDefenseTranscribeResponse(
            proof_session_id=session_id,
            transcript_text="",
            transcription_status=str(row.get("transcription_status") or "uploaded"),
            transcript_reviewed=False,
            provider_used="none",
            configured=False,
            message=(
                "Automatic transcription is not configured yet. "
                "Paste or edit the transcript manually."
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "transcription_failed",
                "message": str(exc),
            },
        )

    # ── No-speech / low-quality guard (mirrors the VBR gates) ─────────────────
    # Whisper over a silent/near-silent recording does not error — it emits
    # punctuation-only segments (a run of "." tokens), and degraded audio can
    # yield a single hallucinated token repeated dozens of times. Neither is a
    # real transcript: refining and persisting it would show "Transcript
    # generated" over meaningless output. Same gate semantics as
    # ``vbr_transcription``: measure meaningful (alphanumeric) words and
    # repetitiveness across the provider's full text AND its raw segment texts
    # (max of the two sources), and fail honestly with ``no_speech`` /
    # ``low_quality`` — nothing is persisted, so a retry re-runs transcription.
    segment_source_text = " ".join(
        seg.text for seg in (tx_result.transcript_segments or [])
    )
    meaningful_word_count = max(
        count_meaningful_words(tx_result.transcript_text),
        count_meaningful_words(segment_source_text),
    )
    if meaningful_word_count < MEANINGFUL_WORD_THRESHOLD:
        return ProjectDefenseTranscribeResponse(
            proof_session_id=session_id,
            transcript_text="",
            transcription_status="no_speech",
            transcript_reviewed=False,
            provider_used=tx_result.provider_used,
            configured=True,
            message=(
                "No useful speech was detected. Please retry with clearer audio "
                "or paste the transcript manually."
            ),
        )
    if is_low_quality_transcript(tx_result.transcript_text) or is_low_quality_transcript(
        segment_source_text
    ):
        return ProjectDefenseTranscribeResponse(
            proof_session_id=session_id,
            transcript_text="",
            transcription_status="low_quality",
            transcript_reviewed=False,
            provider_used=tx_result.provider_used,
            configured=True,
            message=(
                "Transcript quality too low. Please re-record with clearer audio "
                "or paste the transcript manually."
            ),
        )

    # ── Privacy scan ───────────────────────────────────────────────────────────
    privacy_result = scan_proof_data({"transcript": tx_result.transcript_text})

    # ── Auto-refinement ────────────────────────────────────────────────────────
    # Run NLP refinement immediately after transcription so the student sees
    # corrected text by default.  This is best-effort — refinement failure never
    # blocks the transcription response.
    from app.services.transcript_refinement_service import (
        RefinementResult,
        build_correction_display_summary,
        refine_project_defense_transcript,
    )

    refinement: RefinementResult | None = None
    refinement_status = "not_started"

    try:
        # Gather context from the session row
        claimed_skills_raw = row.get("claimed_skills") or []
        claimed_skills: list[str] = (
            claimed_skills_raw if isinstance(claimed_skills_raw, list) else []
        )
        # Attempt to load extended session context (skills, website, github)
        # These may come from the parent skill_evidence row — best effort
        student_profile: dict | None = None
        website_url: str | None = None
        github_url: str | None = None
        project_context: str | None = row.get("proof_objective") or None

        try:
            from app.services.extension_proof_service import ExtensionProofSessionService
            session_row = ExtensionProofSessionService(db)._get_row(user_id, session_id)
            # Try to load claimed_skills and project context from session
            session_skills = session_row.get("claimed_skills") or []
            if isinstance(session_skills, list) and session_skills:
                claimed_skills = session_skills
            if not project_context:
                project_context = session_row.get("proof_objective") or None
            website_url = session_row.get("website_url") or None
            github_url = session_row.get("github_url") or None
        except Exception:
            pass  # non-critical

        refinement = refine_project_defense_transcript(
            raw_transcript=tx_result.transcript_text,
            student_profile=student_profile,
            project_context=project_context,
            claimed_skills=claimed_skills,
            website_url=website_url,
            github_url=github_url,
        )
        refinement_status = "complete"
    except Exception as exc:
        logger.warning("Auto-refinement failed for session %s: %s", session_id, exc)
        refinement_status = "failed"

    # The working transcript shown to the student is the refined version when
    # available; the raw transcript is always preserved separately.
    working_transcript = (
        refinement.refined_transcript
        if refinement and refinement.refined_transcript
        else tx_result.transcript_text
    )

    # ── Serialise transcript segments (faster-whisper produces these) ──────────
    segments_data: list[dict] = [
        {"start_time": seg.start_time, "end_time": seg.end_time, "text": seg.text}
        for seg in (tx_result.transcript_segments or [])
    ]

    # ── Persist ────────────────────────────────────────────────────────────────
    service.save_transcription_result(
        user_id=user_id,
        proof_session_id=session_id,
        transcript_text=working_transcript,
        privacy_scan_status=privacy_result.status,
        transcript_segments=segments_data if segments_data else None,
        raw_transcript=tx_result.transcript_text,
        refined_transcript=refinement.refined_transcript if refinement else None,
        transcript_correction_summary=refinement.correction_summary if refinement else [],
        transcript_glossary_matches=refinement.glossary_matches if refinement else [],
        transcript_refinement_status=refinement_status,
        transcript_needs_review=refinement.needs_review if refinement else False,
    )

    privacy_note = (
        " Privacy flag detected — please review and remove any sensitive data "
        "before submitting for analysis."
        if privacy_result.contains_sensitive_data
        else ""
    )

    display_summary = (
        build_correction_display_summary(refinement.correction_summary)
        if refinement and refinement.correction_summary
        else ""
    )

    needs_review_note = (
        " Please review this transcript before analysis — many corrections were made."
        if refinement and refinement.needs_review
        else ""
    )

    return ProjectDefenseTranscribeResponse(
        proof_session_id=session_id,
        transcript_text=working_transcript,
        transcription_status="transcript_ready",
        transcript_reviewed=False,
        provider_used=tx_result.provider_used,
        configured=True,
        message=(
            f"Transcript generated. Review and edit before analysis."
            f"{needs_review_note}{privacy_note}"
        ),
        transcript_segments=segments_data,
        # Refinement fields
        raw_transcript=tx_result.transcript_text,
        refined_transcript=refinement.refined_transcript if refinement else None,
        transcript_correction_summary=refinement.correction_summary if refinement else [],
        transcript_glossary_matches=refinement.glossary_matches if refinement else [],
        transcript_refinement_status=refinement_status,
        transcript_needs_review=refinement.needs_review if refinement else False,
        refinement_display_summary=display_summary,
    )


# ── POST /defense/refine-transcript ───────────────────────────────────────────

@router.post(
    "/{session_id}/defense/refine-transcript",
    response_model=ProjectDefenseRefineTranscriptResponse,
    summary="(Re-)run NLP transcript refinement on the stored raw transcript",
)
def refine_defense_transcript(
    session_id: str,
    body: ProjectDefenseRefineTranscriptRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ProjectDefenseRefineTranscriptResponse:
    """
    Re-run transcript refinement using the stored raw_transcript and optionally
    overridden context (claimed_skills, project_context, website_url, github_url).

    Use this to re-refine after the student updates their profile or skills list,
    or after the first transcription if auto-refinement failed.

    Returns 404 if no raw transcript exists for this session yet.
    """
    from app.services.transcript_refinement_service import (
        build_correction_display_summary,
        refine_project_defense_transcript,
    )

    _verify_session(user_id, session_id, db)

    service = ProjectDefenseAnalysisService(db)
    row = service.get_analysis(user_id, session_id)

    if row is None or not row.get("raw_transcript"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "raw_transcript_not_found",
                "message": (
                    "No raw transcript found for this session. "
                    "Upload and transcribe a media file first."
                ),
                "session_id": session_id,
            },
        )

    raw_tx = row["raw_transcript"]

    # Collect context: body overrides > session row defaults
    claimed_skills = body.claimed_skills or []
    project_context = body.project_context or None
    website_url = body.website_url or None
    github_url = body.github_url or None

    # Try to pull context from the session if not overridden
    if not claimed_skills or not project_context:
        try:
            from app.services.extension_proof_service import ExtensionProofSessionService
            session_row = ExtensionProofSessionService(db)._get_row(user_id, session_id)
            if not claimed_skills:
                session_skills = session_row.get("claimed_skills") or []
                claimed_skills = session_skills if isinstance(session_skills, list) else []
            if not project_context:
                project_context = session_row.get("proof_objective") or None
            if not website_url:
                website_url = session_row.get("website_url") or None
            if not github_url:
                github_url = session_row.get("github_url") or None
        except Exception:
            pass

    try:
        refinement = refine_project_defense_transcript(
            raw_transcript=raw_tx,
            student_profile=None,
            project_context=project_context,
            claimed_skills=claimed_skills,
            website_url=website_url,
            github_url=github_url,
        )
    except Exception as exc:
        logger.error("Refinement endpoint error for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "refinement_failed",
                "message": "Transcript refinement failed. Please try again.",
            },
        )

    # Persist the new refinement result
    service.save_refinement_result(
        user_id=user_id,
        proof_session_id=session_id,
        raw_transcript=raw_tx,
        refined_transcript=refinement.refined_transcript,
        correction_summary=refinement.correction_summary,
        glossary_matches=refinement.glossary_matches,
        refinement_status="complete",
        needs_review=refinement.needs_review,
    )

    display_summary = build_correction_display_summary(refinement.correction_summary)
    review_note = (
        "Please review the transcript — several corrections were applied."
        if refinement.needs_review
        else "Transcript refined successfully."
    )

    return ProjectDefenseRefineTranscriptResponse(
        proof_session_id=session_id,
        raw_transcript=raw_tx,
        refined_transcript=refinement.refined_transcript,
        transcript_correction_summary=refinement.correction_summary,
        transcript_glossary_matches=refinement.glossary_matches,
        transcript_refinement_status="complete",
        transcript_needs_review=refinement.needs_review,
        confidence=refinement.confidence,
        refinement_display_summary=display_summary,
        message=review_note,
    )
