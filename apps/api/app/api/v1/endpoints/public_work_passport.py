"""Public Work Passport and protected evidence access endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.public_work_passport import (
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestPublicResponse,
    AdminRequesterVerificationUpdate,
    EvidenceAccessGrantResponse,
    EvidenceAccessRequestResponse,
    ProtectedEvidenceResponse,
    PublicPassportSafeResponse,
    PublicWorkPassportCreateRequest,
    PublicWorkPassportStudentResponse,
    RecruiterRequesterProfileResponse,
)
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.public_work_passport_service import (
    EvidenceAccessDeniedError,
    EvidenceAccessGrantNotFoundError,
    EvidenceAccessRequestNotFoundError,
    PublicWorkPassportNotFoundError,
    PublicWorkPassportService,
    RecruiterRequesterProfileNotFoundError,
)

logger = logging.getLogger(__name__)

student_router = APIRouter()
access_router = APIRouter()
public_router = APIRouter()
admin_router = APIRouter()


@student_router.post(
    "/{session_id}/passport",
    response_model=PublicWorkPassportStudentResponse,
    summary="Create or update a public Work Passport for a proof session",
)
def create_or_update_passport(
    session_id: str,
    body: PublicWorkPassportCreateRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PublicWorkPassportStudentResponse:
    try:
        return PublicWorkPassportService(db).create_or_update_passport(user_id, session_id, body)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@student_router.get(
    "/{session_id}/passport",
    response_model=PublicWorkPassportStudentResponse,
    summary="Get the student's Work Passport for a proof session",
)
def get_student_passport(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PublicWorkPassportStudentResponse:
    try:
        return PublicWorkPassportService(db).get_student_passport(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@student_router.get(
    "/{session_id}/access-requests",
    response_model=list[EvidenceAccessRequestResponse],
    summary="List protected evidence access requests for a proof session",
)
def list_access_requests(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[EvidenceAccessRequestResponse]:
    try:
        return PublicWorkPassportService(db).list_access_requests(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@access_router.post(
    "/access-requests/{request_id}/approve",
    response_model=EvidenceAccessGrantResponse,
    summary="Approve a protected evidence access request",
)
def approve_access_request(
    request_id: str,
    body: AccessRequestDecision | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessGrantResponse:
    try:
        return PublicWorkPassportService(db).approve_request(user_id, request_id, body)
    except EvidenceAccessRequestNotFoundError as exc:
        raise _request_not_found(str(exc)) from exc


@access_router.post(
    "/access-requests/{request_id}/deny",
    response_model=EvidenceAccessRequestResponse,
    summary="Deny a protected evidence access request",
)
def deny_access_request(
    request_id: str,
    body: AccessRequestDecision | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessRequestResponse:
    try:
        return PublicWorkPassportService(db).deny_request(user_id, request_id, body)
    except EvidenceAccessRequestNotFoundError as exc:
        raise _request_not_found(str(exc)) from exc


@access_router.post(
    "/access-grants/{grant_id}/revoke",
    response_model=EvidenceAccessGrantResponse,
    summary="Revoke a protected evidence access grant",
)
def revoke_access_grant(
    grant_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> EvidenceAccessGrantResponse:
    try:
        return PublicWorkPassportService(db).revoke_grant(user_id, grant_id)
    except EvidenceAccessGrantNotFoundError as exc:
        raise _grant_not_found(str(exc)) from exc


@access_router.get(
    "/access-requesters",
    response_model=list[RecruiterRequesterProfileResponse],
    summary="List requester profiles linked to the student's evidence access requests",
)
def list_access_requesters(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[RecruiterRequesterProfileResponse]:
    return PublicWorkPassportService(db).list_access_requesters(user_id)


@public_router.get(
    "/passports/{public_slug}",
    response_model=PublicPassportSafeResponse,
    summary="Get a safe public Work Passport summary",
)
def get_public_passport(
    public_slug: str,
    request: Request,
    db: Any = Depends(get_db),
) -> PublicPassportSafeResponse:
    try:
        return PublicWorkPassportService(db).get_public_passport(public_slug, _viewer_context(request))
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.post(
    "/passports/{public_slug}/request-access",
    response_model=AccessRequestPublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request access to protected evidence for a public Work Passport",
)
def request_access(
    public_slug: str,
    body: AccessRequestCreate,
    db: Any = Depends(get_db),
) -> AccessRequestPublicResponse:
    try:
        return PublicWorkPassportService(db).create_access_request(public_slug, body)
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.get(
    "/access/{access_token}/evidence",
    response_model=ProtectedEvidenceResponse,
    summary="Get protected evidence for an approved access grant",
)
def get_protected_evidence(
    access_token: str,
    db: Any = Depends(get_db),
) -> ProtectedEvidenceResponse:
    try:
        return PublicWorkPassportService(db).get_protected_evidence(access_token)
    except EvidenceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "evidence_access_denied",
                "message": str(exc),
            },
        ) from exc


@admin_router.get(
    "/recruiter-requesters",
    response_model=list[RecruiterRequesterProfileResponse],
    summary="Admin: list recruiter/requester identity profiles",
)
def admin_list_recruiter_requesters(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Any = Depends(get_db),
) -> list[RecruiterRequesterProfileResponse]:
    return PublicWorkPassportService(db).admin_list_requester_profiles(limit=limit, offset=offset)


@admin_router.post(
    "/recruiter-requesters/{profile_id}/verification-status",
    response_model=RecruiterRequesterProfileResponse,
    summary="Admin: update requester verification status",
)
def admin_update_recruiter_requester_status(
    profile_id: str,
    body: AdminRequesterVerificationUpdate,
    db: Any = Depends(get_db),
) -> RecruiterRequesterProfileResponse:
    try:
        return PublicWorkPassportService(db).admin_update_requester_verification(profile_id, body)
    except RecruiterRequesterProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "recruiter_requester_profile_not_found",
                "message": "Recruiter requester profile was not found.",
                "requester_profile_id": str(exc),
            },
        ) from exc


def _viewer_context(request: Request) -> dict[str, Any]:
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = forwarded_for.split(",", 1)[0].strip() if forwarded_for else None
    if not ip_address and request.client:
        ip_address = request.client.host
    return {
        "viewer_type": "anonymous",
        "ip_address": ip_address,
        "user_agent": request.headers.get("user-agent"),
    }


def _session_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "extension_proof_session_not_found",
            "message": "Extension proof session not found for the current user.",
            "session_id": session_id,
        },
    )


def _passport_not_found(value: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "public_work_passport_not_found",
            "message": "Public Work Passport was not found.",
            "passport": value,
        },
    )


def _request_not_found(request_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "evidence_access_request_not_found",
            "message": "Evidence access request not found for the current user.",
            "request_id": request_id,
        },
    )


def _grant_not_found(grant_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "evidence_access_grant_not_found",
            "message": "Evidence access grant not found for the current user.",
            "grant_id": grant_id,
        },
    )
