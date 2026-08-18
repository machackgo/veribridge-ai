"""Recruiter candidate comparison endpoints (v2, migration 068).

Authenticated with the standard Supabase JWT and mounted at
``/api/v1/recruiter/comparisons``. Sessions are recruiter-isolated; the
matrix is re-evaluated from live public evidence on every load — nothing
here can serve evidence the candidate has since unpublished.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.schemas.recruiter_comparisons import (
    ComparisonDeleteResponse,
    ComparisonListItem,
    ComparisonListResponse,
    ComparisonResponse,
    CreateComparisonRequest,
    UpdateComparisonRequest,
)
from app.services.recruiter_comparison_service import (
    ComparisonError,
    ComparisonNotFound,
    create_comparison,
    delete_comparison,
    evaluate_matrix,
    get_comparison,
    list_comparisons,
    plan_from_requirements,
    plan_from_role_text,
    resolve_candidate_user_ids,
    update_comparison,
)
from app.services.recruiter_search_service import record_search_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _comparison_error(exc: ComparisonError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "candidate_not_found"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _not_found() -> HTTPException:
    # One generic 404 for missing AND foreign comparisons — indistinguishable.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "comparison_not_found",
            "message": "This comparison was not found.",
        },
    )


def _plan_for(payload: CreateComparisonRequest | UpdateComparisonRequest) -> dict | None:
    """Edited chips win over natural language; both are deterministic."""
    if payload.requirements is not None:
        return plan_from_requirements(payload.requirements.model_dump())
    if payload.role_text is not None and payload.role_text.strip():
        return plan_from_role_text(payload.role_text)
    return None


def _record_comparison_event(
    db: Any, user_id: str, action: str, matrix: dict[str, Any], role_text: Any
) -> None:
    record_search_event(
        db,
        recruiter_user_id=user_id,
        q=str(role_text or "") or None,
        filters={
            "comparison": action,
            "candidates": len(matrix.get("columns") or []),
            "requirements": len(matrix.get("requirements") or []),
        },
        result_count=len(matrix.get("columns") or []),
    )


@router.post(
    "",
    response_model=ComparisonResponse,
    summary="Create a comparison session and evaluate its evidence matrix",
)
def create_comparison_route(
    payload: CreateComparisonRequest,
    user_id: str = Depends(get_provisioned_user_id),
    db: Any = Depends(get_db),
) -> ComparisonResponse:
    try:
        candidate_user_ids = resolve_candidate_user_ids(
            db,
            str(user_id),
            connection_ids=payload.connection_ids,
            candidate_slugs=payload.candidate_slugs,
        )
    except ComparisonError as exc:
        raise _comparison_error(exc)

    plan = _plan_for(payload) or plan_from_requirements({})
    row = create_comparison(
        db,
        str(user_id),
        candidate_user_ids=candidate_user_ids,
        plan=plan,
        title=payload.title,
        role_text=payload.role_text,
    )
    result = get_comparison(db, str(user_id), str(row["id"]))
    _record_comparison_event(
        db, str(user_id), "created", result["matrix"], payload.role_text
    )
    return ComparisonResponse(**result)


@router.get(
    "",
    response_model=ComparisonListResponse,
    summary="List the caller's comparison sessions (most recent first)",
)
def list_comparisons_route(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ComparisonListResponse:
    items = [
        ComparisonListItem(
            id=view["id"],
            title=view["title"],
            role_text=view["role_text"],
            candidate_count=len(view["candidate_user_ids"]),
            created_at=view["created_at"],
            updated_at=view["updated_at"],
        )
        for view in list_comparisons(db, str(user_id))
    ]
    return ComparisonListResponse(comparisons=items, total=len(items))


@router.get(
    "/{comparison_id}",
    response_model=ComparisonResponse,
    summary="Load a comparison session; the matrix is re-evaluated live",
)
def get_comparison_route(
    comparison_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ComparisonResponse:
    try:
        result = get_comparison(db, str(user_id), comparison_id)
    except ComparisonNotFound:
        raise _not_found()
    return ComparisonResponse(**result)


@router.patch(
    "/{comparison_id}",
    response_model=ComparisonResponse,
    summary="Update title / requirements / candidates and re-evaluate",
)
def update_comparison_route(
    comparison_id: str,
    payload: UpdateComparisonRequest,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ComparisonResponse:
    sent = payload.model_fields_set

    candidate_user_ids = None
    if "connection_ids" in sent or "candidate_slugs" in sent:
        try:
            candidate_user_ids = resolve_candidate_user_ids(
                db,
                str(user_id),
                connection_ids=payload.connection_ids or [],
                candidate_slugs=payload.candidate_slugs or [],
            )
        except ComparisonError as exc:
            raise _comparison_error(exc)

    plan = _plan_for(payload)
    try:
        update_comparison(
            db,
            str(user_id),
            comparison_id,
            candidate_user_ids=candidate_user_ids,
            plan=plan,
            title=payload.title if "title" in sent else ...,
            role_text=payload.role_text if "role_text" in sent else ...,
        )
        result = get_comparison(db, str(user_id), comparison_id)
    except ComparisonNotFound:
        raise _not_found()
    _record_comparison_event(
        db, str(user_id), "updated", result["matrix"], payload.role_text
    )
    return ComparisonResponse(**result)


@router.delete(
    "/{comparison_id}",
    response_model=ComparisonDeleteResponse,
    summary="Delete one of the caller's own comparison sessions",
)
def delete_comparison_route(
    comparison_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> ComparisonDeleteResponse:
    if not delete_comparison(db, str(user_id), comparison_id):
        raise _not_found()
    return ComparisonDeleteResponse(deleted=True)


# Re-exported for tests that need the pure evaluator without a session.
__all__ = ["router", "evaluate_matrix"]
