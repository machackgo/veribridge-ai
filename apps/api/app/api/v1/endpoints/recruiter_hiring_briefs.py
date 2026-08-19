"""Recruiter Hiring Brief endpoints (migration 068).

Authenticated with the standard Supabase JWT and mounted at
``/api/v1/recruiter/briefs``. Briefs are recruiter-isolated (foreign ids
are indistinguishable from missing); the comparison matrix and every
candidate evaluation are re-run from live public evidence on every load —
nothing here can serve evidence the candidate has since unpublished.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_hiring_briefs import (
    AddBriefCandidatesRequest,
    AddBriefCandidatesResponse,
    BriefCandidateResponse,
    BriefCandidatesResponse,
    BriefComparisonResponse,
    CreateHiringBriefRequest,
    HiringBriefDeleteResponse,
    HiringBriefListItem,
    HiringBriefListResponse,
    HiringBriefResponse,
    RemoveBriefCandidateResponse,
    UpdateBriefCandidateRequest,
    UpdateHiringBriefRequest,
)
from app.schemas.recruiter_search import RecruiterSearchResponse
from app.services.recruiter_hiring_brief_service import (
    BriefError,
    BriefNotFound,
    ComparisonError,
    add_brief_candidates,
    brief_comparison,
    brief_search,
    create_brief,
    delete_brief,
    get_brief,
    list_briefs,
    list_brief_candidates,
    remove_brief_candidate,
    update_brief,
    update_brief_candidate,
)
from app.services.recruiter_requirement_plan import (
    plan_from_requirements,
    plan_from_role_text,
)
from app.services.recruiter_search_service import (
    AVAILABILITY_VALUES,
    record_search_event,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _not_found() -> HTTPException:
    # One generic 404 for missing AND foreign briefs — indistinguishable.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "brief_not_found", "message": "This role was not found."},
    )


def _brief_error(exc: BriefError | ComparisonError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "candidate_not_found"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _plan_for(
    payload: CreateHiringBriefRequest | UpdateHiringBriefRequest,
) -> dict[str, Any] | None:
    """Edited chips win over natural language; both are deterministic."""
    if payload.requirements is not None:
        return plan_from_requirements(payload.requirements.model_dump())
    if payload.role_text is not None and payload.role_text.strip():
        return plan_from_role_text(payload.role_text)
    return None


def _record_brief_event(
    db: Any, user_id: str, action: str, *, count: int, role_text: Any = None
) -> None:
    """Coarse, privacy-safe analytics: counts + the recruiter's own role
    text only — never titles, notes, or candidate identity."""
    record_search_event(
        db,
        recruiter_user_id=user_id,
        q=str(role_text or "") or None,
        filters={"brief": action},
        result_count=count,
    )


@router.post(
    "",
    response_model=HiringBriefResponse,
    summary="Create a Hiring Brief from role text and/or edited requirements",
)
def create_brief_route(
    payload: CreateHiringBriefRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> HiringBriefResponse:
    plan = _plan_for(payload) or plan_from_requirements({})
    row = create_brief(
        db,
        str(user_id),
        plan=plan,
        title=payload.title,
        role_text=payload.role_text,
        status=payload.status,
    )
    view = get_brief(db, str(user_id), str(row["id"]))
    _record_brief_event(
        db, str(user_id), "created", count=0, role_text=payload.role_text
    )
    return HiringBriefResponse(brief=view)


@router.get(
    "",
    response_model=HiringBriefListResponse,
    summary="List the caller's Hiring Briefs (most recently updated first)",
)
def list_briefs_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> HiringBriefListResponse:
    items = [HiringBriefListItem(**view) for view in list_briefs(db, str(user_id))]
    return HiringBriefListResponse(briefs=items, total=len(items))


@router.get(
    "/{brief_id}",
    response_model=HiringBriefResponse,
    summary="Load one Hiring Brief with its evaluated requirement chips",
)
def get_brief_route(
    brief_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> HiringBriefResponse:
    try:
        view = get_brief(db, str(user_id), brief_id)
    except BriefNotFound:
        raise _not_found()
    return HiringBriefResponse(brief=view)


@router.patch(
    "/{brief_id}",
    response_model=HiringBriefResponse,
    summary="Update title / role text / requirements / lifecycle status",
)
def update_brief_route(
    brief_id: str,
    payload: UpdateHiringBriefRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> HiringBriefResponse:
    sent = payload.model_fields_set
    try:
        view = update_brief(
            db,
            str(user_id),
            brief_id,
            plan=_plan_for(payload),
            title=payload.title if "title" in sent else ...,
            role_text=payload.role_text if "role_text" in sent else ...,
            status=payload.status if "status" in sent else ...,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    _record_brief_event(
        db, str(user_id), "updated", count=0, role_text=payload.role_text
    )
    return HiringBriefResponse(brief=view)


@router.delete(
    "/{brief_id}",
    response_model=HiringBriefDeleteResponse,
    summary="Delete one of the caller's own Hiring Briefs",
)
def delete_brief_route(
    brief_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> HiringBriefDeleteResponse:
    if not delete_brief(db, str(user_id), brief_id):
        raise _not_found()
    return HiringBriefDeleteResponse(deleted=True)


# ── Role-scoped candidate pool ───────────────────────────────────────────────


@router.get(
    "/{brief_id}/candidates",
    response_model=BriefCandidatesResponse,
    summary="The brief's candidate pool with live requirement evaluation",
)
def list_brief_candidates_route(
    brief_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BriefCandidatesResponse:
    try:
        payload = list_brief_candidates(db, str(user_id), brief_id)
    except BriefNotFound:
        raise _not_found()
    return BriefCandidatesResponse(**payload)


@router.post(
    "/{brief_id}/candidates",
    response_model=AddBriefCandidatesResponse,
    summary="Add saved or published candidates to the brief's pool",
)
def add_brief_candidates_route(
    brief_id: str,
    payload: AddBriefCandidatesRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> AddBriefCandidatesResponse:
    try:
        result = add_brief_candidates(
            db,
            str(user_id),
            brief_id,
            connection_ids=payload.connection_ids,
            candidate_slugs=payload.candidate_slugs,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    _record_brief_event(
        db, str(user_id), "candidates_added", count=int(result["added"])
    )
    return AddBriefCandidatesResponse(**result)


@router.patch(
    "/{brief_id}/candidates/{student_user_id}",
    response_model=BriefCandidateResponse,
    summary="Update a candidate's ROLE-SCOPED status / private note",
)
def update_brief_candidate_route(
    brief_id: str,
    student_user_id: str,
    payload: UpdateBriefCandidateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BriefCandidateResponse:
    sent = payload.model_fields_set
    try:
        view = update_brief_candidate(
            db,
            str(user_id),
            brief_id,
            student_user_id,
            status=payload.status if "status" in sent else ...,
            note=payload.note if "note" in sent else ...,
            clear_note=payload.clear_note,
        )
    except BriefNotFound:
        raise _not_found()
    except BriefError as exc:
        raise _brief_error(exc)
    return BriefCandidateResponse(candidate=view)


@router.delete(
    "/{brief_id}/candidates/{student_user_id}",
    response_model=RemoveBriefCandidateResponse,
    summary="Remove a candidate from the brief's pool",
)
def remove_brief_candidate_route(
    brief_id: str,
    student_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> RemoveBriefCandidateResponse:
    if not remove_brief_candidate(db, str(user_id), brief_id, student_user_id):
        raise _not_found()
    return RemoveBriefCandidateResponse(removed=True)


# ── Comparison + brief-scoped search ─────────────────────────────────────────


@router.get(
    "/{brief_id}/comparison",
    response_model=BriefComparisonResponse,
    summary="Live evidence matrix over the brief's pool (never a score)",
)
def brief_comparison_route(
    brief_id: str,
    candidates: str | None = Query(
        default=None,
        description="Comma-separated pool candidate user ids (2–5); "
        "defaults to the pool's non-archived candidates.",
    ),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> BriefComparisonResponse:
    selected = [s.strip() for s in str(candidates or "").split(",") if s.strip()]
    try:
        result = brief_comparison(
            db,
            str(user_id),
            brief_id,
            candidate_user_ids=selected or None,
        )
    except BriefNotFound:
        raise _not_found()
    except (BriefError, ComparisonError) as exc:
        raise _brief_error(exc)
    _record_brief_event(
        db,
        str(user_id),
        "comparison",
        count=len(result["matrix"].get("columns") or []),
    )
    return BriefComparisonResponse(**result)


@router.get(
    "/{brief_id}/search",
    response_model=RecruiterSearchResponse,
    summary="Search candidates with the brief's stored requirement plan",
)
def brief_search_route(
    brief_id: str,
    q: str | None = Query(default=None, max_length=600),
    availability: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=20),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> RecruiterSearchResponse:
    availability_filter = (
        availability if availability in AVAILABILITY_VALUES else None
    )
    try:
        result = brief_search(
            db,
            str(user_id),
            brief_id,
            refine_text=q,
            availability=availability_filter,
            page=page,
            page_size=page_size,
        )
    except BriefNotFound:
        raise _not_found()
    _record_brief_event(
        db,
        str(user_id),
        "search",
        count=int(result.get("total") or 0),
        role_text=q,
    )
    return RecruiterSearchResponse(**result)


__all__ = ["router"]
