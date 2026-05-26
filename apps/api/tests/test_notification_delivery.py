"""Tests for notification delivery / email backend."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_service import NotificationService


USER_ID = "00000000-0000-0000-0000-000000000042"
ADMIN_ID = "00000000-0000-0000-0000-000000000777"


@pytest.fixture()
def mem_store() -> dict:
    return {
        "users": {
            USER_ID: {"id": USER_ID, "email": "student@example.edu"},
            ADMIN_ID: {"id": ADMIN_ID, "email": "admin@example.edu", "role": "admin"},
        }
    }


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: ADMIN_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_notification(mem_store: dict, *, user_id: str = USER_ID, scheduled_for: datetime | None = None) -> dict:
    created = NotificationService(mem_store).create_notification_event(
        user_id=user_id,
        event_type="access_requested",
        recipient_email="student@example.edu",
        title="New evidence access request",
        message="A recruiter requested access to your Work Passport evidence.",
        category="access_request",
        priority="high",
        action_url="/student/notifications",
        action_label="Review request",
        metadata={
            "request_id": "request-1",
            "requester_email": "recruiter@example.com",
            "private_transcript": "should not leak",
            "media_storage_path": "private/path",
            "access_token": "secret-token",
            "admin_notes": "secret-note",
        },
        scheduled_for=scheduled_for,
    )
    return mem_store["notification_events"][created.id]


def test_pending_notifications_can_be_listed(client: TestClient, mem_store: dict) -> None:
    due = _create_notification(mem_store)
    _create_notification(mem_store, scheduled_for=datetime.now(UTC) + timedelta(hours=2))

    response = client.get("/api/v1/admin/notifications/delivery-status")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["id"] == due["id"]


def test_sending_notification_without_provider_marks_skipped(mem_store: dict) -> None:
    notification = _create_notification(mem_store)

    result = NotificationDeliveryService(mem_store).send_notification(notification["id"])

    assert result.delivery_status == "skipped"
    assert result.status == "skipped"
    assert result.delivery_attempts == 1
    assert result.delivery_error == "email_provider_not_configured"


def test_failed_send_marks_failed(monkeypatch: pytest.MonkeyPatch, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    monkeypatch.setenv("RESEND_API_KEY", "resend-test-key")
    monkeypatch.setattr(
        NotificationDeliveryService,
        "_send_via_resend",
        lambda self, row: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )

    result = NotificationDeliveryService(mem_store).send_notification(notification["id"])

    assert result.delivery_status == "failed"
    assert result.status == "failed"
    assert result.delivery_attempts == 1
    assert result.delivery_error == "provider failed"
    assert result.provider == "resend"


def test_sent_notification_stores_provider_fields(monkeypatch: pytest.MonkeyPatch, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    monkeypatch.setenv("RESEND_API_KEY", "resend-test-key")
    monkeypatch.setattr(NotificationDeliveryService, "_send_via_resend", lambda self, row: "msg-123")

    result = NotificationDeliveryService(mem_store).send_notification(notification["id"])

    assert result.delivery_status == "sent"
    assert result.provider == "resend"
    assert result.provider_message_id == "msg-123"
    assert result.delivered_at is not None
    assert result.delivery_attempts == 1


def test_email_rendering_is_safe(mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    service = NotificationDeliveryService(mem_store)

    subject = service.render_email_subject(notification)
    body = service.render_email_body(notification)

    assert subject == "New evidence access request"
    assert "New evidence access request" in body
    assert "A recruiter requested access to your Work Passport evidence." in body
    assert "private transcript" not in body.lower()
    assert "media_storage_path" not in body.lower()
    assert "access_token" not in body.lower()
    assert "admin notes" not in body.lower()


def test_send_pending_notifications_processes_only_due_items(monkeypatch: pytest.MonkeyPatch, mem_store: dict) -> None:
    due = _create_notification(mem_store)
    future = _create_notification(mem_store, scheduled_for=datetime.now(UTC) + timedelta(hours=2))
    monkeypatch.setenv("RESEND_API_KEY", "resend-test-key")
    monkeypatch.setattr(NotificationDeliveryService, "_send_via_resend", lambda self, row: "msg-123")

    summary = NotificationDeliveryService(mem_store).send_pending_notifications(limit=50)

    assert summary.processed == 1
    assert summary.sent == 1
    assert summary.skipped == 0
    assert summary.failed == 0
    assert mem_store["notification_events"][due["id"]]["delivery_status"] == "sent"
    assert mem_store["notification_events"][future["id"]]["delivery_status"] == "pending"


def test_admin_send_endpoint_works(client: TestClient, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    result = client.post(f"/api/v1/admin/notifications/{notification['id']}/send")

    assert result.status_code == 200, result.text
    assert result.json()["delivery_status"] == "skipped"


def test_admin_send_pending_endpoint_works(client: TestClient, mem_store: dict) -> None:
    _create_notification(mem_store)
    result = client.post("/api/v1/admin/notifications/send-pending")

    assert result.status_code == 200, result.text
    assert result.json()["processed"] == 1


def test_no_project_specific_hardcoding() -> None:
    import app.services.notification_delivery_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source
