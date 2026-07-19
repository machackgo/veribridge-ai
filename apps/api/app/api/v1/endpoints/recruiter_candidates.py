"""Recruiter candidate discovery endpoints (Phase J1 + J2)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_db, require_admin_or_university_admin_user_id
from app.schemas.recruiter_candidate_detail import RecruiterCandidateDetailResponse
from app.schemas.recruiter_candidate_search import CandidateSearchResponse
from app.services.recruiter_candidate_detail_service import (
    CandidateNotFoundError,
    RecruiterCandidateDetailService,
)
from app.services.recruiter_candidate_search_service import RecruiterCandidateSearchService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/search",
    response_model=CandidateSearchResponse,
    summary="Search for proof-backed candidates by skill or keyword",
)
def search_candidates(
    query: str = Query(default="", description="Skill name or keyword to search for"),
    _admin_user_id: str = Depends(require_admin_or_university_admin_user_id),
    db: Any = Depends(get_db),
) -> CandidateSearchResponse:
    try:
        results = RecruiterCandidateSearchService(db).search(query)
    except Exception:
        logger.exception("GET /recruiter/candidates/search: unexpected error")
        results = []

    return CandidateSearchResponse(
        query=query,
        results=results,
        result_count=len(results),
    )


@router.get(
    "/{candidate_user_id}/detail",
    response_model=RecruiterCandidateDetailResponse,
    summary="Get full proof-backed candidate detail for recruiter inspection",
)
def get_candidate_detail(
    candidate_user_id: str,
    _admin_user_id: str = Depends(require_admin_or_university_admin_user_id),
    db: Any = Depends(get_db),
) -> RecruiterCandidateDetailResponse:
    try:
        return RecruiterCandidateDetailService(db).get_candidate_detail(candidate_user_id)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    except Exception:
        logger.exception(
            "GET /recruiter/candidates/%s/detail: unexpected error", candidate_user_id
        )
        raise HTTPException(status_code=500, detail="Failed to load candidate detail.")
