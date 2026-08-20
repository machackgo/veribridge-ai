"""Recruiter Talent Pool endpoints (migration 070).

Authenticated with the standard Supabase JWT and mounted at
``/api/v1/recruiter/pools``. Pools are recruiter-isolated (foreign ids are
indistinguishable from missing); candidate identity and evidence context
are resolved live and fail-closed on every load.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Any

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_talent_pools import (
    AddPoolCandidatesRequest,
    AddPoolCandidatesResponse,
    CreateTalentPoolRequest,
    PoolCandidateResponse,
    PoolMembershipsResponse,
    RemovePoolCandidateResponse,
    TalentPoolDeleteResponse,
    TalentPoolDetailResponse,
    TalentPoolListResponse,
    TalentPoolResponse,
    UpdatePoolCandidateRequest,
    UpdateTalentPoolRequest,
)
from app.services.recruiter_talent_pool_service import (
    PoolError,
    PoolNotFound,
    add_pool_candidates,
    create_pool,
    delete_pool,
    list_pool_candidates,
    list_pools,
    pool_memberships,
    remove_pool_candidate,
    update_pool,
    update_pool_candidate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _not_found() -> HTTPException:
    # One generic 404 for missing AND foreign pools — indistinguishable.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "pool_not_found", "message": "This Talent Pool was not found."},
    )


def _pool_error(exc: PoolError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "candidate_not_found"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "",
    response_model=TalentPoolResponse,
    summary="Create a Talent Pool",
)
def create_pool_route(
    payload: CreateTalentPoolRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolResponse:
    try:
        view = create_pool(
            db, str(user_id), name=payload.name, description=payload.description
        )
    except PoolError as exc:
        raise _pool_error(exc)
    return TalentPoolResponse(pool=view)


@router.get(
    "",
    response_model=TalentPoolListResponse,
    summary="List the caller's Talent Pools (most recently updated first)",
)
def list_pools_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolListResponse:
    return TalentPoolListResponse(**list_pools(db, str(user_id)))


# Static route — MUST be declared before /{pool_id}.
@router.get(
    "/memberships",
    response_model=PoolMembershipsResponse,
    summary="Which of the caller's pools each candidate belongs to",
)
def pool_memberships_route(
    student_user_ids: str = Query(
        default="", description="Comma-separated stable candidate user ids."
    ),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PoolMembershipsResponse:
    wanted = [s.strip() for s in str(student_user_ids or "").split(",") if s.strip()]
    return PoolMembershipsResponse(
        memberships=pool_memberships(db, str(user_id), wanted)
    )


@router.get(
    "/{pool_id}",
    response_model=TalentPoolDetailResponse,
    summary="Load one Talent Pool with its live candidate cards",
)
def get_pool_route(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolDetailResponse:
    try:
        payload = list_pool_candidates(db, str(user_id), pool_id)
    except PoolNotFound:
        raise _not_found()
    return TalentPoolDetailResponse(**payload)


@router.patch(
    "/{pool_id}",
    response_model=TalentPoolResponse,
    summary="Update name / description / archived status",
)
def update_pool_route(
    pool_id: str,
    payload: UpdateTalentPoolRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolResponse:
    sent = payload.model_fields_set
    try:
        view = update_pool(
            db,
            str(user_id),
            pool_id,
            name=payload.name if "name" in sent else ...,
            description=payload.description if "description" in sent else ...,
            clear_description=payload.clear_description,
            status=payload.status if "status" in sent else ...,
        )
    except PoolNotFound:
        raise _not_found()
    except PoolError as exc:
        raise _pool_error(exc)
    return TalentPoolResponse(pool=view)


@router.delete(
    "/{pool_id}",
    response_model=TalentPoolDeleteResponse,
    summary="Delete one of the caller's own Talent Pools",
)
def delete_pool_route(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolDeleteResponse:
    if not delete_pool(db, str(user_id), pool_id):
        raise _not_found()
    return TalentPoolDeleteResponse(deleted=True)


@router.post(
    "/{pool_id}/candidates",
    response_model=AddPoolCandidatesResponse,
    summary="Add candidates to the pool (idempotent)",
)
def add_pool_candidates_route(
    pool_id: str,
    payload: AddPoolCandidatesRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> AddPoolCandidatesResponse:
    try:
        result = add_pool_candidates(
            db,
            str(user_id),
            pool_id,
            candidate_slugs=payload.candidate_slugs,
            connection_ids=payload.connection_ids,
            student_user_ids=payload.student_user_ids,
            source=payload.source,
        )
    except PoolNotFound:
        raise _not_found()
    except PoolError as exc:
        raise _pool_error(exc)
    return AddPoolCandidatesResponse(**result)


@router.patch(
    "/{pool_id}/candidates/{student_user_id}",
    response_model=PoolCandidateResponse,
    summary="Update a pool member's recruiter-private note",
)
def update_pool_candidate_route(
    pool_id: str,
    student_user_id: str,
    payload: UpdatePoolCandidateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PoolCandidateResponse:
    sent = payload.model_fields_set
    try:
        view = update_pool_candidate(
            db,
            str(user_id),
            pool_id,
            student_user_id,
            note=payload.note if "note" in sent else ...,
            clear_note=payload.clear_note,
        )
    except PoolNotFound:
        raise _not_found()
    except PoolError as exc:
        raise _pool_error(exc)
    return PoolCandidateResponse(candidate=view)


@router.delete(
    "/{pool_id}/candidates/{student_user_id}",
    response_model=RemovePoolCandidateResponse,
    summary="Remove a candidate from the pool",
)
def remove_pool_candidate_route(
    pool_id: str,
    student_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> RemovePoolCandidateResponse:
    if not remove_pool_candidate(db, str(user_id), pool_id, student_user_id):
        raise _not_found()
    return RemovePoolCandidateResponse(removed=True)


__all__ = ["router"]
