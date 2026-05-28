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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_id, get_db
from app.core.config import settings
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
