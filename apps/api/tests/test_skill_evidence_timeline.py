"""Tests for skill evidence timeline backend."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db
from app.main import app
from app.services.skill_evidence_timeline_service import SkillEvidenceTimelineService


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


def _seed_session(mem_store: dict, *, user_id: str = USER_ID) -> str:
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": "API design",
        "claimed_skills": ["API design", "Data visualization", "Container orchestration"],
        "evidence_url": "https://example.edu/project",
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "skill_evidence_id": evidence_id,
        "status": "completed",
        "website_url": "https://example.edu/project",
        "created_at": datetime.now(UTC).isoformat(),
    }
    return session_id


def _seed_evidence(mem_store: dict, session_id: str, *, user_id: str = USER_ID) -> None:
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "claimed_skills": ["API design", "Data visualization", "Container orchestration"],
        "supported_skills": ["API design"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "matched_claimed_skills": ["API design"],
        "weakly_matched_claimed_skills": ["Data visualization"],
        "repository_url": "https://github.com/example/project",
        "media_storage_path": "private/repo/archive.zip",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "skills_explained_well": ["API design"],
        "skills_mentioned": ["Data visualization"],
        "overall_defense_score": 86,
        "transcript_summary": "Explains ownership and project decisions.",
        "transcript_text": "Private full transcript should not be public.",
        "media_storage_path": "private/project-defense/audio.mp3",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "verified_skills": ["API design"],
        "partially_verified_skills": ["Data visualization"],
        "skills_needing_more_evidence": ["Container orchestration"],
        "domain_review_score": 91,
        "confidence_level": "high",
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


def _seed_passport_and_grant(mem_store: dict, session_id: str) -> dict[str, str]:
    passport_id = str(uuid4())
    grant_id = str(uuid4())
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "public_slug": "skill-timeline-passport",
        "is_public": True,
        "access_token": "passport-token-do-not-leak",
    }
    mem_store.setdefault("evidence_access_grants", {})[grant_id] = {
        "id": grant_id,
        "user_id": USER_ID,
        "proof_session_id": session_id,
        "passport_id": passport_id,
        "access_request_id": str(uuid4()),
        "requester_email": "reviewer@example.org",
        "access_token": "grant-token",
        "granted_sections": ["github_analysis"],
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "revoked_at": None,
    }
    return {"passport_id": passport_id, "grant_id": grant_id}


def _timeline(client: TestClient, session_id: str) -> dict:
    response = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/skill-evidence-timeline")
    assert response.status_code == 200, response.text
    return response.json()


def _skill(payload: dict, skill_name: str) -> dict:
    return next(skill for skill in payload["skills"] if skill["skill_name"] == skill_name)


def test_timeline_returns_claimed_skills(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)

    payload = _timeline(client, session_id)

    assert {skill["skill_name"] for skill in payload["skills"]} >= {
        "API design",
        "Data visualization",
        "Container orchestration",
    }


def test_github_and_project_defense_contribute_to_skill_confidence(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    _seed_evidence(mem_store, session_id)

    payload = _timeline(client, session_id)
    api_skill = _skill(payload, "API design")

    assert api_skill["support_level"] == "strong"
    assert api_skill["confidence_score"] >= 80
    assert "github" in api_skill["evidence_sources"]
    assert "project_defense" in api_skill["evidence_sources"]


def test_ai_domain_review_increases_support(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    _seed_evidence(mem_store, session_id)

    payload = _timeline(client, session_id)
    api_skill = _skill(payload, "API design")

    assert "ai_domain_review" in api_skill["evidence_sources"]
    assert any(item["evidence_type"] == "ai_domain_review" and item["support_strength"] == "strong" for item in api_skill["evidence_items"])


def test_missing_claimed_skill_becomes_weak_or_missing(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)

    payload = _timeline(client, session_id)
    missing_skill = _skill(payload, "Container orchestration")

    assert missing_skill["support_level"] in {"weak", "missing"}
    assert missing_skill["confidence_score"] < 45


def test_public_endpoint_excludes_private_transcript_media_and_tokens(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    _seed_evidence(mem_store, session_id)
    _seed_passport_and_grant(mem_store, session_id)

    response = client.get("/api/v1/public/passports/skill-timeline-passport/skill-evidence-timeline")

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json()).lower()
    assert "private full transcript" not in serialized
    assert "media_storage_path" not in serialized
    assert "passport-token-do-not-leak" not in serialized
    assert "grant-token" not in serialized
    assert "protected evidence available by request" in serialized


def test_protected_endpoint_respects_granted_sections(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    _seed_evidence(mem_store, session_id)
    _seed_passport_and_grant(mem_store, session_id)

    response = client.get("/api/v1/public/access/grant-token/skill-evidence-timeline")

    assert response.status_code == 200, response.text
    api_skill = _skill(response.json(), "API design")
    assert "github" in api_skill["evidence_sources"]
    assert "project_defense" not in api_skill["evidence_sources"]


def test_student_cannot_access_another_students_timeline(client: TestClient, mem_store: dict) -> None:
    other_session = _seed_session(mem_store, user_id=OTHER_USER_ID)

    response = client.get(f"/api/v1/student/extension-proof/sessions/{other_session}/skill-evidence-timeline")

    assert response.status_code == 404


def test_skill_evidence_summary_appears_in_status_response(client: TestClient, mem_store: dict) -> None:
    session_id = _seed_session(mem_store)
    _seed_evidence(mem_store, session_id)

    response = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}/work-passport-status")

    assert response.status_code == 200, response.text
    summary = response.json()["skill_evidence_summary"]
    assert summary["strong_skill_count"] >= 1
    assert summary["partial_skill_count"] >= 1
    assert "missing_skill_count" in summary


def test_no_project_specific_hardcoding() -> None:
    source = inspect.getsource(SkillEvidenceTimelineService).lower()

    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source
