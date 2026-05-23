"""Extension Proof GitHub Analysis endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.extension_proof_github_analysis import (
    ExtensionProofGitHubAnalyzeRequest,
    ExtensionProofGitHubAnalysisResponse,
)
from app.services.extension_proof_github_analysis_service import (
    ExtensionProofGitHubAnalysisService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/analyze/github",
    response_model=ExtensionProofGitHubAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a GitHub repository for an extension proof session",
)
def analyze_github(
    session_id: str,
    body: ExtensionProofGitHubAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofGitHubAnalysisResponse:
    svc = ExtensionProofGitHubAnalysisService(db)
    try:
        row = svc.run_analysis(
            user_id=user_id,
            session_id=session_id,
            github_url=body.github_url,
            claimed_skills=body.claimed_skills,
        )
    except Exception as exc:
        logger.exception("POST analyze/github: unexpected error for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "GitHub analysis failed unexpectedly."},
        ) from exc
    return _to_response(row)


@router.get(
    "/{session_id}/analysis/github",
    response_model=ExtensionProofGitHubAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the latest GitHub analysis for an extension proof session",
)
def get_github_analysis(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ExtensionProofGitHubAnalysisResponse:
    svc = ExtensionProofGitHubAnalysisService(db)
    try:
        row = svc.get_latest(user_id=user_id, session_id=session_id)
    except Exception as exc:
        logger.exception("GET analysis/github: unexpected error for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to retrieve GitHub analysis."},
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No GitHub analysis found for this session."},
        )
    return _to_response(row)


def _to_response(row: dict[str, Any]) -> ExtensionProofGitHubAnalysisResponse:
    return ExtensionProofGitHubAnalysisResponse(
        id=str(row.get("id", "")),
        proof_session_id=str(row.get("proof_session_id", "")),
        repo_url=str(row.get("repo_url", "")),
        status=row.get("status", "failed"),
        detected_stack=row.get("detected_stack") or [],
        detected_features=row.get("detected_features") or [],
        matched_claimed_skills=row.get("matched_claimed_skills") or [],
        missing_claimed_skills=row.get("missing_claimed_skills") or [],
        evidence_files=row.get("evidence_files") or [],
        confidence_score=float(row.get("confidence_score", 0.0)),
        warnings=row.get("warnings") or [],
        recruiter_summary=str(row.get("recruiter_summary", "")),
        created_at=str(row.get("created_at", "")),
        updated_at=row.get("updated_at"),
    )
