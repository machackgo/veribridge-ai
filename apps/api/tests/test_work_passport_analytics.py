"""Tests for Work Passport analytics backend."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.work_passport_analytics_service import WorkPassportAnalyticsService


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


def _seed_passport_dataset(mem_store: dict) -> dict[str, str]:
    now = datetime.now(UTC)
    session_one = str(uuid4())
    session_two = str(uuid4())
    other_session = str(uuid4())
    passport_one = str(uuid4())
    passport_two = str(uuid4())
    other_passport = str(uuid4())
    profile_one = str(uuid4())
    profile_two = str(uuid4())
    other_profile = str(uuid4())

    mem_store["public_work_passports"] = {
        passport_one: {
            "id": passport_one,
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "public_slug": "passport-one",
            "is_public": True,
        },
        passport_two: {
            "id": passport_two,
            "user_id": USER_ID,
            "proof_session_id": session_two,
            "public_slug": "passport-two",
            "is_public": True,
        },
        other_passport: {
            "id": other_passport,
            "user_id": OTHER_USER_ID,
            "proof_session_id": other_session,
            "public_slug": "other-passport",
            "is_public": True,
        },
    }
    mem_store["recruiter_requester_profiles"] = {
        profile_one: {
            "id": profile_one,
            "email": "one@example.com",
            "organization_name": "Example Co",
            "organization_domain": "example.com",
        },
        profile_two: {
            "id": profile_two,
            "email": "two@review.org",
            "organization_name": "Review Org",
            "organization_domain": "review.org",
        },
        other_profile: {
            "id": other_profile,
            "email": "other@other.org",
            "organization_name": "Other Org",
            "organization_domain": "other.org",
        },
    }
    mem_store["evidence_access_requests"] = {
        "request-1": {
            "id": "request-1",
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "passport_id": passport_one,
            "requester_profile_id": profile_one,
            "requester_email": "one@example.com",
            "requester_organization": "Example Co",
            "status": "pending",
            "requested_sections": ["github_analysis", "project_defense_summary"],
            "created_at": now - timedelta(minutes=6),
        },
        "request-2": {
            "id": "request-2",
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "passport_id": passport_one,
            "requester_profile_id": profile_two,
            "requester_email": "two@review.org",
            "requester_organization": "Review Org",
            "status": "approved",
            "requested_sections": ["github_analysis"],
            "created_at": now - timedelta(minutes=5),
        },
        "request-3": {
            "id": "request-3",
            "user_id": USER_ID,
            "proof_session_id": session_two,
            "passport_id": passport_two,
            "requester_profile_id": profile_one,
            "requester_email": "one@example.com",
            "requester_organization": "Example Co",
            "status": "denied",
            "requested_sections": ["workflow_analysis"],
            "created_at": now - timedelta(minutes=4),
        },
        "request-other": {
            "id": "request-other",
            "user_id": OTHER_USER_ID,
            "proof_session_id": other_session,
            "passport_id": other_passport,
            "requester_profile_id": other_profile,
            "requester_email": "other@other.org",
            "requester_organization": "Other Org",
            "status": "approved",
            "requested_sections": ["private_transcript_should_not_leak"],
            "created_at": now - timedelta(minutes=3),
        },
    }
    mem_store["evidence_access_grants"] = {
        "grant-active": {
            "id": "grant-active",
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "access_request_id": "request-2",
            "access_token": "secret-token",
            "revoked_at": None,
        },
        "grant-revoked": {
            "id": "grant-revoked",
            "user_id": USER_ID,
            "proof_session_id": session_two,
            "access_request_id": "request-3",
            "access_token": "revoked-secret-token",
            "revoked_at": now,
        },
        "grant-other": {
            "id": "grant-other",
            "user_id": OTHER_USER_ID,
            "proof_session_id": other_session,
            "access_request_id": "request-other",
            "access_token": "other-secret-token",
            "revoked_at": None,
        },
    }
    mem_store["public_passport_view_events"] = {
        "view-1": {"id": "view-1", "passport_id": passport_one, "public_slug": "passport-one", "created_at": now},
        "view-2": {"id": "view-2", "passport_id": passport_one, "public_slug": "passport-one", "created_at": now},
        "view-3": {"id": "view-3", "passport_id": passport_two, "public_slug": "passport-two", "created_at": now},
        "view-other": {"id": "view-other", "passport_id": other_passport, "public_slug": "other-passport", "created_at": now},
    }
    mem_store["evidence_access_audit_events"] = {
        "event-old": {
            "id": "event-old",
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "passport_id": passport_one,
            "event_type": "access_requested",
            "event_summary": "Older request",
            "actor_type": "recruiter",
            "actor_email": "one@example.com",
            "metadata": {"requester_profile_id": profile_one, "requester_organization": "Example Co"},
            "created_at": now - timedelta(minutes=2),
        },
        "event-new": {
            "id": "event-new",
            "user_id": USER_ID,
            "proof_session_id": session_one,
            "passport_id": passport_one,
            "event_type": "protected_evidence_viewed",
            "event_summary": "Protected evidence viewed",
            "actor_type": "recruiter",
            "actor_email": "two@review.org",
            "metadata": {"requester_profile_id": profile_two, "media_storage_path": "private/audio.webm"},
            "created_at": now - timedelta(minutes=1),
        },
        "event-session-two": {
            "id": "event-session-two",
            "user_id": USER_ID,
            "proof_session_id": session_two,
            "passport_id": passport_two,
            "event_type": "access_denied",
            "event_summary": "Denied request",
            "actor_type": "student",
            "actor_email": None,
            "metadata": {"requester_profile_id": profile_one},
            "created_at": now - timedelta(minutes=7),
        },
        "event-other": {
            "id": "event-other",
            "user_id": OTHER_USER_ID,
            "proof_session_id": other_session,
            "passport_id": other_passport,
            "event_type": "protected_evidence_viewed",
            "event_summary": "Other protected evidence viewed",
            "actor_type": "recruiter",
            "actor_email": "other@other.org",
            "metadata": {"transcript_text": "private transcript"},
            "created_at": now,
        },
    }
    mem_store["notification_events"] = {
        "note-1": {"id": "note-1", "user_id": USER_ID, "read_at": None, "archived_at": None},
        "note-read": {"id": "note-read", "user_id": USER_ID, "read_at": now, "archived_at": None},
        "note-other": {"id": "note-other", "user_id": OTHER_USER_ID, "read_at": None, "archived_at": None},
    }
    return {
        "session_one": session_one,
        "session_two": session_two,
        "passport_one": passport_one,
        "passport_two": passport_two,
    }


def test_analytics_returns_counts_for_current_student(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    response = client.get("/api/v1/student/work-passport/analytics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_passports"] == 2
    assert body["total_public_views"] == 3
    assert body["total_access_requests"] == 3
    assert body["pending_access_requests"] == 1
    assert body["approved_access_requests"] == 1
    assert body["denied_access_requests"] == 1
    assert body["revoked_access_grants"] == 1
    assert body["active_access_grants"] == 1
    assert body["protected_evidence_views"] == 1
    assert body["unique_requester_emails"] == 2
    assert body["unique_requester_organizations"] == 2
    assert body["unread_notifications"] == 1


def test_another_students_passport_data_is_excluded(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    body = client.get("/api/v1/student/work-passport/analytics").json()
    serialized = str(body)
    assert "other@other.org" not in serialized
    assert "Other Org" not in serialized
    assert "other-secret-token" not in serialized


def test_top_requested_sections_calculated(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    body = client.get("/api/v1/student/work-passport/analytics").json()
    assert body["top_requested_sections"][0] == {"section": "github_analysis", "count": 2}
    sections = {row["section"]: row["count"] for row in body["top_requested_sections"]}
    assert sections["project_defense_summary"] == 1
    assert sections["workflow_analysis"] == 1


def test_activity_timeline_is_newest_first(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    response = client.get("/api/v1/student/work-passport/analytics/activity")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["event_type"] for row in rows[:2]] == ["protected_evidence_viewed", "access_requested"]
    assert rows[0]["requester_organization"] == "Review Org"


def test_proof_session_id_filter_works(client: TestClient, mem_store: dict) -> None:
    ids = _seed_passport_dataset(mem_store)
    body = client.get(
        f"/api/v1/student/work-passport/analytics?proof_session_id={ids['session_one']}"
    ).json()
    assert body["total_passports"] == 1
    assert body["total_public_views"] == 2
    assert body["total_access_requests"] == 2
    assert body["pending_access_requests"] == 1
    assert body["approved_access_requests"] == 1
    assert body["denied_access_requests"] == 0
    assert body["protected_evidence_views"] == 1


def test_requester_organizations_counted_correctly(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    body = client.get("/api/v1/student/work-passport/analytics").json()
    organizations = {
        row["organization_name"]: row
        for row in body["requester_organizations"]
    }
    assert organizations["Example Co"]["request_count"] == 2
    assert organizations["Example Co"]["unique_requester_emails"] == 1
    assert organizations["Review Org"]["request_count"] == 1


def test_analytics_does_not_expose_private_fields(client: TestClient, mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    body = client.get("/api/v1/student/work-passport/analytics").json()
    activity = client.get("/api/v1/student/work-passport/analytics/activity").json()
    serialized = f"{body} {activity}"
    assert "access_token" not in serialized
    assert "secret-token" not in serialized
    assert "media_storage_path" not in serialized
    assert "private/audio.webm" not in serialized
    assert "transcript_text" not in serialized
    assert "private transcript" not in serialized


def test_service_methods_return_component_summaries(mem_store: dict) -> None:
    _seed_passport_dataset(mem_store)
    service = WorkPassportAnalyticsService(mem_store)
    access = service.get_access_request_summary(USER_ID)
    organizations = service.get_requester_organization_summary(USER_ID)
    assert access.total_access_requests == 3
    assert access.active_access_grants == 1
    assert len(organizations) == 2


def test_no_project_specific_hardcoding() -> None:
    import app.services.work_passport_analytics_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
