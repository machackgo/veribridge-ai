"""Workflow Privacy Scan endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.workflow_privacy_scan import WorkflowPrivacyScanResponse
from app.services.extension_proof_service import (
    ExtensionProofSessionNotFoundError,
    ExtensionProofSessionService,
)
from app.services.workflow_privacy_scan_service import (
    WorkflowPrivacyScanService,
    scan_proof_data,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/{session_id}/privacy-scan",
    response_model=WorkflowPrivacyScanResponse,
    summary="Run or re-run the privacy scan on an uploaded proof session",
)
def run_privacy_scan(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkflowPrivacyScanResponse:
    """
    Run (or re-run) the privacy scan against the stored proof data for this session.

    The scan looks for unredacted sensitive patterns — API keys, tokens, PII, etc.
    It is project-agnostic and works for any website, local app, GitHub page, or dashboard.
    """
    try:
        session_service = ExtensionProofSessionService(db)
        row = session_service._get_row(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "session_not_found",
                "message": "Extension proof session not found for the current user.",
                "session_id": session_id,
            },
        ) from exc

    proof_data = row.get("proof_data") or {}
    scan_result = scan_proof_data(proof_data)

    scan_service = WorkflowPrivacyScanService(db)
    stored = scan_service.store_scan(user_id, session_id, scan_result)

    return WorkflowPrivacyScanResponse(
        id=str(stored.get("id") or ""),
        user_id=user_id,
        proof_session_id=session_id,
        status=scan_result.status,
        risk_flags=scan_result.risk_flags,
        redacted_fields_count=scan_result.redacted_fields_count,
        redacted_urls_count=scan_result.redacted_urls_count,
        contains_sensitive_data=scan_result.contains_sensitive_data,
        scan_summary=scan_result.scan_summary,
        created_at=str(stored.get("created_at") or ""),
        updated_at=str(stored.get("updated_at") or ""),
    )


@router.get(
    "/{session_id}/privacy-scan",
    response_model=WorkflowPrivacyScanResponse,
    summary="Get the stored privacy scan result for a proof session",
)
def get_privacy_scan(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkflowPrivacyScanResponse:
    """
    Retrieve the most recently stored privacy scan result for a session.
    Returns 404 if no scan has been run yet for this session.
    """
    scan_service = WorkflowPrivacyScanService(db)
    row = scan_service.get_scan(user_id, session_id)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "privacy_scan_not_found",
                "message": "No privacy scan result found for this session.",
                "session_id": session_id,
            },
        )

    return WorkflowPrivacyScanResponse(
        id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or user_id),
        proof_session_id=str(row.get("proof_session_id") or session_id),
        status=row.get("status") or "clean",
        risk_flags=row.get("risk_flags") or [],
        redacted_fields_count=int(row.get("redacted_fields_count") or 0),
        redacted_urls_count=int(row.get("redacted_urls_count") or 0),
        contains_sensitive_data=bool(row.get("contains_sensitive_data")),
        scan_summary=str(row.get("scan_summary") or ""),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )
