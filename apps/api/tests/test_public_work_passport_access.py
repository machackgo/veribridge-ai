"""Tests for Public Work Passport and protected evidence access backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.public_work_passport_service import PublicWorkPassportService


USER_ID = "00000000-0000-0000-0000-000000000042"
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


def _make_session(client: TestClient, mem_store: dict) -> str:
    mem_store.setdefault("student_profiles", {})["profile"] = {
        "id": "profile",
        "user_id": USER_ID,
        "full_name": "Ada Student",
        "major": "Computer Science",
        "preferences": {"show_public_name": True},
    }
    mem_store.setdefault("skill_evidence", {})[EVIDENCE_ID] = {
        "id": EVIDENCE_ID,
        "user_id": USER_ID,
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
        json={"skill_evidence_id": EVIDENCE_ID},
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    mem_store["extension_proof_sessions"][session_id]["status"] = "uploaded_pending_analysis"
    _seed_evidence(mem_store, session_id)
    return session_id


def _seed_evidence(mem_store: dict, session_id: str) -> None:
    mem_store.setdefault("ai_domain_review_results", {})["domain"] = {
        "id": "domain",
        "user_id": USER_ID,
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
    mem_store.setdefault("verification_review_requests", {})["review"] = {
        "id": "review",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "ai_review_status": "ai_approved_for_sharing",
        "readiness_score": 90,
        "readiness_level": "strong",
    }
    mem_store.setdefault("workflow_analysis_results", {})["workflow"] = {
        "id": "workflow",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "supported_skills": ["Machine Learning"],
        "weakly_supported_skills": ["Python"],
        "risk_flags": [],
        "recruiter_summary": "Workflow evidence supports the project claim.",
    }
    mem_store.setdefault("extension_proof_github_analysis", {})["github"] = {
        "id": "github",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "status": "success",
        "matched_claimed_skills": ["Machine Learning"],
        "weakly_matched_claimed_skills": ["Python"],
        "repo_url": "https://github.com/example/project",
        "private_internal_note": "ok",
    }
    mem_store.setdefault("live_website_check_results", {})["live"] = {
        "id": "live",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "is_reachable": True,
        "status_code": 200,
        "url": "https://example.edu/project",
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})["privacy"] = {
        "id": "privacy",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "status": "clean",
        "scan_summary": "No sensitive data found.",
    }
    mem_store.setdefault("project_defense_analysis_results", {})["defense"] = {
        "id": "defense",
        "user_id": USER_ID,
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


def _request_access(client: TestClient, slug: str, sections: list[str] | None = None) -> dict:
    response = client.post(
        f"/api/v1/public/passports/{slug}/request-access",
        json={
            "requester_name": "Recruiter Person",
            "requester_email": "recruiter@example.com",
            "requester_organization": "Example Co",
            "requester_role": "recruiter",
            "request_reason": "Review candidate evidence",
            "requested_sections": sections or ["github_analysis", "project_defense_transcript"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_student_can_create_passport(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    body = _create_passport(client, session_id)
    assert body["proof_session_id"] == session_id
    assert body["public_slug"]
    assert body["is_public"] is True


def test_public_passport_can_be_fetched_by_slug(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    response = client.get(f"/api/v1/public/passports/{passport['public_slug']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["public_slug"] == passport["public_slug"]
    assert body["ai_domain_reviewer_name"] == "Astra"
    assert body["readiness_score"] >= 80


def test_public_passport_does_not_expose_private_media_or_transcript(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    body = client.get(f"/api/v1/public/passports/{passport['public_slug']}").json()
    serialized = str(body)
    assert "media_storage_path" not in serialized
    assert "private/defense/audio.webm" not in serialized
    assert "full private transcript" not in serialized


def test_recruiter_can_request_access(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    body = _request_access(client, passport["public_slug"])
    assert body["status"] == "pending"
    listing = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/access-requests")
    assert listing.status_code == 200
    assert listing.json()[0]["requester_email"] == "recruiter@example.com"


def test_student_can_approve_request_and_grant_token_is_created(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    response = client.post(f"/api/v1/student/access-requests/{request['id']}/approve")
    assert response.status_code == 200, response.text
    grant = response.json()
    assert grant["access_token"].startswith("vbpa_")
    assert grant["granted_sections"] == ["github_analysis"]


def test_denied_request_does_not_create_grant(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"])
    response = client.post(f"/api/v1/student/access-requests/{request['id']}/deny")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "denied"
    assert mem_store.get("evidence_access_grants", {}) == {}


def test_revoked_grant_blocks_access(client: TestClient, mem_store: dict) -> None:
    session_id = _make_session(client, mem_store)
    passport = _create_passport(client, session_id)
    request = _request_access(client, passport["public_slug"], ["github_analysis"])
    grant = client.post(f"/api/v1/student/access-requests/{request['id']}/approve").json()
    revoke = client.post(f"/api/v1/student/access-grants/{grant['id']}/revoke")
    assert revoke.status_code == 200, revoke.text
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


def test_no_project_specific_hardcoding() -> None:
    import inspect

    source = inspect.getsource(PublicWorkPassportService).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
