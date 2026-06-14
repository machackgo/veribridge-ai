"""Verified Build Report (VBR) session recording/upload endpoints (T4A skeleton).

MVP scope only: backend metadata foundation for the browser-recorded defense
session — start/consent/chunk/telemetry/finalize. No real Supabase signed
upload URLs are minted here, and no raw video is publicly exposed.

``get_db`` returns the service-role Supabase client which bypasses RLS, so
every route here manually checks ownership via
``get_owned_vbr_session_or_404`` (which checks the parent project's
``user_id``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.api.v1.endpoints.vbr_projects import _advance_project_status, _to_question_response
from app.schemas.vbr_sessions import (
    VBRChunkResponse,
    VBRChunkUploadRequest,
    VBRChunkUploadUrlRequest,
    VBRChunkUploadUrlResponse,
    VBRConsentRequest,
    VBRConsentResponse,
    VBREvidenceBuildResponse,
    VBRFinalizeRequest,
    VBRJudgmentResponse,
    VBRKeyframeExtractionResponse,
    VBRMediaProcessingResponse,
    VBRRecordingReadinessResponse,
    VBRReportDraftResponse,
    VBRReportPublishResponse,
    VBRReportReviewResponse,
    VBRReportStatusResponse,
    VBRReportUnpublishResponse,
    VBRSessionDetailResponse,
    VBRSessionResponse,
    VBRTelemetryRequest,
    VBRTelemetryResponse,
    VBRTranscriptionResponse,
)
from app.services.vbr_evidence_builder import build_session_evidence
from app.services.vbr_judgment import judge_session_skeleton
from app.services.vbr_keyframes import extract_keyframes_skeleton
from app.services.vbr_media_processing import process_uploaded_session_skeleton
from app.services.vbr_question_generation import list_session_questions
from app.services.vbr_report_draft import generate_report_draft
from app.services.vbr_report_publish import (
    get_report_status,
    publish_report,
    submit_report_review,
    unpublish_report,
)
from app.services.vbr_transcription import transcribe_session
from app.services.vbr_session_recording import (
    cancel_recording_session,
    check_recording_storage_readiness,
    check_session_recording_readiness,
    count_chunks,
    create_chunk_upload_target,
    create_recording_consent,
    finalize_session,
    get_owned_vbr_session_or_404,
    has_recording_consent,
    start_session,
    update_session_telemetry,
    upsert_video_chunk,
    validate_chunk_payload,
)

router = APIRouter()


# ── Response helpers ─────────────────────────────────────────────────────────


def _to_session_response(row: dict[str, Any], chunk_count: int) -> VBRSessionResponse:
    return VBRSessionResponse(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        attempt_no=row.get("attempt_no") or 1,
        status=row.get("status") or "created",
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        duration_s=row.get("duration_s"),
        webcam_present=bool(row.get("webcam_present")),
        chunk_count=chunk_count,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        transcript_status=((row.get("telemetry") or {}).get("transcript") or {}).get("status"),
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/{session_id}",
    response_model=VBRSessionDetailResponse,
    summary="Get a VBR verification session owned by the current user",
)
def get_session_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRSessionDetailResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    questions = list_session_questions(db, session_id)
    chunk_count = count_chunks(db, session_id)

    return VBRSessionDetailResponse(
        **_to_session_response(session, chunk_count).model_dump(),
        questions=[_to_question_response(row) for row in questions],
    )


@router.post(
    "/{session_id}/consent",
    response_model=VBRConsentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record recording consent for the current user (required before /start)",
)
def create_session_consent_route(
    session_id: str,
    body: VBRConsentRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRConsentResponse:
    get_owned_vbr_session_or_404(db, session_id, user_id)

    consent = create_recording_consent(db, user_id, body.text_version, metadata={"session_id": session_id})

    return VBRConsentResponse(
        id=str(consent["id"]),
        user_id=str(consent["user_id"]),
        kind=consent["kind"],
        granted=bool(consent["granted"]),
        text_version=consent["text_version"],
        created_at=str(consent.get("created_at") or ""),
    )


@router.post(
    "/{session_id}/start",
    response_model=VBRSessionResponse,
    summary="Start recording a VBR verification session",
)
def start_session_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRSessionResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if not has_recording_consent(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_recording_consent_required",
                "message": "Recording consent is required before starting a session.",
            },
        )

    if session.get("status") != "created":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_startable",
                "message": "Only sessions in 'created' status can be started.",
            },
        )

    readiness = check_recording_storage_readiness(db)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": readiness["code"], "message": readiness["message"]},
        )

    updated = start_session(db, session)
    return _to_session_response(updated, count_chunks(db, session_id))


@router.get(
    "/{session_id}/recording-readiness",
    response_model=VBRRecordingReadinessResponse,
    summary="Check whether browser recording can be started for this session",
)
def recording_readiness_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRRecordingReadinessResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)
    return VBRRecordingReadinessResponse(**check_session_recording_readiness(db, session))


@router.post(
    "/{session_id}/cancel-recording",
    response_model=VBRSessionResponse,
    summary="Reset a stuck, zero-chunk recording session back to a retryable state",
)
def cancel_recording_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRSessionResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "recording":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_recording",
                "message": "Only sessions in 'recording' status can be reset.",
            },
        )

    chunk_count = count_chunks(db, session_id)
    if chunk_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_has_chunks",
                "message": "This session already has uploaded chunks and cannot be reset.",
            },
        )

    updated = cancel_recording_session(db, session)
    return _to_session_response(updated, chunk_count)


@router.post(
    "/{session_id}/chunk-upload-url",
    response_model=VBRChunkUploadUrlResponse,
    summary="Request a short-lived upload target for a video chunk",
)
def create_chunk_upload_url_route(
    session_id: str,
    body: VBRChunkUploadUrlRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRChunkUploadUrlResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "recording":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_recording",
                "message": "Session must be in 'recording' status to request an upload target.",
            },
        )

    target = create_chunk_upload_target(db, session_id, body.chunk_index, body.bytes, body.sha256)
    return VBRChunkUploadUrlResponse(**target)


@router.post(
    "/{session_id}/chunk",
    response_model=VBRChunkResponse,
    summary="Record metadata for an uploaded video chunk (MVP metadata-only)",
)
def upload_chunk_route(
    session_id: str,
    body: VBRChunkUploadRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRChunkResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "recording":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_recording",
                "message": "Session must be in 'recording' status to accept chunks.",
            },
        )

    validate_chunk_payload(session_id, body.chunk_index, body.storage_path, body.bytes, body.sha256)

    chunk = upsert_video_chunk(db, session_id, body.chunk_index, body.storage_path, body.bytes, body.sha256)

    return VBRChunkResponse(
        id=str(chunk["id"]),
        session_id=session_id,
        chunk_index=chunk["chunk_index"],
        bytes=chunk.get("bytes"),
        sha256=chunk.get("sha256"),
        received_at=str(chunk.get("received_at") or ""),
    )


@router.post(
    "/{session_id}/telemetry",
    response_model=VBRTelemetryResponse,
    summary="Merge session telemetry (question timestamps/events)",
)
def update_telemetry_route(
    session_id: str,
    body: VBRTelemetryRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRTelemetryResponse:
    session, _project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "recording":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_recording",
                "message": "Session must be in 'recording' status to record telemetry.",
            },
        )

    updated = update_session_telemetry(db, session, body.telemetry, merge=body.merge)

    return VBRTelemetryResponse(session_id=session_id, telemetry=updated.get("telemetry") or {})


@router.post(
    "/{session_id}/finalize",
    response_model=VBRSessionResponse,
    summary="Finalize a VBR verification session after upload",
)
def finalize_session_route(
    session_id: str,
    body: VBRFinalizeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRSessionResponse:
    session, project = get_owned_vbr_session_or_404(db, session_id, user_id)

    if session.get("status") != "recording":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "vbr_session_not_recording",
                "message": "Session must be in 'recording' status to finalize.",
            },
        )

    chunk_count = count_chunks(db, session_id)
    if chunk_count < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "vbr_session_no_chunks",
                "message": "At least one video chunk is required before finalizing.",
            },
        )

    updated = finalize_session(db, session, body.duration_s)
    _advance_project_status(db, project, "session_uploaded")

    return _to_session_response(updated, chunk_count)


@router.post(
    "/{session_id}/process",
    response_model=VBRMediaProcessingResponse,
    summary="Run the deterministic media-processing skeleton for an uploaded session",
)
def process_session_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRMediaProcessingResponse:
    result = process_uploaded_session_skeleton(db, session_id, user_id)
    return VBRMediaProcessingResponse(**result)


@router.post(
    "/{session_id}/transcribe",
    response_model=VBRTranscriptionResponse,
    summary="Generate a timestamped transcript for a processed session",
)
def transcribe_session_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRTranscriptionResponse:
    result = transcribe_session(db, session_id, user_id)
    return VBRTranscriptionResponse(**result)


@router.post(
    "/{session_id}/extract-keyframes",
    response_model=VBRKeyframeExtractionResponse,
    summary="Extract keyframes from the processed full session video",
)
def extract_keyframes_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRKeyframeExtractionResponse:
    result = extract_keyframes_skeleton(db, session_id, user_id)
    return VBRKeyframeExtractionResponse(**result)


@router.post(
    "/{session_id}/build-evidence",
    response_model=VBREvidenceBuildResponse,
    summary="Build deterministic evidence items from processed session artifacts",
)
def build_evidence_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBREvidenceBuildResponse:
    result = build_session_evidence(db, session_id, user_id)
    return VBREvidenceBuildResponse(**result)


@router.post(
    "/{session_id}/judge",
    response_model=VBRJudgmentResponse,
    summary="Build a deterministic claim/question judgment skeleton (no LLM)",
)
def judge_session_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRJudgmentResponse:
    result = judge_session_skeleton(db, session_id, user_id)
    return VBRJudgmentResponse(**result)


@router.post(
    "/{session_id}/draft-report",
    response_model=VBRReportDraftResponse,
    summary="Generate a private VBR report draft from confirmed claims and deterministic judgment (no LLM, not published)",
)
def draft_report_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRReportDraftResponse:
    result = generate_report_draft(db, session_id, user_id)
    return VBRReportDraftResponse(**result)


@router.post(
    "/{session_id}/submit-report-review",
    response_model=VBRReportReviewResponse,
    summary="Submit a private VBR report draft for review (no public link is created)",
)
def submit_report_review_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRReportReviewResponse:
    result = submit_report_review(db, session_id, user_id)
    return VBRReportReviewResponse(**result)


@router.post(
    "/{session_id}/publish-report",
    response_model=VBRReportPublishResponse,
    summary="Publish a VBR report, minting a public token only at publish time",
)
def publish_report_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRReportPublishResponse:
    result = publish_report(db, session_id, user_id)
    return VBRReportPublishResponse(**result)


@router.post(
    "/{session_id}/unpublish-report",
    response_model=VBRReportUnpublishResponse,
    summary="Unpublish a VBR report and clear its public token",
)
def unpublish_report_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRReportUnpublishResponse:
    result = unpublish_report(db, session_id, user_id)
    return VBRReportUnpublishResponse(**result)


@router.get(
    "/{session_id}/report-status",
    response_model=VBRReportStatusResponse,
    summary="Get a private status summary for this session's VBR report",
)
def report_status_route(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VBRReportStatusResponse:
    result = get_report_status(db, session_id, user_id)
    return VBRReportStatusResponse(**result)
