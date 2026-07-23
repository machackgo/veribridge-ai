"""Regression tests for the production "Failed to fetch" on passport publish.

Root cause (2026-07-23): a brand-new Supabase account has no ``public.users``
row; ``POST /student/vbr/passport/publish`` inserted ``vbr_work_passports``
with the raw token user_id → 23503 FK violation → unhandled 500 that bypassed
CORSMiddleware → the browser blocked the response and the UI rendered the raw
``TypeError: Failed to fetch``.

Covers:
  - publish self-provisions the fresh caller's own ``public.users`` row
  - beam link create self-provisions too (beam_links.user_id FKs users)
  - passport photo upload self-provisions (student_onboarding_profiles FK)
  - unauthenticated publish still fails closed with 401 (provisioning never
    creates rows for anonymous callers)
  - SafeInternalErrorMiddleware: an unhandled exception returns a safe JSON
    500 WITH CORS headers and no exception/stack detail in the body
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.core.config import settings
from app.main import app

FRESH_USER_ID = "fa53f87f-45f4-42e6-a483-473f515000a7"


@pytest.fixture()
def mem_store() -> dict:
    # Deliberately NO "users" table entry — models a brand-new auth account.
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: FRESH_USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Fresh-user provisioning on first-write passport routes ────────────────────

def test_publish_provisions_fresh_user_and_succeeds(client: TestClient, mem_store: dict):
    res = client.post("/api/v1/student/vbr/passport/publish", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["is_published"] is True
    assert body["public_slug"]
    # The caller's own users row was created (and only that one).
    users = mem_store.get("users", {})
    assert list(users.keys()) == [FRESH_USER_ID]
    assert users[FRESH_USER_ID]["role"] == "student"


def test_publish_is_idempotent_for_fresh_user(client: TestClient, mem_store: dict):
    first = client.post("/api/v1/student/vbr/passport/publish", json={}).json()
    second = client.post("/api/v1/student/vbr/passport/publish", json={}).json()
    assert first["public_slug"] == second["public_slug"]
    passports = mem_store.get("vbr_work_passports", {})
    assert len(passports) == 1  # re-publish never mints a second passport row


def test_beam_link_create_provisions_fresh_user(client: TestClient, mem_store: dict):
    assert client.post("/api/v1/student/vbr/passport/publish", json={}).status_code == 200
    res = client.post("/api/v1/student/vbr/beam/links", json={})
    assert res.status_code == 200, res.text
    assert res.json()["code"]
    assert FRESH_USER_ID in mem_store.get("users", {})


def test_passport_photo_upload_provisions_fresh_user(client: TestClient, mem_store: dict):
    # 1x1 PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63fcffff3f030005fe02fea72d5e2b0000000049454e44ae426082"
    )
    res = client.put(
        "/api/v1/student/vbr/passport/identity/photo",
        files={"file": ("qa.png", png, "image/png")},
    )
    # Storage may be unavailable in unit tests (persisted=false) but the route
    # must not 500 and must have provisioned the caller's row.
    assert res.status_code == 200, res.text
    assert FRESH_USER_ID in mem_store.get("users", {})


def test_unauthenticated_publish_fails_closed_401(mem_store: dict):
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    try:
        with TestClient(app) as anon:
            res = anon.post("/api/v1/student/vbr/passport/publish", json={})
        assert res.status_code == 401
        # No provisioning side effects for anonymous callers.
        assert mem_store.get("users", {}) == {}
    finally:
        app.dependency_overrides.clear()


# ── CORS-safe internal errors ────────────────────────────────────────────────

def test_unhandled_exception_returns_safe_json_500_with_cors():
    route_path = "/api/v1/_qa/boom"
    if not any(getattr(r, "path", None) == route_path for r in app.routes):
        @app.get(route_path)
        def _boom():  # pragma: no cover - body always raises
            raise RuntimeError("secret internal detail must not leak")

    origin = settings.cors_origins[0]
    with TestClient(app, raise_server_exceptions=False) as anon:
        res = anon.get(route_path, headers={"Origin": origin})
    assert res.status_code == 500
    body = res.json()
    assert body["detail"]["code"] == "internal_error"
    text = res.text.lower()
    assert "secret internal detail" not in text
    assert "runtimeerror" not in text
    assert "traceback" not in text
    # The whole point: the browser must be able to READ this error cross-origin.
    assert res.headers.get("access-control-allow-origin") == origin
