"""Tests for admin quality review / moderation backend."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.admin_quality_review_service import AdminQualityReviewService


ADMIN_ID = "00000000-0000-0000-0000-000000000001"
STUDENT_ID = "00000000-0000-0000-0000-000000000042"


@pytest.fixture()
def mem_store() -> dict:
    return {
        "users": {
            ADMIN_ID: {"id": ADMIN_ID, "email": "admin@example.com", "role": "admin"},
            STUDENT_ID: {"id": STUDENT_ID, "email": "student@example.edu", "role": "student"},
        }
    }


@pytest.fixture()
def admin_client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: ADMIN_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def student_client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: STUDENT_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_signals(mem_store: dict) -> dict[str, str]:
    session_id = str(uuid4())
    passport_id = str(uuid4())
    requester_profile_id = str(uuid4())
    access_request_id = str(uuid4())
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": STUDENT_ID,
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": STUDENT_ID,
        "proof_session_id": session_id,
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})["privacy"] = {
        "id": "privacy",
        "user_id": STUDENT_ID,
        "proof_session_id": session_id,
        "status": "flagged",
        "risk_flags": ["API key detected"],
        "scan_summary": "Potential sensitive data detected.",
    }
    mem_store.setdefault("ai_domain_review_results", {})["domain"] = {
        "id": "domain",
        "user_id": STUDENT_ID,
        "proof_session_id": session_id,
        "confidence_level": "low",
        "human_review_recommended": True,
        "recruiter_summary": "Low confidence due to limited evidence.",
    }
    mem_store.setdefault("recruiter_requester_profiles", {})[requester_profile_id] = {
        "id": requester_profile_id,
        "email": "reviewer@example.com",
        "risk_score": 40,
        "risk_flags": ["free_email_domain", "missing_reason"],
        "verification_status": "suspicious",
    }
    mem_store.setdefault("evidence_access_requests", {})[access_request_id] = {
        "id": access_request_id,
        "user_id": STUDENT_ID,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "requester_profile_id": requester_profile_id,
        "requester_email": "reviewer@example.com",
        "status": "denied",
        "request_reason": None,
    }
    mem_store.setdefault("evidence_access_grants", {})["grant"] = {
        "id": "grant",
        "user_id": STUDENT_ID,
        "proof_session_id": session_id,
        "access_request_id": access_request_id,
        "revoked_at": datetime.now(UTC),
    }
    return {
        "session_id": session_id,
        "passport_id": passport_id,
        "requester_profile_id": requester_profile_id,
        "access_request_id": access_request_id,
    }


def test_create_quality_review_case(admin_client: TestClient, mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    response = admin_client.post(
        "/api/v1/admin/quality-review/cases",
        json={
            "user_id": STUDENT_ID,
            "proof_session_id": ids["session_id"],
            "case_type": "manual_review",
            "priority": "high",
            "title": "Manual review",
            "summary": "Review this evidence package.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["case_type"] == "manual_review"
    assert body["priority"] == "high"
    assert len(mem_store["admin_quality_review_events"]) == 1


def test_duplicate_open_case_not_created_for_same_session_and_type(mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    service = AdminQualityReviewService(mem_store)
    first = service.create_cases_from_existing_signals(proof_session_id=ids["session_id"])
    second = service.create_cases_from_existing_signals(proof_session_id=ids["session_id"])
    assert first.created_count >= 1
    assert second.created_count == 0
    assert second.existing_count >= 1


def test_list_cases_with_filters_works(admin_client: TestClient, mem_store: dict) -> None:
    _seed_signals(mem_store)
    AdminQualityReviewService(mem_store).create_cases_from_existing_signals()
    response = admin_client.get("/api/v1/admin/quality-review/cases?case_type=privacy_flag&status=open")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["case_type"] == "privacy_flag"


def test_get_case_works(admin_client: TestClient, mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    created = admin_client.post(
        "/api/v1/admin/quality-review/cases",
        json={"user_id": STUDENT_ID, "proof_session_id": ids["session_id"], "case_type": "manual_review"},
    ).json()
    response = admin_client.get(f"/api/v1/admin/quality-review/cases/{created['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]
    assert response.json()["events"]


def test_update_case_status_and_decision_works(admin_client: TestClient, mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    created = admin_client.post(
        "/api/v1/admin/quality-review/cases",
        json={"user_id": STUDENT_ID, "proof_session_id": ids["session_id"], "case_type": "manual_review"},
    ).json()
    response = admin_client.patch(
        f"/api/v1/admin/quality-review/cases/{created['id']}",
        json={
            "status": "resolved",
            "decision": "safe_for_sharing",
            "decision_reason": "Reviewed by admin.",
            "admin_notes": "Looks safe.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "resolved"
    assert body["decision"] == "safe_for_sharing"
    assert body["resolved_at"] is not None


def test_add_event_works(admin_client: TestClient, mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    created = admin_client.post(
        "/api/v1/admin/quality-review/cases",
        json={"user_id": STUDENT_ID, "proof_session_id": ids["session_id"], "case_type": "manual_review"},
    ).json()
    response = admin_client.post(
        f"/api/v1/admin/quality-review/cases/{created['id']}/events",
        json={"event_type": "admin_note_added", "event_summary": "Need a second look."},
    )
    assert response.status_code == 201, response.text
    assert response.json()["event_type"] == "admin_note_added"


def test_scan_creates_privacy_low_confidence_and_recruiter_cases(
    admin_client: TestClient,
    mem_store: dict,
) -> None:
    _seed_signals(mem_store)
    response = admin_client.post("/api/v1/admin/quality-review/scan", json={})
    assert response.status_code == 200, response.text
    case_types = {case["case_type"] for case in response.json()["cases"]}
    assert "privacy_flag" in case_types
    assert "low_confidence_ai_review" in case_types
    assert "recruiter_risk" in case_types
    assert "access_abuse" in case_types


def test_student_notification_created_for_attention_decisions(admin_client: TestClient, mem_store: dict) -> None:
    ids = _seed_signals(mem_store)
    created = admin_client.post(
        "/api/v1/admin/quality-review/cases",
        json={"user_id": STUDENT_ID, "proof_session_id": ids["session_id"], "case_type": "privacy_flag"},
    ).json()
    response = admin_client.patch(
        f"/api/v1/admin/quality-review/cases/{created['id']}",
        json={"decision": "privacy_blocked", "status": "needs_student_action"},
    )
    assert response.status_code == 200, response.text
    notifications = list(mem_store.get("notification_events", {}).values())
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Evidence review needs attention"
    assert notifications[0]["category"] == "privacy"
    assert notifications[0]["priority"] == "high"
    assert notifications[0]["metadata"]["case_id"] == created["id"]


def test_normal_student_cannot_access_admin_quality_review(
    student_client: TestClient,
    mem_store: dict,
) -> None:
    _seed_signals(mem_store)
    response = student_client.get("/api/v1/admin/quality-review/cases")
    assert response.status_code == 403


def test_no_project_specific_hardcoding() -> None:
    import app.services.admin_quality_review_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
