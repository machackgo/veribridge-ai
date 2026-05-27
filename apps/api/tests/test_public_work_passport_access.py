"""Tests for Public Work Passport and protected evidence access backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.public_work_passport_service import PublicWorkPassportService


USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000042"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_session(client: TestClient, mem_store: dict, user_id: str = USER_ID, evidence_id: str = EVIDENCE_ID) -> str:
    mem_store.setdefault("users", {})[user_id] = {
        "id": user_id,
        "email": "student@example.edu",
        "role": "student",
        "status": "active",
    }
    mem_store.setdefault("student_profiles", {})[f"profile-{user_id}"] = {
        "id": f"profile-{user_id}",
        "user_id": user_id,
        "full_name": "Ada Student",
        "major": "Computer Science",
        "preferences": {"show_public_name": True},
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": "Machine Learning",
        "evidence_type": "project",
        "evidence_url": "https://example.edu/project",
        "repository_url": "https://github.com/example/project",
        "evidence_description": "Machine Learning project evidence",
        "metadata": {"field": "Computer Science", "evidence_title": "ML Evidence Passport"},
        "verification_status": "verified",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    response = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": evidence_id},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    mem_store["extension_proof_sessions"][session_id]["status"] = "uploaded_pending_analysis"
    _seed_evidence(mem_store, session_id, user_id)
    return session_id


def _seed_evidence(mem_store: dict, session_id: str, user_id: str = USER_ID) -> None:
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "reviewer_name": "Astra",
        "reviewer_role": "CS / AI / Data Science AI Reviewer",
        "domain": "cs_ai",
        "ai_domain_review_status": "ai_domain_reviewed",
        "domain_review_score": 91,
        "confidence_level": "high",
        "verified_skills": ["Machine Learning"],
        "partially_verified_skills": ["Python"],
        "skills_needing_more_evidence": ["MLOps"],
        "recruiter_summary": "Reviewed by VeriBridge AI Domain Reviewer Astra using a field-specific rubric.",
        "review_limitations": "AI review limitations.",
        "disclosure_note": "AI Domain Reviewed; human review not completed.",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    # verification_review_requests does not exist in production;
    # ai_domain_review_results is the canonical source (seeded above).
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": ["Python"],
        "risk_flags": [],
        "recruiter_summary": "Workflow evidence supports the project claim.",
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "success",
        "matched_claimed_skills": ["Machine Learning"],
        "weakly_matched_claimed_skills": ["Python"],
        "repo_url": "https://github.com/example/project",
        "private_internal_note": "ok",
    }
    mem_store.setdefault("live_website_check_results", {})[f"live-{session_id}"] = {
        "id": f"live-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "is_reachable": True,
        "status_code": 200,
        "url": "https://example.edu/project",
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})[f"privacy-{session_id}"] = {
        "id": f"privacy-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "clean",
        "scan_summary": "No sensitive data found.",
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "media_storage_path": "private/defense/audio.webm",
        "media_url": "https://storage.example/private/audio.webm",
        "transcript_text": "This is the full private transcript explaining implementation details.",
        "transcript_summary": "Student explained project ownership and model tradeoffs.",
        "skills_mentioned": ["Machine Learning"],
        "skills_explained_well": ["Machine Learning"],
        "overall_defense_score": 88,
        "recruiter_summary": "Defense supports ownership.",
        "risk_flags": [],
    }


def _create_passport(client: TestClient, session_id: str) -> dict:
    response = client.post(f"/api/v1/student/extension-proof/sessions/{session_id}/passport")
    assert response.status_code == 200, response.text
    return response.json()


def _request_access(
    client: TestClient,
    slug: str,
    sections: list[str] | None = None,
    *,
    requester_email: str = "recruiter@example.com",
    requester_organization: str | None = "Example Co",
    requester_role: str | None = "recruiter",
    request_reason: str | None = "Review candidate evidence",
) -> dict:
    response = client.post(
        f"/api/v1/public/passports/{slug}/request-access",
        json={
            "requester_name": "Recruiter Person",
            "requester_email": requester_email,
            "requester_organization": requester_organization,
            "requester_role": requester_role,
            "request_reason": request_reason,
            "requested_sections": sections or ["github_analysis", "project_defense_transcript"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _events(mem_store: dict, event_type: str) -> list[dict]:
    return [
        event
        for event in mem_store.get("evidence_access_audit_events", {}).values()
        if event["event_type"] == event_type
    ]


def _notifications(mem_store: dict, event_type: str) -> list[dict]:
    return [
        event
        for event in mem_store.get("notification_events", {}).values()
        if event["event_type"] == event_type
    ]


def test_student_can_create_passport(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    body = _create_passport(client, session_id)
    assert body["proof_session_id"] == session_id
    assert body["public_slug"]
    assert body["is_public"] is True
    events = _events(mem_store, "passport_created")
    assert len(events) == 1
    assert events[0]["user_id"] == USER_ID
    assert events[0]["proof_session_id"] == session_id
    assert events[0]["passport_id"] == body["id"]


def test_public_passport_can_be_fetched_by_slug(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    response = client.get(
        f"/api/v1/public/passports/{passport['public_slug']}",
        headers={"user-agent": "pytest browser", "x-forwarded-for": "203.0.113.10"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["public_slug"] == passport["public_slug"]
    assert body["ai_domain_reviewer_name"] == "Astra"
    assert body["readiness_score"] >= 80
    view_events = list(mem_store.get("public_passport_view_events", {}).values())
    assert len(view_events) == 1
    assert view_events[0]["passport_id"] == passport["id"]
    assert view_events[0]["public_slug"] == passport["public_slug"]
    assert view_events[0]["ip_hash"]
    assert view_events[0]["user_agent_hash"]
    assert "203.0.113.10" not in str(view_events[0])
    assert "pytest browser" not in str(view_events[0])


def test_public_passport_does_not_expose_private_media_or_transcript(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    body = client.get(f"/api/v1/public/passports/{passport['public_slug']}").json()
    serialized = str(body)
    assert "media_storage_path" not in serialized
    assert "media_url" not in serialized
    assert "private/defense/audio.webm" not in serialized
    assert "full private transcript" not in serialized
    assert "access_token" not in serialized
    assert "private_internal_note" not in serialized


def test_recruiter_can_request_access(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    body = _request_access(client, passport["public_slug"])
    assert body["status"] == "pending"
    listing = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/access-requests")
    assert listing.status_code == 200
    assert listing.json()[0]["requester_email"] == "recruiter@example.com"
    events = _events(mem_store, "access_requested")
    assert len(events) == 1
    assert events[0]["access_request_id"] == body["id"]
    assert events[0]["actor_type"] == "recruiter"
    assert events[0]["actor_email"] == "recruiter@example.com"
    notifications = _notifications(mem_store, "access_request_received")
    assert len(notifications) == 1
    assert notifications[0]["recipient_email"] == "student@example.edu"
    assert notifications[0]["status"] == "pending"
    assert notifications[0]["title"] == "New evidence access request"
    assert notifications[0]["category"] == "access_request"
    assert notifications[0]["priority"] == "high"
    assert "Recruiter Person from Example Co requested access" in notifications[0]["message"]
    profile = next(iter(mem_store["recruiter_requester_profiles"].values()))
    assert listing.json()[0]["requester_profile_id"] == profile["id"]
    assert profile["email"] == "recruiter@example.com"
    assert profile["organization_domain"] == "example.com"
    assert profile["total_access_requests"] == 1
    assert events[0]["metadata"]["requester_profile_id"] == profile["id"]
    assert events[0]["metadata"]["organization_domain"] == "example.com"
    assert notifications[0]["metadata"]["requester_profile_id"] == profile["id"]
    assert notifications[0]["metadata"]["requester_email"] == "recruiter@example.com"
    assert notifications[0]["metadata"]["organization"] == "Example Co"
    assert "requester_identity" in notifications[0]["metadata"]
    assert notifications[0]["metadata"]["requester_identity"]["requester_profile_id"] == profile["id"]


def test_access_request_normalizes_email_and_reuses_requester_profile(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    first = _request_access(client, passport["public_slug"], requester_email="Recruiter@Example.COM")
    second = _request_access(client, passport["public_slug"], requester_email=" recruiter@example.com ")
    profiles = list(mem_store["recruiter_requester_profiles"].values())
    assert len(profiles) == 1
    assert profiles[0]["email"] == "recruiter@example.com"
    assert profiles[0]["total_access_requests"] == 2
    assert mem_store["evidence_access_requests"][first["id"]]["requester_profile_id"] == profiles[0]["id"]
    assert mem_store["evidence_access_requests"][second["id"]]["requester_profile_id"] == profiles[0]["id"]


def test_requester_profile_risk_flags_for_free_email_missing_fields_and_repeated_requests(
    client: TestClient,
    mem_store: dict,
) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    for _ in range(4):
        _request_access(
            client,
            passport["public_slug"],
            requester_email="reviewer@gmail.com",
            requester_organization=None,
            request_reason=None,
        )
    profile = next(iter(mem_store["recruiter_requester_profiles"].values()))
    assert profile["organization_domain"] == "gmail.com"
    assert profile["domain_verified"] is False
    assert profile["email_verified"] is False
    assert profile["verification_status"] == "unverified"
    assert "free_email_domain" in profile["risk_flags"]
    assert "missing_organization" in profile["risk_flags"]
    assert "missing_reason" in profile["risk_flags"]
    assert "repeated_requests" in profile["risk_flags"]
    assert profile["risk_score"] == 40


def test_student_can_approve_request_and_grant_token_is_created(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    response = client.post(f"/api/v1/student/access-requests/{request['id']}/approve")
    assert response.status_code == 200, response.text
    grant = response.json()
    assert grant["access_token"].startswith("vbpa_")
    assert grant["granted_sections"] == ["github_analysis"]
    assert len(_events(mem_store, "access_approved")) == 1
    granted_events = _events(mem_store, "access_granted")
    assert len(granted_events) == 1
    assert granted_events[0]["access_grant_id"] == grant["id"]
    notifications = _notifications(mem_store, "access_approved")
    assert len(notifications) == 1
    assert notifications[0]["recipient_email"] == "student@example.edu"
    assert notifications[0]["title"] == "Evidence access approved"
    assert notifications[0]["category"] == "access_decision"
    assert notifications[0]["priority"] == "normal"
    profile = next(iter(mem_store["recruiter_requester_profiles"].values()))
    assert profile["approved_access_requests"] == 1


def test_denied_request_does_not_create_grant(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"])
    response = client.post(f"/api/v1/student/access-requests/{request['id']}/deny")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "denied"
    assert mem_store.get("evidence_access_grants", {}) == {}
    events = _events(mem_store, "access_denied")
    assert len(events) == 1
    assert events[0]["access_request_id"] == request["id"]
    notifications = _notifications(mem_store, "access_denied")
    assert len(notifications) == 1
    assert notifications[0]["recipient_email"] == "student@example.edu"
    assert notifications[0]["title"] == "Evidence access denied"
    assert notifications[0]["category"] == "access_decision"
    profile = next(iter(mem_store["recruiter_requester_profiles"].values()))
    assert profile["denied_access_requests"] == 1


def test_revoked_grant_blocks_access(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    grant = client.post(f"/api/v1/student/access-requests/{request['id']}/approve").json()
    revoke = client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")
    assert revoke.status_code == 200, revoke.text
    events = _events(mem_store, "access_revoked")
    assert len(events) == 1
    assert events[0]["access_grant_id"] == grant["id"]
    notifications = _notifications(mem_store, "access_revoked")
    assert len(notifications) == 1
    assert notifications[0]["recipient_email"] == "student@example.edu"
    assert notifications[0]["title"] == "Evidence access revoked"
    assert notifications[0]["category"] == "access_decision"
    protected = client.get(f"/api/v1/public/access/{grant['access_token']}/evidence")
    assert protected.status_code == 403


def test_expired_grant_blocks_access(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    expired = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    grant = client.post(
        f"/api/v1/student/access-requests/{request['id']}/approve",
        json={"expires_at": expired},
    ).json()
    protected = client.get(f"/api/v1/public/access/{grant['access_token']}/evidence")
    assert protected.status_code == 403
    assert len(_events(mem_store, "access_expired")) == 1


def test_access_token_returns_only_granted_sections(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    grant = client.post(f"/api/v1/student/access-requests/{request['id']}/approve").json()
    protected = client.get(f"/api/v1/public/access/{grant['access_token']}/evidence")
    assert protected.status_code == 200, protected.text
    body = protected.json()
    assert list(body["evidence"].keys()) == ["github_analysis"]
    serialized = str(body)
    assert "transcript_text" not in serialized
    assert "media_storage_path" not in serialized
    assert "access_token" not in serialized
    assert "private_internal_note" not in serialized
    viewed_events = _events(mem_store, "protected_evidence_viewed")
    assert len(viewed_events) == 1
    assert viewed_events[0]["access_grant_id"] == grant["id"]
    assert viewed_events[0]["metadata"]["viewed_sections"] == ["github_analysis"]


def test_access_token_can_return_granted_transcript_without_media_or_unrelated_sections(
    client: TestClient,
    mem_store: dict,
) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["project_defense_transcript"])
    grant = client.post(f"/api/v1/student/access-requests/{request['id']}/approve").json()
    protected = client.get(f"/api/v1/public/access/{grant['access_token']}/evidence")
    assert protected.status_code == 200, protected.text
    body = protected.json()
    assert list(body["evidence"].keys()) == ["project_defense_transcript"]
    assert body["granted_sections"] == ["project_defense_transcript"]
    serialized = str(body)
    assert "full private transcript" in serialized
    assert "media_storage_path" not in serialized
    assert "github_analysis" not in body["evidence"]


def test_student_access_requesters_returns_only_profiles_linked_to_student(
    client: TestClient,
    mem_store: dict,
) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    _request_access(client, passport["public_slug"], requester_email="first@example.com")

    other_evidence_id = "eeeeeeee-0000-0000-0000-000000000099"
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    other_session_id = _make_session(client, mem_store, OTHER_USER_ID, other_evidence_id)
    other_passport = _create_passport(client, other_session_id)
    _request_access(client, other_passport["public_slug"], requester_email="second@example.org")

    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    response = client.get("/api/v1/student/access-requesters")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["email"] for row in rows] == ["first@example.com"]
    assert rows[0]["organization_domain"] == "example.com"


def test_student_cannot_see_requester_profiles_for_another_student(
    client: TestClient,
    mem_store: dict,
) -> None:
    other_evidence_id = "eeeeeeee-0000-0000-0000-000000000098"
    app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID
    other_session_id = _make_session(client, mem_store, OTHER_USER_ID, other_evidence_id)
    other_passport = _create_passport(client, other_session_id)
    _request_access(client, other_passport["public_slug"], requester_email="other@example.org")

    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    response = client.get("/api/v1/student/access-requesters")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_admin_can_update_requester_verification_status(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    _request_access(client, passport["public_slug"])
    profile = next(iter(mem_store["recruiter_requester_profiles"].values()))
    # Grant admin role so the admin endpoint auth check passes.
    mem_store.setdefault("users", {})[USER_ID]["role"] = "admin"
    response = client.post(
        f"/api/v1/admin/recruiter-requesters/{profile['id']}/verification-status",
        json={"verification_status": "trusted", "domain_verified": True, "email_verified": True, "notes": "Reviewed."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_status"] == "trusted"
    assert body["domain_verified"] is True
    assert body["email_verified"] is True


def test_no_project_specific_hardcoding() -> None:
    import inspect

    source = inspect.getsource(PublicWorkPassportService).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
