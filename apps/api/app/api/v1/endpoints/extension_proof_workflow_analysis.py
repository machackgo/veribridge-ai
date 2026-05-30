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

    stages_raw = _build_completed_stages(
        db_saved=db_saved,
        visible_evidence_status=raw_ve_status,
    )
    stages = [AnalysisStage(**s) for s in stages_raw]
    observed_demonstration = _parse_observed_demonstration(row.get("observed_demonstration"))
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
        visual_analysis_status=row.get("visual_analysis_status", "not_available"),
        visible_evidence_status=raw_ve_status,
        # ── Video keyframe evidence (Phase 0 unified recorder) ────────────────
        # Populated by _enrich_video_keyframes() live query — always current.
        video_keyframe_status=row.get("video_keyframe_status"),
        video_keyframe_count=int(row.get("video_keyframe_count", 0)),
        video_upload_error=row.get("video_upload_error"),
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
    """Live-query for video keyframe frames and inject status into the row dict.

    This is done at response time (not stored) so the status is always current
    even if the video was uploaded AFTER the analysis was run.

    Injects:
      video_keyframe_status: "extracted" | "failed" | None
      video_keyframe_count: int
      video_upload_error: str | None
    """
    try:
        resp = (
            db.table(_VF_TABLE)
            .select("id", count="exact")
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
            return {
                **row,
                "video_keyframe_status": "extracted",
                "video_keyframe_count": count,
                "video_upload_error": None,
            }

        # No keyframe records — video may not have been uploaded
        return {**row, "video_keyframe_status": None, "video_keyframe_count": 0, "video_upload_error": None}

    except Exception:
        logger.warning(
            "_enrich_video_keyframes: query failed for session %s — returning null status",
            session_id, exc_info=True,
        )
        return {**row, "video_keyframe_status": None, "video_keyframe_count": 0, "video_upload_error": None}


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )
