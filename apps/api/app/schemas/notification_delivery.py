"""Schemas for notification email delivery operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationDeliveryResponse(BaseModel):
    id: str
    user_id: str
    event_type: str
    recipient_email: str
    title: str | None = None
    message: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str
    delivery_status: str | None = None
    delivery_attempts: int = 0
    last_attempted_at: datetime | str | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    delivery_error: str | None = None
    scheduled_for: datetime | str | None = None
    delivered_at: datetime | str | None = None
    created_at: datetime | str
    metadata: dict[str, Any] = Field(default_factory=dict)
    subject: str | None = None
    body: str | None = None


class NotificationDeliverySummaryResponse(BaseModel):
    processed: int
    sent: int
    skipped: int
    failed: int
    items: list[NotificationDeliveryResponse] = Field(default_factory=list)
