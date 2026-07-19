"""Tests for Beam Links — the dynamic revocable short QR (Beam Card Phase 2).

Owner-only:
  ``POST /api/v1/student/vbr/beam/links``                  — create / reuse
  ``POST /api/v1/student/vbr/beam/links/{id}/rotate``      — rotate
  ``POST /api/v1/student/vbr/beam/links/{id}/revoke``      — revoke

Public (no auth):
  ``GET  /api/v1/public/beam/{code}``                      — scan-time resolve

Covers:
  - creating a link requires a PUBLISHED passport (clear 409 otherwise)
  - codes are crypto-random, URL-safe, >= 12 chars, unique, non-sequential
  - create is idempotent (the active link is reused)
  - an active code resolves to the live public Passport path + logs "opened"
  - rotate kills the old code immediately and mints a working new one
  - revoke kills the code; revoked_at is stamped; idempotent
  - expired links stop resolving and are lazily stamped "expired"
  - unpublishing the passport makes the code dormant; re-publishing revives it
  - EVERY invalid scan (unknown / revoked / expired / unpublished target)
    returns the SAME generic inactive error with zero holder data
  - a non-owner cannot rotate/revoke someone else's link (indistinct 404)
  - audit events carry only coarse metadata (UA class, referrer host)

All storage is in-memory (dict mode). No network / LLM calls.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.beam_link_service import classify_user_agent, referrer_host

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_store() -> dict:
    return {}


@pytest.fixture()
def client(mem_store: dict) -> TestClient:
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_db] = lambda: mem_store
    app.dependency_overrides[get_pipeline_db] = lambda: {}
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_user(user_id: str) -> None:
    app.dependency_overrides[get_current_user_id] = lambda: user_id


def _publish_passport(client: TestClient):
    return client.post("/api/v1/student/vbr/passport/publish", json={})


def _create_link(client: TestClient, **body):
    return client.post("/api/v1/student/vbr/beam/links", json=body or None)


def _rotate(client: TestClient, link_id: str):
    return client.post(f"/api/v1/student/vbr/beam/links/{link_id}/rotate")


def _revoke(client: TestClient, link_id: str):
    return client.post(f"/api/v1/student/vbr/beam/links/{link_id}/revoke")


def _resolve(client: TestClient, code: str, **kwargs):
    return client.get(f"/api/v1/public/beam/{code}", **kwargs)


def _events(mem_store: dict, link_id: str, event_type: str | None = None) -> list[dict]:
    rows = [
        row
        for row in mem_store.get("beam_link_events", {}).values()
        if row["beam_link_id"] == link_id
    ]
    if event_type:
        rows = [row for row in rows if row["event_type"] == event_type]
    return rows


URL_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


# ── Create / reuse ────────────────────────────────────────────────────────────

def test_create_requires_published_passport(client: TestClient) -> None:
    res = _create_link(client)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "beam_passport_not_published"


def test_create_returns_active_link_with_secure_code(client: TestClient) -> None:
    slug = _publish_passport(client).json()["public_slug"]
    res = _create_link(client)
    assert res.status_code == 200
    link = res.json()
    assert link["status"] == "active"
    assert len(link["code"]) >= 12
    assert set(link["code"]) <= URL_SAFE
    assert link["short_path"] == f"/b/{link['code']}"
    assert link["public_passport_path"] == f"/p/{slug}"
    assert link["expires_at"] is None
    assert link["revoked_at"] is None


def test_create_reuses_the_existing_active_link(client: TestClient) -> None:
    _publish_passport(client)
    first = _create_link(client).json()
    second = _create_link(client).json()
    assert second["id"] == first["id"]
    assert second["code"] == first["code"]


def test_codes_are_unique_and_not_sequential(client: TestClient) -> None:
    _publish_passport(client)
    codes = []
    for _ in range(25):
        link = _create_link(client).json()
        codes.append(link["code"])
        _revoke(client, link["id"])  # free the active slot so a new code mints
    assert len(set(codes)) == len(codes)
    # Non-sequential: no code is a +1 neighbour or shared long prefix of another.
    for a, b in zip(codes, codes[1:]):
        assert a[:8] != b[:8]


def test_event_tag_is_sanitized(client: TestClient) -> None:
    _publish_passport(client)
    link = _create_link(client, event_tag="  career-fair-2026 <script> ").json()
    assert "<" not in (link["event_tag"] or "")
    assert "career-fair-2026" in link["event_tag"]


def test_created_event_is_logged(client: TestClient, mem_store: dict) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    assert len(_events(mem_store, link["id"], "created")) == 1


# ── Public resolution ─────────────────────────────────────────────────────────

def test_active_code_resolves_to_live_public_passport(client: TestClient, mem_store: dict) -> None:
    slug = _publish_passport(client).json()["public_slug"]
    link = _create_link(client).json()
    res = _resolve(client, link["code"])
    assert res.status_code == 200
    assert res.json() == {"status": "active", "public_passport_path": f"/p/{slug}"}
    assert len(_events(mem_store, link["id"], "opened")) == 1


def test_unknown_code_returns_generic_inactive_without_holder_data(client: TestClient) -> None:
    slug = _publish_passport(client).json()["public_slug"]
    _create_link(client)
    res = _resolve(client, "ZZZZunknownZZZZ0")
    assert res.status_code == 404
    body = json.dumps(res.json())
    assert res.json()["detail"]["code"] == "beam_link_inactive"
    assert slug not in body
    assert USER_ID not in body
    assert "/p/" not in body


def test_short_or_empty_code_is_rejected(client: TestClient) -> None:
    _publish_passport(client)
    assert _resolve(client, "abc").status_code == 404


def test_revoked_code_stops_resolving(client: TestClient, mem_store: dict) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    revoked = _revoke(client, link["id"]).json()
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"] is not None

    res = _resolve(client, link["code"])
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "beam_link_inactive"
    assert len(_events(mem_store, link["id"], "revoked")) == 1
    # The failed scan is audited too.
    assert len(_events(mem_store, link["id"], "expired_hit")) == 1


def test_expired_code_stops_resolving_and_is_stamped(client: TestClient, mem_store: dict) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    mem_store["beam_links"][link["id"]]["expires_at"] = "2020-01-01T00:00:00+00:00"

    res = _resolve(client, link["code"])
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "beam_link_inactive"
    assert mem_store["beam_links"][link["id"]]["status"] == "expired"
    assert len(_events(mem_store, link["id"], "expired_hit")) == 1


def test_unpublished_passport_makes_code_dormant_and_republish_revives_it(
    client: TestClient,
) -> None:
    slug = _publish_passport(client).json()["public_slug"]
    link = _create_link(client).json()

    client.post("/api/v1/student/vbr/passport/unpublish")
    res = _resolve(client, link["code"])
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "beam_link_inactive"
    assert slug not in json.dumps(res.json())

    # Re-publishing restores the SAME code — printed cards come back to life.
    _publish_passport(client)
    revived = _resolve(client, link["code"])
    assert revived.status_code == 200
    assert revived.json()["public_passport_path"] == f"/p/{slug}"


def test_resolution_response_never_carries_link_or_user_ids(client: TestClient) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    body = json.dumps(_resolve(client, link["code"]).json())
    assert link["id"] not in body
    assert USER_ID not in body


# ── Rotate ────────────────────────────────────────────────────────────────────

def test_rotate_kills_old_code_and_mints_working_new_one(
    client: TestClient, mem_store: dict
) -> None:
    slug = _publish_passport(client).json()["public_slug"]
    old = _create_link(client).json()

    res = _rotate(client, old["id"])
    assert res.status_code == 200
    new = res.json()
    assert new["id"] != old["id"]
    assert new["code"] != old["code"]
    assert new["status"] == "active"

    assert _resolve(client, old["code"]).status_code == 404
    ok = _resolve(client, new["code"])
    assert ok.status_code == 200
    assert ok.json()["public_passport_path"] == f"/p/{slug}"
    assert len(_events(mem_store, old["id"], "rotated")) == 1


def test_rotate_then_create_reuses_the_new_link(client: TestClient) -> None:
    _publish_passport(client)
    old = _create_link(client).json()
    new = _rotate(client, old["id"]).json()
    assert _create_link(client).json()["code"] == new["code"]


# ── Revoke ────────────────────────────────────────────────────────────────────

def test_revoke_is_idempotent(client: TestClient) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    first = _revoke(client, link["id"]).json()
    second = _revoke(client, link["id"]).json()
    assert first["status"] == second["status"] == "revoked"
    assert second["revoked_at"] == first["revoked_at"]


def test_revoke_then_create_mints_a_fresh_code(client: TestClient) -> None:
    _publish_passport(client)
    old = _create_link(client).json()
    _revoke(client, old["id"])
    fresh = _create_link(client).json()
    assert fresh["code"] != old["code"]
    assert _resolve(client, fresh["code"]).status_code == 200


# ── Ownership ────────────────────────────────────────────────────────────────

def test_non_owner_cannot_rotate_or_revoke(client: TestClient) -> None:
    _publish_passport(client)
    link = _create_link(client).json()

    _as_user(OTHER_USER_ID)
    assert _rotate(client, link["id"]).status_code == 404
    assert _revoke(client, link["id"]).status_code == 404

    # The owner's link is untouched and still resolves.
    _as_user(USER_ID)
    assert _resolve(client, link["code"]).status_code == 200


def test_each_user_gets_their_own_link(client: TestClient) -> None:
    _publish_passport(client)
    mine = _create_link(client).json()

    _as_user(OTHER_USER_ID)
    _publish_passport(client)
    theirs = _create_link(client).json()

    assert theirs["code"] != mine["code"]
    assert theirs["public_passport_path"] != mine["public_passport_path"]


# ── Audit metadata safety ─────────────────────────────────────────────────────

def test_opened_event_metadata_is_coarse_and_privacy_safe(
    client: TestClient, mem_store: dict
) -> None:
    _publish_passport(client)
    link = _create_link(client).json()
    _resolve(
        client,
        link["code"],
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/605.1",
            "Referer": "https://recruiter.example.com/fair/booth-42?candidate=secret",
        },
    )
    (event,) = _events(mem_store, link["id"], "opened")
    assert event["user_agent_class"] == "mobile"
    assert event["referrer_host"] == "recruiter.example.com"
    dumped = json.dumps(event)
    assert "booth-42" not in dumped      # no referrer path/query
    assert "Safari" not in dumped        # no raw user agent
    assert "candidate=secret" not in dumped


def test_user_agent_classifier_is_coarse() -> None:
    assert classify_user_agent(None) == "unknown"
    assert classify_user_agent("curl/8.0") == "bot"
    assert classify_user_agent("Mozilla/5.0 (iPad; ...)") == "tablet"
    assert classify_user_agent("Mozilla/5.0 (Linux; Android 14; Pixel) Mobile") == "mobile"
    assert classify_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X)") == "desktop"


def test_referrer_host_strips_everything_but_the_host() -> None:
    assert referrer_host("https://example.com/private/path?q=1#frag") == "example.com"
    assert referrer_host("not a url") is None
    assert referrer_host(None) is None
