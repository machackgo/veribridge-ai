"""Public recruiter candidate comparison endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, require_recruiter_session
from app.schemas.recruiter_candidate_comparison import (
    RecruiterCandidateComparisonCreate,
    RecruiterCandidateComparisonResponse,
)
from app.services.recruiter_candidate_comparison_service import (
    RecruiterCandidateComparisonNotFoundError,
    RecruiterCandidateComparisonService,
)

router = APIRouter()


@router.post(
    "/candidate-comparisons",
    response_model=RecruiterCandidateComparisonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recruiter candidate comparison",
)
def create_candidate_comparison(
    body: RecruiterCandidateComparisonCreate,
    db: Any = Depends(get_db),
) -> RecruiterCandidateComparisonResponse:
    """Create is intentionally open (no session required) because the recruiter
    provides their email in the body and this is a low-risk write.  The email
    in the body is normalised and scoped server-side; private reads/mutations
    require a session token."""
    try:
        return RecruiterCandidateComparisonService(db).create_candidate_comparison(body)
    except RecruiterCandidateComparisonNotFoundError as exc:
        raise _comparison_not_found(str(exc)) from exc


@router.get(
    "/candidate-comparisons",
    response_model=list[RecruiterCandidateComparisonResponse],
    summary="List recruiter candidate comparisons for the authenticated recruiter session",
)
def list_candidate_comparisons(
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> list[RecruiterCandidateComparisonResponse]:
    """Requires ``X-Recruiter-Token`` header from a valid recruiter session."""
    return RecruiterCandidateComparisonService(db).list_candidate_comparisons(requester_email)


@router.get(
    "/candidate-comparisons/{comparison_id}",
    response_model=RecruiterCandidateComparisonResponse,
    summary="Get a recruiter candidate comparison",
)
def get_candidate_comparison(
    comparison_id: str,
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> RecruiterCandidateComparisonResponse:
    """Requires ``X-Recruiter-Token`` header.  Only the owner session may fetch."""
    try:
        return RecruiterCandidateComparisonService(db).get_candidate_comparison(comparison_id, requester_email)
    except RecruiterCandidateComparisonNotFoundError as exc:
        raise _comparison_not_found(str(exc)) from exc


@router.post(
    "/candidate-comparisons/{comparison_id}/archive",
    response_model=RecruiterCandidateComparisonResponse,
    summary="Archive a recruiter candidate comparison",
)
def archive_candidate_comparison(
    comparison_id: str,
    requester_email: str = Depends(require_recruiter_session),
    db: Any = Depends(get_db),
) -> RecruiterCandidateComparisonResponse:
    """Requires ``X-Recruiter-Token`` header.  Only the owner session may archive."""
    try:
        return RecruiterCandidateComparisonService(db).archive_candidate_comparison(comparison_id, requester_email)
    except RecruiterCandidateComparisonNotFoundError as exc:
        raise _comparison_not_found(str(exc)) from exc


def _comparison_not_found(comparison_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "recruiter_candidate_comparison_not_found",
            "message": "Recruiter candidate comparison was not found for the current requester.",
            "comparison_id": comparison_id,
        },
    )
