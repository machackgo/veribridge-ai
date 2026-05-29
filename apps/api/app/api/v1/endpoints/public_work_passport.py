"""Public Work Passport and protected evidence access endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import get_current_user_id, get_db, require_admin_user_id, require_recruiter_session
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
    RecruiterSessionCreate,
    RecruiterSessionResponse,
)
from app.schemas.github_proof_submission import GitHubProofPublicResponse
from app.schemas.recruiter_shortlist import (
    RecruiterReviewedSectionCreate,
    RecruiterSavedPassportCreate,
    RecruiterSavedPassportResponse,
    RecruiterSavedPassportUpdate,
)
from app.schemas.skill_evidence_timeline import SkillEvidenceTimelineResponse
from app.schemas.work_passport_status import PublicWorkPassportStatusResponse
from app.services.extension_proof_service import ExtensionProofSessionNotFoundError
from app.services.public_work_passport_service import (
    EvidenceAccessDeniedError,
    EvidenceAccessGrantNotFoundError,
    EvidenceAccessRequestNotFoundError,
    PublicWorkPassportNotFoundError,
    PublicWorkPassportService,
    RecruiterRequesterProfileNotFoundError,
)
from app.services.recruiter_session_service import RecruiterSessionService
from app.services.recruiter_shortlist_service import (
    RecruiterSavedPassportNotFoundError,
    RecruiterShortlistService,
)
from app.services.github_proof_service import GitHubProofService
from app.services.work_passport_export_service import WorkPassportExportService
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService
from app.services.work_passport_status_service import WorkPassportStatusService

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


@student_router.post(
    "/{session_id}/export",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a student Work Passport export",
)
def create_student_export(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    try:
        return WorkPassportExportService(db).build_student_export_payload(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc


@student_router.get(
    "/{session_id}/export/latest",
    response_model=dict[str, Any],
    summary="Get the latest student Work Passport export",
)
def get_latest_student_export(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    try:
        svc = WorkPassportExportService(db)
        svc._session_for_user(user_id, session_id)
        record = svc.get_latest_export_record(user_id, session_id)
    except ExtensionProofSessionNotFoundError as exc:
        raise _session_not_found(session_id) from exc
    if not record:
        raise _export_not_found(session_id)
    return record.get("export_payload") or {}


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


@public_router.post(
    "/passports/{public_slug}/save",
    response_model=RecruiterSavedPassportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save or shortlist a public Work Passport for a requester",
)
def save_public_passport(
    public_slug: str,
    body: RecruiterSavedPassportCreate,
    db: Any = Depends(get_db),
) -> RecruiterSavedPassportResponse:
    try:
        return RecruiterShortlistService(db).save_passport(public_slug, body)
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.get(
    "/passports/{public_slug}/status",
    response_model=PublicWorkPassportStatusResponse,
    summary="Get a safe public Work Passport status summary",
)
def get_public_passport_status(
    public_slug: str,
    db: Any = Depends(get_db),
) -> PublicWorkPassportStatusResponse:
    try:
        return WorkPassportStatusService(db).get_public_passport_status(public_slug)
    except ExtensionProofSessionNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.get(
    "/passports/{public_slug}/skill-evidence-timeline",
    response_model=SkillEvidenceTimelineResponse,
    summary="Get a public-safe skill evidence timeline for a Work Passport",
)
def get_public_skill_evidence_timeline(
    public_slug: str,
    db: Any = Depends(get_db),
) -> SkillEvidenceTimelineResponse:
    try:
        return SkillEvidenceTimelineService(db).get_public_skill_evidence_timeline(public_slug)
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.get(
    "/passports/{public_slug}/export",
    response_model=dict[str, Any],
    summary="Get a public-safe Work Passport export payload",
)
def get_public_passport_export(
    public_slug: str,
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    try:
        return WorkPassportExportService(db).build_public_export_payload(public_slug)
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.get(
    "/passports/{public_slug}/github-proofs",
    response_model=list[GitHubProofPublicResponse],
    summary="Get public-safe GitHub proof summaries for a public Work Passport",
)
def get_public_github_proofs(
    public_slug: str,
    db: Any = Depends(get_db),
) -> list[GitHubProofPublicResponse]:
    try:
        return GitHubProofService(db).get_public_github_proofs(public_slug)
    except PublicWorkPassportNotFoundError as exc:
        raise _passport_not_found(str(exc)) from exc


@public_router.post(
    "/recruiter/sessions",
    response_model=RecruiterSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recruiter session token for private recruiter operations",
)
def create_recruiter_session(
    body: RecruiterSessionCreate,
    db: Any = Depends(get_db),
) -> RecruiterSessionResponse:
    """Issue a server-side session token tied to *requester_email*.

    The returned ``session_token`` must be stored by the caller and supplied as
    the ``X-Recruiter-Token`` header on all private recruiter endpoints
    (saved-passports list / update / delete, candidate-comparisons list / get / archive).

    The token is cryptographically random (``vrec_<32-byte urlsafe>``) and
    expires after 30 days.  It is never stored in plaintext — only its
    SHA-256 hash is persisted in the database.
    """
    plaintext, email = RecruiterSessionService(db).create_session(str(body.requester_email))
    return RecruiterSessionResponse(session_token=plaintext, requester_email=email)


@public_router.get(
    "/recruiter/saved-passports",
    response_model=list[RecruiterSavedPassportResponse],
    summary="List saved Work Passports for the authenticated recruiter session",
)
def list_recruiter_saved_passports(
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> list[RecruiterSavedPassportResponse]:
    """Requires ``X-Recruiter-Token`` header from a valid recruiter session."""
    return RecruiterShortlistService(db).list_saved_passports(requester_email)


@public_router.patch(
    "/recruiter/saved-passports/{saved_id}",
    response_model=RecruiterSavedPassportResponse,
    summary="Update requester-private saved Work Passport metadata",
)
def update_recruiter_saved_passport(
    saved_id: str,
    body: RecruiterSavedPassportUpdate,
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> RecruiterSavedPassportResponse:
    """Requires ``X-Recruiter-Token`` header.  Only the owner session may update."""
    try:
        return RecruiterShortlistService(db).update_saved_passport(saved_id, body, requester_email)
    except RecruiterSavedPassportNotFoundError as exc:
        raise _saved_passport_not_found(str(exc)) from exc


@public_router.post(
    "/recruiter/saved-passports/{saved_id}/reviewed-sections",
    response_model=RecruiterSavedPassportResponse,
    summary="Record a reviewed evidence section for a saved Work Passport",
)
def record_saved_passport_reviewed_section(
    saved_id: str,
    body: RecruiterReviewedSectionCreate,
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> RecruiterSavedPassportResponse:
    """Requires ``X-Recruiter-Token`` header.  Email in body is ignored."""
    try:
        return RecruiterShortlistService(db).record_passport_reviewed_section(
            saved_id,
            requester_email,  # from validated session, never from untrusted body
            body.section,
        )
    except RecruiterSavedPassportNotFoundError as exc:
        raise _saved_passport_not_found(str(exc)) from exc


@public_router.delete(
    "/recruiter/saved-passports/{saved_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a requester-private saved Work Passport",
)
def delete_recruiter_saved_passport(
    saved_id: str,
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> Response:
    """Requires ``X-Recruiter-Token`` header.  Only the owner session may delete."""
    try:
        RecruiterShortlistService(db).delete_saved_passport(saved_id, requester_email)
    except RecruiterSavedPassportNotFoundError as exc:
        raise _saved_passport_not_found(str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@public_router.get(
    "/access/{access_token}/skill-evidence-timeline",
    response_model=SkillEvidenceTimelineResponse,
    summary="Get a grant-scoped protected skill evidence timeline",
)
def get_protected_skill_evidence_timeline(
    access_token: str,
    db: Any = Depends(get_db),
) -> SkillEvidenceTimelineResponse:
    try:
        return SkillEvidenceTimelineService(db).get_protected_skill_evidence_timeline(access_token)
    except EvidenceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "evidence_access_denied",
                "message": str(exc),
            },
        ) from exc


@public_router.get(
    "/access/{access_token}/export",
    response_model=dict[str, Any],
    summary="Get a protected recruiter Work Passport export payload",
)
def get_protected_passport_export(
    access_token: str,
    db: Any = Depends(get_db),
) -> dict[str, Any]:
    try:
        return WorkPassportExportService(db).build_protected_export_payload(access_token)
    except EvidenceAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "evidence_access_denied",
                "message": str(exc),
            },
        ) from exc


@public_router.get(
    "/access/{access_token}/github-proofs",
    response_model=list[GitHubProofPublicResponse],
    summary="Get GitHub proof summaries for an approved access grant",
)
def get_protected_github_proofs(
    access_token: str,
    db: Any = Depends(get_db),
) -> list[GitHubProofPublicResponse]:
    try:
        return GitHubProofService(db).get_protected_github_proofs(access_token)
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
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> list[RecruiterRequesterProfileResponse]:
    _ = admin_user_id
    return PublicWorkPassportService(db).admin_list_requester_profiles(limit=limit, offset=offset)


@admin_router.post(
    "/recruiter-requesters/{profile_id}/verification-status",
    response_model=RecruiterRequesterProfileResponse,
    summary="Admin: update requester verification status",
)
def admin_update_recruiter_requester_status(
    profile_id: str,
    body: AdminRequesterVerificationUpdate,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> RecruiterRequesterProfileResponse:
    _ = admin_user_id
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


def _export_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "work_passport_export_not_found",
            "message": "Work Passport export was not found for the current user.",
            "session_id": session_id,
        },
    )


def _saved_passport_not_found(saved_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "recruiter_saved_passport_not_found",
            "message": "Saved Work Passport was not found for the requester.",
            "saved_id": saved_id,
        },
    )
