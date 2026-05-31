"""Workflow Visual Frame endpoints.

Accepts screenshot frames captured by the browser extension during recording,
triggers visual analysis, and provides provider status for the frontend.

Endpoints:
  POST /{session_id}/workflow/visual-frames
      → Submit a batch of frames (called by the extension).
        Triggers async visual analysis (or marks as not_configured).

  GET  /{session_id}/workflow/visual-frames/status
      → Student-facing provider status and frame count.
        Shows which evidence layers are active.

Privacy:
  - frame_storage_path is NEVER returned in any response.
  - Recruiters never access raw frames — only processed workflow_analysis_results.
  - This endpoint is for student + extension use only.

Frame capture triggers (from extension):
  recording_start, page_load, after_click, after_upload,
  after_form_submit, after_dom_mutation, after_result_detected, recording_end

Throttling:
  MAX_WORKFLOW_FRAMES env var limits accepted frames per session (default 15).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_id, get_db
from app.core.config import settings
from app.services.video_keyframe_extractor_service import (
    VideoKeyframeExtractorService,
    VIDEO_STATUS_ANALYZED,
    VIDEO_STATUS_NOT_AVAILABLE,
    VIDEO_STATUS_FAILED,
)
from app.services.workflow_visual_analysis_service import (
    WorkflowVisualAnalysisService,
    VISUAL_STATUS_NOT_CONFIGURED,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class VisualFrameInput(BaseModel):
    """A single frame submitted from the browser extension."""

    frame_type: str = Field(
        default="screenshot",
        description=(
            "What triggered this capture: recording_start | page_load | after_click | "
            "after_upload | after_form_submit | after_dom_mutation | "
            "after_result_detected | recording_end | screenshot"
        ),
    )
    # Frame image as base64-encoded JPEG/PNG
    frame_base64: str | None = Field(
        default=None,
        description="Base64-encoded image bytes (JPEG or PNG). Compressed/resized by extension.",
    )
    timestamp_ms: int | None = Field(
        default=None,
        description="Milliseconds from recording start when this frame was captured.",
    )
    frame_width: int | None = Field(default=None, description="Image width in pixels.")
    frame_height: int | None = Field(default=None, description="Image height in pixels.")
    # Optional correlation back to a DOM visible evidence event
    visible_evidence_event_id: str | None = Field(
        default=None,
        description="ID of the DOM visible evidence event this frame corresponds to.",
    )


class VisualFrameBatchRequest(BaseModel):
    frames: list[VisualFrameInput] = Field(
        default_factory=list,
        description="Batch of visual frames captured during the recording session.",
        max_length=20,
    )


class VisualFrameBatchResponse(BaseModel):
    accepted_count: int
    skipped_count: int
    provider_status: str
    provider_configured: bool
    frame_capture_enabled: bool
    message: str


class VideoUploadResponse(BaseModel):
    """Public-safe response for video keyframe upload.

    Never exposes frame bytes, storage paths, access tokens, or
    private debug metadata.  Only status/count/timestamp metadata.
    """
    session_id: str
    video_analysis_status: str
    keyframe_count: int
    selected_frame_timestamps_ms: list[int]
    extraction_method: str
    duration_ms: int | None = None
    frames_stored: int
    frames_queued_for_visual_analysis: int
    limitations: list[str]
    message: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/{session_id}/workflow/visual-frames",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VisualFrameBatchResponse,
    summary="Submit visual screenshot frames captured during recording",
    description=(
        "Accepts a batch of compressed screenshot frames from the browser extension. "
        "Frames are stored and queued for visual analysis using the configured provider. "
        "If no provider is configured, frames are acknowledged but marked not_configured. "
        "DOM evidence continues to work regardless of visual provider status."
    ),
)
def submit_visual_frames(
    session_id: str,
    body: VisualFrameBatchRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VisualFrameBatchResponse:
    logger.info(
        "[VisualFrames] session=%s user=%s frames=%d",
        session_id, user_id, len(body.frames),
    )

    svc = WorkflowVisualAnalysisService(db)
    provider_status = svc.get_provider_status()

    if not settings.enable_workflow_frame_capture:
        return VisualFrameBatchResponse(
            accepted_count=0,
            skipped_count=len(body.frames),
            provider_status="disabled",
            provider_configured=False,
            frame_capture_enabled=False,
            message="Frame capture is disabled (ENABLE_WORKFLOW_FRAME_CAPTURE=false). DOM evidence is still active.",
        )

    accepted = 0
    skipped = 0
    frame_bytes_map: dict[str, bytes] = {}

    for frame_input in body.frames[: settings.max_workflow_frames]:
        # Validate frame_type
        valid_types = {
            "recording_start", "page_load", "after_click", "after_upload",
            "after_form_submit", "after_dom_mutation", "after_result_detected",
            "recording_end", "screenshot",
        }
        ft = frame_input.frame_type if frame_input.frame_type in valid_types else "screenshot"

        # Decode bytes if provided
        fb: bytes | None = None
        if frame_input.frame_base64:
            try:
                fb = base64.b64decode(frame_input.frame_base64)
            except Exception:
                logger.debug("[VisualFrames] Invalid base64 for frame type=%s", ft)
                skipped += 1
                continue

        frame_id = svc.store_visual_frame(
            user_id=user_id,
            session_id=session_id,
            frame_type=ft,
            frame_bytes=fb,
            timestamp_ms=frame_input.timestamp_ms,
            frame_width=frame_input.frame_width,
            frame_height=frame_input.frame_height,
            visible_evidence_event_id=frame_input.visible_evidence_event_id,
        )

        if fb:
            frame_bytes_map[frame_id] = fb

        accepted += 1

    # Trigger analysis if provider is configured
    if accepted > 0 and provider_status["provider_configured"]:
        try:
            svc.analyze_frames_for_session(
                user_id=user_id,
                session_id=session_id,
                frame_bytes_map=frame_bytes_map,
            )
        except Exception as exc:
            logger.warning("[VisualFrames] Analysis failed (non-fatal): %s", exc)

    provider_name = provider_status["visual_analysis_provider"]
    is_configured = provider_status["provider_configured"]

    if is_configured:
        msg = f"Frames accepted and analyzed via {provider_name}."
    else:
        msg = (
            f"Frames accepted. Provider '{provider_name}' is not configured — "
            "returning not_configured. DOM evidence is still used for workflow analysis. "
            "Set VISUAL_ANALYSIS_PROVIDER and install required packages to enable visual analysis."
        )

    return VisualFrameBatchResponse(
        accepted_count=accepted,
        skipped_count=skipped + max(0, len(body.frames) - settings.max_workflow_frames),
        provider_status=provider_name,
        provider_configured=is_configured,
        frame_capture_enabled=settings.enable_workflow_frame_capture,
        message=msg,
    )


@router.get(
    "/{session_id}/workflow/visual-frames/status",
    summary="Get visual frame analysis provider status for a session",
    description=(
        "Returns the current visual analysis provider configuration and "
        "how many frames have been captured and analyzed for this session. "
        "Used by the frontend to show evidence layer badges."
    ),
)
def get_visual_frames_status(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    svc = WorkflowVisualAnalysisService(db)
    provider_status = svc.get_provider_status()
    visual_obs = svc.get_visual_observations(user_id, session_id)

    return {
        "session_id": session_id,
        "provider": provider_status["visual_analysis_provider"],
        "provider_configured": provider_status["provider_configured"],
        "frame_capture_enabled": provider_status["frame_capture_enabled"],
        "local_ocr_provider": provider_status["local_ocr_provider"],
        "local_vision_provider": provider_status["local_vision_provider"],
        "max_frames": provider_status["max_frames"],
        "visual_frame_count": visual_obs.get("visual_frame_count", 0),
        "visual_frame_analysis_status": visual_obs.get("visual_frame_analysis_status", "not_captured"),
        "extracted_result_values_count": len(visual_obs.get("extracted_result_values", [])),
        "privacy_note": (
            "Visual frame analysis uses local/open-source providers when configured. "
            "No external vision API is required for the local pipeline."
        ),
    }


# ── Video upload endpoint ──────────────────────────────────────────────────────

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "video/webm",
    "video/mp4",
    "video/x-matroska",
    "video/ogg",
    "video/x-msvideo",
    "application/octet-stream",
})

# Frame types accepted by store_visual_frame — keep in sync with extension triggers
_VALID_FRAME_TYPES: frozenset[str] = frozenset({
    "recording_start", "page_load", "after_click", "after_upload",
    "after_form_submit", "after_dom_mutation", "after_result_detected",
    "recording_end", "screenshot", "video_keyframe",
})


@router.post(
    "/{session_id}/workflow/video",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=VideoUploadResponse,
    summary="Upload a recorded workflow video for keyframe extraction",
    description=(
        "Accepts a browser-recorded workflow video (WebM, MP4, etc.), extracts "
        "evenly-spaced keyframes in-memory, and stores each frame as a visual "
        "evidence record for downstream visual analysis.\n\n"
        "**Privacy**: raw video bytes are never persisted.  Only extracted JPEG "
        "keyframes are stored privately as workflow_visual_frame_evidence records.  "
        "No frame paths or storage URLs are returned in the response.\n\n"
        "**Fallback**: if cv2 and ffmpeg are both unavailable, the endpoint returns "
        "video_analysis_status='not_available' without crashing.  "
        "DOM evidence continues to work."
    ),
)
async def upload_workflow_video(
    session_id: str,
    video: UploadFile = File(
        ...,
        description="Recorded workflow video file (WebM or MP4 from browser MediaRecorder).",
    ),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VideoUploadResponse:
    logger.info(
        "[WorkflowVideo] session=%s user=%s filename=%r content_type=%r",
        session_id, user_id, video.filename, video.content_type,
    )

    # ── 1. Read video bytes (bounded by MAX_VIDEO_SIZE_BYTES + 1 byte) ─────────
    # Read one byte more than the limit so we can detect oversized files without
    # loading the entire file into memory first.
    limit_bytes = settings.max_video_size_bytes
    raw = await video.read(limit_bytes + 1)

    mime_type    = (video.content_type or "application/octet-stream").split(";")[0].strip()
    filename_val = video.filename or "recording.webm"

    # ── 2. Reject unsupported MIME types early (before extraction) ─────────────
    if mime_type not in _ALLOWED_CONTENT_TYPES:
        ext = filename_val.rsplit(".", 1)[-1].lower() if "." in filename_val else ""
        if f".{ext}" not in {".webm", ".mp4", ".mkv", ".ogg", ".ogv", ".avi"}:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Unsupported video format '{mime_type}'. "
                    "Upload a WebM or MP4 browser recording."
                ),
            )

    # ── 3. Extract keyframes ────────────────────────────────────────────────────
    extractor = VideoKeyframeExtractorService()
    result    = extractor.extract_keyframes(
        video_bytes=raw,
        filename=filename_val,
        mime_type=mime_type,
    )

    public = result.to_public_dict()
    frames_stored   = 0
    queued_for_analysis = 0

    va_svc = WorkflowVisualAnalysisService(db)

    if result.video_analysis_status == VIDEO_STATUS_ANALYZED and result._extracted_frames:
        # ── 4. Store extracted frames privately via visual analysis service ─────
        provider_info = va_svc.get_provider_status()
        frame_bytes_map: dict[str, bytes] = {}

        for ts_ms, jpeg_bytes in result._extracted_frames:
            frame_id = va_svc.store_visual_frame(
                user_id=user_id,
                session_id=session_id,
                frame_type="video_keyframe",
                frame_bytes=jpeg_bytes,
                timestamp_ms=ts_ms,
                frame_width=result.frame_width,
                frame_height=result.frame_height,
            )
            frame_bytes_map[frame_id] = jpeg_bytes
            frames_stored += 1

        # ── 5. Trigger visual analysis if provider is configured ────────────────
        if frames_stored > 0 and provider_info["provider_configured"]:
            try:
                va_svc.analyze_frames_for_session(
                    user_id=user_id,
                    session_id=session_id,
                    frame_bytes_map=frame_bytes_map,
                )
                queued_for_analysis = frames_stored
            except Exception as exc:
                logger.warning("[WorkflowVideo] Visual analysis failed (non-fatal): %s", exc)

    elif result.video_analysis_status in (VIDEO_STATUS_NOT_AVAILABLE, VIDEO_STATUS_FAILED):
        # ── 4b. Store a marker so the UI knows a video WAS uploaded ────────────
        # Use distinct frame_type to differentiate:
        #   "video_upload_marker"   → cv2/ffmpeg not installed (VIDEO_STATUS_NOT_AVAILABLE)
        #   "video_extract_failed"  → installed but decode failed (VIDEO_STATUS_FAILED)
        # Both make _enrich_video_keyframes() return video_upload_status="uploaded"
        # so the frontend shows "Video uploaded" rather than "No video recorded".
        marker_frame_type = (
            "video_upload_marker"
            if result.video_analysis_status == VIDEO_STATUS_NOT_AVAILABLE
            else "video_extract_failed"
        )
        # Store actual error in visual_summary for diagnostic purposes (never public).
        extraction_error = (
            result.limitations[0] if result.limitations else result.video_analysis_status
        )
        try:
            va_svc.store_visual_frame(
                user_id=user_id,
                session_id=session_id,
                frame_type=marker_frame_type,
                frame_bytes=None,
                timestamp_ms=0,
            )
            logger.info(
                "[WorkflowVideo] Stored %s for session %s "
                "(extraction status: %s, error: %s)",
                marker_frame_type, session_id,
                result.video_analysis_status, extraction_error[:100],
            )
        except Exception as exc:
            logger.warning("[WorkflowVideo] Could not store upload marker: %s", exc)

    # ── 6. Build public-safe response ───────────────────────────────────────────
    status_val = public["video_analysis_status"]

    if status_val == VIDEO_STATUS_ANALYZED:
        message = (
            f"{frames_stored} keyframe(s) extracted and stored. "
            f"Visual analysis queued: {queued_for_analysis > 0}."
        )
    elif status_val == "not_available":
        message = (
            "Video keyframe extraction is not available. "
            "Install opencv-python-headless or ffmpeg to enable it. "
            "DOM evidence is still used for workflow analysis."
        )
    elif status_val == "limit_exceeded":
        message = "Video exceeds size or duration limits. " + " ".join(public.get("limitations", []))
    elif status_val == "unsupported_format":
        message = "Unsupported video format. Use WebM or MP4."
    else:
        message = "Video could not be processed. " + " ".join(public.get("limitations", []))

    return VideoUploadResponse(
        session_id=session_id,
        video_analysis_status=status_val,
        keyframe_count=public["keyframe_count"],
        selected_frame_timestamps_ms=public["selected_frame_timestamps_ms"],
        extraction_method=public["extraction_method"],
        duration_ms=public.get("duration_ms"),
        frames_stored=frames_stored,
        frames_queued_for_visual_analysis=queued_for_analysis,
        limitations=public.get("limitations", []),
        message=message,
    )
