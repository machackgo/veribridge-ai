"""Admin notification delivery endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, require_admin_user_id
from app.schemas.notification_delivery import (
    NotificationDeliveryResponse,
    NotificationDeliverySummaryResponse,
)
from app.services.notification_delivery_service import NotificationDeliveryService

router = APIRouter()


@router.post(
    "/{notification_id}/send",
    response_model=NotificationDeliveryResponse,
    summary="Send a single notification through the configured email provider",
)
def send_notification(
    notification_id: str,
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> NotificationDeliveryResponse:
    return NotificationDeliveryService(db).send_notification(notification_id)


@router.post(
    "/send-pending",
    response_model=NotificationDeliverySummaryResponse,
    summary="Send pending notification emails",
)
def send_pending_notifications(
    limit: int = Query(default=50, ge=1, le=500),
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> NotificationDeliverySummaryResponse:
    return NotificationDeliveryService(db).send_pending_notifications(limit=limit)


@router.get(
    "/delivery-status",
    response_model=list[NotificationDeliveryResponse],
    summary="List recent notification delivery status entries",
)
def delivery_status(
    delivery_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    admin_user_id: str = Depends(require_admin_user_id),
    db: Any = Depends(get_db),
) -> list[NotificationDeliveryResponse]:
    service = NotificationDeliveryService(db)
    rows = service._all_rows()
    if delivery_status:
        rows = [
            row for row in rows
            if str(row.get("delivery_status") or row.get("status") or "pending") == delivery_status
        ]
    rows.sort(key=_delivery_sort_key)
    return [service._response(row) for row in rows[:limit]]


def _delivery_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    scheduled_for = row.get("scheduled_for")
    scheduled_rank = 0 if scheduled_for is None else 1
    return (
        scheduled_rank,
        str(row.get("scheduled_for") or row.get("created_at") or ""),
        str(row.get("created_at") or ""),
    )
