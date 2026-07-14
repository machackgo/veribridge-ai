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
import hashlib
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
from app.services.visual_reasoning_service import (
    VisualReasoningService,
    REASONING_STATUS_ANALYZED,
    REASONING_STATUS_REJECTED_INCONSISTENT,
    REASONING_STATUS_REJECTED_STALE,
    select_frame_ids_for_reasoning,
)
from app.services.keyframe_storage_service import KeyframeStorageService
from app.services.proof_target_resolver import resolve_target_url, resolve_target_domain
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services import proof_artifact_service

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
        max_length=40,
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
    replay_retained: bool = False
    replay_artifact_id: str | None = None


def _require_owned_session(db: Any, user_id: str, session_id: str):
    """Fail closed before any side evidence read/write for a Website Proof."""
    try:
        return ExtensionProofSessionService(db).require_owned_session(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "extension_proof_session_not_found",
                "message": "Website Proof session not found.",
            },
        ) from exc


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
    _require_owned_session(db, user_id, session_id)
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
    _require_owned_session(db, user_id, session_id)
    svc = WorkflowVisualAnalysisService(db)
    provider_status = svc.get_provider_status()
    visual_obs = svc.get_visual_observations(user_id, session_id)

    # ── Qwen visual reasoning status ─────────────────────────────────────────
    vr_svc = VisualReasoningService()
    vr_provider_status = vr_svc.get_provider_status()
    vr_enabled = vr_provider_status["visual_reasoning_enabled"]
    vr_configured = vr_provider_status["visual_reasoning_configured"]

    # Count keyframes: total, analyzed by Qwen, and any that have ANY visual_reasoning_json
    # (even failed/rejected — used to distinguish "Qwen ran and failed" from "pending").
    total_kf = 0
    analyzed_kf = 0
    qwen_ran_count = 0
    try:
        _FRAME_TABLE = "workflow_visual_frame_evidence"
        kf_resp = (
            db.table(_FRAME_TABLE)
            .select("id, visual_reasoning_json")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .eq("frame_type", "video_keyframe")
            .execute()
        )
        kf_rows = kf_resp.data or []
        total_kf = len(kf_rows)
        analyzed_kf = sum(
            1 for r in kf_rows
            if isinstance(r.get("visual_reasoning_json"), dict)
            and r["visual_reasoning_json"].get("status") == "analyzed"
        )
        # qwen_ran_count: frames that have ANY visual_reasoning_json set (regardless of status)
        qwen_ran_count = sum(
            1 for r in kf_rows
            if isinstance(r.get("visual_reasoning_json"), dict)
        )
    except Exception as _exc:
        logger.warning("[VisualFramesStatus] Could not count Qwen keyframes: %s", _exc)

    logger.info(
        "[VisualFramesStatus] session=%s "
        "qwen_enabled=%s qwen_configured=%s "
        "frames_found_count=%d analyzed_kf=%d qwen_ran_count=%d",
        session_id, vr_enabled, vr_configured, total_kf, analyzed_kf, qwen_ran_count,
    )

    if not vr_enabled:
        qwen_status = "disabled"
    elif not vr_configured:
        # Packages not installed — Qwen can never run until packages are added.
        qwen_status = "not_configured"
    elif total_kf == 0:
        # No keyframes: either no video was uploaded, or extraction failed.
        # Either way Qwen cannot run — use a terminal status, not "pending".
        qwen_status = "skipped_no_frames"
    elif analyzed_kf > 0:
        qwen_status = "analyzed" if analyzed_kf >= total_kf else "partial"
    elif qwen_ran_count > 0:
        # Qwen ran (stored visual_reasoning_json) but all frames failed or were rejected.
        qwen_status = "failed"
    else:
        # Keyframes exist but Qwen hasn't stored any results.
        # After the sentinel fix, this only happens transiently during upload
        # or if the DB update for the sentinel also failed.
        # Report as "skipped" so the UI shows a deterministic state.
        qwen_status = "skipped"

    logger.info(
        "[VisualFramesStatus] session=%s qwen_status=%s "
        "total_keyframes=%d analyzed_keyframes=%d qwen_ran_count=%d "
        "final_status_returned_to_ui=%s",
        session_id, qwen_status, total_kf, analyzed_kf, qwen_ran_count, qwen_status,
    )

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
        # Qwen visual reasoning config + per-session status
        "visual_reasoning_enabled": vr_enabled,
        "visual_reasoning_configured": vr_configured,
        "qwen_status": qwen_status,
        "qwen_total_keyframes": total_kf,
        "qwen_analyzed_keyframes": analyzed_kf,
        "privacy_note": (
            "Visual frame analysis uses local/open-source providers when configured. "
            "No external vision API is required for the local pipeline."
        ),
    }


