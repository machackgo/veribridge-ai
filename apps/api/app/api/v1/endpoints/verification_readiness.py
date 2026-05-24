"""Verification Readiness Report endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.verification_readiness import VerificationReadinessReport
from app.services.extension_proof_github_analysis_service import (
    ExtensionProofGitHubAnalysisService,
)
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services.extension_proof_workflow_analysis_service import (
    ExtensionProofWorkflowAnalysisService,
)
from app.services.live_website_check_service import LiveWebsiteCheckService
from app.services.verification_readiness_service import compute_readiness_report
from app.services.workflow_privacy_scan_service import WorkflowPrivacyScanService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{session_id}/readiness",
    response_model=VerificationReadinessReport,
    summary="Get the verification readiness report for a proof session",
)
def get_verification_readiness(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VerificationReadinessReport:
    """
    Compute and return a Verification Readiness Report for a proof session.

    The report combines all available evidence (workflow analysis, live website
    check, GitHub analysis, privacy scan) into a 0–100 readiness score, readiness
    level, skill support breakdown, risk flags, and recommended next actions.

    This endpoint is project-agnostic — no hardcoded project names, URLs, or
    app types.  Returns the same schema for frontend apps, full-stack projects,
    ML models, portfolios, dashboards, and local-only apps.

    IMPORTANT: ``final_verification_status`` is NEVER "complete" — Final
    Verification completion requires a separate VeriBridge reviewer step.
    """
    # ── 1. Fetch and verify session ownership ─────────────────────────────
    try:
        session_row = ExtensionProofSessionService(db)._get_row(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": session_id,
            },
        ) from exc

    # ── 2. Gather all available evidence (failures are non-critical) ───────
    workflow_analysis: dict[str, Any] | None = None
    try:
        workflow_analysis = ExtensionProofWorkflowAnalysisService(db).get_latest(
            user_id, session_id
        )
    except Exception:
        logger.warning("Readiness: workflow analysis fetch failed for %s", session_id)

    live_check: dict[str, Any] | None = None
    try:
        live_check = LiveWebsiteCheckService(db).get_latest(user_id, session_id)
    except Exception:
        logger.warning("Readiness: live check fetch failed for %s", session_id)

    github_analysis: dict[str, Any] | None = None
    try:
        github_analysis = ExtensionProofGitHubAnalysisService(db).get_latest(
            user_id, session_id
        )
    except Exception:
        logger.warning("Readiness: github analysis fetch failed for %s", session_id)

    privacy_scan: dict[str, Any] | None = None
    try:
        privacy_scan = WorkflowPrivacyScanService(db).get_scan(user_id, session_id)
    except Exception:
        logger.warning("Readiness: privacy scan fetch failed for %s", session_id)

    # ── 3. Extract session metadata ────────────────────────────────────────
    website_url: str = str(session_row.get("website_url") or "")
    claimed_skills: list[str] = list(session_row.get("claimed_skills") or [])
    session_status: str = str(session_row.get("status") or "created")

    # ── 4. Compute and return the report ───────────────────────────────────
    result = compute_readiness_report(
        proof_session_id=session_id,
        session_status=session_status,
        website_url=website_url,
        claimed_skills=claimed_skills,
        workflow_analysis=workflow_analysis,
        live_check=live_check,
        github_analysis=github_analysis,
        privacy_scan=privacy_scan,
    )

    return VerificationReadinessReport(
        proof_session_id=result.proof_session_id,
        readiness_score=result.readiness_score,
        readiness_level=result.readiness_level,
        final_verification_status=result.final_verification_status,
        strongly_supported_skills=result.strongly_supported_skills,
        partially_supported_skills=result.partially_supported_skills,
        needs_more_evidence=result.needs_more_evidence,
        risk_flags=result.risk_flags,
        recommended_next_actions=result.recommended_next_actions,
        recruiter_summary=result.recruiter_summary,
        is_local_only=result.is_local_only,
        has_github_evidence=result.has_github_evidence,
        computed_at=result.computed_at,
    )
