"""
Tests for the Extension Proof Sessions API.

All storage is in-memory — no real network calls.
The get_db dependency is overridden with an empty dict, which triggers
the isinstance(client, dict) in-memory path in the service.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user_id, get_db
from app.schemas.extension_proof import ExtensionProofSessionCreate

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000001"

VALID_POST_BODY = {"skill_evidence_id": EVIDENCE_ID}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    """Fresh in-memory store shared across one test."""
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Schema validation ─────────────────────────────────────────────────────────


class TestExtensionProofSessionCreateSchema:
    def test_valid_body(self) -> None:
        s = ExtensionProofSessionCreate(skill_evidence_id=EVIDENCE_ID)
        assert s.skill_evidence_id == EVIDENCE_ID

    def test_missing_skill_evidence_id_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ExtensionProofSessionCreate()  # type: ignore[call-arg]

    def test_blank_skill_evidence_id_raises(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ExtensionProofSessionCreate(skill_evidence_id="   ")

    def test_whitespace_trimmed(self) -> None:
        s = ExtensionProofSessionCreate(skill_evidence_id=f"  {EVIDENCE_ID}  ")
        assert s.skill_evidence_id == EVIDENCE_ID


# ── POST /api/v1/student/extension-proof/sessions ─────────────────────────────


class TestCreateExtensionProofSession:
    def test_returns_201_with_session(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        )
        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == DEMO_USER_ID
        assert data["skill_evidence_id"] == EVIDENCE_ID
        assert data["status"] == "pending"
        assert data["id"] != ""
        assert data["created_at"] != ""
        assert data["updated_at"] != ""

    def test_missing_skill_evidence_id_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions", json={}
        )
        assert response.status_code == 422

    def test_blank_skill_evidence_id_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": ""},
        )
        assert response.status_code == 422

    def test_two_sessions_get_distinct_ids(
        self, client: TestClient, mem_store: dict
    ) -> None:
        r1 = client.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        )
        r2 = client.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]


# ── GET /api/v1/student/extension-proof/sessions/{session_id} ─────────────────


class TestGetExtensionProofSession:
    def test_returns_200_for_existing_session(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        ).json()
        session_id = created["id"]

        response = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session_id
        assert data["user_id"] == DEMO_USER_ID
        assert data["skill_evidence_id"] == EVIDENCE_ID
        assert data["status"] == "pending"

    def test_returns_404_for_unknown_session(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/student/extension-proof/sessions/does-not-exist"
        )
        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["code"] == "extension_proof_session_not_found"
        assert body["detail"]["session_id"] == "does-not-exist"

    def test_404_is_json_not_plain_text(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/student/extension-proof/sessions/ghost"
        )
        assert response.headers["content-type"].startswith("application/json")

    def test_user_isolation(self, mem_store: dict) -> None:
        """A session created by user A must not be visible to user B."""
        app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
        app.dependency_overrides[get_db] = lambda: mem_store
        client_a = TestClient(app)

        created = client_a.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        ).json()
        session_id = created["id"]

        other_user = "ffffffff-0000-0000-0000-000000000002"
        app.dependency_overrides[get_current_user_id] = lambda: other_user
        client_b = TestClient(app)

        response = client_b.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}"
        )
        assert response.status_code == 404

        app.dependency_overrides.clear()


# ── Route registration ─────────────────────────────────────────────────────────


class TestRouteRegistration:
    def test_post_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions" in paths
        assert "post" in paths["/api/v1/student/extension-proof/sessions"]

    def test_get_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions/{session_id}" in paths
        assert "get" in paths["/api/v1/student/extension-proof/sessions/{session_id}"]
