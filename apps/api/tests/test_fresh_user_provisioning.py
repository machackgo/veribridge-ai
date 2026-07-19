"""Fresh-user provisioning regression suite.

Root class of bugs under test: a freshly signed-up Supabase user has an
``auth.users`` row but NO ``public.users`` row, and every student-owned table
FKs ``user_id`` against ``public.users(id)``. Historically the FIRST write on
each proof flow therefore failed (23503 → opaque 500) until GitHub Proof got a
one-off fix. The central fix is ``get_provisioned_user_id`` /
``ensure_public_user_for_auth_user`` — this suite locks in that EVERY
first-write flow provisions the caller's own row, scopes rows to the caller,
and that auth still fails closed with no fallback/default user.

All storage is in-memory dict mode — no network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.api.deps import (
    AuthenticatedUser,
    get_current_user_id,
    get_current_user_identity,
    get_db,
    get_pipeline_db,
)
from app.core.config import settings
from app.services import video_proof_service
from app.services.user_provisioning_service import ensure_public_user_for_auth_user
from app.services.transcription_service import TranscriptionUnavailableError
from app.services.video_keyframe_extractor_service import VideoKeyframeResult

FRESH_USER = "aaaaaaaa-1111-2222-3333-444444444444"
OTHER_USER = "bbbbbbbb-5555-6666-7777-888888888888"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_store() -> dict:
    # Deliberately EMPTY: no public.users row exists for the caller — the
    # exact state of a fresh Supabase signup.
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    caller: dict = {"user_id": FRESH_USER}
    app.dependency_overrides[get_current_user_id] = lambda: caller["user_id"]
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    test_client = TestClient(app)
    test_client.caller = caller  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def video_analysis_offline(monkeypatch: pytest.MonkeyPatch):
    """Keep video upload hermetic: no transcription/keyframe backends."""

    def _unavailable(*_args, **_kwargs):
        raise TranscriptionUnavailableError("not configured")

    class _NoBackend:
        def extract_keyframes(self, *_args, **_kwargs):
            return VideoKeyframeResult(
                video_analysis_status="not_available",
                keyframe_count=0,
                selected_frame_timestamps_ms=[],
                extraction_method="none",
                duration_ms=None,
                frame_width=None,
                frame_height=None,
                limitations=["No extraction backend installed."],
            )

    monkeypatch.setattr(video_proof_service, "transcribe_audio", _unavailable)
    monkeypatch.setattr(video_proof_service, "VideoKeyframeExtractorService", _NoBackend)


def _users(mem_store: dict) -> dict:
    return mem_store.get("users", {})


# ── First writes succeed for a fresh user and provision exactly their row ─────


def test_fresh_user_can_create_extension_proof_session(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": "eeeeeeee-0000-0000-0000-000000000001"},
    )
    assert res.status_code == 201
    assert res.json()["user_id"] == FRESH_USER
    assert FRESH_USER in _users(mem_store)
    assert set(_users(mem_store)) == {FRESH_USER}  # only the caller's own row


def test_fresh_user_can_submit_document_proof_text(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/document-proofs",
        json={
            "source_type": "document",
            "raw_text": "I built a FastAPI service with CI and tests.",
            "title": "Project report",
            "claimed_skills": ["Python"],
        },
    )
    assert res.status_code == 201
    assert res.json()["user_id"] == FRESH_USER
    assert FRESH_USER in _users(mem_store)


def test_fresh_user_can_upload_video_proof(
    client: TestClient, mem_store: dict, video_analysis_offline
) -> None:
    res = client.post(
        "/api/v1/proofs/video",
        files={"file": ("demo.mp4", b"fake-mp4-bytes", "video/mp4")},
        data={"title": "Demo", "source_kind": "hackathon_demo", "claimed_skills": "Python"},
    )
    assert res.status_code == 201
    assert FRESH_USER in _users(mem_store)
    proofs = mem_store.get("video_proofs", {})
    assert proofs and all(row["user_id"] == FRESH_USER for row in proofs.values())


def test_fresh_user_can_upsert_student_profile() -> None:
    """StudentProfileService talks to a real Supabase client (no dict mode), so
    this exercises the provisioning insert against a mocked client: the users
    select finds no row → the caller's own row is inserted → the profile upsert
    proceeds instead of dying on the FK."""
    users_tbl = MagicMock()
    users_tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    users_tbl.insert.return_value.execute.return_value = MagicMock(data=[{"id": FRESH_USER}])
    profiles_tbl = MagicMock()
    profiles_tbl.upsert.return_value.execute.return_value = MagicMock(
        data=[
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "user_id": FRESH_USER,
                "full_name": "Fresh User",
                "school_name": "WPI",
                "degree": "MS",
                "major": "CS",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )
    db = MagicMock()
    db.table.side_effect = lambda name: users_tbl if name == "users" else profiles_tbl

    app.dependency_overrides[get_current_user_id] = lambda: FRESH_USER
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        res = client.put(
            "/api/v1/student/profile",
            json={"full_name": "Fresh User", "university": "WPI", "degree": "MS", "major": "CS"},
        )
        assert res.status_code == 200
        inserted = users_tbl.insert.call_args[0][0]
        assert inserted["id"] == FRESH_USER
        assert inserted["role"] == "student"
    finally:
        app.dependency_overrides.clear()


def test_fresh_user_can_create_vbr_project(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/vbr/projects",
        json={"title": "My project", "repo_url": "https://github.com/fresh/proj"},
    )
    assert res.status_code == 201
    assert FRESH_USER in _users(mem_store)
    projects = mem_store.get("vbr_projects", {})
    assert projects and all(row["user_id"] == FRESH_USER for row in projects.values())


def test_fresh_user_can_create_project_defense(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/vbr/project-defense",
        json={
            "title": "Defense project",
            "repo_url": "https://github.com/fresh/defense",
            "claimed_skills": ["Python"],
        },
    )
    assert res.status_code == 201
    assert FRESH_USER in _users(mem_store)


def test_fresh_user_can_submit_github_proof(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/github-proofs",
        json={"repo_url": "https://github.com/fresh/repo"},
    )
    assert res.status_code == 201
    assert res.json()["user_id"] == FRESH_USER
    assert FRESH_USER in _users(mem_store)


# ── Provisioning semantics ────────────────────────────────────────────────────


def test_provisioning_uses_verified_email_claim(mem_store: dict) -> None:
    """When the JWT email claim is known, it seeds the provisioned users row."""
    app.dependency_overrides[get_current_user_identity] = lambda: AuthenticatedUser(
        id=FRESH_USER, email="fresh@example.edu"
    )
    app.dependency_overrides[get_db] = lambda: mem_store
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/student/extension-proof/sessions",
            json={"skill_evidence_id": "eeeeeeee-0000-0000-0000-000000000001"},
        )
        assert res.status_code == 201
        assert _users(mem_store)[FRESH_USER]["email"] == "fresh@example.edu"
        assert _users(mem_store)[FRESH_USER]["role"] == "student"
    finally:
        app.dependency_overrides.clear()


def test_provisioning_is_idempotent_and_never_overwrites(client: TestClient, mem_store: dict) -> None:
    """An existing users row (e.g. from a signup trigger) is left untouched."""
    mem_store["users"] = {
        FRESH_USER: {
            "id": FRESH_USER,
            "email": "original@example.edu",
            "role": "student",
            "status": "active",
            "full_name": "Original Name",
        }
    }
    res = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": "eeeeeeee-0000-0000-0000-000000000001"},
    )
    assert res.status_code == 201
    row = _users(mem_store)[FRESH_USER]
    assert row["email"] == "original@example.edu"
    assert row["full_name"] == "Original Name"


def test_helper_is_idempotent_across_calls() -> None:
    store: dict = {}
    assert ensure_public_user_for_auth_user(store, FRESH_USER, "a@b.c") == FRESH_USER
    assert ensure_public_user_for_auth_user(store, FRESH_USER, "later@b.c") == FRESH_USER
    assert store["users"][FRESH_USER]["email"] == "a@b.c"
    assert len(store["users"]) == 1


# ── Tenant isolation ──────────────────────────────────────────────────────────


def test_user_a_cannot_read_user_b_session(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/extension-proof/sessions",
        json={"skill_evidence_id": "eeeeeeee-0000-0000-0000-000000000001"},
    )
    session_id = res.json()["id"]

    client.caller["user_id"] = OTHER_USER  # type: ignore[attr-defined]
    res_b = client.get(f"/api/v1/student/extension-proof/sessions/{session_id}")
    assert res_b.status_code == 404


def test_user_a_cannot_read_user_b_github_proof(client: TestClient, mem_store: dict) -> None:
    res = client.post(
        "/api/v1/student/github-proofs",
        json={"repo_url": "https://github.com/fresh/repo"},
    )
    proof_id = res.json()["id"]

    client.caller["user_id"] = OTHER_USER  # type: ignore[attr-defined]
    res_b = client.get(f"/api/v1/student/github-proofs/{proof_id}")
    assert res_b.status_code == 404


def test_provisioning_never_touches_other_tenants(client: TestClient, mem_store: dict) -> None:
    mem_store["users"] = {
        OTHER_USER: {"id": OTHER_USER, "email": "other@example.edu", "role": "student"}
    }
    res = client.post(
        "/api/v1/student/document-proofs",
        json={"source_type": "document", "raw_text": "text", "title": "t"},
    )
    assert res.status_code == 201
    users = _users(mem_store)
    assert set(users) == {OTHER_USER, FRESH_USER}
    assert users[OTHER_USER]["email"] == "other@example.edu"


# ── Auth still fails closed (no fallback/default user) ────────────────────────

_WRITE_ROOTS = [
    ("post", "/api/v1/student/extension-proof/sessions", {"skill_evidence_id": "e-1"}),
    ("post", "/api/v1/student/document-proofs", {"source_type": "document", "raw_text": "x"}),
    ("post", "/api/v1/student/github-proofs", {"repo_url": "https://github.com/a/b"}),
    ("post", "/api/v1/student/vbr/projects", {"title": "t", "repo_url": "https://github.com/a/b"}),
    (
        "put",
        "/api/v1/student/profile",
        {"full_name": "N", "university": "U", "degree": "D", "major": "M"},
    ),
]


@pytest.mark.parametrize("method,path,body", _WRITE_ROOTS)
def test_write_roots_401_without_token(
    mem_store: dict, monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: dict
) -> None:
    """With the REAL auth dependency and no Authorization header, every
    first-write endpoint is 401 — nothing is provisioned, no fallback user."""
    monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    try:
        client = TestClient(app)
        res = getattr(client, method)(path, json=body)
        assert res.status_code == 401
        assert res.json()["detail"]["code"] == "unauthorized"
        assert _users(mem_store) == {}  # nothing provisioned for anonymous callers
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path,body", _WRITE_ROOTS)
def test_write_roots_401_with_invalid_token(
    mem_store: dict, monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: dict
) -> None:
    monkeypatch.setattr(settings, "enable_demo_user_fallback", False)
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    try:
        client = TestClient(app)
        res = getattr(client, method)(
            path, json=body, headers={"Authorization": "Bearer not-a-real-jwt"}
        )
        assert res.status_code == 401
        assert res.json()["detail"]["code"] in {"invalid_token", "token_expired"}
        assert _users(mem_store) == {}
    finally:
        app.dependency_overrides.clear()
