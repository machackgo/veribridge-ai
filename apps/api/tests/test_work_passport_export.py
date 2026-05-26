"""Tests for Work Passport export backend."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.work_passport_export_service import WorkPassportExportService


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


def _seed_export_context(mem_store: dict, *, user_id: str = USER_ID, public: bool = True) -> dict[str, str]:
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    passport_id = str(uuid4())
    version_id = str(uuid4())
    profile_id = str(uuid4())

    mem_store.setdefault("users", {})[user_id] = {
        "id": user_id,
        "email": f"student-{user_id[-4:]}@example.edu",
    }
    mem_store.setdefault("student_profiles", {})[profile_id] = {
        "id": profile_id,
        "user_id": user_id,
        "full_name": "Avery Student",
        "university": "VeriBridge University",
        "degree": "BS",
        "major": "Computer Science",
        "graduation_year": 2026,
        "visa_status": None,
        "target_roles": ["Backend Engineer"],
        "target_locations": ["Remote"],
        "github_url": "https://github.com/example/project",
        "linkedin_url": "https://linkedin.com/in/example",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": "FastAPI",
        "evidence_url": "https://example.edu/project",
        "claimed_skills": ["FastAPI", "React"],
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "skill_evidence_id": evidence_id,
        "status": "completed",
        "website_url": "https://example.edu/project",
        "github_url": "https://github.com/example/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "claimed_skills": ["FastAPI", "React"],
        "supported_skills": ["FastAPI"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})[f"privacy-{session_id}"] = {
        "id": f"privacy-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "clean",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("live_website_check_results", {})[f"live-{session_id}"] = {
        "id": f"live-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "is_reachable": True,
        "website_url": "https://example.edu/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "matched_claimed_skills": ["FastAPI"],
        "weakly_matched_claimed_skills": ["React"],
        "repository_url": "https://github.com/example/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "skills_explained_well": ["FastAPI"],
        "skills_mentioned": ["React"],
        "overall_defense_score": 88,
        "transcript_summary": "Explains API design and delivery.",
        "transcript_text": "Private transcript that must not leak.",
        "media_storage_path": "private/project-defense/audio.webm",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "verified_skills": ["FastAPI"],
        "partially_verified_skills": ["React"],
        "domain_review_score": 92,
        "confidence_level": "high",
        "reviewer_name": "Generalist AI Reviewer",
        "recruiter_summary": "Strong support across backend and frontend evidence.",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("proof_evidence_versions", {})[version_id] = {
        "id": version_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "version_number": 2,
        "version_label": "Version 2",
        "status": "submitted",
        "change_summary": "Refined the evidence package.",
        "resubmission_reason": "Address feedback",
        "is_active": True,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "public_slug": "export-passport",
        "is_public": public,
        "public_title": "Safe Work Passport",
        "public_summary": "Safe shareable summary.",
        "field": "Computer Science",
        "visible_sections": ["summary", "skills"],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "access_token": "passport-secret-token",
        "media_storage_path": "private/passport/media.png",
    }
    return {
        "session_id": session_id,
        "passport_id": passport_id,
        "version_id": version_id,
        "evidence_id": evidence_id,
    }


def _seed_grant(mem_store: dict, *, user_id: str = USER_ID, session_id: str, passport_id: str, requester_email: str = "recruiter@example.com", sections: list[str] | None = None, revoked_at: str | None = None, expires_at: datetime | None = None) -> str:
    request_id = str(uuid4())
    grant_id = str(uuid4())
    access_token = "grant-token"
    mem_store.setdefault("evidence_access_requests", {})[request_id] = {
        "id": request_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "requester_profile_id": None,
        "requester_name": "Recruiter Person",
        "requester_email": requester_email,
        "requester_organization": "Example Org",
        "requester_role": "recruiter",
        "request_reason": "Review candidate",
        "status": "approved",
        "requested_sections": sections or ["github_analysis", "project_defense_summary"],
        "decision_notes": None,
        "decided_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("evidence_access_grants", {})[grant_id] = {
        "id": grant_id,
        "access_request_id": request_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "requester_email": requester_email,
        "granted_sections": sections or ["github_analysis", "project_defense_summary"],
        "access_token": access_token,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "revoked_at": revoked_at,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return access_token


def test_student_can_generate_export_for_own_session(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)

    response = client.post(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export")

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["verification_disclaimer"].startswith("This Work Passport uses VeriBridge AI")
    assert payload["passport_status"]["overall_status"] in {"ai_domain_reviewed", "public_passport_active", "evidence_collected"}
    assert payload["skills"]
    assert payload["evidence_summary"]
    assert len(mem_store["work_passport_exports"]) == 1


def test_student_cannot_export_another_students_session(client: TestClient, mem_store: dict) -> None:
    other_ids = _seed_export_context(mem_store, user_id=OTHER_USER_ID)

    response = client.post(f"/api/v1/student/extension-proof/sessions/{other_ids['session_id']}/export")

    assert response.status_code == 404


def test_latest_export_endpoint_returns_newest_export(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)

    first = client.post(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export")
    assert first.status_code == 201, first.text
    mem_store["proof_evidence_versions"][ids["version_id"]]["change_summary"] = "Second export change summary."
    mem_store["proof_evidence_versions"][ids["version_id"]]["updated_at"] = datetime.now(UTC).isoformat()
    second = client.post(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export")
    assert second.status_code == 201, second.text

    latest = client.get(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export/latest")

    assert latest.status_code == 200, latest.text
    assert latest.json() == second.json()
    assert len(mem_store["work_passport_exports"]) == 2


def test_public_export_excludes_private_transcript_media_and_tokens(client: TestClient, mem_store: dict) -> None:
    _seed_export_context(mem_store)

    response = client.get("/api/v1/public/passports/export-passport/export")

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json()).lower()
    assert "private transcript" not in serialized
    assert "media_storage_path" not in serialized
    assert "passport-secret-token" not in serialized
    assert "admin notes" not in serialized
    assert response.json()["export_metadata"]["export_type"] == "public"


def test_protected_export_requires_valid_access_token(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)
    _seed_grant(mem_store, session_id=ids["session_id"], passport_id=ids["passport_id"], sections=["github_analysis"])

    response = client.get("/api/v1/public/access/grant-token/export")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["access_and_privacy"]["public_safe"] is False
    assert any("github" in skill["evidence_sources"] for skill in payload["skills"])
    assert not any("project_defense" in skill["evidence_sources"] for skill in payload["skills"])
    assert "grant-token" not in json.dumps(payload).lower()


def test_revoked_grant_blocks_protected_export(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)
    _seed_grant(
        mem_store,
        session_id=ids["session_id"],
        passport_id=ids["passport_id"],
        sections=["github_analysis"],
        revoked_at=datetime.now(UTC).isoformat(),
    )

    response = client.get("/api/v1/public/access/grant-token/export")

    assert response.status_code == 403


def test_expired_grant_blocks_protected_export(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)
    _seed_grant(
        mem_store,
        session_id=ids["session_id"],
        passport_id=ids["passport_id"],
        sections=["github_analysis"],
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    response = client.get("/api/v1/public/access/grant-token/export")

    assert response.status_code == 403


def test_export_payload_includes_expected_summaries(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)

    response = client.post(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export")

    payload = response.json()
    assert "passport_status" in payload
    assert "skill_evidence_summary" in payload["passport_status"]
    assert payload["versions"]["active_version_number"] == 2
    assert payload["versions"]["latest_change_summary"] == "Refined the evidence package."
    assert payload["export_metadata"]["limitations"]


def test_no_human_verified_claimed_automatically(client: TestClient, mem_store: dict) -> None:
    ids = _seed_export_context(mem_store)

    response = client.post(f"/api/v1/student/extension-proof/sessions/{ids['session_id']}/export")

    assert "human_verified" not in json.dumps(response.json()).lower()


def test_no_project_specific_hardcoding() -> None:
    source = inspect.getsource(WorkPassportExportService).lower()

    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source
