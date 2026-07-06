"""Tests for the Recruiter Candidate Search endpoint and service (Phase J1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db, require_admin_or_university_admin_user_id
from app.main import app
from app.services.recruiter_candidate_search_service import (
    RecruiterCandidateSearchService,
    _sanitize_query,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db(
    evidence: list[dict] | None = None,
    profiles: list[dict] | None = None,
) -> dict:
    db: dict = {"skill_evidence": {}, "student_profiles": {}}
    for row in evidence or []:
        db["skill_evidence"][row["id"]] = row
    for p in profiles or []:
        db["student_profiles"][p["id"]] = p
    return db


def _make_evidence(
    id: str = "ev-1",
    user_id: str = "user-1",
    skill_name: str = "Machine Learning",
    evidence_type: str = "github repository",
    evidence_description: str = "Built a Decision Tree model.",
    verification_status: str = "verified",
    metadata: dict | None = None,
) -> dict:
    return {
        "id": id,
        "user_id": user_id,
        "skill_name": skill_name,
        "evidence_type": evidence_type,
        "evidence_description": evidence_description,
        "verification_status": verification_status,
        "metadata": metadata or {},
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }


def _make_profile(
    id: str = "prof-1",
    user_id: str = "user-1",
    full_name: str = "Mohammed Mubashir",
    school_name: str = "WPI",
    degree: str = "Master's",
    major: str = "Artificial Intelligence",
) -> dict:
    return {
        "id": id,
        "user_id": user_id,
        "full_name": full_name,
        "school_name": school_name,
        "degree": degree,
        "major": major,
        "graduation_year": 2026,
        "work_authorization": "F-1",
        "target_roles": [],
        "target_locations": [],
        "links": {},
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }


# ── _sanitize_query ────────────────────────────────────────────────────────────

def test_sanitize_query_strips_sql_wildcards():
    assert _sanitize_query("Machine%Learning") == "MachineLearning"
    assert _sanitize_query("Docer_Compose") == "DocerCompose"


def test_sanitize_query_preserves_normal_text():
    assert _sanitize_query("Machine Learning") == "Machine Learning"
    assert _sanitize_query("  FastAPI  ") == "FastAPI"


def test_sanitize_query_empty_input():
    assert _sanitize_query("") == ""
    assert _sanitize_query("  ") == ""


# ── RecruiterCandidateSearchService ───────────────────────────────────────────

class TestRecruiterCandidateSearchService:
    def test_empty_query_returns_empty(self):
        db = _make_db()
        svc = RecruiterCandidateSearchService(db)
        assert svc.search("") == []
        assert svc.search("  ") == []

    def test_no_matching_evidence_returns_empty(self):
        db = _make_db(
            evidence=[_make_evidence(skill_name="Python")],
        )
        svc = RecruiterCandidateSearchService(db)
        assert svc.search("Docker") == []

    def test_matches_skill_name(self):
        db = _make_db(
            evidence=[_make_evidence(skill_name="Machine Learning", user_id="u1")],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert len(results) == 1
        assert results[0].matched_skill_names == ["Machine Learning"]

    def test_matches_skill_name_case_insensitive(self):
        db = _make_db(
            evidence=[_make_evidence(skill_name="Machine Learning", user_id="u1")],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("machine learning")
        assert len(results) == 1

    def test_matches_evidence_description(self):
        db = _make_db(
            evidence=[
                _make_evidence(
                    skill_name="Python",
                    evidence_description="Used Docker Compose to deploy the service.",
                    user_id="u1",
                )
            ],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("docker")
        assert len(results) == 1

    def test_computes_github_and_website_proof_flags(self):
        db = _make_db(
            evidence=[
                _make_evidence(
                    id="ev-1", evidence_type="github repository", user_id="u1"
                ),
                _make_evidence(
                    id="ev-2", evidence_type="deployed website", user_id="u1",
                    skill_name="Machine Learning",
                ),
            ],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert len(results) == 1
        r = results[0]
        assert r.has_github_proof is True
        assert r.has_website_proof is True

    def test_accepted_evidence_count(self):
        db = _make_db(
            evidence=[
                _make_evidence(id="ev-1", verification_status="verified", user_id="u1"),
                _make_evidence(id="ev-2", verification_status="pending_review", user_id="u1"),
            ],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert results[0].accepted_evidence_count == 1
        assert results[0].evidence_count == 2

    def test_strongest_project_title_from_metadata(self):
        db = _make_db(
            evidence=[
                _make_evidence(
                    user_id="u1",
                    metadata={"evidence_title": "Boston Accident Risk System"},
                )
            ],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert results[0].strongest_project_title == "Boston Accident Risk System"

    def test_groups_multiple_evidence_per_user_by_query_match(self):
        # Both ev-1 (skill_name) and ev-3 (description) match "Machine Learning".
        # ev-2 (Python) does not match so it is excluded.
        # evidence_count reflects matched evidence rows for this candidate.
        db = _make_db(
            evidence=[
                _make_evidence(id="ev-1", user_id="u1", skill_name="Machine Learning"),
                _make_evidence(id="ev-2", user_id="u1", skill_name="Python",
                               evidence_description="Python class project"),
                _make_evidence(id="ev-3", user_id="u1", skill_name="Python",
                               evidence_description="Machine Learning pipeline code"),
            ],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert len(results) == 1
        # ev-1 and ev-3 match; ev-2 does not
        assert results[0].evidence_count == 2

    def test_multiple_users_returned_as_separate_results(self):
        db = _make_db(
            evidence=[
                _make_evidence(id="ev-1", user_id="u1", skill_name="Machine Learning"),
                _make_evidence(id="ev-2", user_id="u2", skill_name="Machine Learning",
                               verification_status="verified"),
            ],
            profiles=[
                _make_profile(id="p1", user_id="u1", full_name="Alice"),
                _make_profile(id="p2", user_id="u2", full_name="Bob"),
            ],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert len(results) == 2
        names = {r.display_name for r in results}
        assert names == {"Alice", "Bob"}

    def test_results_sorted_by_accepted_evidence_count_descending(self):
        db = _make_db(
            evidence=[
                _make_evidence(id="ev-1", user_id="u1", skill_name="Machine Learning",
                               verification_status="pending_review"),
                _make_evidence(id="ev-2", user_id="u2", skill_name="Machine Learning",
                               verification_status="verified"),
            ],
            profiles=[
                _make_profile(id="p1", user_id="u1", full_name="Alice"),
                _make_profile(id="p2", user_id="u2", full_name="Bob"),
            ],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert results[0].display_name == "Bob"

    def test_proof_status_label_evidence_accepted(self):
        db = _make_db(
            evidence=[_make_evidence(verification_status="verified", user_id="u1")],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert results[0].proof_status_label == "Evidence Accepted"

    def test_proof_status_label_pending(self):
        db = _make_db(
            evidence=[_make_evidence(verification_status="pending_review", user_id="u1")],
            profiles=[_make_profile(user_id="u1")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert results[0].proof_status_label == "Pending Analysis"

    def test_missing_profile_still_returns_result(self):
        db = _make_db(
            evidence=[_make_evidence(user_id="u-no-profile")],
        )
        results = RecruiterCandidateSearchService(db).search("Machine Learning")
        assert len(results) == 1
        assert results[0].display_name == "Unknown Candidate"
        assert results[0].school_name is None


# ── HTTP endpoint ──────────────────────────────────────────────────────────────

def _make_client_with_db(db: dict) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    # Candidate discovery is an internal (admin/university_admin-gated) surface:
    # a plain authenticated student must never browse other students' evidence.
    app.dependency_overrides[require_admin_or_university_admin_user_id] = lambda: "recruiter-user-1"
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def test_search_endpoint_returns_empty_for_blank_query():
    client = _make_client_with_db(_make_db())
    res = client.get("/api/v1/recruiter/candidates/search?query=")
    assert res.status_code == 200
    body = res.json()
    assert body["results"] == []
    assert body["result_count"] == 0


def test_search_endpoint_returns_match():
    db = _make_db(
        evidence=[_make_evidence(skill_name="FastAPI", user_id="u1")],
        profiles=[_make_profile(user_id="u1", full_name="Sam Hassan")],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/search?query=FastAPI")
    assert res.status_code == 200
    body = res.json()
    assert body["result_count"] == 1
    assert body["results"][0]["display_name"] == "Sam Hassan"
    assert "FastAPI" in body["results"][0]["matched_skill_names"]


def test_search_endpoint_no_match_returns_empty():
    db = _make_db(
        evidence=[_make_evidence(skill_name="Python", user_id="u1")],
        profiles=[_make_profile(user_id="u1")],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/search?query=Docker")
    assert res.status_code == 200
    body = res.json()
    assert body["results"] == []
    assert body["result_count"] == 0


def test_search_endpoint_includes_proof_flags():
    db = _make_db(
        evidence=[
            _make_evidence(id="ev-1", evidence_type="github repository", user_id="u1"),
            _make_evidence(
                id="ev-2", evidence_type="deployed website", user_id="u1",
                skill_name="Machine Learning",
            ),
        ],
        profiles=[_make_profile(user_id="u1")],
    )
    client = _make_client_with_db(db)
    res = client.get("/api/v1/recruiter/candidates/search?query=Machine+Learning")
    assert res.status_code == 200
    r = res.json()["results"][0]
    assert r["has_github_proof"] is True
    assert r["has_website_proof"] is True


def test_search_endpoint_echoes_query():
    client = _make_client_with_db(_make_db())
    res = client.get("/api/v1/recruiter/candidates/search?query=Docker")
    assert res.json()["query"] == "Docker"
