"""Schemas for the student notification center."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


NotificationPriority = Literal["low", "normal", "high", "urgent"]
NotificationCategory = Literal[
    "access_request",
    "access_decision",
    "verification",
    "ai_domain_review",
    "project_defense",
    "privacy",
    "passport",
    "system",
    "general",
]


class NotificationResponse(BaseModel):
    id: str
    event_type: str
    category: NotificationCategory
    priority: NotificationPriority
    title: str | None = None
    message: str | None = None
    action_url: str | None = None
    action_label: str | None = None
    status: str
    read_at: datetime | str | None = None
    archived_at: datetime | str | None = None
    dismissed_at: datetime | str | None = None
    delivery_attempts: int | None = None
    last_attempted_at: datetime | str | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    delivery_status: str | None = None
    delivery_error: str | None = None
    scheduled_for: datetime | str | None = None
    delivered_at: datetime | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | str


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class BulkMarkReadRequest(BaseModel):
    notification_ids: list[str] | None = None
