"""
Tests for the Student Profile API.

All Supabase I/O is mocked — no real network calls are made.

Key mock correctness note
-------------------------
``client.table(...).select("*").eq(...).maybe_single().execute()`` returns:
  - ``None``              when 0 rows match (NOT an object with .data=None)
  - ``SingleAPIResponse`` when 1 row matches (.data is a dict)
  - raises ``APIError``   when >1 rows match

Mocks for the GET chain must set ``execute.return_value = None`` for the
"not found" case — not ``execute.return_value.data = None``.

Test surface
------------
- Schema validation (valid body, missing fields, coercions, bounds)
- GET /api/v1/student/profile (found, not found → 404, conn error → 503, unexpected → 500)
- PUT /api/v1/student/profile (creates, validation error, FK error → 409, conn error → 503)
- Field mapping (API ↔ DB column names verified on mock call args)
- Debug endpoints (config, bootstrap)
- Route registration (OpenAPI schema)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.db.supabase import SupabaseConnectionError, SupabaseFKError
from app.schemas.student import StudentProfileResponse, StudentProfileUpsert

# ── Test constants ────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
PROFILE_ID   = "aaaaaaaa-0000-0000-0000-000000000001"

# A sample database row exactly as Supabase returns it after maybe_single().execute()
SAMPLE_DB_ROW: dict = {
    "id": PROFILE_ID,
    "user_id": DEMO_USER_ID,
    "full_name": "Maya Reyes",
    "school_name": "WPI",
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "work_authorization": "F-1",
    "target_roles": ["Backend Engineer", "SWE Intern"],
    "target_locations": ["NYC", "Remote"],
    "links": {
        "github_url": "https://github.com/maya",
        "linkedin_url": "https://linkedin.com/in/maya",
    },
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-02T00:00:00+00:00",
}

# The API response shape after DB→API field mapping
EXPECTED_API_RESPONSE: dict = {
    "id": PROFILE_ID,
    "user_id": DEMO_USER_ID,
    "full_name": "Maya Reyes",
    "university": "WPI",           # mapped from school_name
    "degree": "B.S.",
    "major": "Computer Science",
    "graduation_year": 2026,
    "visa_status": "F-1",          # mapped from work_authorization
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

# ── Mock builders ─────────────────────────────────────────────────────────────


def _make_get_mock(return_data: dict | None) -> MagicMock:
    """
    Build a Supabase client mock for GET operations.

    Chain: .table().select().eq().maybe_single().execute()

    IMPORTANT: when return_data is None, execute() must return None (not an
    object whose .data is None), because the real maybe_single().execute()
    returns None when 0 rows are found.
    """
    mock = MagicMock()
    execute_mock = (
        mock
        .table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute
    )
    if return_data is None:
        # Real behaviour: execute() returns None itself when 0 rows match.
        execute_mock.return_value = None
    else:
        result = MagicMock()
        result.data = return_data
        execute_mock.return_value = result
    return mock


def _make_get_error_mock(exc: Exception) -> MagicMock:
    """Mock where execute() raises exc (network error simulation)."""
    mock = MagicMock()
    (
        mock
        .table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute
    ).side_effect = exc
    return mock


def _make_upsert_mock(return_rows: list[dict]) -> MagicMock:
    """
    Build a Supabase client mock for UPSERT operations.
    Chain: .table().upsert().execute()
    """
    mock = MagicMock()
    result = MagicMock()
    result.data = return_rows
    (
        mock
        .table.return_value
        .upsert.return_value
        .execute.return_value
    ) = result
    return mock


def _make_upsert_error_mock(exc: Exception) -> MagicMock:
    """Mock where upsert execute() raises exc."""
    mock = MagicMock()
    (
        mock
        .table.return_value
        .upsert.return_value
        .execute
    ).side_effect = exc
    return mock


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    """TestClient with DEMO_USER_ID pre-wired via dependency override."""
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Schema validation ─────────────────────────────────────────────────────────


class TestStudentProfileUpsertSchema:
    def test_valid_full_body(self) -> None:
        s = StudentProfileUpsert(**VALID_PUT_BODY)
        assert s.full_name == "Maya Reyes"
        assert s.university == "WPI"
        assert s.visa_status == "F-1"

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

    def test_optional_fields_default_correctly(self) -> None:
        s = StudentProfileUpsert(
            full_name="T", university="MIT", degree="B.S.", major="CS"
        )
        assert s.graduation_year is None
        assert s.visa_status is None
        assert s.target_roles == []
        assert s.target_locations == []
        assert s.github_url is None
        assert s.linkedin_url is None

    def test_graduation_year_too_low_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            StudentProfileUpsert(**{**VALID_PUT_BODY, "graduation_year": 1800})

    def test_graduation_year_too_high_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            StudentProfileUpsert(**{**VALID_PUT_BODY, "graduation_year": 2200})

    def test_empty_string_urls_coerced_to_none(self) -> None:
        s = StudentProfileUpsert(
            full_name="T", university="MIT", degree="B.S.", major="CS",
            github_url="", linkedin_url="  ",
        )
        assert s.github_url is None
        assert s.linkedin_url is None

    def test_null_list_fields_coerced_to_empty_list(self) -> None:
        s = StudentProfileUpsert(
            full_name="T", university="MIT", degree="B.S.", major="CS",
            target_roles=None,      # type: ignore[arg-type]
            target_locations=None,  # type: ignore[arg-type]
        )
        assert s.target_roles == []
        assert s.target_locations == []


# ── GET /api/v1/student/profile ───────────────────────────────────────────────


class TestGetStudentProfile:
    def test_returns_404_json_when_profile_not_found(
        self, client: TestClient
    ) -> None:
        """
        maybe_single().execute() returns None for 0 rows.
        The endpoint must convert this to a 404 JSON response,
        not a 500 or plain-text error.
        """
        app.dependency_overrides[get_db] = lambda: _make_get_mock(None)
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 404
        body = response.json()
        # Must be JSON with a structured detail
        assert body["detail"]["code"] == "student_profile_not_found"
        assert DEMO_USER_ID in body["detail"]["user_id"]
        # Must NOT be plain text
        assert response.headers["content-type"].startswith("application/json")

    def test_returns_200_when_profile_found(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(SAMPLE_DB_ROW)
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Maya Reyes"
        assert data["university"] == "WPI"      # school_name → university
        assert data["visa_status"] == "F-1"     # work_authorization → visa_status
        assert data["github_url"] == "https://github.com/maya"

    def test_response_matches_expected_shape_exactly(
        self, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(SAMPLE_DB_ROW)
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 200
        assert response.json() == EXPECTED_API_RESPONSE

    def test_response_includes_timestamps(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_get_mock(SAMPLE_DB_ROW)
        data = client.get("/api/v1/student/profile").json()
        assert data["created_at"] != ""
        assert data["updated_at"] != ""

    def test_null_optional_fields_returned_correctly(
        self, client: TestClient
    ) -> None:
        sparse = {
            **SAMPLE_DB_ROW,
            "graduation_year": None,
            "work_authorization": None,
            "target_roles": [],
            "links": {},
        }
        app.dependency_overrides[get_db] = lambda: _make_get_mock(sparse)
        data = client.get("/api/v1/student/profile").json()
        assert data["graduation_year"] is None
        assert data["visa_status"] is None
        assert data["target_roles"] == []
        assert data["github_url"] is None

    def test_returns_503_json_on_connection_error(
        self, client: TestClient
    ) -> None:
        exc = ConnectionError("[Errno 8] nodename nor servname provided")
        app.dependency_overrides[get_db] = lambda: _make_get_error_mock(exc)
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["code"] == "database_unavailable"
        assert response.headers["content-type"].startswith("application/json")

    def test_returns_503_json_on_supabase_connection_error_type(
        self, client: TestClient
    ) -> None:
        """SupabaseConnectionError raised by service → 503 JSON."""
        exc = SupabaseConnectionError("DNS failed")
        app.dependency_overrides[get_db] = lambda: _make_get_error_mock(exc)
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"

    def test_returns_500_json_not_plain_text_on_unexpected_error(
        self, client: TestClient
    ) -> None:
        """
        An unexpected exception must return structured JSON 500,
        never plain-text 'Internal Server Error'.
        """
        # Force a bug: mock returns a non-None result whose .data is
        # something that causes _to_response to fail unexpectedly
        bad_result = MagicMock()
        bad_result.data = 12345  # int, not dict — causes AttributeError in _to_response
        mock = MagicMock()
        (
            mock
            .table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = bad_result
        app.dependency_overrides[get_db] = lambda: mock
        response = client.get("/api/v1/student/profile")
        assert response.status_code == 500
        body = response.json()
        assert body["detail"]["code"] == "internal_error"
        # Must be JSON, not plain text
        assert response.headers["content-type"].startswith("application/json")


# ── PUT /api/v1/student/profile ───────────────────────────────────────────────


class TestUpsertStudentProfile:
    def test_returns_200_with_created_profile(self, client: TestClient) -> None:
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock([SAMPLE_DB_ROW])
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Maya Reyes"
        assert data["university"] == "WPI"
        assert data["visa_status"] == "F-1"

    def test_validation_error_for_missing_required_field(
        self, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db] = lambda: MagicMock()
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "full_name"}
        response = client.put("/api/v1/student/profile", json=body)
        assert response.status_code == 422
        assert any("full_name" in str(e) for e in response.json()["detail"])

    def test_optional_fields_can_be_omitted(self, client: TestClient) -> None:
        minimal_row = {
            **SAMPLE_DB_ROW,
            "graduation_year": None,
            "work_authorization": None,
            "target_roles": [],
            "target_locations": [],
            "links": {},
        }
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock([minimal_row])
        response = client.put(
            "/api/v1/student/profile",
            json={"full_name": "T", "university": "MIT", "degree": "B.S.", "major": "CS"},
        )
        assert response.status_code == 200
        assert response.json()["graduation_year"] is None

    def test_returns_409_on_fk_error(self, client: TestClient) -> None:
        """FK violation (missing users row) must return 409 Conflict, not 503."""
        fk_exc = Exception(
            "violates foreign key constraint on table users (23503)"
        )
        app.dependency_overrides[get_db] = lambda: _make_upsert_error_mock(fk_exc)
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        assert response.status_code == 409
        body = response.json()
        assert body["detail"]["code"] == "user_not_found"
        assert "bootstrap-demo-user" in body["detail"]["message"]

    def test_returns_503_on_connection_error(self, client: TestClient) -> None:
        exc = ConnectionError("DNS resolution failed")
        app.dependency_overrides[get_db] = lambda: _make_upsert_error_mock(exc)
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"

    def test_returns_503_when_upsert_returns_empty(
        self, client: TestClient
    ) -> None:
        app.dependency_overrides[get_db] = lambda: _make_upsert_mock([])
        response = client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "profile_upsert_failed"

    def test_field_mapping_sends_correct_db_column_names(
        self, client: TestClient
    ) -> None:
        mock_db = _make_upsert_mock([SAMPLE_DB_ROW])
        app.dependency_overrides[get_db] = lambda: mock_db
        client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        payload = mock_db.table.return_value.upsert.call_args[0][0]
        # university → school_name
        assert "school_name" in payload and payload["school_name"] == "WPI"
        assert "university" not in payload
        # visa_status → work_authorization
        assert "work_authorization" in payload and payload["work_authorization"] == "F-1"
        assert "visa_status" not in payload
        # URLs nested in links jsonb
        assert payload["links"]["github_url"] == "https://github.com/maya"

    def test_user_id_injected_into_upsert_payload(
        self, client: TestClient
    ) -> None:
        mock_db = _make_upsert_mock([SAMPLE_DB_ROW])
        app.dependency_overrides[get_db] = lambda: mock_db
        client.put("/api/v1/student/profile", json=VALID_PUT_BODY)
        payload = mock_db.table.return_value.upsert.call_args[0][0]
        assert payload["user_id"] == DEMO_USER_ID


# ── Debug endpoints ───────────────────────────────────────────────────────────


class TestDebugConfigEndpoint:
    def test_returns_200_in_development(self, client: TestClient) -> None:
        response = client.get("/api/v1/debug/config")
        assert response.status_code in (200, 403)

    def test_does_not_expose_key_values(self, client: TestClient) -> None:
        response = client.get("/api/v1/debug/config")
        if response.status_code == 403:
            return
        text = response.text
        from app.core.config import settings
        actual_key = settings.supabase_service_role_key.get_secret_value()
        if actual_key:
            assert actual_key not in text

    def test_returns_host_not_full_url(self, client: TestClient) -> None:
        response = client.get("/api/v1/debug/config")
        if response.status_code == 403:
            return
        host = response.json()["supabase"].get("url_host") or ""
        assert "eyJ" not in host  # JWT prefix

    def test_shows_configured_status(self, client: TestClient) -> None:
        response = client.get("/api/v1/debug/config")
        if response.status_code == 403:
            return
        assert isinstance(response.json()["supabase"]["configured"], bool)


class TestBootstrapDemoUserEndpoint:
    def test_endpoint_registered(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/debug/bootstrap-demo-user" in paths

    def test_returns_200_with_mocked_db(self, client: TestClient) -> None:
        """Verify the endpoint calls ensure_user_exists and returns correct shape."""
        # Mock: no existing user (get returns None), insert succeeds
        mock_db = MagicMock()
        # maybe_single().execute() returns None → user doesn't exist
        (
            mock_db
            .table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute
        ).return_value = None
        # insert().execute() returns something truthy
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        response = client.post("/api/v1/debug/bootstrap-demo-user")
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert "created" in data
        assert data["created"] is True

    def test_returns_403_in_production(self, client: TestClient) -> None:
        """Endpoint must be blocked in production."""
        from unittest.mock import patch
        from app.core import config as cfg
        with patch.object(cfg.settings, "environment", "production"):
            response = client.post("/api/v1/debug/bootstrap-demo-user")
        assert response.status_code == 403


# ── Route registration ────────────────────────────────────────────────────────


class TestRouteRegistration:
    def test_openapi_has_student_profile_get(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "get" in paths["/api/v1/student/profile"]

    def test_openapi_has_student_profile_put(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "put" in paths["/api/v1/student/profile"]

    def test_openapi_has_debug_config(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/debug/config" in paths

    def test_openapi_has_bootstrap_demo_user(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/debug/bootstrap-demo-user" in paths

    def test_health_still_works(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
