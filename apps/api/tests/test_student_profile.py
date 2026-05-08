"""
Tests for the Student Profile API.

All Supabase I/O is mocked — no real network calls are made.
The FastAPI dependency-override mechanism replaces ``get_db`` with a
``MagicMock`` and ``get_current_user_id`` with a fixed UUID so that
tests are fully deterministic.

Test surface
------------
- Schema validation (valid, missing required fields, bad types)
- GET /api/v1/student/profile (found, not found)
- PUT /api/v1/student/profile (creates, updates, validation error)
- Field mapping (API ↔ DB column names)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.schemas.student import StudentProfileUpsert, StudentProfileResponse

# ── Fixtures and helpers ──────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
PROFILE_ID   = "aaaaaaaa-0000-0000-0000-000000000001"

# A sample database row exactly as Supabase would return it.
SAMPLE_DB_ROW: dict = {
    "id": PROFILE_ID,
    "user_id": DEMO_USER_ID,
    "full_name": "Maya Reyes",
    "school_name": "WPI",                   # DB column name
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "work_authorization": "F-1",             # DB column name
    "target_roles": ["Backend Engineer", "SWE Intern"],
    "target_locations": ["NYC", "Remote"],
    "links": {                               # DB jsonb column
        "github_url": "https://github.com/maya",
        "linkedin_url": "https://linkedin.com/in/maya",
    },
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-02T00:00:00+00:00",
}

# The API response shape that should match SAMPLE_DB_ROW after mapping.
EXPECTED_API_RESPONSE: dict = {
    "id": PROFILE_ID,
    "user_id": DEMO_USER_ID,
    "full_name": "Maya Reyes",
    "university": "WPI",                     # mapped from school_name
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "visa_status": "F-1",                    # mapped from work_authorization
    "target_roles": ["Backend Engineer", "SWE Intern"],
    "target_locations": ["NYC", "Remote"],
    "github_url": "https://github.com/maya",
    "linkedin_url": "https://linkedin.com/in/maya",
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-02T00:00:00+00:00",
}

VALID_PUT_BODY: dict = {
    "full_name": "Maya Reyes",
    "university": "WPI",
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "visa_status": "F-1",
    "target_roles": ["Backend Engineer"],
    "target_locations": ["NYC", "Remote"],
    "github_url": "https://github.com/maya",
    "linkedin_url": "https://linkedin.com/in/maya",
}


def _make_get_mock(return_data: dict | None) -> MagicMock:
    """
    Build a Supabase client mock for GET operations.
    Chain: .table().select().eq().maybe_single().execute()
    """
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = return_data
    (
        mock
        .table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = execute_result
    return mock


def _make_upsert_mock(return_rows: list[dict]) -> MagicMock:
    """
    Build a Supabase client mock for UPSERT operations.
    Chain: .table().upsert().execute()
    """
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = return_rows
    (
        mock
        .table.return_value
        .upsert.return_value
        .execute.return_value
    ) = execute_result
    return mock


@pytest.fixture()
def client() -> TestClient:
    """
    TestClient with dependency overrides pre-applied for the demo user.
    Each test can further override get_db as needed.
    """
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Schema validation tests ───────────────────────────────────────────────────


class TestStudentProfileUpsertSchema:
    def test_valid_full_body(self) -> None:
        schema = StudentProfileUpsert(**VALID_PUT_BODY)
        assert schema.full_name == "Maya Reyes"
        assert schema.university == "WPI"
        assert schema.visa_status == "F-1"

    def test_missing_required_full_name_raises(self) -> None:
        import pydantic
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "full_name"}
        with pytest.raises(pydantic.ValidationError) as exc_info:
            StudentProfileUpsert(**body)
        assert "full_name" in str(exc_info.value)

    def test_missing_required_university_raises(self) -> None:
        import pydantic
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "university"}
        with pytest.raises(pydantic.ValidationError) as exc_info:
            StudentProfileUpsert(**body)
        assert "university" in str(exc_info.value)

    def test_missing_required_degree_raises(self) -> None:
        import pydantic
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "degree"}
        with pytest.raises(pydantic.ValidationError) as exc_info:
            StudentProfileUpsert(**body)
        assert "degree" in str(exc_info.value)

    def test_missing_required_major_raises(self) -> None:
        import pydantic
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "major"}
        with pytest.raises(pydantic.ValidationError) as exc_info:
            StudentProfileUpsert(**body)
        assert "major" in str(exc_info.value)

    def test_optional_fields_default_to_none_and_empty_list(self) -> None:
        schema = StudentProfileUpsert(
            full_name="Test",
            university="MIT",
            degree="B.S.",
            major="CS",
        )
        assert schema.graduation_year is None
        assert schema.visa_status is None
        assert schema.target_roles == []
        assert schema.target_locations == []
        assert schema.github_url is None
        assert schema.linkedin_url is None

    def test_graduation_year_below_minimum_raises(self) -> None:
        import pydantic
        body = {**VALID_PUT_BODY, "graduation_year": 1800}
        with pytest.raises(pydantic.ValidationError):
            StudentProfileUpsert(**body)

    def test_graduation_year_above_maximum_raises(self) -> None:
        import pydantic
        body = {**VALID_PUT_BODY, "graduation_year": 2200}
        with pytest.raises(pydantic.ValidationError):
            StudentProfileUpsert(**body)

    def test_empty_string_urls_coerced_to_none(self) -> None:
        schema = StudentProfileUpsert(
            full_name="Test",
            university="MIT",
            degree="B.S.",
            major="CS",
            github_url="",
            linkedin_url="  ",
        )
        assert schema.github_url is None
        assert schema.linkedin_url is None

    def test_null_list_fields_coerced_to_empty_list(self) -> None:
        schema = StudentProfileUpsert(
            full_name="Test",
            university="MIT",
            degree="B.S.",
            major="CS",
            target_roles=None,  # type: ignore[arg-type]
            target_locations=None,  # type: ignore[arg-type]
        )
        assert schema.target_roles == []
        assert schema.target_locations == []


# ── GET /api/v1/student/profile ───────────────────────────────────────────────


class TestGetStudentProfile:
    def test_returns_404_when_profile_not_found(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(return_data=None)
        response = client.get("/api/v1/student/profile")

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["code"] == "student_profile_not_found"
        assert DEMO_USER_ID in body["detail"]["user_id"]

    def test_returns_200_and_profile_when_found(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(
            return_data=SAMPLE_DB_ROW
        )
        response = client.get("/api/v1/student/profile")

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Maya Reyes"
        assert data["university"] == "WPI"        # mapped from school_name
        assert data["visa_status"] == "F-1"       # mapped from work_authorization
        assert data["github_url"] == "https://github.com/maya"
        assert data["target_roles"] == ["Backend Engineer", "SWE Intern"]
        assert data["user_id"] == DEMO_USER_ID
        assert data["id"] == PROFILE_ID

    def test_response_matches_expected_shape(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(
            return_data=SAMPLE_DB_ROW
        )
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 200
        assert response.json() == EXPECTED_API_RESPONSE

    def test_response_includes_timestamps(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(
            return_data=SAMPLE_DB_ROW
        )
        data = client.get("/api/v1/student/profile").json()
        assert "created_at" in data
        assert "updated_at" in data
        assert data["created_at"] != ""

    def test_profile_with_null_optional_fields(self, client: TestClient) -> None:
        sparse_row = {
            **SAMPLE_DB_ROW,
            "graduation_year": None,
            "work_authorization": None,
            "target_roles": [],
            "links": {},
        }
        app.dependency_overrides[get_db] = lambda: _make_get_mock(
            return_data=sparse_row
        )
        data = client.get("/api/v1/student/profile").json()
        assert data  # ensure body is returned
        assert data["graduation_year"] is None
        assert data["visa_status"] is None
        assert data["target_roles"] == []
        assert data["github_url"] is None


# ── PUT /api/v1/student/profile ───────────────────────────────────────────────


class TestUpsertStudentProfile:
    def test_returns_200_with_created_profile(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock(
            return_rows=[SAMPLE_DB_ROW]
        )
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Maya Reyes"
        assert data["university"] == "WPI"
        assert data["visa_status"] == "F-1"

    def test_returns_validation_error_for_missing_required_field(
        self, client: TestClient
    ) -> None:
        # Use a real mock so no Supabase call is attempted
        app.dependency_overrides[get_db] = lambda: MagicMock()
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "full_name"}
        response = client.put("/api/v1/student/profile", json=body)
        assert response.status_code == 422
        errors = response.json()["detail"]
        fields_mentioned = [
            str(e) for e in errors
        ]
        assert any("full_name" in str(e) for e in errors)

    def test_optional_fields_can_be_omitted(self, client: TestClient) -> None:
        minimal_row = {
            **SAMPLE_DB_ROW,
            "graduation_year": None,
            "work_authorization": None,
            "target_roles": [],
            "target_locations": [],
            "links": {},
        }
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock(
            return_rows=[minimal_row]
        )
        minimal_body = {
            "full_name": "Maya Reyes",
            "university": "WPI",
            "degree": "B.S.",
            "major": "Computer Science",
        }
        response = client.put("/api/v1/student/profile", json=minimal_body)
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Maya Reyes"
        assert data["graduation_year"] is None
        assert data["visa_status"] is None

    def test_returns_503_when_supabase_upsert_returns_empty(
        self, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock(return_rows=[])
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "profile_upsert_failed"

    def test_field_mapping_sends_correct_db_column_names(
        self, client: TestClient
    ) -> None:
        """Verify the service maps API field names to DB column names."""
        mock_db = _make_upsert_mock(return_rows=[SAMPLE_DB_ROW])
        app.dependency_overrides[get_db] = lambda: mock_db

        client.put("/api/v1/student/profile", json=VALID_PUT_BODY)

        # Inspect the payload sent to Supabase upsert
        call_args = mock_db.table.return_value.upsert.call_args
        payload = call_args[0][0]  # first positional arg to upsert()

        # API sends "university" but DB column is "school_name"
        assert "school_name" in payload
        assert payload["school_name"] == "WPI"
        assert "university" not in payload

        # API sends "visa_status" but DB column is "work_authorization"
        assert "work_authorization" in payload
        assert payload["work_authorization"] == "F-1"
        assert "visa_status" not in payload

        # URLs must be nested under "links" jsonb column
        assert "links" in payload
        assert payload["links"]["github_url"] == "https://github.com/maya"

    def test_user_id_injected_into_upsert_payload(
        self, client: TestClient
    ) -> None:
        mock_db = _make_upsert_mock(return_rows=[SAMPLE_DB_ROW])
        app.dependency_overrides[get_db] = lambda: mock_db

        client.put("/api/v1/student/profile", json=VALID_PUT_BODY)

        payload = mock_db.table.return_value.upsert.call_args[0][0]
        assert payload["user_id"] == DEMO_USER_ID


# ── Routing sanity checks ─────────────────────────────────────────────────────


class TestRouteRegistration:
    def test_openapi_lists_student_profile_get(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert "/api/v1/student/profile" in paths
        assert "get" in paths["/api/v1/student/profile"]

    def test_openapi_lists_student_profile_put(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        paths = response.json()["paths"]
        assert "put" in paths["/api/v1/student/profile"]

    def test_health_still_works_after_router_changes(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
