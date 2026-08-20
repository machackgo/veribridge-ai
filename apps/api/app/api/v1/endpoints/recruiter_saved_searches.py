"""Recruiter Saved Search endpoints (migration 070).

Authenticated with the standard Supabase JWT and mounted at
``/api/v1/recruiter/saved-searches``. Saved searches are recruiter-isolated
(foreign ids are indistinguishable from missing). Results are ALWAYS
recomputed live by the search engine — nothing here can serve evidence a
candidate has since unpublished; the persisted match rows only power the
"new / updated since last review" annotations.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_saved_searches import (
    CreateSavedSearchRequest,
    SavedSearchDeleteResponse,
    SavedSearchListResponse,
    SavedSearchResponse,
    SavedSearchResultsResponse,
    UpdateSavedSearchRequest,
)
from app.services.recruiter_saved_search_service import (
    SavedSearchError,
    SavedSearchNotFound,
    create_saved_search,
    delete_saved_search,
    get_saved_search_results,
    list_saved_searches,
    mark_reviewed,
    update_saved_search,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _not_found() -> HTTPException:
    # One generic 404 for missing AND foreign saved searches.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "saved_search_not_found",
            "message": "This saved search was not found.",
        },
    )


def _search_error(exc: SavedSearchError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "",
    response_model=SavedSearchResponse,
    summary="Save a recruiter search (parsed, baselined — nothing 'new' yet)",
)
def create_saved_search_route(
    payload: CreateSavedSearchRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchResponse:
    try:
        view = create_saved_search(
            db,
            str(user_id),
            q=payload.q,
            name=payload.name,
            filters=payload.filters.model_dump() if payload.filters else None,
        )
    except SavedSearchError as exc:
        raise _search_error(exc)
    return SavedSearchResponse(saved_search=view)


@router.get(
    "",
    response_model=SavedSearchListResponse,
    summary="List the caller's saved searches (stale active ones re-evaluate)",
)
def list_saved_searches_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchListResponse:
    return SavedSearchListResponse(**list_saved_searches(db, str(user_id)))


@router.get(
    "/{saved_search_id}",
    response_model=SavedSearchResultsResponse,
    summary="Live results + new/updated-evidence annotations",
)
def get_saved_search_route(
    saved_search_id: str,
    page: int = Query(default=1, ge=1),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchResultsResponse:
    try:
        payload = get_saved_search_results(
            db, str(user_id), saved_search_id, page=page
        )
    except SavedSearchNotFound:
        raise _not_found()
    return SavedSearchResultsResponse(**payload)


@router.patch(
    "/{saved_search_id}",
    response_model=SavedSearchResponse,
    summary="Rename / pause / resume / edit the query or filters",
)
def update_saved_search_route(
    saved_search_id: str,
    payload: UpdateSavedSearchRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchResponse:
    sent = payload.model_fields_set
    try:
        view = update_saved_search(
            db,
            str(user_id),
            saved_search_id,
            name=payload.name if "name" in sent else ...,
            status=payload.status if "status" in sent else ...,
            q=payload.q if "q" in sent else ...,
            filters=payload.filters.model_dump()
            if "filters" in sent and payload.filters is not None
            else ...,
        )
    except SavedSearchNotFound:
        raise _not_found()
    except SavedSearchError as exc:
        raise _search_error(exc)
    return SavedSearchResponse(saved_search=view)


@router.post(
    "/{saved_search_id}/review",
    response_model=SavedSearchResponse,
    summary="Mark the saved search reviewed (moves the 'new since' boundary)",
)
def mark_reviewed_route(
    saved_search_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchResponse:
    try:
        view = mark_reviewed(db, str(user_id), saved_search_id)
    except SavedSearchNotFound:
        raise _not_found()
    return SavedSearchResponse(saved_search=view)


@router.delete(
    "/{saved_search_id}",
    response_model=SavedSearchDeleteResponse,
    summary="Delete one of the caller's own saved searches",
)
def delete_saved_search_route(
    saved_search_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> SavedSearchDeleteResponse:
    if not delete_saved_search(db, str(user_id), saved_search_id):
        raise _not_found()
    return SavedSearchDeleteResponse(deleted=True)


__all__ = ["router"]
