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
from app.core.config import settings
from app.schemas.extension_proof import (
    ExtensionProofSessionCreate,
    ExtensionProofUploadRequest,
)
from app.services.extension_proof_service import mask_sensitive

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
EVIDENCE_ID = "eeeeeeee-0000-0000-0000-000000000001"

VALID_POST_BODY = {"skill_evidence_id": EVIDENCE_ID}

VALID_UPLOAD_BODY: dict = {
    "workflow_events": [
        {"type": "navigation", "url": "https://example.com/dashboard"},
        {"type": "click", "target": "button#submit"},
    ],
    "extension_version": "1.0.0",
    "started_at": "2026-05-23T10:00:00Z",
    "stopped_at": "2026-05-23T10:05:00Z",
    "student_final_note": "Demonstrated the feature successfully.",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: DEMO_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_session(client: TestClient) -> dict:
    """Helper: POST to create a session and return the response body."""
    r = client.post("/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY)
    assert r.status_code == 201
    return r.json()


def _start_session(client: TestClient, session_id: str) -> dict:
    r = client.post(f"/api/v1/student/extension-proof/sessions/{session_id}/start")
    assert r.status_code == 200
    return r.json()


def _upload_proof(client: TestClient, session_id: str, body: dict | None = None) -> dict:
    r = client.post(
        f"/api/v1/student/extension-proof/sessions/{session_id}/upload",
        json=body or VALID_UPLOAD_BODY,
    )
    assert r.status_code == 200
    return r.json()


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


class TestExtensionProofUploadRequestSchema:
    def test_defaults(self) -> None:
        r = ExtensionProofUploadRequest()
        assert r.workflow_events == []
        assert r.screenshots is None
        assert r.browser_metadata is None

    def test_student_final_note_max_length(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ExtensionProofUploadRequest(student_final_note="x" * 2001)


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
        assert data["status"] == "created"
        assert data["id"] != ""
        assert data["created_at"] != ""
        assert data["updated_at"] != ""
        assert data["started_at"] is None
        assert data["proof_upload_id"] is None

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

    def test_two_sessions_get_distinct_ids(self, client: TestClient) -> None:
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
        created = _create_session(client)
        session_id = created["id"]

        response = client.get(
            f"/api/v1/student/extension-proof/sessions/{session_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session_id
        assert data["user_id"] == DEMO_USER_ID
        assert data["skill_evidence_id"] == EVIDENCE_ID
        assert data["status"] == "created"

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


class TestExtensionProofAuthGate:
    """The recorder extension uploads workflow evidence to these endpoints with
    an ``Authorization: Bearer`` header carrying the signed-in user's Supabase
    token (handed to it same-origin by the authenticated app). The endpoints
    must therefore fail closed: a missing or invalid token is a 401, never an
    anonymous/downgraded recording. Here we exercise the REAL
    ``get_current_user_id`` dependency (not overridden) — only ``get_db`` is
    stubbed so dependency resolution never reaches a live Supabase client.
    """

    def test_create_without_token_returns_401(
        self, mem_store: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
        app.dependency_overrides[get_db] = lambda: mem_store
        try:
            client = TestClient(app)
            res = client.post(
                "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
            )
            assert res.status_code == 401
            assert res.json()["detail"]["code"] == "unauthorized"
        finally:
            app.dependency_overrides.clear()

    def test_create_with_invalid_token_returns_401(
        self, mem_store: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
        app.dependency_overrides[get_db] = lambda: mem_store
        try:
            client = TestClient(app)
            res = client.post(
                "/api/v1/student/extension-proof/sessions",
                json=VALID_POST_BODY,
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )
            assert res.status_code == 401
            assert res.json()["detail"]["code"] in {"invalid_token", "token_expired"}
        finally:
            app.dependency_overrides.clear()


# ── POST /{session_id}/start ──────────────────────────────────────────────────


class TestStartSession:
    def test_start_moves_status_to_recording(self, client: TestClient) -> None:
        session = _create_session(client)
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "recording"
        assert data["started_at"] is not None
        assert data["id"] == session["id"]

    def test_start_invalid_session_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions/no-such-id/start"
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "extension_proof_session_not_found"

    def test_start_from_waiting_for_extension_allowed(
        self, client: TestClient, mem_store: dict
    ) -> None:
        session = _create_session(client)
        # Manually set status to waiting_for_extension in the store
        from app.services.extension_proof_service import _TABLE
        mem_store[_TABLE][session["id"]]["status"] = "waiting_for_extension"

        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recording"

    def test_start_wrong_status_returns_409(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])

        # Already recording — start again should be rejected
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        )
        assert response.status_code == 409
        body = response.json()
        assert body["detail"]["code"] == "invalid_session_transition"
        assert body["detail"]["session_id"] == session["id"]

    def test_start_response_is_json(self, client: TestClient) -> None:
        session = _create_session(client)
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        )
        assert response.headers["content-type"].startswith("application/json")


# ── POST /{session_id}/upload ─────────────────────────────────────────────────


class TestUploadProof:
    def test_upload_valid_payload_returns_200(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])

        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/upload",
            json=VALID_UPLOAD_BODY,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "uploaded_pending_analysis"
        assert data["proof_upload_id"] not in ("", None)
        assert data["id"] == session["id"]

    def test_upload_sets_proof_upload_id(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        data = _upload_proof(client, session["id"])
        assert len(data["proof_upload_id"]) == 36  # str(uuid4())

    def test_upload_rejects_missing_session(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions/ghost-id/upload",
            json=VALID_UPLOAD_BODY,
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "extension_proof_session_not_found"

    def test_upload_wrong_status_returns_409(self, client: TestClient) -> None:
        # Upload without calling start first
        session = _create_session(client)
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/upload",
            json=VALID_UPLOAD_BODY,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "invalid_session_transition"

    def test_upload_empty_workflow_events_accepted(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/upload",
            json={"workflow_events": []},
        )
        assert response.status_code == 200

    def test_upload_masks_password_in_workflow_events(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        # Check mask_sensitive directly — endpoint stores masked data, not returning it
        events = [{"type": "form", "formData": {"email": "a@b.com", "password": "s3cr3t"}}]
        masked = mask_sensitive(events)
        assert masked[0]["formData"]["password"] == "[REDACTED]"
        assert masked[0]["formData"]["email"] == "a@b.com"

    def test_upload_masks_token_key(self) -> None:
        result = mask_sensitive({"Authorization": "Bearer abc123", "url": "/api"})
        assert result["Authorization"] == "[REDACTED]"
        assert result["url"] == "/api"

    def test_upload_masks_nested_sensitive_keys(self) -> None:
        obj = {"outer": {"inner": {"token": "xyz", "name": "test"}}}
        result = mask_sensitive(obj)
        assert result["outer"]["inner"]["token"] == "[REDACTED]"
        assert result["outer"]["inner"]["name"] == "test"

    def test_upload_drops_cookies_entirely(self) -> None:
        obj = {"cookies": {"session": "abc"}, "url": "/home"}
        result = mask_sensitive(obj)
        assert "cookies" not in result
        assert result["url"] == "/home"

    def test_upload_drops_localstorage(self) -> None:
        obj = {"localStorage": {"token": "x"}, "page": "dashboard"}
        result = mask_sensitive(obj)
        assert "localStorage" not in result
        assert result["page"] == "dashboard"

    def test_upload_drops_sessionstorage(self) -> None:
        obj = {"sessionStorage": {"key": "v"}, "tab": 1}
        result = mask_sensitive(obj)
        assert "sessionStorage" not in result

    def test_upload_masks_api_key(self) -> None:
        result = mask_sensitive({"api_key": "sk-abc", "model": "gpt-4"})
        assert result["api_key"] == "[REDACTED]"
        assert result["model"] == "gpt-4"

    def test_upload_masks_cvv_ssn_otp(self) -> None:
        obj = {"cvv": "123", "ssn": "000-00-0000", "otp": "456789"}
        result = mask_sensitive(obj)
        for key in ("cvv", "ssn", "otp"):
            assert result[key] == "[REDACTED]"

    def test_upload_masks_list_of_events(self) -> None:
        events = [
            {"action": "click", "secret": "abc"},
            {"action": "navigate", "url": "https://example.com"},
        ]
        result = mask_sensitive(events)
        assert result[0]["secret"] == "[REDACTED]"
        assert result[1]["url"] == "https://example.com"

    def test_upload_case_insensitive_key_matching(self) -> None:
        result = mask_sensitive({"PASSWORD": "abc", "Token": "xyz"})
        assert result["PASSWORD"] == "[REDACTED]"
        assert result["Token"] == "[REDACTED]"


# ── POST /{session_id}/complete ───────────────────────────────────────────────


class TestCompleteSession:
    def test_complete_moves_status_to_analyzing(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        _upload_proof(client, session["id"])

        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/complete"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "analyzing"
        assert data["id"] == session["id"]

    def test_complete_invalid_session_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions/no-such/complete"
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "extension_proof_session_not_found"

    def test_complete_wrong_status_returns_409(self, client: TestClient) -> None:
        # complete without uploading first
        session = _create_session(client)
        _start_session(client, session["id"])
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/complete"
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "invalid_session_transition"

    def test_complete_from_created_returns_409(self, client: TestClient) -> None:
        session = _create_session(client)
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/complete"
        )
        assert response.status_code == 409

    def test_complete_proof_upload_id_preserved(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        upload_data = _upload_proof(client, session["id"])
        upload_id = upload_data["proof_upload_id"]

        complete_data = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/complete"
        ).json()
        assert complete_data["proof_upload_id"] == upload_id


# ── Full lifecycle ────────────────────────────────────────────────────────────


class TestFullLifecycle:
    def test_create_start_upload_complete(self, client: TestClient) -> None:
        # create
        session = _create_session(client)
        assert session["status"] == "created"

        # start
        started = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        ).json()
        assert started["status"] == "recording"
        assert started["started_at"] is not None

        # upload
        uploaded = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/upload",
            json=VALID_UPLOAD_BODY,
        ).json()
        assert uploaded["status"] == "uploaded_pending_analysis"
        assert uploaded["proof_upload_id"] is not None

        # complete
        completed = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/complete"
        ).json()
        assert completed["status"] == "analyzing"

        # GET still returns the session with final status
        fetched = client.get(
            f"/api/v1/student/extension-proof/sessions/{session['id']}"
        ).json()
        assert fetched["status"] == "analyzing"
        assert fetched["proof_upload_id"] is not None


# ── Route registration ─────────────────────────────────────────────────────────


class TestRouteRegistration:
    def test_post_create_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions" in paths
        assert "post" in paths["/api/v1/student/extension-proof/sessions"]

    def test_get_session_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "get" in paths["/api/v1/student/extension-proof/sessions/{session_id}"]

    def test_post_start_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions/{session_id}/start" in paths

    def test_post_upload_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions/{session_id}/upload" in paths

    def test_post_complete_route_in_openapi(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/student/extension-proof/sessions/{session_id}/complete" in paths
