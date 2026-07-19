"""
Student profile endpoints.

HTTP status contract
--------------------
200 — profile found (GET) or created/updated (PUT)
404 — profile does not exist (GET only)
409 — foreign-key error: demo user row missing in public.users
422 — request body failed Pydantic validation (PUT only)
503 — Supabase unreachable or returned an API error
500 — unexpected programming error (returns structured JSON, never plain text)

All error responses return JSON with at least:
  { "detail": { "code": "...", "message": "..." } }
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.db.supabase import SupabaseAPIError, SupabaseConnectionError, SupabaseFKError
from app.schemas.onboarding import (
    OnboardingCompleteResponse,
    OpportunityHeatmapResponse,
    StudentOnboardingResponse,
    StudentOnboardingUpsert,
)
from app.schemas.student import StudentProfileResponse, StudentProfileUpsert
from app.services.onboarding_service import OpportunityHeatmapService, StudentOnboardingService
from app.services.student_service import StudentProfileService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── GET /student/profile ──────────────────────────────────────────────────────


@router.get(
    "/profile",
    response_model=StudentProfileResponse,
    summary="Get student profile",
)
def get_student_profile(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> StudentProfileResponse:
    service = StudentProfileService(db)

    try:
        profile = service.get_profile(user_id)

    except (SupabaseConnectionError, SupabaseAPIError) as exc:
        logger.error("GET /student/profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": (
                    "The database is temporarily unavailable. "
                    "Check that SUPABASE_URL is correct and the project is not paused."
                ),
            },
        ) from exc

    except Exception as exc:
        # Catch-all: ensures we always return JSON, never plain-text 500.
        logger.exception("GET /student/profile: unexpected error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "internal_error",
                "message": "An unexpected error occurred. Check server logs.",
            },
        ) from exc

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "student_profile_not_found",
                "message": (
                    "No profile found. "
                    "Use PUT /api/v1/student/profile to create one."
                ),
                "user_id": user_id,
            },
        )

    return profile


# ── Universal onboarding + Career Graph ───────────────────────────────────────


@router.get(
    "/onboarding",
    response_model=StudentOnboardingResponse,
    summary="Get universal student onboarding profile",
)
def get_student_onboarding(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> StudentOnboardingResponse:
    return StudentOnboardingService(db).get_onboarding(user_id)


@router.put(
    "/onboarding",
    response_model=StudentOnboardingResponse,
    summary="Create or update universal student onboarding profile",
)
def upsert_student_onboarding(
    body: StudentOnboardingUpsert,
    # First-write flow: onboarding rows FK public.users — provision fresh users.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> StudentOnboardingResponse:
    return StudentOnboardingService(db).upsert_onboarding(user_id, body)


@router.post(
    "/onboarding/complete",
    response_model=OnboardingCompleteResponse,
    summary="Mark universal student onboarding complete",
)
def complete_student_onboarding(
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> OnboardingCompleteResponse:
    completed_at = StudentOnboardingService(db).mark_complete(user_id)
    return OnboardingCompleteResponse(
        user_id=user_id,
        completed=True,
        completed_at=completed_at,
    )


@router.get(
    "/opportunity-heatmap",
    response_model=OpportunityHeatmapResponse,
    summary="Get Opportunity & Salary Heatmap recommendations",
)
def get_opportunity_heatmap(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> OpportunityHeatmapResponse:
    onboarding = StudentOnboardingService(db)
    return OpportunityHeatmapService(onboarding).get_heatmap(user_id)


# ── PUT /student/profile ──────────────────────────────────────────────────────


@router.put(
    "/profile",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update student profile",
)
def upsert_student_profile(
    body: StudentProfileUpsert,
    # First-write flow: student_profiles FKs public.users — provision fresh users.
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> StudentProfileResponse:
    service = StudentProfileService(db)

    try:
        profile = service.upsert_profile(user_id, body)

    except SupabaseFKError as exc:
        logger.warning("PUT /student/profile: FK error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "user_not_found",
                "message": (
                    "The demo user row does not exist in public.users. "
                    "Call POST /api/v1/debug/bootstrap-demo-user first, then retry."
                ),
                "user_id": user_id,
            },
        ) from exc

    except (SupabaseConnectionError, SupabaseAPIError) as exc:
        logger.error("PUT /student/profile: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_unavailable",
                "message": (
                    "The database is temporarily unavailable. "
                    "Check that SUPABASE_URL is correct and the project is not paused."
                ),
            },
        ) from exc

    except RuntimeError as exc:
        logger.error("PUT /student/profile: upsert returned empty: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "profile_upsert_failed",
                "message": str(exc),
            },
        ) from exc

    except Exception as exc:
        logger.exception("PUT /student/profile: unexpected error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "internal_error",
                "message": "An unexpected error occurred. Check server logs.",
            },
        ) from exc

    return profile
