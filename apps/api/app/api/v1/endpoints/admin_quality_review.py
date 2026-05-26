"""Admin quality review / moderation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_db, require_admin_user_id
from app.schemas.admin_quality_review import (
    AdminQualityReviewCaseCreate,
    AdminQualityReviewCaseResponse,
    AdminQualityReviewCaseUpdate,
    AdminQualityReviewEventCreate,
    AdminQualityReviewEventResponse,
    AdminQualityReviewScanRequest,
    AdminQualityReviewScanResponse,
)
from app.services.admin_quality_review_service import (
    AdminQualityReviewCaseNotFoundError,
    AdminQualityReviewService,
)

router = APIRouter()


@router.get(
    "/cases",
    response_model=list[AdminQualityReviewCaseResponse],
    summary="Admin: list quality review cases",
)
def list_quality_review_cases(
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    case_type: str | None = None,
    user_id: str | None = None,
    proof_session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> list[AdminQualityReviewCaseResponse]:
    _ = admin_user_id
    return AdminQualityReviewService(db).list_quality_review_cases(
        status=status_filter,
        priority=priority,
        case_type=case_type,
        user_id=user_id,
        proof_session_id=proof_session_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/cases/{case_id}",
    response_model=AdminQualityReviewCaseResponse,
    summary="Admin: get a quality review case",
)
def get_quality_review_case(
    case_id: str,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> AdminQualityReviewCaseResponse:
    _ = admin_user_id
    try:
        return AdminQualityReviewService(db).get_quality_review_case(case_id)
    except AdminQualityReviewCaseNotFoundError as exc:
        raise _case_not_found(str(exc)) from exc


@router.post(
    "/cases",
    response_model=AdminQualityReviewCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a quality review case",
)
def create_quality_review_case(
    body: AdminQualityReviewCaseCreate,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> AdminQualityReviewCaseResponse:
    return AdminQualityReviewService(db).create_quality_review_case(body, actor_user_id=admin_user_id)


@router.patch(
    "/cases/{case_id}",
    response_model=AdminQualityReviewCaseResponse,
    summary="Admin: update a quality review case",
)
def update_quality_review_case(
    case_id: str,
    body: AdminQualityReviewCaseUpdate,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> AdminQualityReviewCaseResponse:
    try:
        return AdminQualityReviewService(db).update_quality_review_case(case_id, body, actor_user_id=admin_user_id)
    except AdminQualityReviewCaseNotFoundError as exc:
        raise _case_not_found(str(exc)) from exc


@router.post(
    "/cases/{case_id}/events",
    response_model=AdminQualityReviewEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a quality review event",
)
def add_quality_review_event(
    case_id: str,
    body: AdminQualityReviewEventCreate,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> AdminQualityReviewEventResponse:
    try:
        return AdminQualityReviewService(db).add_quality_review_event(
            case_id,
            body,
            actor_user_id=admin_user_id,
            actor_type="admin",
        )
    except AdminQualityReviewCaseNotFoundError as exc:
        raise _case_not_found(str(exc)) from exc


@router.post(
    "/scan",
    response_model=AdminQualityReviewScanResponse,
    summary="Admin: scan existing signals and create quality review cases",
)
def scan_quality_review_signals(
    body: AdminQualityReviewScanRequest | None = None,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> AdminQualityReviewScanResponse:
    _ = admin_user_id
    payload = body or AdminQualityReviewScanRequest()
    return AdminQualityReviewService(db).create_cases_from_existing_signals(
        user_id=payload.user_id,
        proof_session_id=payload.proof_session_id,
    )


def _case_not_found(case_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "admin_quality_review_case_not_found",
            "message": "Admin quality review case was not found.",
            "case_id": case_id,
        },
    )
