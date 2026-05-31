"""Extension Proof Workflow Analysis endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.extension_proof_workflow_analysis import (
    AnalysisStage,
    DetectedResultValue,
    DemonstrationSkillEvidence,
    DemonstrationStep,
    ObservedDemonstration,
    WorkflowAnalyzeRequest,
    WorkflowAnalysisResponse,
    VisibleEvidenceStatus,
)
from app.services.extension_proof_workflow_analysis_service import (
    ExtensionProofWorkflowAnalysisService,
    InvalidAnalysisStateError,
    SessionNotFoundError,
    _build_completed_stages,
    _build_frame_ocr_evidence_summary,
)
from typing import Any

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/analyze/workflow",
    response_model=WorkflowAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze the recorded workflow evidence for an extension proof session",
)
def analyze_workflow(
    session_id: str,
    body: WorkflowAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkflowAnalysisResponse:
    svc = ExtensionProofWorkflowAnalysisService(db)
    try:
        row = svc.run_analysis(
            user_id=user_id,
            session_id=session_id,
            claimed_skills=body.claimed_skills,
            proof_objective=body.proof_objective,
            original_url=body.original_url,
            url_type=body.url_type,
            github_url=body.github_url,
        )
    except SessionNotFoundError as exc:
        raise _not_found(session_id) from exc
    except InvalidAnalysisStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "invalid_analysis_state",
                "message": str(exc),
                "session_id": session_id,
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "POST analyze/workflow: unexpected error for session %s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Workflow analysis failed unexpectedly."},
        ) from exc
    row = _enrich_video_keyframes(db, user_id, session_id, row)
    row = _enrich_frame_ocr_evidence(row)
    return _to_response(row)


@router.get(
    "/{session_id}/analysis/workflow",
    response_model=WorkflowAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the latest workflow analysis for an extension proof session",
)
def get_workflow_analysis(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkflowAnalysisResponse:
    svc = ExtensionProofWorkflowAnalysisService(db)
    try:
        row = svc.get_latest(user_id=user_id, session_id=session_id)
    except Exception as exc:
        logger.exception(
            "GET analysis/workflow: unexpected error for session %s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to retrieve workflow analysis."},
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No workflow analysis found for this session."},
        )
    row = _enrich_video_keyframes(db, user_id, session_id, row)
    row = _enrich_frame_ocr_evidence(row)
    return _to_response(row)


def _parse_observed_demonstration(raw: Any) -> ObservedDemonstration | None:
    """Safely parse the observed_demonstration dict from the service result."""
    if raw is None:
        return None
    if isinstance(raw, ObservedDemonstration):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        steps_raw = raw.get("steps") or []
        steps: list[DemonstrationStep] = []
        for s in steps_raw:
            if not isinstance(s, dict):
                continue
            result_vals = [
                DetectedResultValue(**rv) for rv in (s.get("detected_result_values") or [])
                if isinstance(rv, dict)
            ]
            skill_ev = [
                DemonstrationSkillEvidence(**se) for se in (s.get("skill_evidence") or [])
                if isinstance(se, dict)
            ]
            raw_evidence_source = s.get("evidence_source", "event_metadata")
            # Validate evidence_source value
            valid_sources = ("dom_snapshot", "event_metadata", "inferred_from_click")
            if raw_evidence_source not in valid_sources:
                raw_evidence_source = "event_metadata"

            steps.append(DemonstrationStep(
                step_number=int(s.get("step_number", 0)),
                timestamp_ms=s.get("timestamp_ms"),
                user_action=str(s.get("user_action", "")),
                observed_input=s.get("observed_input"),
                observed_output=s.get("observed_output"),
                visible_text_evidence=list(s.get("visible_text_evidence") or []),
                detected_result_values=result_vals,
                demonstrated_feature=str(s.get("demonstrated_feature", "")),
                skill_evidence=skill_ev,
                confidence=s.get("confidence", "medium"),
                needs_review=bool(s.get("needs_review", False)),
                evidence_source=raw_evidence_source,
            ))

        raw_vis_ev_status = raw.get("visible_evidence_status", "not_captured")
        valid_ve_statuses: tuple[VisibleEvidenceStatus, ...] = ("available", "partial", "not_captured")
        if raw_vis_ev_status not in valid_ve_statuses:
            raw_vis_ev_status = "not_captured"

        return ObservedDemonstration(
            target_app=str(raw.get("target_app", "")),
            visual_analysis_status=raw.get("visual_analysis_status", "not_available"),
            visible_evidence_status=raw_vis_ev_status,
            steps=steps,
            summary=str(raw.get("summary", "")),
            limitations=list(raw.get("limitations") or []),
        )
    except Exception:
        logger.warning("_parse_observed_demonstration: failed to parse", exc_info=True)
        return None


def _to_response(row: dict[str, Any]) -> WorkflowAnalysisResponse:
    db_saved = bool(row.get("_db_saved", True))
    raw_ve_status = row.get("visible_evidence_status", "not_captured")
    valid_ve: tuple[Any, ...] = ("available", "partial", "not_captured")
    if raw_ve_status not in valid_ve:
        raw_ve_status = "not_captured"

    # ── Fix observed_demonstration limitations when video keyframes exist ──────
    # The analysis service sets "Visual frame analysis is not configured" at
    # analysis time (before the video is typically uploaded).  When keyframes ARE
    # extracted we replace that message with a more accurate one that acknowledges
    # the video evidence while still explaining OCR is not configured.
    video_kf_status = row.get("video_keyframe_status")
    video_kf_count  = int(row.get("video_keyframe_count", 0))
    visual_status   = row.get("visual_analysis_status", "not_configured")
    raw_demo = row.get("observed_demonstration")
    if isinstance(raw_demo, dict):
        raw_lims = list(raw_demo.get("limitations") or [])
        new_lims: list[str] = []
        replaced = False

        if video_kf_status == "not_available":
            # Video was uploaded but cv2/ffmpeg are not installed — replace the generic
            # "not_configured" limitation with a precise message.
            for lim in raw_lims:
                if "VISUAL_ANALYSIS_PROVIDER" in lim or "Visual frame analysis is not configured" in lim:
                    if not replaced:
                        new_lims.append(
                            "Video was recorded but keyframe extraction is not available.  "
                            "Install opencv-python-headless (pip install opencv-python-headless) "
                            "or ffmpeg (brew install ffmpeg) to enable frame extraction.  "
                            "Verification is based on recording metadata, browser events, and "
                            "DOM/visible evidence where available."
                        )
                        replaced = True
                else:
                    new_lims.append(lim)
        elif (
            video_kf_status == "extracted"
            and visual_status in ("not_configured", "not_available")
        ):
            # Keyframes extracted but OCR not configured.
            for lim in raw_lims:
                if "VISUAL_ANALYSIS_PROVIDER" in lim or "Visual frame analysis is not configured" in lim:
                    if not replaced:
                        kf_str = f"{video_kf_count} keyframe{'s' if video_kf_count != 1 else ''}"
                        new_lims.append(
                            f"Video was recorded and {kf_str} extracted, but OCR/visual model "
                            "analysis is not configured.  Verification is based on recording "
                            "metadata, browser events, DOM/visible evidence where available, and "
                            "sequence timing.  "
                            "Set VISUAL_ANALYSIS_PROVIDER=local_ocr or local_vision to enable "
                            "frame analysis."
                        )
                        replaced = True
                else:
                    new_lims.append(lim)
        else:
            new_lims = raw_lims

        if replaced or new_lims != raw_lims:
            row = {**row, "observed_demonstration": {**raw_demo, "limitations": new_lims}}

    stages_raw = _build_completed_stages(
        db_saved=db_saved,
        visible_evidence_status=raw_ve_status,
    )
    stages = [AnalysisStage(**s) for s in stages_raw]
    observed_demonstration = _parse_observed_demonstration(row.get("observed_demonstration"))
    # ── Derive video_upload_status from keyframe status ───────────────────────
    _kf_status = row.get("video_keyframe_status")
    _video_upload_status: str
    if _kf_status == "extracted":
        _video_upload_status = "uploaded"
    elif _kf_status == "not_available":
        # Video was received but cv2/ffmpeg not installed — still show as uploaded
        _video_upload_status = "uploaded"
    elif _kf_status == "failed":
        _video_upload_status = "failed"
    else:
        _video_upload_status = "none"

    # ── Sequence analysis (v6) — pass through raw dict from service/DB ────────
    # The service stores it as a jsonb dict (to_public_dict() output).
    # None is safe — the frontend treats it as "not available".
    _seq_analysis = row.get("sequence_analysis") or None
    if isinstance(_seq_analysis, dict) and not _seq_analysis:
        _seq_analysis = None   # treat empty dict same as None

    return WorkflowAnalysisResponse(
        id=str(row.get("id", "")),
        proof_session_id=str(row.get("proof_session_id", "")),
        analysis_type=row.get("analysis_type", "timeline_only"),
        analyzer_version=str(row.get("analyzer_version", "")),
        workflow_summary=str(row.get("workflow_summary", "")),
        demonstrated_actions=row.get("demonstrated_actions") or [],
        supported_skills=row.get("supported_skills") or [],
        weakly_supported_skills=row.get("weakly_supported_skills") or [],
        unsupported_skills=row.get("unsupported_skills") or [],
        evidence_strength_score=int(row.get("evidence_strength_score", 0)),
        workflow_confidence=row.get("workflow_confidence", "insufficient"),
        missing_evidence=row.get("missing_evidence") or [],
        risk_flags=row.get("risk_flags") or [],
        recruiter_summary=str(row.get("recruiter_summary", "")),
        student_improvement_suggestions=row.get("student_improvement_suggestions") or [],
        human_review_needed=bool(row.get("human_review_needed", False)),
        target_website=str(row.get("target_website", "")),
        target_site_pages_count=int(row.get("target_site_pages_count", 0)),
        supporting_evidence_count=int(row.get("supporting_evidence_count", 0)),
        noise_filtered_count=int(row.get("noise_filtered_count", 0)),
        observed_demonstration=observed_demonstration,
        visual_analysis_status=row.get("visual_analysis_status", "not_configured"),
        visible_evidence_status=raw_ve_status,
        # ── Sequence analysis (v6 — Week 3) ───────────────────────────────────
        sequence_analysis=_seq_analysis,
        # ── Video keyframe evidence (Phase 0 unified recorder) ────────────────
        # Populated by _enrich_video_keyframes() live query — always current.
        video_upload_status=_video_upload_status,
        video_keyframe_status=row.get("video_keyframe_status"),
        video_keyframe_count=int(row.get("video_keyframe_count", 0)),
        video_keyframe_timestamps_ms=list(row.get("video_keyframe_timestamps_ms") or []),
        video_duration_ms=row.get("video_duration_ms"),
        video_upload_error=row.get("video_upload_error"),
        # ── Frame OCR evidence summary (v6 — computed by _enrich_frame_ocr_evidence) ─
        # Safe to expose: never includes raw frame paths, storage URLs, or tokens.
        frame_ocr_evidence_summary=_safe_frame_ocr_summary(row.get("frame_ocr_evidence_summary")),
        progress=100,
        current_stage="AI reviewed",
        stages=stages,
        analysis_stage="complete",
        progress_percent=100,
        created_at=str(row.get("created_at", "")),
        updated_at=row.get("updated_at"),
    )


# ── Video keyframe enrichment ──────────────────────────────────────────────────

_VF_TABLE = "workflow_visual_frame_evidence"


def _enrich_video_keyframes(
    db: Any,
    user_id: str,
    session_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Live-query for video keyframe frames and inject status/metadata into the row dict.

    Done at response time (not stored) so the status is always current even if
    the video was uploaded AFTER the analysis was run.

    Injects:
      video_keyframe_status:       "extracted" | None
      video_keyframe_count:        int
      video_keyframe_timestamps_ms: list[int]  — timestamps from each stored frame
      video_duration_ms:           int | None  — derived from max timestamp (approximate)
      video_upload_error:          str | None
    """
    try:
        resp = (
            db.table(_VF_TABLE)
            .select("id,timestamp_ms", count="exact")
            .eq("user_id", user_id)
            .eq("proof_session_id", session_id)
            .eq("frame_type", "video_keyframe")
            .execute()
        )
        # Supabase returns count in resp.count when count="exact" is set
        count: int = 0
        if hasattr(resp, "count") and resp.count is not None:
            count = int(resp.count)
        elif resp.data:
            count = len(resp.data)

        if count > 0:
            # Extract timestamps for the frontend "Video Keyframe Evidence" section
            timestamps: list[int] = sorted([
                int(r["timestamp_ms"])
                for r in (resp.data or [])
                if r.get("timestamp_ms") is not None
            ])
            # Approximate duration: last keyframe timestamp
            duration_ms: int | None = timestamps[-1] if timestamps else None

            return {
                **row,
                "video_keyframe_status": "extracted",
                "video_keyframe_count": count,
                "video_keyframe_timestamps_ms": timestamps,
                "video_duration_ms": duration_ms,
                "video_upload_error": None,
            }

        # No keyframe records — check for upload markers:
        #   "video_upload_marker"  → cv2/ffmpeg not installed
        #   "video_extract_failed" → installed but decode failed
        # Both mean a video WAS uploaded (so UI shows "Video uploaded" ✓).
        try:
            marker_resp = (
                db.table(_VF_TABLE)
                .select("id,frame_type", count="exact")
                .eq("user_id", user_id)
                .eq("proof_session_id", session_id)
                .in_("frame_type", ["video_upload_marker", "video_extract_failed"])
                .execute()
            )
            marker_rows = marker_resp.data or []
            marker_count = len(marker_rows)
        except Exception:
            # Fallback: try original single-type query (backward compat)
            try:
                marker_resp = (
                    db.table(_VF_TABLE)
                    .select("id", count="exact")
                    .eq("user_id", user_id)
                    .eq("proof_session_id", session_id)
                    .eq("frame_type", "video_upload_marker")
                    .execute()
                )
                marker_rows = []
                marker_count = (
                    int(marker_resp.count)
                    if hasattr(marker_resp, "count") and marker_resp.count is not None
                    else len(marker_resp.data or [])
                )
            except Exception:
                marker_rows = []
                marker_count = 0

        if marker_count > 0:
            # Determine precise error message based on marker type
            has_extract_failed = any(
                r.get("frame_type") == "video_extract_failed"
                for r in marker_rows
            )
            if has_extract_failed:
                upload_error = (
                    "Video was uploaded but keyframe extraction failed. "
                    "cv2 and ffmpeg are installed but could not decode this video. "
                    "The recording may use an unsupported codec or be corrupted. "
                    "Try recording in MP4 format instead of WebM."
                )
            else:
                upload_error = (
                    "Video was uploaded but keyframe extraction is not available. "
                    "Install opencv-python-headless (pip install opencv-python-headless) "
                    "or ffmpeg (brew install ffmpeg) to enable frame extraction."
                )

            return {
                **row,
                "video_keyframe_status": "not_available",
                "video_keyframe_count": 0,
                "video_keyframe_timestamps_ms": [],
                "video_duration_ms": None,
                "video_upload_error": upload_error,
            }

        # No video at all
        return {
            **row,
            "video_keyframe_status": None,
            "video_keyframe_count": 0,
            "video_keyframe_timestamps_ms": [],
            "video_duration_ms": None,
            "video_upload_error": None,
        }

    except Exception:
        logger.warning(
            "_enrich_video_keyframes: query failed for session %s — returning null status",
            session_id, exc_info=True,
        )
        return {
            **row,
            "video_keyframe_status": None,
            "video_keyframe_count": 0,
            "video_keyframe_timestamps_ms": [],
            "video_duration_ms": None,
            "video_upload_error": None,
        }


