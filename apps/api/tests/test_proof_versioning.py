"""Tests for proof evidence versioning and resubmission backend."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.proof_versioning_service import ProofVersioningService


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


def _seed_session(mem_store: dict, user_id: str = USER_ID) -> str:
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    mem_store.setdefault("users", {})[user_id] = {
        "id": user_id,
        "email": f"{user_id[-4:]}@example.edu",
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": "Data Analysis",
        "evidence_type": "project",
        "evidence_url": "https://example.edu/project",
        "repository_url": "https://github.com/example/project",
        "evidence_description": "Evidence summary",
        "verification_status": "verified",
        "metadata": {"claimed_skills": ["Data Analysis"], "field": "Analytics"},
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "skill_evidence_id": evidence_id,
        "status": "completed",
        "website_url": "https://example.edu/project",
        "github_url": "https://github.com/example/project",
        "claimed_skills": ["Data Analysis"],
        "title": "Evidence Package",
        "proof_data": {"access_token": "should-not-leak", "workflow_events": []},
        "metadata": {"access_token": "hidden"},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "supported_skills": ["Data Analysis"],
        "weakly_supported_skills": [],
        "risk_flags": [],
        "recruiter_summary": "Workflow supports the claim.",
    }
    mem_store.setdefault("workflow_privacy_scan_results", {})[f"privacy-{session_id}"] = {
        "id": f"privacy-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "clean",
        "scan_summary": "No sensitive data found.",
    }
    mem_store.setdefault("live_website_check_results", {})[f"live-{session_id}"] = {
        "id": f"live-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "is_reachable": True,
        "status_code": 200,
        "url": "https://example.edu/project",
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "status": "success",
        "matched_claimed_skills": ["Data Analysis"],
        "repo_url": "https://github.com/example/project",
        "access_token": "private-token",
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "media_storage_path": "private/defense/audio.webm",
        "media_url": "https://storage.example/private/audio.webm",
        "transcript_text": "This full private transcript should not be stored in the version snapshot.",
        "transcript_summary": "Student explained ownership.",
        "skills_mentioned": ["Data Analysis"],
        "skills_explained_well": ["Data Analysis"],
        "overall_defense_score": 86,
        "recruiter_summary": "Defense supports ownership.",
        "risk_flags": [],
    }
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "ai_domain_review_status": "ai_domain_reviewed",
        "domain_review_score": 91,
        "verified_skills": ["Data Analysis"],
        "recruiter_summary": "Domain review supports the evidence.",
    }
    # verification_review_requests does not exist in production;
    # ai_domain_review_results is the canonical source (seeded above).
    mem_store.setdefault("public_work_passports", {})[f"passport-{session_id}"] = {
        "id": f"passport-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "public_slug": "dynamic-passport",
        "is_public": True,
        "public_title": "Evidence Package",
        "visible_sections": ["summary"],
    }
    return session_id


def test_create_initial_evidence_version(mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    version = ProofVersioningService(mem_store).create_initial_version(USER_ID, session_id)
    assert version.version_number == 1
    assert version.is_active is True
    assert version.version_label == "Version 1"
    assert version.readiness_score is not None


def test_create_resubmission_version_increments_version_number(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    service = ProofVersioningService(mem_store)
    first = service.create_initial_version(USER_ID, session_id)
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/versions",
        json={"change_summary": "Added stronger evidence.", "resubmission_reason": "Improve proof strength."},
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["version_number"] == 2
    assert second["created_from_version_id"] == first.id
    assert second["is_active"] is True


def test_only_one_active_version_per_session(mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    service = ProofVersioningService(mem_store)
    service.create_initial_version(USER_ID, session_id)
    service.create_resubmission_version(USER_ID, session_id, "Change", "Reason")
    active = [
        row for row in mem_store["proof_evidence_versions"].values()
        if row["proof_session_id"] == session_id and row["is_active"]
    ]
    assert len(active) == 1
    assert active[0]["version_number"] == 2


def test_list_versions_returns_newest_first(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    service = ProofVersioningService(mem_store)
    service.create_initial_version(USER_ID, session_id)
    service.create_resubmission_version(USER_ID, session_id, "Change", "Reason")
    response = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/versions")
    assert response.status_code == 200, response.text
    assert [row["version_number"] for row in response.json()] == [2, 1]


def test_activate_old_version_makes_it_active_and_deactivates_others(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    service = ProofVersioningService(mem_store)
    first = service.create_initial_version(USER_ID, session_id)
    service.create_resubmission_version(USER_ID, session_id, "Change", "Reason")
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/versions/{first.id}/activate"
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    active = [
        row for row in mem_store["proof_evidence_versions"].values()
        if row["proof_session_id"] == session_id and row["is_active"]
    ]
    assert len(active) == 1
    assert active[0]["id"] == first.id


def test_archive_version_works(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    version = ProofVersioningService(mem_store).create_initial_version(USER_ID, session_id)
    response = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/versions/{version.id}/archive"
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"
    assert response.json()["is_active"] is False


def test_student_cannot_access_another_students_versions(client: TestClient, mem_store: dict) -> None:
    other_session_id = _seed_session(mem_store, OTHER_USER_ID)
    ProofVersioningService(mem_store).create_initial_version(OTHER_USER_ID, other_session_id)
    response = client.get(f"/api/v1/student/extension-proof/sessions/{other_session_id}/versions")
    assert response.status_code == 404


def test_snapshots_do_not_include_private_fields(mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    version = ProofVersioningService(mem_store).create_initial_version(USER_ID, session_id)
    serialized = f"{version.evidence_snapshot} {version.analysis_snapshot}"
    assert "media_storage_path" not in serialized
    assert "private/defense/audio.webm" not in serialized
    assert "media_url" not in serialized
    assert "access_token" not in serialized
    assert "private-token" not in serialized
    assert "full private transcript" not in serialized


def test_analysis_snapshot_includes_summary_scores_without_human_verification(mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    version = ProofVersioningService(mem_store).create_initial_version(USER_ID, session_id)
    assert version.analysis_snapshot["readiness"]["readiness_score"] >= 0
    assert version.analysis_snapshot["project_defense"]["transcript_summary"] == "Student explained ownership."
    assert version.analysis_snapshot["ai_domain_review"]["recruiter_summary"] == "Domain review supports the evidence."
    assert version.project_defense_score == 86
    assert version.ai_domain_review_score == 91
    serialized = str(version.model_dump())
    assert "human_verified" not in serialized


def test_notification_event_created_for_resubmission(mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    service = ProofVersioningService(mem_store)
    service.create_initial_version(USER_ID, session_id)
    version = service.create_resubmission_version(USER_ID, session_id, "Change", "Reason")
    notifications = list(mem_store.get("notification_events", {}).values())
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Evidence version created"
    assert notifications[0]["category"] == "verification"
    assert notifications[0]["metadata"]["version_id"] == version.id


def test_no_project_specific_hardcoding() -> None:
    import app.services.proof_versioning_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "route risk" not in source