# ── Owner-safe captured-frame listing ──────────────────────────────────────────


class SafeVisualFrameDescriptor(BaseModel):
    """One owner-safe captured-frame locator.

    Carries ONLY what the owner's UI needs to render a frame via the
    visibility-gated thumbnail proxy (``GET /api/v1/proof/frame-thumbnail/{frame_id}``):
    the frame id, its capture trigger, a timestamp, and whether a thumbnail is
    stored. Never storage paths, raw bytes, OCR text, or provider JSON.
    """

    frame_id: str
    frame_type: str
    timestamp_ms: int | None = None
    timestamp_label: str | None = None
    has_thumbnail: bool = False


class SessionVisualFramesResponse(BaseModel):
    session_id: str
    frame_count: int
    frames: list[SafeVisualFrameDescriptor]


# Upper bound on returned frame descriptors — captured frames per session are
# already throttled at ingest, this is a defensive response cap.
_MAX_LISTED_FRAMES = 40


@router.get(
    "/{session_id}/workflow/visual-frames",
    response_model=SessionVisualFramesResponse,
    summary="List the owner's captured evidence frames for a session (safe locators only)",
    description=(
        "Owner-only listing of the frames VeriBridge captured during this proof "
        "session (video keyframes and trigger screenshots), so the owner's Skill "
        "Report / Proof Vault can render them through the visibility-gated "
        "thumbnail proxy.\n\n"
        "**Privacy**: results are filtered to the authenticated caller's own "
        "frames — another user's session id returns an empty list, exactly like "
        "a session with no frames (no existence leak). The response carries only "
        "frame ids, capture triggers, and timestamps — never storage paths, raw "
        "frame bytes, OCR text, or visual-reasoning JSON."
    ),
)
def list_session_visual_frames(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SessionVisualFramesResponse:
    _require_owned_session(db, user_id, session_id)
    try:
        resp = (
            db.table("workflow_visual_frame_evidence")
            .select("id, frame_type, timestamp_ms, frame_thumbnail_storage_path")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .order("timestamp_ms", desc=False)
            .limit(_MAX_LISTED_FRAMES)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.warning("[VisualFramesList] Frame lookup failed for session %s: %s", session_id, exc)
        rows = []

    frames: list[SafeVisualFrameDescriptor] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        ts_ms = row.get("timestamp_ms")
        label = None
        if ts_ms is not None:
            try:
                total_s = int(ts_ms) // 1000
                label = f"{total_s // 60}:{total_s % 60:02d}"
            except (TypeError, ValueError):
                label = None
        frames.append(
            SafeVisualFrameDescriptor(
                frame_id=str(row["id"]),
                frame_type=str(row.get("frame_type") or "screenshot"),
                timestamp_ms=int(ts_ms) if isinstance(ts_ms, (int, float)) else None,
                timestamp_label=label,
                # Presence flag ONLY — the storage path itself never leaves the server.
                has_thumbnail=bool(row.get("frame_thumbnail_storage_path")),
            )
        )

    return SessionVisualFramesResponse(
        session_id=session_id,
        frame_count=len(frames),
        frames=frames,
    )


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
        "**Privacy**: the original recording is retained once in the private, "
        "owner-gated proof artifact store so replay and canonical finalization use "
        "the same evidence. Extracted JPEG keyframes remain private. No storage "
        "path or storage URL is returned in the response.\n\n"
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
    owned_session = _require_owned_session(db, user_id, session_id)
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
    replay_artifact: dict[str, Any] | None = None
    existing_replays = [
        row
        for row in proof_artifact_service.list_artifacts_for_proof(
            db,
            proof_type="website",
            proof_id=session_id,
            artifact_type="website_replay_video",
            retained_only=True,
        )
        if str(row.get("owner_user_id") or "") == str(user_id)
    ]
    if existing_replays:
        # Duplicate recorder delivery is idempotent: the first retained replay
        # remains the exact canonical artifact for this proof session.
        replay_artifact = existing_replays[-1]
    elif result.video_analysis_status not in {"limit_exceeded", "unsupported_format"}:
        replay_artifact = proof_artifact_service.register_artifact_with_bytes(
            db,
            owner_user_id=user_id,
            proof_type="website",
            artifact_type="website_replay_video",
            data=raw,
            file_name=filename_val,
            mime_type=mime_type,
            proof_id=session_id,
            project_id=(
                owned_session.get("project_id")
                or (
                    owned_session.get("metadata", {}).get("project_id")
                    if isinstance(owned_session.get("metadata"), dict)
                    else None
                )
            ),
            access_policy="owner_only",
            duration_seconds=(result.duration_ms / 1000) if result.duration_ms is not None else None,
        )
    if replay_artifact is None:
        logger.error(
            "[WebsiteProofRecorder] event=replay_retention_failed session_id=%s state=recording error_code=replay_storage_unavailable",
            session_id,
        )
    else:
        logger.info(
            "[WebsiteProofRecorder] event=replay_retained session_id=%s state=recording",
            session_id,
        )
    frames_stored   = 0
    queued_for_analysis = 0

    va_svc = WorkflowVisualAnalysisService(db)

    if result.video_analysis_status == VIDEO_STATUS_ANALYZED and result._extracted_frames:
        # ── 4. Store extracted frames privately via visual analysis service ─────
        provider_info = va_svc.get_provider_status()
        frame_bytes_map: dict[str, bytes] = {}

        # Clear stale visual_reasoning_json from any previous video uploads to this
        # session.  Without this, a second upload would leave old Qwen results (from
        # a different recording) in the DB, causing the session summary to mix
        # results from two different recordings.  The clear is a soft wipe: it NULLs
        # the json column on existing rows but does NOT delete them, so the row count
        # and timestamp history remain intact for debugging.
        try:
            db.table("workflow_visual_frame_evidence").update({
                "visual_reasoning_json": None,
            }).eq("proof_session_id", session_id).eq(
                "user_id", user_id,
            ).eq("frame_type", "video_keyframe").execute()
            logger.info(
                "[WorkflowVideo] Cleared stale visual_reasoning_json "
                "for session=%s before new upload",
                session_id,
            )
        except Exception as _clr_exc:
            logger.warning(
                "[WorkflowVideo] Could not clear stale visual_reasoning_json "
                "(non-fatal): session=%s error=%s",
                session_id, _clr_exc,
            )

        _frame_bucket = settings.supabase_frame_evidence_bucket
        _storage_svc = KeyframeStorageService() if _frame_bucket else None

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

            # Upload JPEG + thumbnail to Supabase Storage (non-fatal)
            if _storage_svc and not isinstance(db, dict):
                try:
                    paths = _storage_svc.upload_keyframe(
                        db=db,
                        user_id=user_id,
                        session_id=session_id,
                        frame_id=frame_id,
                        jpeg_bytes=jpeg_bytes,
                        bucket=_frame_bucket,
                    )
                    update: dict[str, str | None] = {}
                    if paths.get("storage_path"):
                        update["frame_storage_path"] = paths["storage_path"]
                    if paths.get("thumbnail_path"):
                        update["frame_thumbnail_storage_path"] = paths["thumbnail_path"]
                    if update:
                        db.table("workflow_visual_frame_evidence").update(
                            update
                        ).eq("id", frame_id).eq("user_id", user_id).execute()
                except Exception as _stor_exc:
                    logger.warning(
                        "[WorkflowVideo] Storage upload failed (non-fatal) "
                        "frame_id=%s: %s",
                        frame_id, _stor_exc,
                    )

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

        # ── 6. Trigger advanced visual reasoning if enabled ────────────────────
        # Runs after OCR. Uses result._extracted_frames (in-memory, real timestamps).
        # Stores per-frame reasoning JSON in workflow_visual_frame_evidence.
        # Non-fatal: reasoning failure never blocks the upload response.
        if frames_stored > 0:
            try:
                reasoning_svc = VisualReasoningService()
                provider_status = reasoning_svc.get_provider_status()
                is_reasoning_enabled = provider_status["visual_reasoning_enabled"]
                is_reasoning_configured = provider_status["visual_reasoning_configured"]
                reasoning_max_frames = provider_status["visual_reasoning_max_frames"]
                logger.info(
                    "[WorkflowVideo] qwen_enabled=%s qwen_configured=%s "
                    "provider=%s max_frames=%d frames_stored=%d session=%s",
                    is_reasoning_enabled,
                    is_reasoning_configured,
                    provider_status.get("local_vision_provider", "none"),
                    reasoning_max_frames,
                    frames_stored,
                    session_id,
                )
                if is_reasoning_configured:
                    # result._extracted_frames has real (ts_ms, jpeg_bytes) — pass full list,
                    # service applies midpoint-of-interval sampling internally.
                    frames_for_reasoning = result._extracted_frames
                    selected_ts = [
                        frames_for_reasoning[min(int((i + 0.5) * (len(frames_for_reasoning) / reasoning_max_frames)), len(frames_for_reasoning) - 1)][0]
                        for i in range(min(reasoning_max_frames, len(frames_for_reasoning)))
                    ] if frames_for_reasoning else []
                    logger.info(
                        "[WorkflowVideo] Qwen inference STARTING: session=%s "
                        "total_frames=%d expected_selected_timestamps_ms=%s",
                        session_id, len(frames_for_reasoning), selected_ts,
                    )

                    # Fetch session context (claimed skills, objective, URL) for dynamic prompt
                    _claimed_skills: list[str] = []
                    _proof_objective: str = ""
                    _website_context: str = ""
                    _target_domain: str = ""
                    _ocr_snippets: list[str] = []
                    try:
                        _sess = db.table("extension_proof_sessions").select(
                            "claimed_skills, proof_objective, website_url, proof_data"
                        ).eq("id", session_id).eq("user_id", user_id).maybe_single().execute()
                        if _sess and _sess.data:
                            raw_skills = _sess.data.get("claimed_skills") or []
                            _claimed_skills = [str(s) for s in raw_skills if s] if isinstance(raw_skills, list) else []
                            _proof_objective = str(_sess.data.get("proof_objective") or "")[:300]
                            # Use proof_target_resolver to get canonical URL/domain,
                            # falling back to proof_data.live_website_check.website_url
                            # when extension_proof_sessions.website_url is None.
                            _session_url = _sess.data.get("website_url")
                            _proof_data = _sess.data.get("proof_data") or {}
                            _resolved_url = resolve_target_url(_session_url, _proof_data)
                            _resolved_domain = resolve_target_domain(_session_url, _proof_data)
                            _website_context = (_resolved_url or "")[:150]
                            _target_domain = (_resolved_domain or "")[:100]
                    except Exception as _ctx_exc:
                        logger.warning("[WorkflowVideo] Could not fetch session context for Qwen prompt (non-fatal): %s", _ctx_exc)

                    # Fetch OCR text already extracted from keyframes (OCR ran in step 5)
                    _RECORDER_NOISE_LOWER: frozenset[str] = frozenset({
                        "veribridge screen recorder", "recording active", "stop recording",
                        "send proof", "recording controls", "recorder controls",
                        "stop & upload", "live video recording", "stop or send the recording",
                        "screen recorder", "veribridge recorder",
                    })
                    try:
                        _ocr_resp = db.table("workflow_visual_frame_evidence").select(
                            "ocr_text"
                        ).eq("proof_session_id", session_id).eq(
                            "user_id", user_id
                        ).eq("frame_type", "video_keyframe").limit(10).execute()
                        for _row in (_ocr_resp.data or []):
                            _ocr_val = _row.get("ocr_text")
                            if isinstance(_ocr_val, str) and _ocr_val.strip():
                                snip = _ocr_val.strip()[:150]
                                if not any(p in snip.lower() for p in _RECORDER_NOISE_LOWER):
                                    _ocr_snippets.append(snip)
                            elif isinstance(_ocr_val, list):
                                for _item in _ocr_val[:5]:
                                    # Support both plain strings and {"text": "..."} dicts
                                    if isinstance(_item, dict):
                                        _text = str(_item.get("text", "")).strip()
                                    elif isinstance(_item, str):
                                        _text = _item.strip()
                                    else:
                                        continue
                                    if _text and not any(p in _text.lower() for p in _RECORDER_NOISE_LOWER):
                                        _ocr_snippets.append(_text[:150])
                    except Exception as _ocr_ctx_exc:
                        logger.warning("[WorkflowVideo] Could not fetch OCR context for Qwen prompt (non-fatal): %s", _ocr_ctx_exc)

                    logger.info(
                        "[WorkflowVideo] Qwen context: skills=%s objective=%r website=%r domain=%r ocr_snippets=%d",
                        _claimed_skills, _proof_objective[:60], _website_context, _target_domain, len(_ocr_snippets),
                    )

                    summary = reasoning_svc.analyze_frames(
                        frames=frames_for_reasoning,
                        max_frames=reasoning_max_frames,
                        claimed_skills=_claimed_skills or None,
                        proof_objective=_proof_objective,
                        website_context=_website_context,
                        target_domain=_target_domain,
                        ocr_snippets=_ocr_snippets or None,
                    )
                    logger.info(
                        "[WorkflowVideo] Qwen inference DONE: session=%s "
                        "status=%s frames_analyzed=%d",
                        session_id, summary.status, summary.frames_analyzed,
                    )
                    # Persist per-frame reasoning (both analyzed and rejected obs).
                    # summary.observations now includes analyzed + rejected obs.
                    #
                    # Frame mapping: use select_frame_ids_for_reasoning() which applies
                    # the SAME percentile algorithm as VisualReasoningService.analyze_frames().
                    # Using a different algorithm here would store observations to wrong rows.
                    if summary.observations:
                        frame_ids = list(frame_bytes_map.keys())
                        n_total = len(frames_for_reasoning)
                        selected_frame_ids = select_frame_ids_for_reasoning(
                            frame_ids, reasoning_max_frames
                        )
                        logger.info(
                            "[WorkflowVideo] frame_id→observation mapping: "
                            "session=%s total_frames=%d selected_frame_ids=%s "
                            "obs_count=%d status=%s",
                            session_id, n_total, selected_frame_ids,
                            len(summary.observations), summary.status,
                        )
                        persisted = 0
                        for i, obs_dict in enumerate(summary.observations):
                            if i >= len(selected_frame_ids):
                                break
                            target_id = selected_frame_ids[i]
                            try:
                                db.table("workflow_visual_frame_evidence").update({
                                    "visual_reasoning_json": obs_dict,
                                }).eq("id", target_id).eq(
                                    "user_id", user_id
                                ).execute()
                                persisted += 1
                            except Exception as _exc:
                                logger.warning(
                                    "[WorkflowVideo] Could not persist visual_reasoning_json "
                                    "frame_id=%s: %s",
                                    target_id, _exc,
                                )
                        logger.info(
                            "[WorkflowVideo] visual_reasoning_json STORED: "
                            "session=%s persisted=%d/%d status=%s",
                            session_id, persisted, len(summary.observations), summary.status,
                        )
                    else:
                        # No per-frame observations produced (status may be failed/skipped/
                        # missing_dependency). Store a sentinel on the first keyframe row
                        # so the status endpoint can distinguish "Qwen ran but failed"
                        # from "Qwen hasn't run yet". Without this, the UI shows "pending"
                        # forever because _build_visual_reasoning_session_summary_from_db
                        # finds no rows with visual_reasoning_json and returns None.
                        _sentinel: dict[str, Any] = {
                            "status": summary.status,
                            "frames_analyzed": 0,
                            "summary": summary.summary or (
                                f"Qwen ran (provider={summary.provider}) "
                                f"but produced no analyzed frames (status={summary.status})."
                            ),
                            "limitations": list(summary.limitations or []),
                            "provider": summary.provider or "qwen_vl",
                            "model_provider": "qwen_vl",
                        }
                        logger.info(
                            "[WorkflowVideo] Visual reasoning not analyzed: "
                            "session=%s status=%s limitations=%s — storing sentinel",
                            session_id, summary.status, summary.limitations,
                        )
                        _sentinel_ids = list(frame_bytes_map.keys())
                        if _sentinel_ids:
                            try:
                                db.table("workflow_visual_frame_evidence").update({
                                    "visual_reasoning_json": _sentinel,
                                }).eq("id", _sentinel_ids[0]).eq(
                                    "user_id", user_id
                                ).execute()
                                logger.info(
                                    "[WorkflowVideo] Qwen sentinel stored: "
                                    "session=%s status=%s frame_id=%s",
                                    session_id, summary.status, _sentinel_ids[0],
                                )
                            except Exception as _s_exc:
                                logger.warning(
                                    "[WorkflowVideo] Could not store Qwen sentinel "
                                    "(non-fatal): %s", _s_exc,
                                )
                else:
                    logger.info(
                        "[WorkflowVideo] Visual reasoning skipped (not configured): "
                        "enabled=%s configured=%s session=%s",
                        is_reasoning_enabled, is_reasoning_configured, session_id,
                    )
            except Exception as exc:
                logger.warning(
                    "[WorkflowVideo] Advanced visual reasoning FAILED (non-fatal): %s",
                    exc, exc_info=True,
                )
                # Store a failed sentinel so the status endpoint shows "failed"
                # rather than "pending" forever.
                _fail_sentinel_ids = list(frame_bytes_map.keys())
                if _fail_sentinel_ids:
                    try:
                        db.table("workflow_visual_frame_evidence").update({
                            "visual_reasoning_json": {
                                "status": "failed",
                                "frames_analyzed": 0,
                                "summary": "Qwen visual reasoning encountered an unexpected error during upload.",
                                "limitations": [str(exc)[:200]],
                                "provider": "qwen_vl",
                                "model_provider": "qwen_vl",
                            },
                        }).eq("id", _fail_sentinel_ids[0]).eq(
                            "user_id", user_id
                        ).execute()
                    except Exception:
                        pass

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
        replay_retained=replay_artifact is not None,
        replay_artifact_id=str(replay_artifact.get("id")) if replay_artifact else None,
    )


# ── Dev-only debug endpoint ────────────────────────────────────────────────────
# Returns per-frame reasoning metadata for the given session.
# Only accessible when ENVIRONMENT != "production".
# Never exposes raw frame bytes, storage paths, or private URLs.

@router.get(
    "/{session_id}/debug/visual-reasoning-frames",
    summary="[DEV ONLY] Per-frame visual reasoning debug info for a session",
    include_in_schema=False,
)
def debug_visual_reasoning_frames(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    """Return per-frame reasoning metadata — dev/staging only.

    Safe fields returned per frame:
      - frame_id
      - frame_type
      - timestamp_ms
      - frame_dimensions (width × height)
      - frame_bytes_sha256  (first 16 hex chars — integrity check, not reversible)
      - ocr_text_preview    (first 120 chars of OCR)
      - visual_reasoning_status
      - visual_reasoning_summary (the visual_summary field from Qwen output)
      - visual_reasoning_provider

    Never returns: frame_storage_path, raw bytes, signed URLs, access tokens.
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debug endpoint not available in production.",
        )
    _require_owned_session(db, user_id, session_id)

    try:
        resp = (
            db.table("workflow_visual_frame_evidence")
            .select(
                "id, frame_type, timestamp_ms, frame_width, frame_height, "
                "ocr_text, frame_storage_path, visual_reasoning_json, "
                "proof_session_id, frame_sha256, created_at"
            )
            .eq("proof_session_id", session_id)
            .eq("user_id", user_id)
            .eq("frame_type", "video_keyframe")
            .order("timestamp_ms", desc=False)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB query failed: {exc}",
        ) from exc

    rows = resp.data or []
    frames_debug: list[dict[str, Any]] = []

    for row in rows:
        vr_json = row.get("visual_reasoning_json")
        vr_status        = vr_json.get("status")        if isinstance(vr_json, dict) else None
        vr_visual_summary = vr_json.get("visual_summary") if isinstance(vr_json, dict) else None
        vr_provider      = vr_json.get("model_provider") if isinstance(vr_json, dict) else None
        vr_model         = vr_json.get("model_id")       if isinstance(vr_json, dict) else None
        vr_confidence    = vr_json.get("confidence_score") if isinstance(vr_json, dict) else None
        vr_supported     = (vr_json.get("supported_skills") or vr_json.get("detected_skills_supported")) \
                           if isinstance(vr_json, dict) else None

        ocr_raw = row.get("ocr_text")
        if isinstance(ocr_raw, list):
            # ocr_text is stored as [{"text": "..."}] by analyze_visual_frame
            parts: list[str] = []
            for item in ocr_raw[:3]:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", ""))[:60])
                else:
                    parts.append(str(item)[:60])
            ocr_preview: str | None = " | ".join(parts)[:120] or None
        elif isinstance(ocr_raw, str):
            ocr_preview = ocr_raw[:120]
        else:
            ocr_preview = None

        # frame_sha256: stored at upload time (migration 042).
        # frame_path_sha256_prefix: integrity check from storage path (pre-migration fallback).
        frame_sha256_val: str | None = row.get("frame_sha256")
        storage_path: str | None = row.get("frame_storage_path")
        frame_path_hash: str | None = None
        if storage_path:
            frame_path_hash = hashlib.sha256(storage_path.encode()).hexdigest()[:16]

        row_session_id = row.get("proof_session_id", "")
        frames_debug.append({
            "frame_id":                  row.get("id"),
            "proof_session_id":          row_session_id,
            "belongs_to_current_session": row_session_id == session_id,
            "frame_type":                row.get("frame_type"),
            "timestamp_ms":              row.get("timestamp_ms"),
            "timestamp_label":           f"{row['timestamp_ms'] / 1000:.1f}s"
                                         if row.get("timestamp_ms") is not None else None,
            "frame_width":               row.get("frame_width"),
            "frame_height":              row.get("frame_height"),
            "created_at":                row.get("created_at"),
            # Frame integrity — frame_sha256 is the SHA-256 of the raw bytes (migration 042),
            # frame_path_sha256_prefix is a fallback from the storage path.
            "frame_sha256":              frame_sha256_val,
            "frame_path_sha256_prefix":  frame_path_hash,
            "ocr_text_preview":          ocr_preview,
            "visual_reasoning_status":   vr_status,
            "visual_reasoning_summary":  vr_visual_summary,
            "visual_reasoning_provider": vr_provider,
            "visual_reasoning_model":    vr_model,
            "visual_reasoning_confidence": vr_confidence,
            "visual_reasoning_supported_skills": vr_supported,
        })

    # Summary line: how many frames have Qwen results vs. stale/missing
    analyzed_count  = sum(1 for f in frames_debug if f["visual_reasoning_status"] == "analyzed")
    stale_count     = sum(1 for f in frames_debug if f["visual_reasoning_status"] is None)

    return {
        "session_id":       session_id,
        "user_id":          user_id,
        "frame_count":      len(frames_debug),
        "qwen_analyzed":    analyzed_count,
        "qwen_missing":     stale_count,
        "frames":           frames_debug,
    }
