"""Student notification center service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.notification import NotificationResponse

_NOTIFICATIONS = "notification_events"

_SUPPORTED_EVENT_TYPES = {
    "access_requested",
    "access_approved",
    "access_denied",
    "access_revoked",
    "ai_domain_review_ready",
    "project_defense_analysis_complete",
    "verification_needs_more_evidence",
    "privacy_issue_detected",
    "passport_viewed",
    "access_request_received",
}
_ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
_ALLOWED_CATEGORIES = {
    "access_request",
    "access_decision",
    "verification",
    "ai_domain_review",
    "project_defense",
    "privacy",
    "passport",
    "system",
    "general",
}


class NotificationNotFoundError(LookupError):
    """Notification not found for the scoped student."""


class NotificationService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def create_notification_event(
        self,
        *,
        user_id: str,
        event_type: str,
        recipient_email: str,
        title: str | None = None,
        message: str | None = None,
        category: str = "general",
        priority: str = "normal",
        action_url: str | None = None,
        action_label: str | None = None,
        channel: str = "email",
        subject: str | None = None,
        body: str | None = None,
        status: str = "pending",
        metadata: dict[str, Any] | None = None,
    ) -> NotificationResponse:
        now = _now()
        normalized_event_type = event_type if event_type in _SUPPORTED_EVENT_TYPES else event_type
        row = {
            "id": str(uuid4()),
            "user_id": user_id,
            "event_type": normalized_event_type,
            "channel": channel,
            "recipient_email": recipient_email,
            "subject": subject or title,
            "body": body or message,
            "status": status,
            "metadata": metadata or {},
            "title": title or subject,
            "message": message or body,
            "action_url": action_url,
            "action_label": action_label,
            "priority": priority if priority in _ALLOWED_PRIORITIES else "normal",
            "category": category if category in _ALLOWED_CATEGORIES else "general",
            "read_at": None,
            "archived_at": None,
            "dismissed_at": None,
            "created_at": now,
            "sent_at": None,
            "failure_reason": None,
        }
        return _notification_response(self._insert(row))

    def list_student_notifications(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        category: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationResponse]:
        rows = self._rows_for_user(user_id)
        if unread_only:
            rows = [row for row in rows if row.get("read_at") is None]
        if category:
            rows = [row for row in rows if str(row.get("category") or "general") == category]
        if not include_archived:
            rows = [row for row in rows if row.get("archived_at") is None]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [_notification_response(row) for row in rows[offset:offset + limit]]

    def unread_count(self, user_id: str) -> int:
        return len([
            row for row in self._rows_for_user(user_id)
            if row.get("read_at") is None and row.get("archived_at") is None
        ])

    def mark_notification_read(self, notification_id: str, user_id: str) -> NotificationResponse:
        return self._update_for_user(notification_id, user_id, {"read_at": _now()})

    def mark_notification_unread(self, notification_id: str, user_id: str) -> NotificationResponse:
        return self._update_for_user(notification_id, user_id, {"read_at": None})

    def archive_notification(self, notification_id: str, user_id: str) -> NotificationResponse:
        return self._update_for_user(notification_id, user_id, {"archived_at": _now()})

    def dismiss_notification(self, notification_id: str, user_id: str) -> NotificationResponse:
        return self._update_for_user(notification_id, user_id, {"dismissed_at": _now()})

    def bulk_mark_read(
        self,
        user_id: str,
        notification_ids: list[str] | None = None,
    ) -> list[NotificationResponse]:
        target_ids = set(notification_ids or [])
        rows = [
            row for row in self._rows_for_user(user_id)
            if not target_ids or str(row.get("id")) in target_ids
        ]
        return [
            self._update_for_user(str(row["id"]), user_id, {"read_at": _now()})
            for row in rows
        ]

    def _insert(self, row: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self._client, dict):
            self._client.setdefault(_NOTIFICATIONS, {})[str(row["id"])] = row
            return row
        result = self._client.table(_NOTIFICATIONS).insert(row).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise RuntimeError("notification_events insert returned no data.")
        return rows[0]

    def _rows_for_user(self, user_id: str) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return [
                row for row in self._client.get(_NOTIFICATIONS, {}).values()
                if str(row.get("user_id")) == user_id
            ]
        result = self._client.table(_NOTIFICATIONS).select("*").eq("user_id", user_id).execute()
        return getattr(result, "data", []) or []

    def _notification_for_user(self, notification_id: str, user_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.get(_NOTIFICATIONS, {}).get(notification_id)
            if not row or str(row.get("user_id")) != user_id:
                raise NotificationNotFoundError(notification_id)
            return row
        result = (
            self._client.table(_NOTIFICATIONS)
            .select("*")
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise NotificationNotFoundError(notification_id)
        return rows[0]

    def _update_for_user(
        self,
        notification_id: str,
        user_id: str,
        fields: dict[str, Any],
    ) -> NotificationResponse:
        self._notification_for_user(notification_id, user_id)
        if isinstance(self._client, dict):
            row = self._client[_NOTIFICATIONS][notification_id]
            row.update(fields)
            return _notification_response(row)
        result = (
            self._client.table(_NOTIFICATIONS)
            .update(fields)
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = getattr(result, "data", []) or []
        if not rows:
            raise NotificationNotFoundError(notification_id)
        return _notification_response(rows[0])


def _notification_response(row: dict[str, Any]) -> NotificationResponse:
    return NotificationResponse(
        id=str(row["id"]),
        event_type=str(row["event_type"]),
        category=row.get("category") or "general",
        priority=row.get("priority") or "normal",
        title=row.get("title") or row.get("subject"),
        message=row.get("message") or row.get("body"),
        action_url=row.get("action_url"),
        action_label=row.get("action_label"),
        status=row.get("status") or "pending",
        read_at=row.get("read_at"),
        archived_at=row.get("archived_at"),
        dismissed_at=row.get("dismissed_at"),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        created_at=row["created_at"],
    )


def _now() -> datetime:
    return datetime.now(UTC)
