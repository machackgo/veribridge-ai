"""Provider-ready notification delivery service."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from app.schemas.notification_delivery import (
    NotificationDeliveryResponse,
    NotificationDeliverySummaryResponse,
)

_NOTIFICATIONS = "notification_events"
_DEFAULT_FROM_EMAIL = os.getenv("NOTIFICATION_FROM_EMAIL", "no-reply@veribridge.local")
_DEFAULT_FROM_NAME = os.getenv("NOTIFICATION_FROM_NAME", "VeriBridge")


class NotificationDeliveryError(RuntimeError):
    """Raised when a notification cannot be delivered."""


class NotificationDeliveryService:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_pending_notifications(self, limit: int = 50) -> list[NotificationDeliveryResponse]:
        rows = [
            row for row in self._all_rows()
            if self._is_pending(row) and self._is_due(row)
        ]
        rows.sort(key=lambda row: str(row.get("scheduled_for") or row.get("created_at") or ""), reverse=False)
        return [self._response(row) for row in rows[:limit]]

    def send_notification(self, notification_id: str) -> NotificationDeliveryResponse:
        row = self._notification(notification_id)
        if not self._is_due(row):
            return self.mark_notification_skipped(
                row,
                "notification_scheduled_for_future",
                delivery_status="skipped",
            )
        provider = self._provider_name()
        if provider is None:
            return self.mark_notification_skipped(
                row,
                "email_provider_not_configured",
                delivery_status="skipped",
            )
        try:
            if provider == "resend":
                provider_message_id = self._send_via_resend(row)
            else:
                provider_message_id = self._send_via_sendgrid(row)
        except Exception as exc:  # pragma: no cover - defensive path
            return self.mark_notification_failed(row, str(exc), provider=provider)
        return self.mark_notification_sent(row, provider=provider, provider_message_id=provider_message_id)

    def send_pending_notifications(self, limit: int = 50) -> NotificationDeliverySummaryResponse:
        pending = self.get_pending_notifications(limit=limit)
        processed: list[NotificationDeliveryResponse] = []
        sent = skipped = failed = 0
        for notification in pending:
            updated = self.send_notification(notification.id)
            processed.append(updated)
            if updated.delivery_status == "sent":
                sent += 1
            elif updated.delivery_status == "skipped":
                skipped += 1
            elif updated.delivery_status == "failed":
                failed += 1
        return NotificationDeliverySummaryResponse(
            processed=len(processed),
            sent=sent,
            skipped=skipped,
            failed=failed,
            items=processed,
        )

    def mark_notification_sent(
        self,
        notification: dict[str, Any] | str,
        *,
        provider: str,
        provider_message_id: str | None,
    ) -> NotificationDeliveryResponse:
        row = self._coerce_notification(notification)
        updates = {
            "delivery_attempts": int(row.get("delivery_attempts") or 0) + 1,
            "last_attempted_at": _now(),
            "provider": provider,
            "provider_message_id": provider_message_id,
            "delivery_status": "sent",
            "delivery_error": None,
            "delivered_at": _now(),
            "status": "sent",
            "sent_at": _now(),
        }
        return self._update(row["id"], updates)

    def mark_notification_failed(
        self,
        notification: dict[str, Any] | str,
        error: str,
        *,
        provider: str | None = None,
    ) -> NotificationDeliveryResponse:
        row = self._coerce_notification(notification)
        updates = {
            "delivery_attempts": int(row.get("delivery_attempts") or 0) + 1,
            "last_attempted_at": _now(),
            "provider": provider or row.get("provider"),
            "delivery_status": "failed",
            "delivery_error": error,
            "status": "failed",
            "failure_reason": error,
        }
        return self._update(row["id"], updates)

    def mark_notification_skipped(
        self,
        notification: dict[str, Any] | str,
        reason: str,
        *,
        delivery_status: str = "skipped",
    ) -> NotificationDeliveryResponse:
        row = self._coerce_notification(notification)
        updates = {
            "delivery_attempts": int(row.get("delivery_attempts") or 0) + 1,
            "last_attempted_at": _now(),
            "delivery_status": delivery_status,
            "delivery_error": reason,
            "status": delivery_status,
            "failure_reason": reason,
        }
        return self._update(row["id"], updates)

    def render_email_subject(self, notification: dict[str, Any] | NotificationDeliveryResponse) -> str:
        row = self._coerce_notification(notification)
        title = str(row.get("title") or row.get("subject") or "VeriBridge notification").strip()
        return title[:140]

    def render_email_body(self, notification: dict[str, Any] | NotificationDeliveryResponse) -> str:
        row = self._coerce_notification(notification)
        title = str(row.get("title") or row.get("subject") or "VeriBridge notification").strip()
        message = str(row.get("message") or row.get("body") or "").strip()
        action_label = str(row.get("action_label") or "Review notification").strip()
        action_url = str(row.get("action_url") or "").strip()
        lines = [
            title,
            "",
            message,
            "",
            f"Action: {action_label}",
        ]
        if action_url:
            lines.append(f"Link: {action_url}")
        lines.extend([
            "",
            "This message was generated by VeriBridge notification delivery.",
        ])
        return "\n".join(lines).strip()

    def _provider_name(self) -> str | None:
        if os.getenv("RESEND_API_KEY"):
            return "resend"
        if os.getenv("SENDGRID_API_KEY"):
            return "sendgrid"
        return None

    def _send_via_resend(self, notification: dict[str, Any]) -> str:
        payload = {
            "from": f"{_DEFAULT_FROM_NAME} <{_DEFAULT_FROM_EMAIL}>",
            "to": [str(notification.get("recipient_email") or "")],
            "subject": self.render_email_subject(notification),
            "text": self.render_email_body(notification),
        }
        response = self._post_json(
            "https://api.resend.com/emails",
            payload,
            headers={
                "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            },
        )
        message_id = response.get("id") if isinstance(response, dict) else None
        return str(message_id or "")

    def _send_via_sendgrid(self, notification: dict[str, Any]) -> str:
        payload = {
            "personalizations": [
                {
                    "to": [{"email": str(notification.get("recipient_email") or "")}],
                    "subject": self.render_email_subject(notification),
                }
            ],
            "from": {
                "email": _DEFAULT_FROM_EMAIL,
                "name": _DEFAULT_FROM_NAME,
            },
            "content": [
                {
                    "type": "text/plain",
                    "value": self.render_email_body(notification),
                }
            ],
        }
        response = self._post_json(
            "https://api.sendgrid.com/v3/mail/send",
            payload,
            headers={
                "Authorization": f"Bearer {os.environ['SENDGRID_API_KEY']}",
            },
            expect_json=False,
        )
        if isinstance(response, dict) and response.get("message_id"):
            return str(response["message_id"])
        return ""

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        expect_json: bool = True,
    ) -> dict[str, Any] | None:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                **headers,
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=15) as response:
                if not expect_json:
                    return {"message_id": response.headers.get("X-Message-Id")}
                raw = response.read().decode("utf-8").strip()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raise NotificationDeliveryError(f"provider_http_error:{exc.code}") from exc
        except URLError as exc:
            raise NotificationDeliveryError(f"provider_url_error:{exc.reason}") from exc

    def _all_rows(self) -> list[dict[str, Any]]:
        if isinstance(self._client, dict):
            return list(self._client.get(_NOTIFICATIONS, {}).values())
        result = self._client.table(_NOTIFICATIONS).select("*").execute()
        return getattr(result, "data", []) or []

    def _notification(self, notification_id: str) -> dict[str, Any]:
        if isinstance(self._client, dict):
            row = self._client.get(_NOTIFICATIONS, {}).get(notification_id)
            if not row:
                raise NotificationDeliveryError(notification_id)
            return row
        result = self._client.table(_NOTIFICATIONS).select("*").eq("id", notification_id).limit(1).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise NotificationDeliveryError(notification_id)
        return rows[0]

    def _coerce_notification(self, notification: dict[str, Any] | NotificationDeliveryResponse | str) -> dict[str, Any]:
        if isinstance(notification, str):
            return self._notification(notification)
        if isinstance(notification, NotificationDeliveryResponse):
            return notification.model_dump(mode="json")
        return notification

    def _is_pending(self, row: dict[str, Any]) -> bool:
        delivery_status = str(row.get("delivery_status") or row.get("status") or "pending")
        return delivery_status in {"pending", "queued"}

    def _is_due(self, row: dict[str, Any]) -> bool:
        scheduled_for = row.get("scheduled_for")
        if scheduled_for is None:
            return True
        parsed = _parse_dt(scheduled_for)
        return parsed is None or parsed <= _now()

    def _update(self, notification_id: str, fields: dict[str, Any]) -> NotificationDeliveryResponse:
        if isinstance(self._client, dict):
            row = self._client.setdefault(_NOTIFICATIONS, {}).get(notification_id)
            if not row:
                raise NotificationDeliveryError(notification_id)
            row.update(fields)
            return self._response(row)
        result = self._client.table(_NOTIFICATIONS).update(fields).eq("id", notification_id).execute()
        rows = getattr(result, "data", []) or []
        if not rows:
            raise NotificationDeliveryError(notification_id)
        return self._response(rows[0])

    def _response(self, row: dict[str, Any]) -> NotificationDeliveryResponse:
        return NotificationDeliveryResponse(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            event_type=str(row["event_type"]),
            recipient_email=str(row.get("recipient_email") or ""),
            title=row.get("title"),
            message=row.get("message"),
            category=row.get("category"),
            priority=row.get("priority"),
            status=str(row.get("status") or "pending"),
            delivery_status=row.get("delivery_status"),
            delivery_attempts=int(row.get("delivery_attempts") or 0),
            last_attempted_at=row.get("last_attempted_at"),
            provider=row.get("provider"),
            provider_message_id=row.get("provider_message_id"),
            delivery_error=row.get("delivery_error"),
            scheduled_for=row.get("scheduled_for"),
            delivered_at=row.get("delivered_at"),
            created_at=row["created_at"],
            metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            subject=row.get("subject"),
            body=row.get("body"),
        )


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _now() -> datetime:
    return datetime.now(UTC)
