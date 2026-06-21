"""Verified Work Passport (v1) endpoints.

Owner-only (auth required, ownership enforced because ``get_db`` is the
service-role client):
  ``GET    /api/v1/student/vbr/passport``          — private evidence wallet
  ``GET    /api/v1/student/vbr/passport/status``   — publish status
  ``POST   /api/v1/student/vbr/passport/publish``  — publish / re-publish
  ``POST   /api/v1/student/vbr/passport/unpublish``— hide the public passport

Public (no auth, requires an actively published passport):
  ``GET    /api/v1/public/p/{public_slug}``        — recruiter-safe profile
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.schemas.vbr_work_passport import (
    PrivateWorkPassportResponse,
    PublicWorkPassportResponse,
    PublishPassportRequest,
    WorkPassportStatusResponse,
)
from app.services.vbr_work_passport_service import (
    build_private_passport,
    build_public_passport,
    get_passport_status,
    publish_passport,
    unpublish_passport,
)

student_router = APIRouter()
public_router = APIRouter()


@student_router.get(
    "/passport",
    response_model=PrivateWorkPassportResponse,
    summary="Get the current user's private Verified Work Passport",
)
def get_private_passport_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PrivateWorkPassportResponse:
    return PrivateWorkPassportResponse(**build_private_passport(db, pipeline_db, user_id))


@student_router.get(
    "/passport/status",
    response_model=WorkPassportStatusResponse,
    summary="Get the publish status of the current user's Work Passport",
)
def get_passport_status_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    return WorkPassportStatusResponse(**get_passport_status(db, user_id))


@student_router.post(
    "/passport/publish",
    response_model=WorkPassportStatusResponse,
    summary="Publish (or re-publish) the current user's public Work Passport",
)
def publish_passport_route(
    body: PublishPassportRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    payload = body or PublishPassportRequest()
    result = publish_passport(db, user_id, headline=payload.headline, summary=payload.summary)
    return WorkPassportStatusResponse(**result)


@student_router.post(
    "/passport/unpublish",
    response_model=WorkPassportStatusResponse,
    summary="Hide the current user's public Work Passport",
)
def unpublish_passport_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> WorkPassportStatusResponse:
    return WorkPassportStatusResponse(**unpublish_passport(db, user_id))


@public_router.get(
    "/p/{public_slug}",
    response_model=PublicWorkPassportResponse,
    summary="Get a published recruiter-safe Verified Work Passport (no auth required)",
)
def get_public_passport_route(
    public_slug: str,
    db: Any = Depends(get_db),
    pipeline_db: Any = Depends(get_pipeline_db),
) -> PublicWorkPassportResponse:
    return PublicWorkPassportResponse(**build_public_passport(db, pipeline_db, public_slug))
