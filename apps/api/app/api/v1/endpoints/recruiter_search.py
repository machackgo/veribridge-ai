"""Recruiter Search & Discovery endpoints (v1).

Mounted at ``/api/v1/recruiter/search``. Authenticated with the standard
Supabase JWT (same policy as the connections API): candidate discovery is a
recruiter-product surface, so it requires a signed-in account — individual
public passports remain reachable by slug without auth, but bulk discovery
does not. This keeps enumeration behind a real identity.

Privacy: results come exclusively from the public-projection-derived search
index (see recruiter_search_service), re-validated live per request.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user_id, get_db
from app.schemas.recruiter_search import RecruiterSearchResponse
from app.services.recruiter_search_service import (
    AVAILABILITY_VALUES,
    DEFAULT_PAGE_SIZE,
    EVIDENCE_FILTERS,
    MAX_PAGE,
    MAX_PAGE_SIZE,
    MAX_QUERY_LENGTH,
    record_search_event,
    search_candidates,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _csv(value: str | None) -> list[str]:
    """Split a comma-separated query param into clean tokens."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@router.get(
    "",
    response_model=RecruiterSearchResponse,
    summary="Search the discoverable candidate population (public passports only)",
)
def search_candidates_route(
    q: str | None = Query(default=None, max_length=MAX_QUERY_LENGTH),
    skills: str | None = Query(
        default=None,
        max_length=400,
        description="Comma-separated skill names; candidates must match all.",
    ),
    evidence: str | None = Query(
        default=None,
        max_length=120,
        description=f"Comma-separated evidence filters from {EVIDENCE_FILTERS}.",
    ),
    availability: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> RecruiterSearchResponse:
    """Free-text + structured-filter search with deterministic, explainable
    ranking. Unknown evidence/availability values are ignored (never an
    error); every result links to the candidate's live public passport."""
    evidence_filter = [e for e in _csv(evidence) if e in EVIDENCE_FILTERS]
    availability_filter = availability if availability in AVAILABILITY_VALUES else None
    result = search_candidates(
        db,
        q=q,
        skills=_csv(skills),
        evidence=evidence_filter,
        availability=availability_filter,
        page=page,
        page_size=page_size,
    )
    # Coarse, best-effort observability — recruiter-authored inputs only.
    record_search_event(
        db,
        recruiter_user_id=str(user_id),
        q=q,
        filters={
            "skills": _csv(skills),
            "evidence": evidence_filter,
            "availability": availability_filter,
            "page": page if page > 1 else None,
        },
        result_count=int(result.get("total") or 0),
    )
    return RecruiterSearchResponse(**result)
