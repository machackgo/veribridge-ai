"""Tests for centralized Work Passport status orchestration."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.work_passport_status_service import WorkPassportStatusService


USER_ID = "00000000-0000-0000-0000-000000000042"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000099"
ADMIN_USER_ID = "00000000-0000-0000-0000-000000000007"


@pytest.fixture()
def mem_store() -> dict:
    return {"users": {ADMIN_USER_ID: {"id": ADMIN_USER_ID, "role": "admin"}}}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_session(mem_store: dict, *, user_id: str = USER_ID, status: str = "created") -> str:
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": "Data analysis",
        "evidence_url": "https://example.edu/project",
        "claimed_skills": ["Data analysis", "Technical writing"],
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "skill_evidence_id": evidence_id,
        "status": status,
        "website_url": "https://example.edu/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    return session_id


def _seed_clean_evidence(mem_store: dict, session_id: str, *, user_id: str = USER_ID) -> None:
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "completed",
        "claimed_skills": ["Data analysis", "Technical writing"],
        "supported_skills": ["Data analysis", "Technical writing"],
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})[f"privacy-{session_id}"] = {
        "id": f"privacy-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "clean",
    }
    mem_store.setdefault("live_website_check_results", {})[f"live-{session_id}"] = {
        "id": f"live-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "is_reachable": True,
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "success",
        "matched_claimed_skills": ["Data analysis", "Technical writing"],
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "overall_defense_score": 88,
        "transcript_summary": "Explains project decisions clearly.",
        "transcript_text": "Private detailed transcript should not appear in public status.",
        "media_storage_path": "private/project-defense/video.webm",
    }


def _seed_ai_domain(mem_store: dict, session_id: str, *, user_id: str = USER_ID) -> None:
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "ai_domain_review_status": "ai_domain_reviewed",
        "reviewer_name": "Generalist AI Reviewer",
        "domain_review_score": 91,
        "confidence_level": "high",
        "recruiter_summary": "Evidence shows strong project ownership across the submitted skills.",
    }


def _seed_passport(mem_store: dict, session_id: str, *, user_id: str = USER_ID, slug: str = "status-passport") -> str:
    passport_id = str(uuid4())
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "public_slug": slug,
        "is_public": True,
        "public_summary": "Public-safe evidence summary.",
        "access_token": "internal-token-that-must-not-leak",
        "media_storage_path": "private/passport/media.png",
    }
    return passport_id


def _get_status(client: TestClient, session_id: str) -> dict:
    response = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/work-passport-status")
    assert response.status_code == 200, response.text
    return response.json()


def test_status_for_draft_session(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "draft"
    assert payload["proof_session_id"] == session_id
    assert "create_evidence_version" in payload["missing_steps"]
    assert "human_verified" not in json.dumps(payload).lower()


def test_status_after_evidence_exists_but_no_ai_domain_review(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)

    payload = _get_status(client, session_id)

    assert payload["ai_domain_review_status"] is None
    assert "no_domain_review_yet" in {warning["code"] for warning in payload["warnings"]}
    assert "workflow_recorded" in payload["completed_steps"]


def test_status_when_privacy_flagged(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    mem_store["workflow_privacy_scan_results"][f"privacy-{session_id}"]["status"] = "flagged"

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "privacy_review_required"
    assert "privacy_flagged" in {issue["code"] for issue in payload["blocking_issues"]}


def test_status_when_ai_domain_review_is_strong(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    _seed_ai_domain(mem_store, session_id)

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "ai_domain_reviewed"
    assert payload["ai_domain_review_score"] == 91
    assert payload["ai_domain_reviewer_name"] == "Generalist AI Reviewer"


def test_status_when_admin_case_open(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    mem_store.setdefault("admin_quality_review_cases", {})["case-1"] = {
        "id": "case-1",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "case_type": "manual_review",
        "status": "open",
        "summary": "Internal review is pending.",
    }

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "admin_review_pending"
    assert payload["open_admin_case_count"] == 1
    assert "admin_case_open" in {issue["code"] for issue in payload["blocking_issues"]}


def test_status_when_public_passport_active(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    _seed_ai_domain(mem_store, session_id)
    _seed_passport(mem_store, session_id, slug="public-active-status")

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "public_passport_active"
    assert payload["public_slug"] == "public-active-status"


def test_status_when_access_requests_pending(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    _seed_ai_domain(mem_store, session_id)
    passport_id = _seed_passport(mem_store, session_id)
    mem_store.setdefault("evidence_access_requests", {})["request-1"] = {
        "id": "request-1",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "status": "pending",
        "requester_email": "reviewer@example.org",
    }

    payload = _get_status(client, session_id)

    assert payload["overall_status"] == "access_requests_pending"
    assert payload["pending_access_request_count"] == 1


def test_status_when_active_evidence_version_exists(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    version_id = str(uuid4())
    mem_store.setdefault("proof_evidence_versions", {})[version_id] = {
        "id": version_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "version_number": 2,
        "status": "submitted",
        "is_active": True,
    }

    payload = _get_status(client, session_id)

    assert payload["active_version_id"] == version_id
    assert payload["active_version_number"] == 2
    assert "active_version_available" in payload["completed_steps"]


def test_student_cannot_access_another_students_status(client: TestClient, mem_store: dict) -> None:
    other_session_id = _seed_session(mem_store, user_id=OTHER_USER_ID, status="completed")

    response = client.get(f"/api/v1/student/extension-proof/sessions/{other_session_id}/work-passport-status")

    assert response.status_code == 404


def test_public_status_endpoint_excludes_private_and_internal_fields(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    _seed_ai_domain(mem_store, session_id)
    _seed_passport(mem_store, session_id, slug="public-safe-status")
    mem_store.setdefault("admin_quality_review_cases", {})["case-private"] = {
        "id": "case-private",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "case_type": "manual_review",
        "status": "open",
        "admin_notes": "Internal notes should stay private.",
    }

    response = client.get("/api/v1/public/passports/public-safe-status/status")

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json()).lower()
    assert "media_storage_path" not in serialized
    assert "private detailed transcript" not in serialized
    assert "internal-token-that-must-not-leak" not in serialized
    assert "internal notes" not in serialized
    assert "blocking_issues" not in response.json()


def test_admin_status_includes_internal_blocking_issues(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    mem_store.setdefault("admin_quality_review_cases", {})["case-admin"] = {
        "id": "case-admin",
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "case_type": "manual_review",
        "status": "open",
        "summary": "Internal review is pending.",
    }
    app.dependency_overrides[get_current_user_id] = lambda: ADMIN_USER_ID

    response = client.get(f"/api/v1/admin/quality-review/sessions/{session_id}/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["open_admin_case_count"] == 1
    assert "admin_case_open" in {issue["code"] for issue in payload["blocking_issues"]}


def test_no_project_specific_hardcoding() -> None:
    source = inspect.getsource(WorkPassportStatusService).lower()

    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source


def test_status_does_not_crash_when_no_ai_domain_review_exists(client: TestClient, mem_store: dict) -> None:
    """Regression: work-passport-status must return 200 even when ai_domain_review_results is empty.

    Before the fix, the service queried verification_review_requests (nonexistent table),
    which caused a 500 from PostgREST. After the fix it uses ai_domain_review_results only
    and gracefully returns None fields when no review row exists.
    """
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    # Explicitly omit any ai_domain_review_results row

    payload = _get_status(client, session_id)

    assert payload["overall_status"] in {"evidence_collected", "ai_reviewed", "needs_more_evidence"}
    assert payload["ai_domain_review_status"] is None
    assert payload["ai_review_status"] is None
    assert "no_domain_review_yet" in {w["code"] for w in payload["warnings"]}
    assert "run_ai_domain_review" in payload["missing_steps"]


def test_ai_domain_review_status_comes_from_ai_domain_review_results_table(client: TestClient, mem_store: dict) -> None:
    """ai_domain_review_status and ai_domain_reviewer_name are read from ai_domain_review_results.

    Verifies the service does not query verification_review_requests to populate these fields.
    """
    session_id = _seed_session(mem_store, status="completed")
    _seed_clean_evidence(mem_store, session_id)
    _seed_ai_domain(mem_store, session_id)
    # Deliberately do NOT seed verification_review_requests — it shouldn't be needed

    payload = _get_status(client, session_id)

    assert payload["ai_domain_review_status"] == "ai_domain_reviewed"
    assert payload["ai_domain_reviewer_name"] == "Generalist AI Reviewer"
    assert payload["ai_domain_review_score"] == 91
    assert payload["overall_status"] == "ai_domain_reviewed"


def test_service_does_not_reference_nonexistent_table() -> None:
    """verification_review_requests must not appear in WorkPassportStatusService source.

    That table was never created in the live database (migrations 020-032 applied,
    migration 019 was superseded). Any reference would cause a 500 via PostgREST.
    """
    source = inspect.getsource(WorkPassportStatusService)

    assert "verification_review_requests" not in source, (
        "WorkPassportStatusService still references verification_review_requests — "
        "this table does not exist in the live database and will cause a 500."
    )
