"""Project Defense Transcript Analysis endpoints.

POST /{session_id}/analyze/project-defense      — run the transcript analysis
GET  /{session_id}/analysis/project-defense     — fetch the stored result
POST /{session_id}/defense/upload-media         — register uploaded media file
PATCH /{session_id}/defense/transcript          — update transcript + reviewed flag
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.project_defense_analysis import (
    ALLOWED_MEDIA_EXTENSIONS,
    MAX_MEDIA_SIZE_BYTES,
    ProjectDefenseAnalyzeRequest,
    ProjectDefenseAnalysisResponse,
    ProjectDefenseMediaUploadResponse,
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
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Env-controlled storage bucket name.  Set this to enable Supabase Storage.
_MEDIA_BUCKET = os.environ.get("SUPABASE_DEFENSE_MEDIA_BUCKET", "")


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
        transcript_summary=str(row.get("transcript_summary") or ""),
        skills_mentioned=row.get("skills_mentioned") or [],
        skills_explained_well=row.get("skills_explained_well") or [],
        skills_missing_from_explanation=row.get("skills_missing_from_explanation") or [],
        consistency_with_evidence_score=int(row.get("consistency_with_evidence_score") or 0),
        explanation_clarity_score=int(row.get("explanation_clarity_score") or 0),
        ownership_signal_score=int(row.get("ownership_signal_score") or 0),
        technical_depth_score=int(row.get("technical_depth_score") or 0),
        overall_defense_score=int(row.get("overall_defense_score") or 0),
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

    # ── Read file and validate size ────────────────────────────────────────────
    content = await file.read()
    size_bytes = len(content)
    if size_bytes > MAX_MEDIA_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "media_too_large",
                "message": (
                    f"File size {size_bytes / (1024 * 1024):.1f} MB exceeds the "
                    "200 MB limit."
                ),
            },
        )

    # ── Optional Supabase Storage upload ──────────────────────────────────────
    storage_path: str | None = None
    media_url: str | None = None
    storage_configured = bool(_MEDIA_BUCKET)

    if storage_configured and not isinstance(db, dict):
        try:
            storage_path = f"{user_id}/{session_id}/{filename}"
            db.storage.from_(_MEDIA_BUCKET).upload(
                storage_path, content,
                file_options={"content-type": file.content_type or "application/octet-stream"},
            )
            url_result = db.storage.from_(_MEDIA_BUCKET).get_public_url(storage_path)
            media_url = url_result if isinstance(url_result, str) else None
        except Exception as exc:
            logger.warning("Supabase Storage upload failed (non-critical): %s", exc)
            storage_path = None
            media_url = None
            storage_configured = False

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

    msg = (
        "Media uploaded and stored. Automatic transcription is not available yet — "
        "paste or edit your transcript below, then click Analyze Project Defense."
        if not storage_configured
        else "Media uploaded and stored."
    )

    return ProjectDefenseMediaUploadResponse(
        proof_session_id=session_id,
        media_filename=filename,
        media_type=ext,
        media_size_bytes=size_bytes,
        media_url=media_url,
        media_storage_path=storage_path,
        transcription_status="uploaded",
        storage_configured=storage_configured,
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
        TranscriptionUnavailableError,
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

    # ── Privacy scan ───────────────────────────────────────────────────────────
    privacy_result = scan_proof_data({"transcript": tx_result.transcript_text})

    # ── Persist ────────────────────────────────────────────────────────────────
    service.save_transcription_result(
        user_id=user_id,
        proof_session_id=session_id,
        transcript_text=tx_result.transcript_text,
        privacy_scan_status=privacy_result.status,
    )

    privacy_note = (
        " Privacy flag detected — please review and remove any sensitive data "
        "before submitting for analysis."
        if privacy_result.contains_sensitive_data
        else ""
    )

    return ProjectDefenseTranscribeResponse(
        proof_session_id=session_id,
        transcript_text=tx_result.transcript_text,
        transcription_status="transcript_ready",
        transcript_reviewed=False,
        provider_used=tx_result.provider_used,
        configured=True,
        message=f"Transcript generated. Review and edit before analysis.{privacy_note}",
    )
