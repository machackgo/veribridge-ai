"""Recruiter talent pool endpoints (v2, migration 068).

Authenticated with the standard Supabase JWT and mounted at
``/api/v1/recruiter/pools``. Pools and memberships are recruiter-isolated;
candidates never see pool membership.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_talent_pools import (
    AddPoolMemberRequest,
    CreatePoolRequest,
    PoolDeleteResponse,
    TalentPool,
    TalentPoolListResponse,
)
from app.services.recruiter_talent_pool_service import (
    PoolError,
    PoolNotFound,
    add_member,
    create_pool,
    delete_pool,
    list_pools,
    remove_member,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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


def _pool_not_found() -> HTTPException:
    # One generic 404 for missing AND foreign pools — indistinguishable.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "pool_not_found", "message": "This pool was not found."},
    )


@router.post(
    "",
    response_model=TalentPool,
    summary="Create a talent pool (idempotent per name)",
)
def create_pool_route(
    payload: CreatePoolRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> TalentPool:
    try:
        return TalentPool(**create_pool(db, str(user_id), payload.name))
    except PoolError as exc:
        raise _pool_error(exc)


@router.get(
    "",
    response_model=TalentPoolListResponse,
    summary="List the caller's talent pools",
)
def list_pools_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPoolListResponse:
    pools = [TalentPool(**view) for view in list_pools(db, str(user_id))]
    return TalentPoolListResponse(pools=pools, total=len(pools))


@router.delete(
    "/{pool_id}",
    response_model=PoolDeleteResponse,
    summary="Delete one of the caller's own pools (members cascade)",
)
def delete_pool_route(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> PoolDeleteResponse:
    if not delete_pool(db, str(user_id), pool_id):
        raise _pool_not_found()
    return PoolDeleteResponse(deleted=True)


@router.post(
    "/{pool_id}/members",
    response_model=TalentPool,
    summary="Add one of the caller's saved candidates to their pool (idempotent)",
)
def add_member_route(
    pool_id: str,
    payload: AddPoolMemberRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPool:
    try:
        return TalentPool(
            **add_member(db, str(user_id), pool_id, payload.connection_id)
        )
    except PoolNotFound:
        raise _pool_not_found()
    except PoolError as exc:
        raise _pool_error(exc)


@router.delete(
    "/{pool_id}/members/{student_user_id}",
    response_model=TalentPool,
    summary="Remove a member from the caller's pool (idempotent)",
)
def remove_member_route(
    pool_id: str,
    student_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> TalentPool:
    try:
        return TalentPool(**remove_member(db, str(user_id), pool_id, student_user_id))
    except PoolNotFound:
        raise _pool_not_found()
