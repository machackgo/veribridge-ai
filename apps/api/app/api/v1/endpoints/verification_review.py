"""Verification Review endpoints.

Student endpoints:
  POST /student/extension-proof/sessions/{session_id}/submit-ai-review
    Submit proof session for VeriBridge AI review.
    Reads current readiness score + privacy scan from query param / body.

  GET  /student/extension-proof/sessions/{session_id}/review-status
    Return current AI + human review status for the session.

Admin endpoints (future reviewers):
  GET  /admin/verification-reviews
    List all submitted review requests.

  POST /admin/verification-reviews/{id}/decision
    Admin manually overrides the AI review decision.

  POST /admin/verification-reviews/{id}/invite-reviewer
    Admin invites a human reviewer (faculty/company/domain expert).
    Architecture-ready; not surfaced in MVP UI.

Wording enforced:
  - "ai_approved_for_sharing" is the correct AI approval status.
  - "human_verified" is NEVER set by these endpoints; only by human_review_assignments.
  - admin/decision endpoint cannot set human_review_status = human_verified.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.verification_review import (
    AdminDecisionRequest,
    AdminReviewListItem,
    VerificationReviewResponse,
)
from app.services.verification_review_service import (
    VerificationReviewDuplicateError,
    VerificationReviewNotFoundError,
    VerificationReviewService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Student: submit for AI review ─────────────────────────────────────────────


@router.post(
    "/{session_id}/submit-ai-review",
    response_model=VerificationReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit a proof session for VeriBridge AI review",
)
def submit_for_ai_review(
    session_id: str,
    readiness_score: int = Query(
        ...,
        ge=0,
        le=100,
        description=(
            "Current readiness score (0–100) from the Verification Readiness Report. "
            "The frontend reads this from the already-computed report."
        ),
    ),
    readiness_level: str = Query(
        ...,
        description="Readiness level from the report: strong | moderate | weak | insufficient",
    ),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VerificationReviewResponse:
    """Submit the proof session for VeriBridge AI review.

    The backend reads the existing privacy scan result for this session and
    applies the AI decision rules:

    - readiness_score >= 80 AND privacy clean → ai_approved_for_sharing
    - readiness_score >= 60 AND privacy clean → manual_review_recommended
    - privacy flagged → privacy_flagged
    - otherwise → needs_more_evidence

    IMPORTANT: human_verified is NEVER set here.
    Re-submission is allowed when previous status was needs_more_evidence,
    manual_review_recommended, or privacy_flagged.
    """
    try:
        return VerificationReviewService(db).submit_for_ai_review(
            user_id=user_id,
            session_id=session_id,
            readiness_score=readiness_score,
            readiness_level=readiness_level,
        )
    except VerificationReviewDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "review_already_submitted",
                "message": str(exc),
                "session_id": session_id,
            },
        ) from exc
    except Exception as exc:
        logger.exception("POST submit-ai-review: unexpected error for %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "internal_error",
                "message": "An unexpected error occurred while submitting for AI review.",
            },
        ) from exc


# ── Student: get review status ─────────────────────────────────────────────────


@router.get(
    "/{session_id}/review-status",
    response_model=VerificationReviewResponse,
    summary="Get the current AI and human review status for a proof session",
)
def get_review_status(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> VerificationReviewResponse:
    """Return the current Track A (AI) and Track B (human) review status.

    Returns 404 if the student has not yet submitted for review.
    """
    try:
        return VerificationReviewService(db).get_review_status(user_id, session_id)
    except VerificationReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "review_not_found",
                "message": "No review request found for this session. Submit for AI review first.",
                "session_id": session_id,
            },
        ) from exc


# ── Admin: list all reviews ───────────────────────────────────────────────────

admin_router = APIRouter()


@admin_router.get(
    "",
    response_model=list[AdminReviewListItem],
    summary="Admin: list all verification review requests",
)
def admin_list_reviews(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Any = Depends(get_db),
) -> list[AdminReviewListItem]:
    """Return all review requests ordered by created_at desc.

    NOTE: In production this endpoint must be protected by admin/service-role
    authentication.  For MVP it shares the same JWT auth as student endpoints.
    """
    return VerificationReviewService(db).admin_list_reviews(limit=limit, offset=offset)


@admin_router.post(
    "/{review_id}/decision",
    response_model=VerificationReviewResponse,
    summary="Admin: manually override the AI review decision",
)
def admin_set_decision(
    review_id: str,
    body: AdminDecisionRequest,
    db: Any = Depends(get_db),
) -> VerificationReviewResponse:
    """Admin manually sets the AI review status.

    Allowed target statuses:
      ai_approved_for_sharing, needs_more_evidence, manual_review_recommended,
      privacy_flagged.

    IMPORTANT: This does NOT set human_review_status = human_verified.
    Human verification requires a real human reviewer completing their
    human_review_assignments row.
    """
    try:
        return VerificationReviewService(db).admin_set_decision(review_id, body)
    except VerificationReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "review_not_found",
                "message": str(exc),
            },
        ) from exc


@admin_router.post(
    "/{review_id}/invite-reviewer",
    status_code=status.HTTP_201_CREATED,
    summary="Admin: invite a human reviewer (faculty/company/domain expert)",
)
def admin_invite_reviewer(
    review_id: str,
    reviewer_email: str = Query(..., description="Reviewer email address"),
    reviewer_name: str = Query(..., description="Reviewer display name"),
    reviewer_role: str = Query(
        ...,
        description="veribridge_admin | faculty_reviewer | company_reviewer | domain_expert | recruiter_reviewer",
    ),
    reviewer_field: str = Query(default="", description="Field/domain (e.g. Machine Learning)"),
    db: Any = Depends(get_db),
) -> dict:
    """Invite a human reviewer to evaluate this review request.

    MVP: creates the assignment row; no actual email is sent yet.
    Future: will trigger reviewer notification and onboarding flow.

    WORDING: Once a reviewer completes their review and sets reviewer_decision
    to 'approved', the system may display:
      - 'Faculty Reviewed' (if reviewer_role = faculty_reviewer)
      - 'Company Reviewed' (if reviewer_role = company_reviewer)
      - 'Domain Expert Reviewed' (if reviewer_role = domain_expert)
    Only admin can then set human_review_status = 'human_verified'.
    """
    try:
        result = VerificationReviewService(db).admin_invite_reviewer(
            review_id=review_id,
            reviewer_email=reviewer_email,
            reviewer_name=reviewer_name,
            reviewer_role=reviewer_role,
            reviewer_field=reviewer_field,
        )
        return {
            "ok": True,
            "assignment_id": str(result["id"]),
            "message": f"Reviewer {reviewer_name} invited successfully. Assignment is pending.",
        }
    except Exception as exc:
        logger.exception("POST invite-reviewer: unexpected error for %s", review_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "internal_error", "message": str(exc)},
        ) from exc
