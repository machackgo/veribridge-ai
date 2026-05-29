"""Tests for recruiter candidate comparisons."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, require_recruiter_session
from app.main import app
from app.schemas.recruiter_candidate_comparison import RecruiterCandidateComparisonCreate
from app.schemas.recruiter_shortlist import RecruiterSavedPassportCreate
from app.services.recruiter_candidate_comparison_service import RecruiterCandidateComparisonService
from app.services.recruiter_shortlist_service import RecruiterShortlistService


REQUESTER_EMAIL = "recruiter@example.com"
OTHER_REQUESTER_EMAIL = "other.recruiter@example.com"
USER_A = "00000000-0000-0000-0000-000000000042"
USER_B = "00000000-0000-0000-0000-000000000043"


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_db] = lambda: mem_store
    # Default recruiter session resolves to REQUESTER_EMAIL
    app.dependency_overrides[require_recruiter_session] = lambda: REQUESTER_EMAIL
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_candidate(
    mem_store: dict,
    *,
    user_id: str,
    session_suffix: str,
    public_slug: str,
    full_name: str,
    field: str,
    claimed_skills: list[str],
    supported_skills: list[str],
    ai_score: int,
    readiness_score: int,
    public_summary: str,
) -> dict[str, str]:
    session_id = str(uuid4())
    evidence_id = str(uuid4())
    passport_id = str(uuid4())
    version_id = str(uuid4())
    profile_id = str(uuid4())
    mem_store.setdefault("users", {})[user_id] = {
        "id": user_id,
        "email": f"{session_suffix}@example.edu",
    }
    mem_store.setdefault("student_profiles", {})[profile_id] = {
        "id": profile_id,
        "user_id": user_id,
        "full_name": full_name,
        "major": field,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("skill_evidence", {})[evidence_id] = {
        "id": evidence_id,
        "user_id": user_id,
        "skill_name": claimed_skills[0],
        "claimed_skills": claimed_skills,
        "evidence_url": f"https://{session_suffix}.example.edu",
    }
    mem_store.setdefault("extension_proof_sessions", {})[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "skill_evidence_id": evidence_id,
        "status": "completed",
        "website_url": f"https://{session_suffix}.example.edu",
        "github_url": f"https://github.com/example/{session_suffix}",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("workflow_analysis_results", {})[f"workflow-{session_id}"] = {
        "id": f"workflow-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "claimed_skills": claimed_skills,
        "supported_skills": supported_skills,
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
        "website_url": f"https://{session_suffix}.example.edu",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("extension_proof_github_analysis", {})[f"github-{session_id}"] = {
        "id": f"github-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "matched_claimed_skills": supported_skills,
        "weakly_matched_claimed_skills": [skill for skill in claimed_skills if skill not in supported_skills],
        "repository_url": f"https://github.com/example/{session_suffix}",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("project_defense_analysis_results", {})[f"defense-{session_id}"] = {
        "id": f"defense-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "skills_explained_well": supported_skills,
        "skills_mentioned": claimed_skills,
        "overall_defense_score": max(60, ai_score),
        "transcript_summary": f"Defense summary for {full_name}.",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("ai_domain_review_results", {})[f"domain-{session_id}"] = {
        "id": f"domain-{session_id}",
        "user_id": user_id,
        "proof_session_id": session_id,
        "verified_skills": supported_skills,
        "partially_verified_skills": [skill for skill in claimed_skills if skill not in supported_skills],
        "domain_review_score": ai_score,
        "confidence_level": "high" if ai_score >= 80 else "medium",
        "reviewer_name": "Generalist AI Reviewer",
        "recruiter_summary": f"Strong support for {full_name}.",
        "created_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("proof_evidence_versions", {})[version_id] = {
        "id": version_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "version_number": 1,
        "status": "submitted",
        "change_summary": "Initial evidence package.",
        "is_active": True,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    mem_store.setdefault("public_work_passports", {})[passport_id] = {
        "id": passport_id,
        "user_id": user_id,
        "proof_session_id": session_id,
        "public_slug": public_slug,
        "is_public": True,
        "public_title": f"{full_name} passport",
        "public_summary": public_summary,
        "field": field,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return {
        "session_id": session_id,
        "passport_id": passport_id,
        "full_name": full_name,
    }


def _save_candidate(mem_store: dict, *, public_slug: str, requester_email: str, status: str = "saved") -> dict:
    saved = RecruiterShortlistService(mem_store).save_passport(
        public_slug,
        RecruiterSavedPassportCreate(
            requester_email=requester_email,
            requester_name="Recruiter",
            organization_name="Example Org",
            status=status,
            tags=["shortlist"],
            private_notes="private note",
        ),
    )
    return saved.model_dump(mode="json")


def test_recruiter_can_create_comparison_from_saved_passports(client: TestClient, mem_store: dict) -> None:
    candidate_a = _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI", "PostgreSQL"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    candidate_b = _seed_candidate(
        mem_store,
        user_id=USER_B,
        session_suffix="candidate-b",
        public_slug="candidate-b",
        full_name="Blake Candidate",
        field="CS / Product",
        claimed_skills=["React", "Python"],
        supported_skills=["React"],
        ai_score=71,
        readiness_score=68,
        public_summary="Frontend-leaning public summary.",
    )
    saved_a = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    saved_b = _save_candidate(mem_store, public_slug="candidate-b", requester_email=REQUESTER_EMAIL.upper())

    response = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL.upper(),
            "comparison_name": "AI Intern Shortlist",
            "role_title": "AI / Data Science Intern",
            "role_requirements": {
                "required_skills": ["Python", "FastAPI"],
                "preferred_skills": ["React", "PostgreSQL"],
                "field": "CS / AI / Data Science",
            },
            "saved_passport_ids": [saved_a["id"], saved_b["id"]],
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["requester_email"] == REQUESTER_EMAIL
    assert payload["status"] == "generated"
    assert payload["comparison_snapshot"]["candidate_count"] == 2
    assert payload["comparison_snapshot"]["candidates"][0]["candidate_match_score"] >= payload["comparison_snapshot"]["candidates"][1]["candidate_match_score"]
    assert any("python" in skill.lower() for skill in payload["comparison_snapshot"]["candidates"][0]["matched_required_skills"])
    assert payload["comparison_snapshot"]["candidates"][0]["matched_preferred_skills"]


def test_repeated_requester_email_is_normalized_lowercase(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=88,
        readiness_score=80,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL.upper())

    response = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL.upper(),
            "comparison_name": "Normalized Email Test",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
            "saved_passport_ids": [saved["id"]],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["requester_email"] == REQUESTER_EMAIL
    # List uses session dep (overridden to REQUESTER_EMAIL); no query param needed
    listed = client.get("/api/v1/public/recruiter/candidate-comparisons")
    assert listed.status_code == 200, listed.text
    assert all(row["requester_email"] == REQUESTER_EMAIL for row in listed.json())


def test_recruiter_can_list_only_their_own_comparisons(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    own = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Own comparison",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
            "saved_passport_ids": [saved["id"]],
        },
    )
    assert own.status_code == 201, own.text
    other = RecruiterCandidateComparisonService(mem_store).create_candidate_comparison(
        RecruiterCandidateComparisonCreate(
            requester_email=OTHER_REQUESTER_EMAIL,
            comparison_name="Other comparison",
            role_title="Frontend Intern",
            role_requirements={"required_skills": ["React"], "preferred_skills": []},
            saved_passport_ids=[],
        )
    )
    assert other.requester_email == OTHER_REQUESTER_EMAIL
    # Session dep returns REQUESTER_EMAIL — should only see own comparisons
    listed = client.get("/api/v1/public/recruiter/candidate-comparisons")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["requester_email"] == REQUESTER_EMAIL


def test_recruiter_cannot_fetch_another_requesters_comparison(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    comparison = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Protected comparison",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
            "saved_passport_ids": [saved["id"]],
        },
    ).json()

    # Simulate attacker with a session for OTHER_REQUESTER_EMAIL trying to fetch
    app.dependency_overrides[require_recruiter_session] = lambda: OTHER_REQUESTER_EMAIL
    response = client.get(
        f"/api/v1/public/recruiter/candidate-comparisons/{comparison['id']}"
    )
    # Restore default session
    app.dependency_overrides[require_recruiter_session] = lambda: REQUESTER_EMAIL

    assert response.status_code == 404


def test_archive_comparison_works(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    comparison = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Archive me",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
            "saved_passport_ids": [saved["id"]],
        },
    ).json()

    # Session dep returns REQUESTER_EMAIL (owner) — archive should succeed
    archived = client.post(
        f"/api/v1/public/recruiter/candidate-comparisons/{comparison['id']}/archive"
    )

    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"


def test_comparison_snapshot_excludes_private_transcript_media_path_access_token_and_admin_notes(
    client: TestClient,
    mem_store: dict,
) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)

    response = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Safety test",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": []},
            "saved_passport_ids": [saved["id"]],
        },
    )

    assert response.status_code == 201, response.text
    serialized = json.dumps(response.json()).lower()
    assert "private transcript" not in serialized
    assert "media_storage_path" not in serialized
    assert "access_token" not in serialized
    assert "admin notes" not in serialized
    assert "human_verified" not in serialized


def test_candidate_match_score_is_between_0_and_100(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    response = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Score test",
            "role_title": "Backend Intern",
            "role_requirements": {"required_skills": ["Python"], "preferred_skills": ["PostgreSQL"]},
            "saved_passport_ids": [saved["id"]],
        },
    )
    score = response.json()["comparison_snapshot"]["candidates"][0]["candidate_match_score"]
    assert 0 <= score <= 100


def test_required_and_preferred_skill_matching_works(client: TestClient, mem_store: dict) -> None:
    _seed_candidate(
        mem_store,
        user_id=USER_A,
        session_suffix="candidate-a",
        public_slug="candidate-a",
        full_name="Avery Candidate",
        field="CS / AI",
        claimed_skills=["Python", "FastAPI", "PostgreSQL"],
        supported_skills=["Python", "FastAPI"],
        ai_score=90,
        readiness_score=82,
        public_summary="Backend-heavy public summary.",
    )
    saved = _save_candidate(mem_store, public_slug="candidate-a", requester_email=REQUESTER_EMAIL)
    response = client.post(
        "/api/v1/public/recruiter/candidate-comparisons",
        json={
            "requester_email": REQUESTER_EMAIL,
            "comparison_name": "Skill match test",
            "role_title": "Backend Intern",
            "role_requirements": {
                "required_skills": ["Python", "FastAPI", "Docker"],
                "preferred_skills": ["PostgreSQL"],
            },
            "saved_passport_ids": [saved["id"]],
        },
    )
    candidate = response.json()["comparison_snapshot"]["candidates"][0]
    assert "Python" in candidate["matched_required_skills"]
    assert "FastAPI" in candidate["matched_required_skills"]
    assert "Docker" in candidate["missing_required_skills"]
    assert "PostgreSQL" in candidate["matched_preferred_skills"]


def test_no_project_specific_hardcoding() -> None:
    import app.services.recruiter_candidate_comparison_service as service

    source = inspect.getsource(service).lower()
    assert "boston" not in source
    assert "react demo" not in source
    assert "repo name" not in source
