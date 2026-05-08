"""
Student profile endpoints.

Routes
------
GET  /api/v1/student/profile   — read the current student's profile
PUT  /api/v1/student/profile   — create or update the current student's profile

The "current student" is identified by ``get_current_user_id()``.
Until Supabase Auth is integrated, this resolves to ``DEMO_USER_ID``
from environment (default: ``00000000-0000-0000-0000-000000000001``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.student import StudentProfileResponse, StudentProfileUpsert
from app.services.student_service import StudentProfileService

router = APIRouter()


# ── GET /student/profile ──────────────────────────────────────────────────────


@router.get(
    "/profile",
    response_model=StudentProfileResponse,
    summary="Get student profile",
    description=(
        "Returns the authenticated student's profile. "
        "Returns 404 if no profile has been created yet — "
        "use PUT /student/profile to create one."
    ),
)
def get_student_profile(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> StudentProfileResponse:
    service = StudentProfileService(db)
    profile = service.get_profile(user_id)

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "student_profile_not_found",
                "message": (
                    "No profile found for this user. "
                    "Use PUT /api/v1/student/profile to create one."
                ),
                "user_id": user_id,
            },
        )

    return profile


# ── PUT /student/profile ──────────────────────────────────────────────────────


@router.put(
    "/profile",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update student profile",
    description=(
        "Upserts the authenticated student's profile. "
        "Idempotent — sending the same payload twice produces the same result."
    ),
)
def upsert_student_profile(
    body: StudentProfileUpsert,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> StudentProfileResponse:
    service = StudentProfileService(db)

    try:
        profile = service.upsert_profile(user_id, body)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "profile_upsert_failed",
                "message": str(exc),
            },
        )

    return profile
