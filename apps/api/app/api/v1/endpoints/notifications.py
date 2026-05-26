"""Student notification center endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user_id, get_db
from app.schemas.notification import (
    BulkMarkReadRequest,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from app.services.notification_service import NotificationNotFoundError, NotificationService

router = APIRouter()


@router.get(
    "",
    response_model=list[NotificationResponse],
    summary="List student notifications",
)
def list_notifications(
    unread_only: bool = False,
    category: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[NotificationResponse]:
    return NotificationService(db).list_student_notifications(
        user_id,
        unread_only=unread_only,
        category=category,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/unread-count",
    response_model=NotificationUnreadCountResponse,
    summary="Get unread student notification count",
)
def unread_count(
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> NotificationUnreadCountResponse:
    return NotificationUnreadCountResponse(unread_count=NotificationService(db).unread_count(user_id))


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a notification read",
)
def mark_read(
    notification_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> NotificationResponse:
    try:
        return NotificationService(db).mark_notification_read(notification_id, user_id)
    except NotificationNotFoundError as exc:
        raise _notification_not_found(str(exc)) from exc


@router.post(
    "/{notification_id}/unread",
    response_model=NotificationResponse,
    summary="Mark a notification unread",
)
def mark_unread(
    notification_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> NotificationResponse:
    try:
        return NotificationService(db).mark_notification_unread(notification_id, user_id)
    except NotificationNotFoundError as exc:
        raise _notification_not_found(str(exc)) from exc


@router.post(
    "/{notification_id}/archive",
    response_model=NotificationResponse,
    summary="Archive a notification",
)
def archive(
    notification_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> NotificationResponse:
    try:
        return NotificationService(db).archive_notification(notification_id, user_id)
    except NotificationNotFoundError as exc:
        raise _notification_not_found(str(exc)) from exc


@router.post(
    "/{notification_id}/dismiss",
    response_model=NotificationResponse,
    summary="Dismiss a notification",
)
def dismiss(
    notification_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> NotificationResponse:
    try:
        return NotificationService(db).dismiss_notification(notification_id, user_id)
    except NotificationNotFoundError as exc:
        raise _notification_not_found(str(exc)) from exc


@router.post(
    "/mark-all-read",
    response_model=list[NotificationResponse],
    summary="Mark all or selected notifications read",
)
def mark_all_read(
    body: BulkMarkReadRequest | None = None,
    user_id: str = Depends(get_current_user_id),
    db: Any = Depends(get_db),
) -> list[NotificationResponse]:
    return NotificationService(db).bulk_mark_read(
        user_id,
        notification_ids=(body.notification_ids if body else None),
    )


def _notification_not_found(notification_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "notification_not_found",
            "message": "Notification was not found for the current user.",
            "notification_id": notification_id,
        },
    )
