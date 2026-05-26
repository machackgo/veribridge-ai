"""Admin user role management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, require_admin_user_id
from app.schemas.permissions import UserRoleGrantRequest, UserRoleResponse
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get(
    "/{user_id}/roles",
    response_model=list[UserRoleResponse],
    summary="Admin: list a user's active roles",
)
def list_user_roles(
    user_id: str,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> list[UserRoleResponse]:
    _ = admin_user_id
    return PermissionService(db).get_user_roles(user_id)


@router.post(
    "/{user_id}/roles",
    response_model=UserRoleResponse,
    summary="Admin: grant a role to a user",
)
def grant_user_role(
    user_id: str,
    body: UserRoleGrantRequest,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> UserRoleResponse:
    PermissionService(db).require_role(admin_user_id, ["admin", "support"])
    return PermissionService(db).grant_role(
        user_id,
        body.role,
        admin_user_id,
        scope=body.scope,
        scope_id=body.scope_id,
        metadata=body.metadata,
    )


@router.delete(
    "/{user_id}/roles/{role}",
    response_model=UserRoleResponse,
    summary="Admin: revoke a user's role",
)
def revoke_user_role(
    user_id: str,
    role: str,
    scope: str = Query(default="global"),
    scope_id: str | None = Query(default=None),
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> UserRoleResponse:
    PermissionService(db).require_role(admin_user_id, ["admin", "support"])
    return PermissionService(db).revoke_role(
        user_id,
        role,
        admin_user_id,
        scope=scope,
        scope_id=scope_id,
    )

