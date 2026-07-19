"""Tests for the Passport Card profile photo (avatar) surface.

Covers:
  - client/server file validation (type + size)
  - the identity header emits ONLY a public-safe avatar URL (signed/private URLs
    are dropped so the card falls back to safe initials)
  - the upload endpoint degrades gracefully when storage is not configured
    (``persisted=false``, no error) and rejects invalid uploads (400)
  - the delete endpoint clears the persisted URL (idempotent)

All storage is in-memory (dict mode). No network / storage calls.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user_id, get_db, get_pipeline_db
from app.main import app
from app.services.passport_avatar_service import (
    MAX_AVATAR_BYTES,
    AvatarValidationError,
    clear_avatar,
    validate_avatar,
)

USER_ID = "11111111-1111-1111-1111-111111111111"


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


def _seed_onboarding(mem_store: dict, **fields) -> str:
    row = {"id": str(uuid4()), "user_id": USER_ID}
    row.update(fields)
    mem_store.setdefault("student_onboarding_profiles", {})[row["id"]] = row
    return row["id"]


def _identity(client: TestClient) -> dict:
    body = client.get("/api/v1/student/vbr/passport").json()
    return body["identity"]


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content_type,ext", [
    ("image/jpeg", "jpg"),
    ("image/png", "png"),
    ("image/webp", "webp"),
    ("image/png; charset=binary", "png"),  # parameters are tolerated
])
def test_validate_avatar_accepts_allowed_types(content_type: str, ext: str) -> None:
    assert validate_avatar(b"x", content_type) == ext


def test_validate_avatar_rejects_unsupported_type() -> None:
    with pytest.raises(AvatarValidationError):
        validate_avatar(b"x", "image/gif")


def test_validate_avatar_rejects_oversize() -> None:
    with pytest.raises(AvatarValidationError):
        validate_avatar(b"x" * (MAX_AVATAR_BYTES + 1), "image/png")


def test_validate_avatar_rejects_empty() -> None:
    with pytest.raises(AvatarValidationError):
        validate_avatar(b"", "image/png")


# ── Identity emission + sanitization ──────────────────────────────────────────

def test_identity_emits_public_safe_avatar_url(client: TestClient, mem_store: dict) -> None:
    _seed_onboarding(mem_store, avatar_url="https://cdn.example.com/u/ada.png?v=123")
    identity = _identity(client)
    assert identity["avatar_url"] == "https://cdn.example.com/u/ada.png?v=123"


def test_identity_drops_signed_or_private_avatar_url(client: TestClient, mem_store: dict) -> None:
    signed = (
        "https://proj.supabase.co/storage/v1/object/sign/private/avatars/ada.png"
        "?token=eyJhbGciOiJI&X-Amz-Signature=abc"
    )
    _seed_onboarding(mem_store, avatar_url=signed)
    identity = _identity(client)
    # Unsafe URL is never emitted; the card will fall back to initials.
    assert identity["avatar_url"] is None
    assert "X-Amz-Signature" not in str(identity)
    assert "/object/sign/" not in str(identity)


def test_identity_avatar_absent_when_unset(client: TestClient, mem_store: dict) -> None:
    _seed_onboarding(mem_store, major="Computer Science")
    assert _identity(client)["avatar_url"] is None


# ── Upload endpoint (storage not configured → graceful, non-persistent) ────────

def test_upload_without_storage_returns_non_persisted(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/student/vbr/passport/identity/photo",
        files={"file": ("me.png", b"binarypngdata", "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["persisted"] is False
    assert body["avatar_url"] is None


def test_upload_rejects_unsupported_type(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/student/vbr/passport/identity/photo",
        files={"file": ("me.gif", b"gifdata", "image/gif")},
    )
    assert resp.status_code == 400
    assert "JPG, PNG, or WebP" in str(resp.json()["detail"])


# ── Delete endpoint ───────────────────────────────────────────────────────────

def test_delete_clears_persisted_avatar(client: TestClient, mem_store: dict) -> None:
    _seed_onboarding(mem_store, avatar_url="https://cdn.example.com/u/ada.png")
    assert _identity(client)["avatar_url"] == "https://cdn.example.com/u/ada.png"

    resp = client.delete("/api/v1/student/vbr/passport/identity/photo")
    assert resp.status_code == 200
    assert resp.json() == {"avatar_url": None, "persisted": True}
    # The persisted URL is cleared, so the identity now has no photo.
    assert _identity(client)["avatar_url"] is None


def test_clear_avatar_is_idempotent_without_row(mem_store: dict) -> None:
    # No onboarding row yet — clearing must not raise and must leave it unset.
    clear_avatar(mem_store, USER_ID, bucket="")
    row = next(
        (r for r in mem_store.get("student_onboarding_profiles", {}).values()
         if r.get("user_id") == USER_ID),
        None,
    )
    assert row is not None
    assert row["avatar_url"] is None
