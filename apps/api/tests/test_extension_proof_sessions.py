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

from tests.conftest import seed_skill_evidence

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
    # Session creation fail-closes on unowned skill_evidence_id (G6).
    seed_skill_evidence(mem_store, DEMO_USER_ID, EVIDENCE_ID)
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

    def test_optional_project_id_is_preserved(self) -> None:
        project_id = "00000000-0000-0000-0000-000000000077"
        s = ExtensionProofSessionCreate(
            skill_evidence_id=EVIDENCE_ID,
            project_id=project_id,
        )
        assert s.project_id == project_id


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

    # ── G6: caller-supplied ids are validated fail-closed ────────────────────

    def test_unknown_skill_evidence_id_returns_404(self, client: TestClient) -> None:
        """A garbage skill_evidence_id fails closed at create time (404), never
        persisted to surface later as an opaque FK 503."""
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": "eeeeeeee-9999-9999-9999-999999999999"},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"

    def test_foreign_skill_evidence_id_returns_404(
        self, client: TestClient, mem_store: dict
    ) -> None:
        """Another student's evidence id is rejected with the SAME 404 — its
        existence is never confirmed, and it can never be bound as this
        caller's evidence."""
        other_user = "ffffffff-0000-0000-0000-000000000002"
        foreign_id = "eeeeeeee-0000-0000-0000-000000000777"
        seed_skill_evidence(mem_store, other_user, foreign_id)
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": foreign_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "skill_evidence_not_found"
        # Nothing was persisted.
        assert mem_store.get("extension_proof_sessions", {}) == {}

    def test_unknown_parent_proof_session_id_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={
                "skill_evidence_id": EVIDENCE_ID,
                "parent_proof_session_id": "99999999-9999-9999-9999-999999999999",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "extension_proof_session_not_found"

    def test_foreign_parent_proof_session_id_returns_404(
        self, client: TestClient, mem_store: dict
    ) -> None:
        other_user = "ffffffff-0000-0000-0000-000000000002"
        mem_store.setdefault("extension_proof_sessions", {})["parent-foreign"] = {
            "id": "parent-foreign",
            "user_id": other_user,
            "skill_evidence_id": "e-x",
            "status": "completed",
        }
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={
                "skill_evidence_id": EVIDENCE_ID,
                "parent_proof_session_id": "parent-foreign",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "extension_proof_session_not_found"

    def test_owned_parent_proof_session_id_is_accepted(
        self, client: TestClient, mem_store: dict
    ) -> None:
        parent = client.post(
            "/api/v1/student/extension-proof/sessions", json=VALID_POST_BODY
        ).json()
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={
                "skill_evidence_id": EVIDENCE_ID,
                "parent_proof_session_id": parent["id"],
                "proof_attempt_type": "followup",
            },
        )
        assert response.status_code == 201
        stored = mem_store["extension_proof_sessions"][response.json()["id"]]
        assert stored["parent_proof_session_id"] == parent["id"]

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

    def test_explicit_owned_project_creates_direct_relationship(
        self, client: TestClient, mem_store: dict
    ) -> None:
        project_id = "00000000-0000-0000-0000-000000000077"
        mem_store.setdefault("vbr_projects", {})[project_id] = {
            "id": project_id,
            "user_id": DEMO_USER_ID,
            "title": "VeriBridge",
        }
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={**VALID_POST_BODY, "project_id": project_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == project_id
        assert data["project_relationship_state"] == "directly_linked"
        row = mem_store["extension_proof_sessions"][data["id"]]
        assert row["metadata"]["project_id"] == project_id
        [relationship] = list(mem_store["proof_project_relationships"].values())
        assert relationship["relationship_state"] == "directly_linked"
        assert relationship["match_method"] == "explicit_project_id"

    def test_foreign_project_id_is_rejected_without_creating_session(
        self, client: TestClient, mem_store: dict
    ) -> None:
        project_id = "00000000-0000-0000-0000-000000000088"
        mem_store.setdefault("vbr_projects", {})[project_id] = {
            "id": project_id,
            "user_id": "00000000-0000-0000-0000-000000000099",
            "title": "Foreign project",
        }
        response = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={**VALID_POST_BODY, "project_id": project_id},
        )
        assert response.status_code == 404
        assert mem_store.get("extension_proof_sessions", {}) == {}


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
        seed_skill_evidence(mem_store, DEMO_USER_ID, EVIDENCE_ID)
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


class TestListExtensionProofSessions:
    def test_history_lists_only_owned_sessions_without_mutating_them(
        self, client: TestClient, mem_store: dict
    ) -> None:
        old = _create_session(client)
        fresh = _create_session(client)
        rows = mem_store["extension_proof_sessions"]
        rows[old["id"]].update({
            "status": "completed",
            "website_url": "http://localhost:3000",
            "created_at": "2026-07-01T10:00:00+00:00",
        })
        rows[fresh["id"]].update({
            "status": "recording",
            "website_url": "https://wikitok.io/",
            "created_at": "2026-07-14T10:00:00+00:00",
        })
        rows["foreign-session"] = {
            "id": "foreign-session",
            "user_id": "ffffffff-0000-0000-0000-000000000002",
            "skill_evidence_id": EVIDENCE_ID,
            "status": "completed",
            "website_url": "https://foreign.example/",
            "created_at": "2026-07-15T10:00:00+00:00",
            "updated_at": "2026-07-15T10:00:00+00:00",
        }
        before = dict(rows[old["id"]])

        response = client.get("/api/v1/student/extension-proof/sessions")

        assert response.status_code == 200
        payload = response.json()
        assert [item["id"] for item in payload] == [fresh["id"], old["id"]]
        assert payload[0]["status"] == "recording"
        assert payload[1]["website_url"] == "http://localhost:3000"
        assert all(item["id"] != "foreign-session" for item in payload)
        assert rows[old["id"]] == before

    def test_history_exposes_durable_saved_state(
        self, client: TestClient, mem_store: dict
    ) -> None:
        session = _create_session(client)
        project_id = "00000000-0000-0000-0000-000000000077"
        mem_store["extension_proof_sessions"][session["id"]]["metadata"] = {
            "project_id": project_id,
            "project_relationship_state": "directly_linked",
            "canonical_finalized_at": "2026-07-14T12:00:00+00:00",
            "canonical_finalized_project_id": project_id,
        }

        [item] = client.get("/api/v1/student/extension-proof/sessions").json()
        assert item["project_id"] == project_id
        assert item["finalized_project_id"] == project_id
        assert item["finalized_at"] == "2026-07-14T12:00:00+00:00"


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

    def test_duplicate_start_is_idempotent(self, client: TestClient) -> None:
        session = _create_session(client)
        first = _start_session(client, session["id"])

        # The extension retries after a lost response. The retry must not create
        # a second start or move the original timestamp.
        response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/start"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recording"
        assert response.json()["started_at"] == first["started_at"]

    def test_start_from_completed_returns_409(
        self, client: TestClient, mem_store: dict
    ) -> None:
        session = _create_session(client)
        from app.services.extension_proof_service import _TABLE
        mem_store[_TABLE][session["id"]]["status"] = "completed"

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

    def test_duplicate_upload_is_idempotent(self, client: TestClient) -> None:
        session = _create_session(client)
        _start_session(client, session["id"])
        first = _upload_proof(client, session["id"])

        second_response = client.post(
            f"/api/v1/student/extension-proof/sessions/{session['id']}/upload",
            json=VALID_UPLOAD_BODY,
        )

        assert second_response.status_code == 200
        second = second_response.json()
        assert second["proof_upload_id"] == first["proof_upload_id"]
        assert second["status"] == first["status"]

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


# ── Migration 061 RLS guarantees (Gate 14 repair) ─────────────────────────────
#
# Root cause (Gate 13): extension_proof_sessions / extension_proof_uploads had
# RLS enabled but their only policy was an ALL policy on the `public` role with
# USING(true), so the anon key could read AND write every row across all users.
# Migration 061 replaces it with owner-only (authenticated) + explicit
# service-role policies. These assertions guard that contract at the SQL level
# so the permissive policy cannot be reintroduced.

from pathlib import Path  # noqa: E402

_MIGRATION_061 = (
    Path(__file__).resolve().parents[1]
    / "app" / "db" / "migrations"
    / "061_extension_proof_sessions_rls_owner_only.sql"
)


@pytest.fixture(scope="module")
def migration_061_sql() -> str:
    return _MIGRATION_061.read_text(encoding="utf-8").lower()


class TestMigration061Rls:
    def test_migration_file_exists(self) -> None:
        assert _MIGRATION_061.exists()

    def test_enables_rls_on_both_tables(self, migration_061_sql: str) -> None:
        assert (
            "alter table public.extension_proof_sessions enable row level security"
            in migration_061_sql
        )
        assert (
            "alter table public.extension_proof_uploads enable row level security"
            in migration_061_sql
        )

    def test_drops_permissive_public_policy(self, migration_061_sql: str) -> None:
        # The exact over-permissive policies observed in production must be dropped.
        assert (
            'drop policy if exists "allow service role full access to extension proof sessions"'
            in migration_061_sql
        )
        assert (
            'drop policy if exists "allow service role full access to extension proof uploads"'
            in migration_061_sql
        )

    def test_no_public_or_anon_grant_policy(self, migration_061_sql: str) -> None:
        # No policy may target the anon or the catch-all `public` role. Owner
        # access is `to authenticated`; backend access is `to service_role`.
        assert "to anon" not in migration_061_sql
        assert "to public" not in migration_061_sql
        # A CREATE POLICY ... USING (true) is only allowed for service_role.
        assert "for all\n  to public" not in migration_061_sql

    def test_sessions_owner_only_policies(self, migration_061_sql: str) -> None:
        # Owner-only select/insert/update keyed on the ::text-cast comparison
        # (tolerates the production `text` user_id column).
        for verb in ("select", "insert", "update"):
            assert f'"ext_proof_sessions: own row {verb}"' in migration_061_sql
        assert "to authenticated" in migration_061_sql
        assert "(user_id)::text = ((select auth.uid()))::text" in migration_061_sql

    def test_explicit_service_role_policies(self, migration_061_sql: str) -> None:
        assert '"ext_proof_sessions: service role all"' in migration_061_sql
        assert '"ext_proof_uploads: service role all"' in migration_061_sql
        assert "to service_role" in migration_061_sql

    def test_uploads_has_no_authenticated_policy(self, migration_061_sql: str) -> None:
        # extension_proof_uploads is legacy/empty with no user_id column: it is
        # locked to service_role only (default-deny for anon + authenticated).
        assert '"ext_proof_uploads: own row' not in migration_061_sql
