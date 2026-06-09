"""Workflow Visible Evidence endpoints.

Accepts DOM-snapshot events captured by the browser extension during recording,
and provides a student-facing summary of captured evidence for debugging.

Endpoints:
  POST /{session_id}/workflow/visible-evidence
      → Submit a batch of visible evidence events (called by the extension).

  GET  /{session_id}/workflow/visible-evidence/summary
      → Student/admin debugging summary.  NOT exposed to recruiters.

Privacy:
  - Raw visible_text_blocks are stored privately (student-only RLS).
  - The summary endpoint is for student + admin debugging only.
  - Recruiter surfaces always use the processed WorkflowAnalysisResponse.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.workflow_visible_evidence import (
    VisibleEvidenceBatchRequest,
    VisibleEvidenceSummaryResponse,
)
from app.services.proof_target_resolver import resolve_target_domain
from app.services.workflow_visible_evidence_service import (
    WorkflowVisibleEvidenceService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/workflow/visible-evidence",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit visible DOM evidence captured during recording",
    description=(
        "Accepts a batch of DOM-snapshot events from the browser extension. "
        "Events are sanitized server-side and stored privately. "
        "This data enriches the subsequent workflow analysis."
    ),
)
def submit_visible_evidence(
    session_id: str,
    body: VisibleEvidenceBatchRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    logger.info(
        "[VisibleEvidence] endpoint hit | session_id=%s | user_id=%s | events_count=%d",
        session_id, user_id, len(body.events),
    )
    svc = WorkflowVisibleEvidenceService(db)
    try:
        result = svc.ingest(user_id=user_id, session_id=session_id, request=body)
        logger.info(
            "[VisibleEvidence] insert success | session_id=%s | events_stored=%d/%d",
            session_id, result.get("events_stored", 0), len(body.events),
        )
        return result
    except Exception as exc:
        logger.exception(
            "[VisibleEvidence] insert failure | session_id=%s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to store visible evidence events."},
        ) from exc


@router.get(
    "/{session_id}/workflow/visible-evidence/summary",
    response_model=VisibleEvidenceSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get visible evidence summary for a session (student/admin debug only)",
    description=(
        "Returns a public-safe summary of captured visible evidence events. "
        "This endpoint is for student debugging and VeriBridge admin use ONLY. "
        "Recruiters always use the processed /analysis/workflow endpoint instead."
    ),
)
def get_visible_evidence_summary(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VisibleEvidenceSummaryResponse:
    svc = WorkflowVisibleEvidenceService(db)
    try:
        # Resolve canonical target domain so unrelated titles/text are excluded
        # from events_summary (Supabase, GitHub, localhost, etc.).
        target_domain: str | None = None
        session = svc._get_session(user_id, session_id)
        if session:
            target_domain = resolve_target_domain(
                session.get("website_url") or "",
                session.get("proof_data") or {},
            )
        summary = svc.get_summary(
            user_id=user_id,
            session_id=session_id,
            target_domain=target_domain,
        )
        return summary
    except Exception as exc:
        logger.exception(
            "GET visible-evidence/summary: unexpected error for session %s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to retrieve visible evidence summary."},
        ) from exc
