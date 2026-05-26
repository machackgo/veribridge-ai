"""Tests for the student notification center backend."""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.notification_service import NotificationService


USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_notification(
    mem_store: dict,
    user_id: str = USER_ID,
    *,
    event_type: str = "access_request_received",
    category: str = "access_request",
    priority: str = "high",
    title: str = "New evidence access request",
) -> dict:
    created = NotificationService(mem_store).create_notification_event(
        user_id=user_id,
        event_type=event_type,
        recipient_email="student@example.edu",
        title=title,
        message="A reviewer requested access to evidence.",
        category=category,
        priority=priority,
        action_label="Review request",
        metadata={"request_id": "request-1", "requester_email": "reviewer@example.com"},
    )
    return mem_store["notification_events"][created.id]


def test_student_can_list_own_notifications(client: TestClient, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    _create_notification(mem_store, OTHER_USER_ID, title="Other notification")
    response = client.get("/api/v1/student/notifications")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["id"] == notification["id"]
    assert rows[0]["title"] == "New evidence access request"
    assert rows[0]["category"] == "access_request"
    assert rows[0]["priority"] == "high"


def test_unread_count_works(client: TestClient, mem_store: dict) -> None:
    first = _create_notification(mem_store)
    _create_notification(mem_store)
    NotificationService(mem_store).mark_notification_read(first["id"], USER_ID)
    response = client.get("/api/v1/student/notifications/unread-count")
    assert response.status_code == 200, response.text
    assert response.json()["unread_count"] == 1


def test_mark_read_and_unread_work(client: TestClient, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    read = client.post(f"/api/v1/student/notifications/{notification['id']}/read")
    assert read.status_code == 200, read.text
    assert read.json()["read_at"] is not None
    unread = client.post(f"/api/v1/student/notifications/{notification['id']}/unread")
    assert unread.status_code == 200, unread.text
    assert unread.json()["read_at"] is None


def test_archive_hides_notification_by_default_and_include_archived_returns_it(
    client: TestClient,
    mem_store: dict,
) -> None:
    notification = _create_notification(mem_store)
    archived = client.post(f"/api/v1/student/notifications/{notification['id']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert client.get("/api/v1/student/notifications").json() == []
    with_archived = client.get("/api/v1/student/notifications?include_archived=true")
    assert len(with_archived.json()) == 1


def test_dismiss_works(client: TestClient, mem_store: dict) -> None:
    notification = _create_notification(mem_store)
    response = client.post(f"/api/v1/student/notifications/{notification['id']}/dismiss")
    assert response.status_code == 200, response.text
    assert response.json()["dismissed_at"] is not None


def test_mark_all_read_works(client: TestClient, mem_store: dict) -> None:
    _create_notification(mem_store)
    _create_notification(mem_store)
    response = client.post("/api/v1/student/notifications/mark-all-read", json={})
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2
    assert client.get("/api/v1/student/notifications/unread-count").json()["unread_count"] == 0


def test_student_cannot_read_another_students_notifications(client: TestClient, mem_store: dict) -> None:
    _create_notification(mem_store, OTHER_USER_ID)
    response = client.get("/api/v1/student/notifications")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_student_cannot_update_another_students_notification(client: TestClient, mem_store: dict) -> None:
    notification = _create_notification(mem_store, OTHER_USER_ID)
    response = client.post(f"/api/v1/student/notifications/{notification['id']}/read")
    assert response.status_code == 404
    assert mem_store["notification_events"][notification["id"]]["read_at"] is None


def test_filters_unread_and_category(client: TestClient, mem_store: dict) -> None:
    access = _create_notification(mem_store, category="access_request")
    verification = _create_notification(
        mem_store,
        event_type="verification_needs_more_evidence",
        category="verification",
        title="More evidence needed",
    )
    NotificationService(mem_store).mark_notification_read(verification["id"], USER_ID)
    response = client.get("/api/v1/student/notifications?unread_only=true&category=access_request")
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [access["id"]]


def test_no_project_specific_hardcoding() -> None:
    import app.services.notification_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
