"""Current-user permission endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_db
from app.schemas.permissions import CurrentUserPermissionsResponse
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get(
    "/permissions",
    response_model=CurrentUserPermissionsResponse,
    summary="Get current user roles and permissions",
)
def get_current_user_permissions(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> CurrentUserPermissionsResponse:
    return PermissionService(db).get_current_user_permissions(user_id)

