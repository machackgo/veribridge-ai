"""Tests for universal onboarding and Opportunity & Salary Heatmap APIs."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError as PostgrestAPIError

from app.api.deps import get_current_user_id, get_db, get_provisioned_user_id
from app.main import app

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"


class _MissingTableDB:
    """Supabase-shaped stub whose every query fails like an unapplied migration.

    Reproduces the production failure where migration 002's tables are absent
    and PostgREST raises PGRST205 ("Could not find the table ... in the schema
    cache"). Regression guard for the /student/onboarding 500.
    """

    def table(self, _name: str) -> "_MissingTableDB":
        return self

    def select(self, *args: object, **kwargs: object) -> "_MissingTableDB":
        return self

    def eq(self, *args: object, **kwargs: object) -> "_MissingTableDB":
        return self

    def maybe_single(self) -> "_MissingTableDB":
        return self

    def upsert(self, *args: object, **kwargs: object) -> "_MissingTableDB":
        return self

    def update(self, *args: object, **kwargs: object) -> "_MissingTableDB":
        return self

    def insert(self, *args: object, **kwargs: object) -> "_MissingTableDB":
        return self

    def execute(self) -> None:
        raise PostgrestAPIError(
            {
                "message": (
                    "Could not find the table 'public.student_onboarding_profiles' "
                    "in the schema cache"
                ),
                "code": "PGRST205",
                "hint": "Perhaps you meant the table 'public.student_profiles'",
                "details": None,
            }
        )


def _client_with_failing_db() -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_provisioned_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = _MissingTableDB
    return TestClient(app)


def _client_with_store(store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: store
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


VALID_ONBOARDING = {
    "university_country": "United States",
    "degree_level": "Bachelor's",
    "major": "Mechanical Engineering",
    "graduation_year": 2027,
    "career_fields": ["Mechanical/Electrical/Civil Engineering", "Robotics & Manufacturing"],
    "target_roles": ["Manufacturing Engineer", "Robotics Test Engineer"],
    "target_industries": ["Advanced manufacturing", "Automotive"],
    "target_locations": ["Massachusetts, USA"],
    "preferred_work_modes": ["Hybrid", "On-site"],
    "open_to_relocate": True,
    "global_search_open": True,
    "job_search_timeline": "Internship this summer",
    "urgency_level": "Medium",
    "work_authorization_countries": ["USA", "Canada"],
    "sponsorship_needed": True,
    "visa_status": "F-1 CPT/OPT",
    "work_authorization_notes": "Student controls visibility.",
    "skills": [
        {
            "skill_name": "CAD",
            "skill_category": "Engineering",
            "proficiency_level": "Intermediate",
            "evidence": [{"type": "coursework", "title": "Design studio"}],
        }
    ],
    "expected_salary_min": 70000,
    "expected_salary_max": 95000,
    "minimum_acceptable_salary": 65000,
    "salary_currency": "USD",
    "salary_period": "yearly",
    "open_to_negotiation": True,
}


def test_onboarding_get_returns_default_for_demo_user() -> None:
    store: dict = {}
    client = _client_with_store(store)
    try:
        response = client.get("/api/v1/student/onboarding")
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == DEMO_USER_ID
        assert data["career_fields"] == []
        assert data["salary_currency"] == "USD"
    finally:
        _clear_overrides()


def test_onboarding_put_saves_compensation_preferences() -> None:
    store: dict = {}
    client = _client_with_store(store)
    try:
        response = client.put("/api/v1/student/onboarding", json=VALID_ONBOARDING)
        assert response.status_code == 200
        data = response.json()
        assert data["major"] == "Mechanical Engineering"
        assert data["minimum_acceptable_salary"] == 65000
        assert data["salary_period"] == "yearly"
        assert store["onboarding"][DEMO_USER_ID]["expected_salary_max"] == 95000
    finally:
        _clear_overrides()


def test_onboarding_complete_marks_profile_complete() -> None:
    store: dict = {"onboarding": {DEMO_USER_ID: VALID_ONBOARDING.copy()}}
    client = _client_with_store(store)
    try:
        response = client.post("/api/v1/student/onboarding/complete")
        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is True
        assert "completed_at" in data
        assert store["onboarding"][DEMO_USER_ID]["completed_at"]
    finally:
        _clear_overrides()


def test_opportunity_heatmap_returns_mock_recommendations() -> None:
    store: dict = {"onboarding": {DEMO_USER_ID: VALID_ONBOARDING.copy()}}
    client = _client_with_store(store)
    try:
        response = client.get("/api/v1/student/opportunity-heatmap")
        assert response.status_code == 200
        data = response.json()
        assert data["career_graph_name"] == "VeriBridge Career Graph"
        assert data["data_provider"] == "mock"
        assert len(data["recommended_locations"]) >= 5
        first = data["recommended_locations"][0]
        assert "location_name" in first
        assert "estimated_open_roles" in first
        assert "salary_fit" in first
        assert "mock data" in data["market_data_warning"]
    finally:
        _clear_overrides()


def test_onboarding_get_maps_missing_table_to_503_not_500() -> None:
    client = _client_with_failing_db()
    try:
        response = client.get("/api/v1/student/onboarding")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
    finally:
        _clear_overrides()


def test_onboarding_put_maps_missing_table_to_503_not_500() -> None:
    client = _client_with_failing_db()
    try:
        response = client.put("/api/v1/student/onboarding", json=VALID_ONBOARDING)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
    finally:
        _clear_overrides()


def test_onboarding_complete_maps_missing_table_to_503_not_500() -> None:
    client = _client_with_failing_db()
    try:
        response = client.post("/api/v1/student/onboarding/complete")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
    finally:
        _clear_overrides()


def test_opportunity_heatmap_maps_missing_table_to_503_not_500() -> None:
    client = _client_with_failing_db()
    try:
        response = client.get("/api/v1/student/opportunity-heatmap")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
    finally:
        _clear_overrides()


def test_onboarding_service_tables_are_defined_in_migrations() -> None:
    # Drift tripwire: every table the onboarding service touches must have a
    # CREATE TABLE in the migrations dir. (Catches defined-vs-referenced drift;
    # applied-vs-defined drift needs a live-DB probe.)
    from app.services import onboarding_service as svc

    migrations_dir = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations"
    sql = "\n".join(
        p.read_text(encoding="utf-8").lower() for p in migrations_dir.glob("*.sql")
    )
    for table in (svc._PROFILE_TABLE, svc._CAREER_TABLE, svc._SKILLS_TABLE, svc._COMP_TABLE):
        assert re.search(
            rf"create table (?:if not exists )?(?:public\.)?{table}\b", sql
        ), f"no CREATE TABLE for {table} in migrations"


def test_onboarding_requires_auth_when_no_demo_override_is_present() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user_id] = lambda: (_ for _ in ()).throw(
        HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Authentication required."},
        )
    )
    app.dependency_overrides[get_db] = lambda: {}
    client = TestClient(app)
    try:
        response = client.get("/api/v1/student/onboarding")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "unauthorized"
    finally:
        _clear_overrides()
