"""Project Defense Transcript Analysis endpoints.

POST /{session_id}/analyze/project-defense  — run the transcript analysis
GET  /{session_id}/analysis/project-defense — fetch the stored result
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.project_defense_analysis import (
    ProjectDefenseAnalyzeRequest,
    ProjectDefenseAnalysisResponse,
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
    # ── 1. Verify session ownership ────────────────────────────────────────────
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

    # ── 2. Run analysis ────────────────────────────────────────────────────────
    result = analyze_defense_transcript(
        transcript_text=body.transcript_text,
        claimed_skills=body.claimed_skills,
        proof_objective=body.proof_objective,
        workflow_summary=body.workflow_summary,
        github_summary=body.github_summary,
        live_check_summary=body.live_check_summary,
    )

    # ── 3. Persist ─────────────────────────────────────────────────────────────
    service = ProjectDefenseAnalysisService(db)
    stored = service.store_analysis(
        user_id=user_id,
        proof_session_id=session_id,
        video_url=body.video_url,
        transcript_text=body.transcript_text,
        result=result,
    )

    return ProjectDefenseAnalysisResponse(
        id=str(stored.get("id") or ""),
        user_id=user_id,
        proof_session_id=session_id,
        video_url=stored.get("video_url"),
        transcript_text=body.transcript_text,
        transcript_summary=result.transcript_summary,
        skills_mentioned=result.skills_mentioned,
        skills_explained_well=result.skills_explained_well,
        skills_missing_from_explanation=result.skills_missing_from_explanation,
        consistency_with_evidence_score=result.consistency_with_evidence_score,
        explanation_clarity_score=result.explanation_clarity_score,
        ownership_signal_score=result.ownership_signal_score,
        technical_depth_score=result.technical_depth_score,
        overall_defense_score=result.overall_defense_score,
        risk_flags=result.risk_flags,
        recruiter_summary=result.recruiter_summary,
        recommended_improvements=result.recommended_improvements,
        privacy_scan_status=result.privacy_scan_status,
        created_at=str(stored.get("created_at") or ""),
        updated_at=str(stored.get("updated_at") or ""),
    )


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

    return ProjectDefenseAnalysisResponse(
        id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or user_id),
        proof_session_id=str(row.get("proof_session_id") or session_id),
        video_url=row.get("video_url"),
        transcript_text=str(row.get("transcript_text") or ""),
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
