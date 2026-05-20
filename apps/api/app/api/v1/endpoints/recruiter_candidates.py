"""Recruiter candidate discovery endpoints (Phase J1)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user_id, get_db
from app.schemas.recruiter_candidate_search import CandidateSearchResponse
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
    _user_id: str = Depends(get_current_user_id),
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
