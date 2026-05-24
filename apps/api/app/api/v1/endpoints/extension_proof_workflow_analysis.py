"""Extension Proof Workflow Analysis endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.extension_proof_workflow_analysis import (
    WorkflowAnalyzeRequest,
    WorkflowAnalysisResponse,
)
from app.services.extension_proof_workflow_analysis_service import (
    ExtensionProofWorkflowAnalysisService,
    InvalidAnalysisStateError,
    SessionNotFoundError,
)

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
    return _to_response(row)


def _to_response(row: dict[str, Any]) -> WorkflowAnalysisResponse:
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
        created_at=str(row.get("created_at", "")),
        updated_at=row.get("updated_at"),
    )


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )
