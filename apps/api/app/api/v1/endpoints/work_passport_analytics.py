"""Student Work Passport analytics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user_id, get_db
from app.schemas.work_passport_analytics import (
    WorkPassportActivityItem,
    WorkPassportAnalyticsResponse,
)
from app.services.work_passport_analytics_service import WorkPassportAnalyticsService

router = APIRouter()


@router.get(
    "/analytics",
    response_model=WorkPassportAnalyticsResponse,
    summary="Get Work Passport analytics for the current student",
)
def get_work_passport_analytics(
    proof_session_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportAnalyticsResponse:
    return WorkPassportAnalyticsService(db).get_student_passport_analytics(user_id, proof_session_id)


@router.get(
    "/analytics/activity",
    response_model=list[WorkPassportActivityItem],
    summary="Get Work Passport activity timeline for the current student",
)
def get_work_passport_activity(
    proof_session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[WorkPassportActivityItem]:
    return WorkPassportAnalyticsService(db).get_passport_activity_timeline(
        user_id,
        proof_session_id,
        limit=limit,
    )