_OCR_PRIVATE_FIELDS = frozenset({
    "frame_storage_path", "frame_path", "storage_url", "signed_url",
    "access_token", "raw_dom", "debug_metadata", "admin_notes",
    "raw_frame", "frame_bytes",
})


def _safe_frame_ocr_summary(summary: Any) -> dict | None:
    """Return only public-safe fields from frame_ocr_evidence_summary.

    Strips any field whose name is in _OCR_PRIVATE_FIELDS.
    Returns None when input is not a dict.
    """
    if not isinstance(summary, dict):
        return None
    return {k: v for k, v in summary.items() if k not in _OCR_PRIVATE_FIELDS}


def _enrich_frame_ocr_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Compute frame_ocr_evidence_summary from existing row fields if not already set.

    The analysis service stores this in the result dict and (when the DB column
    exists) in the DB.  For sessions analysed before migration 040, the DB value
    is null, so we reconstruct from the visual_summary / visual_analysis_status
    columns that ARE always stored.

    Privacy: reconstructed dict never includes raw paths, storage URLs, or tokens.
    """
    # If already present and non-empty, use it directly
    existing = row.get("frame_ocr_evidence_summary")
    if isinstance(existing, dict) and existing:
        return row

    # Reconstruct visual_frame_observations from stored columns
    visual_status = row.get("visual_analysis_status", "not_configured")
    visual_provider = row.get("visual_analysis_provider", "none")
    visual_frame_count = int(row.get("visual_frame_count", 0))
    visual_summary = row.get("visual_summary", "") or ""

    vf_obs: dict[str, Any] = {
        "visual_frame_analysis_status": visual_status,
        "provider_used": visual_provider,
        "visual_frame_count": visual_frame_count,
        "visual_summary": visual_summary,
    }

    # Reconstruct claimed_skills from stored skill lists
    claimed_skills: list[str] = (
        list(row.get("supported_skills") or [])
        + list(row.get("weakly_supported_skills") or [])
        + list(row.get("unsupported_skills") or [])
    )

    summary = _build_frame_ocr_evidence_summary(vf_obs, claimed_skills)
    return {**row, "frame_ocr_evidence_summary": summary}


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )
