"""Recruiter ↔ candidate connection endpoints (v1).

Authenticated with the standard Supabase JWT — the recruiter is a real
verified user, unlike the legacy email-only ``X-Recruiter-Token`` surface.
Mounted at ``/api/v1/recruiter/connections``.

Uses ``get_provisioned_user_id`` on the write path: a recruiter's very first
action may be saving a candidate, so their ``public.users`` row must be
guaranteed before the FK'd insert.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_connections import (
    ConnectionDeleteResponse,
    ConnectionStatusResponse,
    RecruiterConnection,
    RecruiterConnectionListResponse,
    SaveCandidateRequest,
    SaveCandidateResponse,
)
from app.services.recruiter_connection_service import (
    PassportNotFound,
    connection_status,
    delete_connection,
    list_connections,
    save_candidate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _passport_not_found() -> HTTPException:
    # One generic 404 for unknown AND unpublished slugs — the save path must
    # not reveal more about a slug than the public passport GET does.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "passport_not_found",
            "message": "This passport is not available.",
        },
    )


@router.post(
    "",
    response_model=SaveCandidateResponse,
    summary="Save the owner of a published passport as a candidate (idempotent)",
)
def save_candidate_route(
    payload: SaveCandidateRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> SaveCandidateResponse:
    """Repeat saves of the same candidate return the existing connection with
    ``already_saved: true`` — never a duplicate, never an error."""
    try:
        view = save_candidate(
            db,
            str(user_id),
            payload.passport_slug,
            source=payload.source,
            source_context=payload.source_context,
        )
    except PassportNotFound:
        raise _passport_not_found()
    return SaveCandidateResponse(**view, saved=True)


@router.get(
    "",
    response_model=RecruiterConnectionListResponse,
    summary="List the caller's saved candidates (newest first)",
)
def list_connections_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> RecruiterConnectionListResponse:
    connections = [
        RecruiterConnection(**view) for view in list_connections(db, str(user_id))
    ]
    return RecruiterConnectionListResponse(
        connections=connections, total=len(connections)
    )


@router.get(
    "/status",
    response_model=ConnectionStatusResponse,
    summary="Whether the caller has already saved this passport's owner",
)
def connection_status_route(
    passport_slug: str = Query(min_length=1, max_length=128),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ConnectionStatusResponse:
    return ConnectionStatusResponse(
        **connection_status(db, str(user_id), passport_slug)
    )


@router.delete(
    "/{connection_id}",
    response_model=ConnectionDeleteResponse,
    summary="Remove one of the caller's own saved candidates",
)
def delete_connection_route(
    connection_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ConnectionDeleteResponse:
    """404 for both "does not exist" and "belongs to another recruiter" —
    indistinguishable by design."""
    if not delete_connection(db, str(user_id), connection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "connection_not_found",
                "message": "This saved candidate was not found.",
            },
        )
    return ConnectionDeleteResponse(deleted=True)
