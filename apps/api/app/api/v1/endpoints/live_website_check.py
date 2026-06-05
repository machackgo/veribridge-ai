"""Extension Proof Live Website Check endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.live_website_check import (
    LiveWebsiteCheckRequest,
    LiveWebsiteCheckResponse,
    LiveWebsiteCheckStage,
)
from app.services.live_website_check_service import (
    LiveWebsiteCheckService,
    build_completed_stages,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/check/live-website",
    response_model=LiveWebsiteCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Run a live HTTP reachability check on the submitted website URL",
)
def run_live_website_check(
    session_id: str,
    body: LiveWebsiteCheckRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> LiveWebsiteCheckResponse:
    svc = LiveWebsiteCheckService(db)
    try:
        row = svc.run_check(
            user_id=user_id,
            session_id=session_id,
            website_url=body.website_url,
        )
    except Exception as exc:
        logger.exception(
            "POST check/live-website: unexpected error for session %s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Live website check failed unexpectedly."},
        ) from exc
    return _to_response(row)


@router.get(
    "/{session_id}/check/live-website",
    response_model=LiveWebsiteCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the latest live website check result for an extension proof session",
)
def get_live_website_check(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> LiveWebsiteCheckResponse:
    svc = LiveWebsiteCheckService(db)
    try:
        row = svc.get_latest(user_id=user_id, session_id=session_id)
    except Exception as exc:
        logger.exception(
            "GET check/live-website: unexpected error for session %s", session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to retrieve live website check."},
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "No live website check found for this session."},
        )
    return _to_response(row)


def _to_response(row: dict[str, Any]) -> LiveWebsiteCheckResponse:
    is_reachable = bool(row.get("is_reachable", False))
    check_status = str(row.get("status") or ("complete" if is_reachable else "failed"))
    stages = [LiveWebsiteCheckStage(**s) for s in build_completed_stages(is_reachable, check_status)]
    confidence = row.get("confidence", "failed")
    current_stage = "Not applicable" if check_status == "not_applicable" else "Complete" if is_reachable else "Failed"
    return LiveWebsiteCheckResponse(
        id=str(row.get("id", "")),
        proof_session_id=str(row.get("proof_session_id", "")),
        status=check_status,
        website_url=str(row.get("website_url", "")),
        final_url=row.get("final_url"),
        status_code=row.get("status_code"),
        response_time_ms=row.get("response_time_ms"),
        content_type=row.get("content_type"),
        page_title=row.get("page_title"),
        is_reachable=is_reachable,
        confidence=confidence,
        risk_flags=row.get("risk_flags") or [],
        recruiter_summary=str(row.get("recruiter_summary", "")),
        error_message=row.get("error_message"),
        checked_at=str(row.get("checked_at", "")),
        progress=100,
        current_stage=current_stage,
        stages=stages,
    )
